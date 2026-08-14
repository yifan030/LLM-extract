# -*- coding: utf-8 -*-
"""抽取流水线编排服务。"""
import json
import os

from conf.config import Settings
from logs.decorators import log_step
from logs.logging import get_logger
from libs.hugegraph import HugeGraphRepository
from libs.minio import MinioRepository
from service.llm import LlmService
from service.matcher import MatcherService
from service.prompt import PromptService, load_level4_names
from service.mysql_events import extract_file_id

log = get_logger(__name__)

# question_type_id → 题型名称（与 model.schemas / service.knowledge / bin.backfill_milvus 一致）
TYPE_MAP: dict[int, str] = {1: "单选题", 2: "多选题", 3: "填空题", 4: "解答题"}

# Milvus question collection 各层级 KP ARRAY 字段的容量上限（与 libs/milvus.py schema 一致）
_KP_ARRAY_CAPACITY: dict[int, int] = {1: 8, 2: 16, 3: 32, 4: 32}
# 单批 upsert 到 Milvus 的试题条数
_MILVUS_BATCH_SIZE = 50


@log_step
class ExtractionService:
    def __init__(
        self,
        minio_repo: MinioRepository,
        hg_repo: HugeGraphRepository,
        llm_svc: LlmService,
        prompt_svc: PromptService,
        matcher_svc: MatcherService,
        settings: Settings | None = None,
        embed_svc=None,
        milvus_repo=None,
        mysql_repo=None,
    ):
        self._minio = minio_repo
        self._hg = hg_repo
        self._llm = llm_svc
        self._prompt = prompt_svc
        self._matcher = matcher_svc
        # Milvus 双写依赖的两个可选服务；缺省 None 以保持向后兼容
        self._embed_svc = embed_svc
        self._milvus = milvus_repo
        # MySQL 仓库：反解 construct content_hash 用（内容派生 paper_id）；缺省 None 走路径派生
        self._mysql = mysql_repo
        self._settings = settings
        self._output_dir = settings.output_dir if settings else "tmp/extractions"

    async def run(
        self,
        object_key: str,
        save_artifacts: bool = False,
        import_to_hg: bool = True,
    ) -> dict:
        log.info("开始抽取流水线: object_key=%s", object_key)
        # 1. 从 MinIO 读取 Markdown
        markdown = await self._minio.get_object_text(object_key)
        # 2. 从静态文件加载四级知识点名称（一次加载，复用给 prompt + matcher）
        level4_names = load_level4_names()
        # 3. 构建 Prompt
        prompt = self._prompt.build_prompt_sync(markdown, level4_names)
        # 4. LLM 抽取
        extracted = await self._llm.extract(prompt)
        # 4.5 反解原始文件 content_hash（内容派生 paper_id，与 MySQL 管线一致；拿不到则退回路径派生）
        content_hash = await self._resolve_content_hash(object_key)
        # 5. 知识点匹配 (stateless matcher: level4_names passed as arg)
        #    当 embed_svc + milvus_repo 可用时，启用模糊匹配（Milvus 向量检索兜底），
        #    否则退化为纯字符串精确匹配。
        if self._embed_svc is not None and self._milvus is not None:
            threshold = self._settings.embed_kp_match_threshold if self._settings else 0.75
            top_k = self._settings.embed_kp_top_k if self._settings else 5
            intermediate = await self._matcher.match_fuzzy(
                extracted,
                source_file=object_key,
                level4_names=level4_names,
                embed_svc=self._embed_svc,
                milvus_repo=self._milvus,
                threshold=threshold,
                top_k=top_k,
                content_hash=content_hash,
            )
        else:
            intermediate = self._matcher.match(
                extracted, source_file=object_key, level4_names=level4_names,
                content_hash=content_hash,
            )

        # 提取 paper_id 用于目录命名
        paper_v = intermediate.vertices[0] if intermediate.vertices else None
        paper_id = paper_v.id if paper_v else "unknown"
        # paper_id 格式 "paper_{md5hex}" → 取后 12 位做目录名
        artifact_dir: str | None = None

        # 6. 保存中间产物（在导入之前，确保审计材料不会因导入失败丢失）
        if save_artifacts:
            artifact_dir = self._save_artifacts(
                paper_id, extracted, intermediate
            )

        # 7. 导入 HugeGraph（可选）
        if import_to_hg:
            report = await self._import_to_hg(intermediate)

            # 导入报告也落盘
            if artifact_dir:
                self._write_json(os.path.join(artifact_dir, "import_report.json"), report)
        else:
            # 仅审计，不导入
            report = {
                "paper_id": paper_id,
                "question_count": len(intermediate.vertices) - 1 if intermediate.vertices else 0,
                "matched_kp": len([e for e in intermediate.edges if e.label == "examines"]),
                "unmatched_count": len(intermediate.unmatched),
                "imported": False,
            }

        # 8. 双写 Milvus（可选）：仅当真正导入 HugeGraph（KPs 必须已存在于图）时
        #    才双写，且需 embed_svc + milvus_repo 同时可用。
        #    失败只记日志，绝不让 Milvus 拖垮抽取主流程。
        report["milvus_upserted"] = 0
        report["milvus_enabled"] = False
        if (
            import_to_hg
            and self._embed_svc is not None
            and self._milvus is not None
        ):
            milvus_report = await self._import_to_milvus(intermediate, markdown)
            report["milvus_upserted"] = milvus_report.get("milvus_upserted", 0)
            report["milvus_enabled"] = milvus_report.get("milvus_enabled", True)

        report["artifact_dir"] = artifact_dir
        log.info("抽取完成: paper_id=%s", paper_id)
        return report

    async def _resolve_content_hash(self, object_key: str) -> str | None:
        """反解原始文件 content_hash（内容派生 paper_id，与 MySQL 管线一致）。

        优先查 construct 侧 ``edu_construct_files.content_hash``；查不到（无 construct
        记录、mysql_repo 未配置、老数据缺 content_hash）时返回 None，由 matcher 退回路径派生。
        """
        if self._mysql is None:
            return None
        file_id = extract_file_id(object_key)
        if not file_id:
            return None
        try:
            row = await self._mysql.find_one("edu_construct_files", {"file_id": file_id})
        except Exception as exc:  # noqa: BLE001 - 图库管线不因查库失败而中断
            log.warning("查询 construct content_hash 失败: %s", exc)
            return None
        if row and row.get("content_hash"):
            return row["content_hash"]
        return None

    async def _import_to_hg(self, data) -> dict:
        question_type_cache = await self._hg.preload_question_types()

        vertices_created = 0
        vertices_duplicated = 0
        vertices_failed = 0
        for v in data.vertices:
            created, dup = await self._hg.create_vertex(v)
            if created:
                vertices_created += 1
            elif dup:
                vertices_duplicated += 1
            else:
                vertices_failed += 1

        edges_created = 0
        edges_duplicated = 0
        edges_failed = 0
        for e in data.edges:
            inV = e.inV
            if e.label == "belongs_to_type":
                inV = question_type_cache.get(e.inV)
                if not inV:
                    log.error("题型顶点不存在: %s", e.inV)
                    edges_failed += 1
                    continue
                e.inV = inV
            created, dup = await self._hg.create_edge(e)
            if created:
                edges_created += 1
            elif dup:
                edges_duplicated += 1
            else:
                edges_failed += 1

        paper_v = data.vertices[0] if data.vertices else None
        paper_id = paper_v.id if paper_v else "unknown"
        return {
            "paper_id": paper_id,
            "question_count": len(data.vertices) - 1 if data.vertices else 0,
            "matched_kp": len([e for e in data.edges if e.label == "examines"]),
            "unmatched_count": len(data.unmatched),
            "imported": True,
            "vertices_created": vertices_created,
            "vertices_duplicated": vertices_duplicated,
            "vertices_failed": vertices_failed,
            "edges_created": edges_created,
            "edges_duplicated": edges_duplicated,
            "edges_failed": edges_failed,
        }

    # ── Milvus 双写 ──

    async def _import_to_milvus(self, intermediate, markdown: str) -> dict:
        """双写 Milvus：把抽取出的试题 upsert 到 question collection。

        KP 层级（``kp_names/ids_l1~l4``）从 HugeGraph 沿 ``contains_kp`` 入边
        向上遍历得到；每题的 level-4 KP 取自 ``examines`` 边的 ``inV``。
        所有 Milvus/Embedding 操作都包裹在 try/except 中——失败只记日志并返回
        统计，绝不让双写异常拖垮抽取主流程。

        前置条件：调用方需在启动阶段通过 ``MilvusRepository.ensure_collections()``
        确保 collection 已存在并已加载；本方法不再重复检查。

        ``markdown`` 为源文档原始文本（保留入参以兼容调用方契约，当前仅审计用）。
        """
        if self._embed_svc is None or self._milvus is None:
            log.info("Milvus 双写跳过: embed_svc/milvus_repo 未配置")
            return {"milvus_upserted": 0, "milvus_enabled": False}

        report = {"milvus_upserted": 0, "milvus_enabled": True}
        if markdown:
            log.debug("Milvus 双写: 源 markdown 长度=%d", len(markdown))

        paper_v = next(
            (v for v in intermediate.vertices if v.label == "exam_paper"), None
        )
        paper_props = paper_v.properties if paper_v else {}
        paper_id = paper_v.id if paper_v else "unknown"

        # question_id -> [level-4 kp_ids]（examines 边的 inV 即 kp_id，如 "level_4_交集"）
        exam_kp: dict[str, list[str]] = {}
        for e in intermediate.edges:
            if e.label == "examines":
                exam_kp.setdefault(e.outV, []).append(e.inV)

        rows: list[dict] = []
        for v in intermediate.vertices:
            if v.label != "question":
                continue
            props = v.properties
            content = str(props.get("content") or "")

            # 汇总该题全部 level-4 KP 的祖先链（L1~L4 的 name + id）
            buckets: dict[str, list[str]] = {
                key: [] for lvl in (1, 2, 3, 4)
                for key in (f"l{lvl}", f"l{lvl}_ids")
            }
            for kp_id in exam_kp.get(v.id, []):
                try:
                    hierarchy = await self._get_kp_hierarchy(kp_id)
                except Exception as exc:  # noqa: BLE001 - 单个 KP 失败不中断整题
                    log.warning("解析知识点 %s 祖先链失败: %s", kp_id, exc)
                    continue
                for lvl in (1, 2, 3, 4):
                    key = f"l{lvl}"
                    buckets[key].extend(hierarchy.get(key, []))
                    buckets[f"{key}_ids"].extend(hierarchy.get(f"{key}_ids", []))

            score = props.get("score")
            if score is not None and not isinstance(score, int):
                try:
                    score = int(score)
                except (TypeError, ValueError):
                    score = None

            rows.append({
                "question_id": v.id,
                "paper_id": paper_id,
                "number": str(props.get("number") or ""),
                "content": content,
                "answer": props.get("answer") or None,
                "question_type": TYPE_MAP.get(props.get("question_type_id", 0), ""),
                "subject": paper_props.get("subject") or "数学",
                "grade": paper_props.get("grade"),
                "score": score,
                "kp_names_l1": self._dedupe(buckets["l1"], _KP_ARRAY_CAPACITY[1]),
                "kp_ids_l1": self._dedupe(buckets["l1_ids"], _KP_ARRAY_CAPACITY[1]),
                "kp_names_l2": self._dedupe(buckets["l2"], _KP_ARRAY_CAPACITY[2]),
                "kp_ids_l2": self._dedupe(buckets["l2_ids"], _KP_ARRAY_CAPACITY[2]),
                "kp_names_l3": self._dedupe(buckets["l3"], _KP_ARRAY_CAPACITY[3]),
                "kp_ids_l3": self._dedupe(buckets["l3_ids"], _KP_ARRAY_CAPACITY[3]),
                "kp_names_l4": self._dedupe(buckets["l4"], _KP_ARRAY_CAPACITY[4]),
                "kp_ids_l4": self._dedupe(buckets["l4_ids"], _KP_ARRAY_CAPACITY[4]),
                "_embed_text": content or v.id,
            })

        if not rows:
            log.info("Milvus 双写跳过: 本次抽取无试题")
            return report

        # 批量 embed 所有题目正文（embedding 昂贵，一次调用尽量多）
        try:
            vectors = await self._embed_svc.embed_texts(
                [r["_embed_text"] for r in rows]
            )
        except Exception as exc:  # noqa: BLE001
            log.error("Milvus 双写失败: embed 试题正文出错: %s", exc)
            report["milvus_error"] = str(exc)
            return report

        upserted = 0
        for start in range(0, len(rows), _MILVUS_BATCH_SIZE):
            batch = rows[start:start + _MILVUS_BATCH_SIZE]
            data = [
                {k: r[k] for k in r if k != "_embed_text"} | {"dense_vector": vec}
                for r, vec in zip(batch, vectors[start:start + len(batch)])
            ]
            try:
                await self._milvus.upsert_question(data)
                upserted += len(data)
            except Exception as exc:  # noqa: BLE001 - 单批失败停止，避免无限重试
                log.error("Milvus 双写失败: upsert 批次失败: %s", exc)
                report["milvus_error"] = str(exc)
                break

        report["milvus_upserted"] = upserted
        log.info("Milvus 双写完成: 试题 %d 条", upserted)
        return report

    async def _get_kp_hierarchy(self, kp_id: str) -> dict:
        """获取一个 level-4 KP 的完整祖先链（L1~L4 的 name + id）。

        沿 ``contains_kp`` 的 IN 边向上遍历：IN 边的 ``outV`` 即父节点
        （与 ``service/knowledge.py`` / ``bin/backfill_milvus.py`` 的方向约定一致）。
        返回形如 ``{"l1": [...], "l1_ids": [...], ..., "l4": [...], "l4_ids": [...]}``。
        """
        result: dict[str, list[str]] = {
            key: [] for lvl in (1, 2, 3, 4)
            for key in (f"l{lvl}", f"l{lvl}_ids")
        }

        # level-4 KP 自身（examines 边的 inV 即 kp_id）
        try:
            kp = await self._hg.get_vertex(kp_id)
        except Exception as exc:  # noqa: BLE001
            log.warning("查询知识点 %s 失败: %s", kp_id, exc)
            kp = None
        if kp:
            name = kp.get("properties", {}).get("name", "")
            if name:
                result["l4"].append(name)
                result["l4_ids"].append(kp_id)

        # 向上遍历 contains_kp IN 边（L4→L3→L2→L1，最多 3 步）
        current_id = kp_id
        seen: set[str] = set()
        for _ in range(3):
            if not current_id or current_id in seen:
                break
            seen.add(current_id)
            try:
                edges = await self._hg.get_vertex_edges(
                    current_id, direction="IN", label="contains_kp"
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("查询知识点 %s 的 contains_kp 入边失败: %s", current_id, exc)
                break
            if not edges:
                break
            parent_id = edges[0].get("outV", "")
            if not parent_id or parent_id == current_id:
                break
            try:
                parent = await self._hg.get_vertex(parent_id)
            except Exception as exc:  # noqa: BLE001
                log.warning("查询父知识点 %s 失败: %s", parent_id, exc)
                break
            if parent:
                p_level = parent.get("properties", {}).get("level", 0)
                p_name = parent.get("properties", {}).get("name", "")
                if p_name and p_level in (1, 2, 3):
                    key = f"l{p_level}"
                    result[key].append(p_name)
                    result[f"{key}_ids"].append(parent_id)
            current_id = parent_id

        return result

    @staticmethod
    def _dedupe(items: list[str], max_capacity: int) -> list[str]:
        """去重并保持顺序，截断到 Milvus ARRAY 字段的容量上限。"""
        out: list[str] = []
        for it in items:
            if it and it not in out:
                out.append(it)
            if len(out) >= max_capacity:
                break
        return out

    # ── 产物持久化 ──

    def _save_artifacts(self, paper_id: str, extracted, intermediate) -> str:
        """保存 LLM 原始输出和中间 JSON 到磁盘，返回产物目录路径。"""
        # paper_id 格式 "paper_{32-char md5}" → 取尾部 12 位做目录名
        paper_hash = paper_id.replace("paper_", "")[:12]
        artifact_dir = os.path.join(self._output_dir, paper_hash)
        os.makedirs(artifact_dir, exist_ok=True)

        try:
            self._write_json(
                os.path.join(artifact_dir, "llm_response.json"),
                extracted.model_dump(),
            )
            self._write_json(
                os.path.join(artifact_dir, "intermediate.json"),
                intermediate.model_dump(),
            )
            log.info("产物已保存: %s", artifact_dir)
        except Exception as exc:
            log.error("保存产物失败: %s", exc)

        return artifact_dir

    @staticmethod
    def _write_json(path: str, obj) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=2, ensure_ascii=False)

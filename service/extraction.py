# -*- coding: utf-8 -*-
"""抽取流水线编排服务。"""
import json
import os

from conf.config import Settings
from logs.logging import get_logger
from libs.hugegraph import HugeGraphRepository
from libs.minio import MinioRepository
from service.llm import LlmService
from service.matcher import MatcherService
from service.prompt import PromptService

log = get_logger(__name__)


class ExtractionService:
    def __init__(
        self,
        minio_repo: MinioRepository,
        hg_repo: HugeGraphRepository,
        llm_svc: LlmService,
        prompt_svc: PromptService,
        matcher_svc: MatcherService,
        settings: Settings | None = None,
    ):
        self._minio = minio_repo
        self._hg = hg_repo
        self._llm = llm_svc
        self._prompt = prompt_svc
        self._matcher = matcher_svc
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
        # 2. 加载四级知识点名称（一次加载，复用给 prompt + matcher）
        level4_names = await self._hg.load_level4_names()
        # 3. 构建 Prompt（同步版本，传入已加载的知识点，避免重复查询 HugeGraph）
        prompt = self._prompt.build_prompt_sync(markdown, level4_names)
        # 4. LLM 抽取
        extracted = await self._llm.extract(prompt)
        # 5. 知识点匹配 (stateless matcher: level4_names passed as arg)
        intermediate = self._matcher.match(
            extracted, source_file=object_key, level4_names=level4_names
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

        report["artifact_dir"] = artifact_dir
        log.info("抽取完成: paper_id=%s", paper_id)
        return report

    async def _import_to_hg(self, data) -> dict:
        question_type_cache = await self._hg.preload_question_types()

        vertices_created = 0
        vertices_duplicated = 0
        for v in data.vertices:
            created, dup = await self._hg.create_vertex(v)
            if created:
                vertices_created += 1
            if dup:
                vertices_duplicated += 1

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
            "edges_created": edges_created,
            "edges_duplicated": edges_duplicated,
            "edges_failed": edges_failed,
        }

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

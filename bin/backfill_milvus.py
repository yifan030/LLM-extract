# -*- coding: utf-8 -*-
"""Milvus 回填脚本 — 从 HugeGraph 加载知识点与试题，embed 后写入 Milvus。

用法:
    python -m bin.backfill_milvus

流程:
    1. ``ensure_collections()`` 幂等创建/加载两个 collection。
    2. ``backfill_kps()``      — 全量知识点，沿 ``contains_kp`` 入边向上遍历构建
       path（如 "代数>集合>集合的基本运算>交集"），embed 后 ``upsert_kp``。
    3. ``backfill_questions()`` — 全量试题，沿 ``examines`` 出边取 level-4 知识点并
       向上遍历得到 L1~L4 层级数组；经 ``contains`` 入边取 paper_id 与试卷
       subject/grade；embed 后 ``upsert_question``。
    4. ``close()`` 关闭 Milvus 长连接。

边方向约定（与 HugeGraph 数据模型一致）:
    - ``contains``:    paper -[contains]-> question
    - ``examines``:    question -[examines]-> level4_kp
    - ``contains_kp``: parent -[contains_kp]-> child

因此对 child 顶点查 ``contains_kp`` 的 **IN** 边，父节点位于边的 ``outV``
（与 ``service/knowledge.py`` 的 ``get_kp_relations`` 实现一致）。
"""
import asyncio
from typing import Any

from conf.config import Settings
from libs.hugegraph import HugeGraphRepository
from libs.milvus import MilvusRepository
from logs.logging import get_logger
from service.embedding import EmbeddingService

log = get_logger(__name__)

BATCH_SIZE = 50

# question_type_id → 题型名称（与 model.schemas / service.knowledge 保持一致）
TYPE_MAP: dict[int, str] = {1: "单选题", 2: "多选题", 3: "填空题", 4: "解答题"}

# 模块级缓存：backfill_kps / backfill_questions 共享，避免重复遍历祖先链。
# _kp_map:      HugeGraph 知识点顶点 id → properties（list_vertices 一次性加载）
# _chain_cache: KP 顶点 id → [(level, kp_id, name), ...]（root→leaf 顺序）
_kp_map: dict[str, dict[str, Any]] = {}
_chain_cache: dict[str, list[tuple[int | None, str, str]]] = {}


# ── 小工具 ─────────────────────────────────────────────────────────

def _clip(value: Any, max_len: int) -> str:
    """任意值转字符串并截断到 ``max_len`` 字符；None → 空串。"""
    if value is None:
        return ""
    s = str(value)
    return s if len(s) <= max_len else s[:max_len]


def _str_or_none(value: Any, max_len: int) -> str | None:
    """可空字符串：None 保持 None；否则转字符串并截断（供 nullable 字段用）。"""
    if value is None:
        return None
    s = str(value)
    return s if len(s) <= max_len else s[:max_len]


def _to_int(value: Any) -> int | None:
    """容错转 int：int 直通、数字字符串转换；失败返回 None。"""
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _clip_array(items: list[str], max_capacity: int, elem_max: int = 128) -> list[str]:
    """数组字段归一化：截断到容量上限、单元素限长、去重且保持顺序。"""
    out: list[str] = []
    for v in items:
        if len(out) >= max_capacity:
            break
        clipped = v[:elem_max]
        if clipped and clipped not in out:
            out.append(clipped)
    return out


async def _load_all(hg_repo: HugeGraphRepository, label: str, page: int = 10000) -> list[dict]:
    """分页加载某 label 的全部顶点（offset 翻页，防单次 limit 截断）。"""
    vertices: list[dict] = []
    offset = 0
    while True:
        batch = await hg_repo.list_vertices(label, limit=page, offset=offset)
        vertices.extend(batch)
        if len(batch) < page:
            break
        offset += page
    return vertices


# ── 祖先链遍历 ─────────────────────────────────────────────────────

async def _kp_chain(
    hg_repo: HugeGraphRepository, kp_id: str
) -> list[tuple[int | None, str, str]]:
    """从 ``kp_id`` 沿 ``contains_kp`` 入边向上走，返回 root(L1)→leaf 的 (level, kp_id, name)。

    说明: ``contains_kp`` 边方向为 parent -[contains_kp]-> child；对 child 查 IN 边，
    父节点在 ``edge.outV``。结果以 root-first 顺序缓存到 ``_chain_cache``。
    """
    cached = _chain_cache.get(kp_id)
    if cached is not None:
        return cached

    nodes: list[tuple[int | None, str, str]] = []
    current_id = kp_id
    seen: set[str] = set()
    for _ in range(4):  # L4→L3→L2→L1，最多 4 层
        if not current_id or current_id in seen:
            break
        seen.add(current_id)
        props = _kp_map.get(current_id)
        if props is None:
            vertex = await hg_repo.get_vertex(current_id)
            props = (vertex or {}).get("properties", {})
        nodes.append((
            _to_int(props.get("level")),
            current_id,
            _clip(props.get("name"), 128),
        ))
        edges = await hg_repo.get_vertex_edges(
            current_id, direction="IN", label="contains_kp"
        )
        if not edges:
            break
        parent_id = edges[0].get("outV", "")
        if not parent_id or parent_id == current_id:
            break
        current_id = parent_id

    nodes.reverse()  # root-first: L1 → L4
    _chain_cache[kp_id] = nodes
    return nodes


async def _build_kp_path(hg_repo: HugeGraphRepository, kp_id: str, name: str) -> str:
    """构建知识点 path，形如 '代数>集合>集合的基本运算>交集'。"""
    chain = await _kp_chain(hg_repo, kp_id)
    names = [n for _, _, n in chain if n]
    if not names:
        names = [name]
    return ">".join(names)


# ── 回填主流程 ─────────────────────────────────────────────────────

async def backfill_kps(
    hg_repo: HugeGraphRepository,
    milvus_repo: MilvusRepository,
    embed_svc: EmbeddingService,
) -> None:
    """回填全部知识点到 Milvus kp collection。"""
    kp_vertices = await _load_all(hg_repo, "knowledge_point")
    _kp_map.clear()
    _kp_map.update({
        v.get("id"): v.get("properties", {})
        for v in kp_vertices
        if v.get("id")
    })
    log.info("加载知识点 %d 个", len(kp_vertices))

    rows: list[dict] = []
    for v in kp_vertices:
        props = v.get("properties", {})
        kp_id = v.get("id", "")
        name = _clip(props.get("name"), 128)
        path = await _build_kp_path(hg_repo, kp_id, name)
        description = _str_or_none(props.get("description"), 1024)
        embed_text = " | ".join(p for p in [name, path, description or ""] if p)
        rows.append({
            "kp_id": _clip(kp_id, 128),
            "name": name,
            "level": _to_int(props.get("level")) or 0,
            "subject": _clip(props.get("subject"), 16),
            "description": description,
            "path": path,
            "_embed_text": embed_text or kp_id,
        })

    for start in range(0, len(rows), BATCH_SIZE):
        batch = rows[start:start + BATCH_SIZE]
        vectors = await embed_svc.embed_texts([r["_embed_text"] for r in batch])
        data = [
            {
                "kp_id": r["kp_id"],
                "name": r["name"],
                "level": r["level"],
                "subject": r["subject"],
                "description": r["description"],
                "path": r["path"],
                "dense_vector": vec,
            }
            for r, vec in zip(batch, vectors)
        ]
        await milvus_repo.upsert_kp(data)
        log.info("知识点已回填 %d/%d", min(start + BATCH_SIZE, len(rows)), len(rows))


async def backfill_questions(
    hg_repo: HugeGraphRepository,
    milvus_repo: MilvusRepository,
    embed_svc: EmbeddingService,
) -> None:
    """回填全部试题到 Milvus question collection。"""
    questions = await _load_all(hg_repo, "question")
    log.info("加载试题 %d 条", len(questions))

    paper_cache: dict[str, dict[str, str | None]] = {}

    async def _paper_info(paper_id: str) -> dict[str, str | None]:
        """按 paper 顶点 id 取 subject/grade（按试卷缓存，避免重复查询）。"""
        if paper_id in paper_cache:
            return paper_cache[paper_id]
        info: dict[str, str | None] = {"subject": "", "grade": None}
        if paper_id:
            vertex = await hg_repo.get_vertex(paper_id)
            if vertex:
                pp = vertex.get("properties", {})
                info = {
                    "subject": _clip(pp.get("subject"), 16),
                    "grade": _str_or_none(pp.get("grade"), 16),
                }
        paper_cache[paper_id] = info
        return info

    rows: list[dict] = []
    for q in questions:
        q_id = q.get("id", "")
        props = q.get("properties", {})
        content = _clip(props.get("content"), 65535)

        # paper_id：contains 入边（paper -[contains]-> question），父试卷在 outV
        paper_id = ""
        try:
            contains_edges = await hg_repo.get_vertex_edges(
                q_id, direction="IN", label="contains"
            )
        except Exception as exc:  # noqa: BLE001 — 单条失败不中断整个回填
            log.warning("查询试题 %s 的 contains 入边失败: %s", q_id, exc)
            contains_edges = []
        if contains_edges:
            paper_id = contains_edges[0].get("outV", "") or ""
        paper_info = await _paper_info(paper_id)

        # 层级知识点数组：examines 出边 → level-4 KP → 向上遍历祖先
        buckets: dict[int, list[tuple[str, str]]] = {1: [], 2: [], 3: [], 4: []}
        try:
            exam_edges = await hg_repo.get_vertex_edges(
                q_id, direction="OUT", label="examines"
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("查询试题 %s 的 examines 出边失败: %s", q_id, exc)
            exam_edges = []
        for e in exam_edges:
            kp_id = e.get("inV", "")
            if not kp_id:
                continue
            chain = await _kp_chain(hg_repo, kp_id)
            for level, cid, cname in chain:
                lvl = _to_int(level)
                if lvl in buckets and cname:
                    buckets[lvl].append((cid, cname))

        question_type = TYPE_MAP.get(_to_int(props.get("question_type_id")), "")
        score = _to_int(props.get("score"))

        rows.append({
            "question_id": _clip(q_id, 64),
            "paper_id": _clip(paper_id, 64),
            "number": _clip(props.get("number") or q_id, 16),
            "content": content,
            "answer": _str_or_none(props.get("answer"), 65535),
            "question_type": _clip(question_type, 16),
            "subject": paper_info.get("subject") or "",
            "grade": paper_info.get("grade"),
            "score": score,
            "kp_names_l1": _clip_array([n for _, n in buckets[1]], 8),
            "kp_ids_l1": _clip_array([i for i, _ in buckets[1]], 8),
            "kp_names_l2": _clip_array([n for _, n in buckets[2]], 16),
            "kp_ids_l2": _clip_array([i for i, _ in buckets[2]], 16),
            "kp_names_l3": _clip_array([n for _, n in buckets[3]], 32),
            "kp_ids_l3": _clip_array([i for i, _ in buckets[3]], 32),
            "kp_names_l4": _clip_array([n for _, n in buckets[4]], 32),
            "kp_ids_l4": _clip_array([i for i, _ in buckets[4]], 32),
            "_embed_text": content or q_id,
        })

    for start in range(0, len(rows), BATCH_SIZE):
        batch = rows[start:start + BATCH_SIZE]
        vectors = await embed_svc.embed_texts([r["_embed_text"] for r in batch])
        data = [
            {
                "question_id": r["question_id"],
                "paper_id": r["paper_id"],
                "number": r["number"],
                "content": r["content"],
                "answer": r["answer"],
                "question_type": r["question_type"],
                "subject": r["subject"],
                "grade": r["grade"],
                "score": r["score"],
                "kp_names_l1": r["kp_names_l1"],
                "kp_ids_l1": r["kp_ids_l1"],
                "kp_names_l2": r["kp_names_l2"],
                "kp_ids_l2": r["kp_ids_l2"],
                "kp_names_l3": r["kp_names_l3"],
                "kp_ids_l3": r["kp_ids_l3"],
                "kp_names_l4": r["kp_names_l4"],
                "kp_ids_l4": r["kp_ids_l4"],
                "dense_vector": vec,
            }
            for r, vec in zip(batch, vectors)
        ]
        await milvus_repo.upsert_question(data)
        log.info("试题已回填 %d/%d", min(start + BATCH_SIZE, len(rows)), len(rows))


async def main() -> None:
    settings = Settings()
    hg_repo = HugeGraphRepository(settings)
    milvus_repo = MilvusRepository(settings)
    embed_svc = EmbeddingService(settings)

    await milvus_repo.ensure_collections()
    await backfill_kps(hg_repo, milvus_repo, embed_svc)
    await backfill_questions(hg_repo, milvus_repo, embed_svc)
    await milvus_repo.close()
    log.info("Milvus 回填全部完成")


if __name__ == "__main__":
    asyncio.run(main())

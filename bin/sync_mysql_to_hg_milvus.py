# -*- coding: utf-8 -*-
"""把 MySQL 回填到 HugeGraph + Milvus（主同步脚本）。

前置
----
先跑 ``python -m bin.sync_kp_to_mysql --apply`` 把四级知识点层级补齐到 MySQL，
本脚本即可自包含地从 MySQL 读出全部层级（无需再依赖 HugeGraph 的知识点数据）。

流程
----
1. 从 MySQL 读 ``exam_papers`` / ``questions`` / ``knowledge_points`` /
   ``question_knowledge_point``。
2. 探测 HugeGraph 中的旧 id 顶点（雪花 id 遗留），--apply 时清理。
3. HugeGraph：确保 ``question.difficulty`` 属性存在，写 ``exam_paper`` / ``question``
   顶点 + ``contains`` / ``belongs_to_type`` / ``examines`` 边。``knowledge_point``
   顶点与 ``contains_kp`` 边已在 HG（脚本 1 即从其读取），不重复写。
4. Milvus：写 ``question`` collection（含 L1~L4 层级数组）+ ``kp`` collection
   （含 path）。所有标量字段 + dense_vector（BM25 稀疏向量由 Milvus 自动生成）。

字段映射见 ``service/sync_mapping.py``。

用法（默认 dry-run 只读不落库，不调 embedding）
------------------------------------------------
    set -a && source .env.prod && set +a
    python -m bin.sync_mysql_to_hg_milvus                 # dry-run
    python -m bin.sync_mysql_to_hg_milvus --apply
"""
import argparse
import asyncio
import re
from datetime import datetime

from conf.config import Settings
from libs.hugegraph import HugeGraphRepository
from libs.mysql import MySqlRepository
from logs.logging import get_logger
from model.models import Edge, Vertex
from service.sync_mapping import (
    KP_ARRAY_CAPACITY,
    build_kp_chain,
    build_kp_path,
    build_paper_props,
    build_question_props,
    clip,
    clip_array,
    paper_content_hash,
    str_or_none,
    to_int,
)

log = get_logger(__name__)

_BATCH_SIZE = 50

_MD5_HEX = re.compile(r"[0-9a-f]{32}")


def _is_md5_id(vid: str, prefix: str) -> bool:
    """判断顶点 id 是否符合 ``prefix_{32位hex}`` 的 md5 约定。"""
    if not vid.startswith(prefix):
        return False
    return bool(_MD5_HEX.fullmatch(vid[len(prefix):]))


# ── 主流程 ─────────────────────────────────────────────────────────

async def _load_all(mysql: MySqlRepository, table: str) -> list[dict]:
    return await mysql._execute(f"SELECT * FROM {table}")


async def _load_label_ids(hg: HugeGraphRepository, label: str) -> list[str]:
    """分页加载某 label 的全部顶点 id。"""
    ids: list[str] = []
    offset = 0
    while True:
        batch = await hg.list_vertices(label, limit=10000, offset=offset)
        if not batch:
            break
        ids.extend(v.get("id", "") for v in batch)
        if len(batch) < 10000:
            break
        offset += 10000
    return ids


async def _collect_old_ids(hg: HugeGraphRepository) -> list[str]:
    """收集 HG 中非 md5 id 的 exam_paper / question 顶点（旧雪花 id 遗留）。"""
    old: list[str] = []
    for label, prefix in (("exam_paper", "paper_"), ("question", "question_")):
        for vid in await _load_label_ids(hg, label):
            if vid and not _is_md5_id(vid, prefix):
                old.append(vid)
    return old


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="实际落库（默认 dry-run）")
    args = parser.parse_args()

    settings = Settings()
    mysql = MySqlRepository(settings)
    hg = HugeGraphRepository(settings)

    papers = await _load_all(mysql, "exam_papers")
    questions = await _load_all(mysql, "questions")
    kps = await _load_all(mysql, "knowledge_points")
    qkp = await _load_all(mysql, "question_knowledge_point")

    # ── 构建映射 ──
    paper_hash_map = {
        p["id"]: (p.get("content_hash") or paper_content_hash(p["id"]))
        for p in papers
    }
    kp_by_id = {
        r["id"]: {
            "name": (r.get("name") or "").strip(),
            "level": to_int(r.get("level")),
            "parent_id": to_int(r.get("parent_id")),
            "subject": r.get("subject"),
            "description": r.get("description"),
        }
        for r in kps
    }
    # question_id -> [level-4 kp_id]（经 question_knowledge_point 关联表）
    q_l4_kp_ids: dict[str, list[int]] = {}
    for r in qkp:
        kp_id = to_int(r.get("knowledge_point_id"))
        node = kp_by_id.get(kp_id) if kp_id is not None else None
        if node is not None and node.get("level") == 4:
            q_l4_kp_ids.setdefault(r["question_id"], []).append(kp_id)

    # 探测 HG 旧 id 顶点（雪花 id 遗留，--apply 时清理）
    old_ids: list[str] = []
    try:
        old_ids = await _collect_old_ids(hg)
    except Exception as exc:  # noqa: BLE001 — HG 不可达不阻断 dry-run
        log.warning("探测 HG 旧顶点失败（忽略）: %s", exc)

    print(
        f"试卷={len(papers)} | 题目={len(questions)} | 知识点={len(kps)} | "
        f"题目-知识点关联={len(qkp)} | 待清理旧 id 顶点={len(old_ids)}"
    )

    if not args.apply:
        if old_ids:
            print(f"[dry-run] 将清理 {len(old_ids)} 个旧 id 顶点：")
            for vid in old_ids[:20]:
                print(f"  - {vid}")
            if len(old_ids) > 20:
                print(f"  ... 等共 {len(old_ids)} 个")
        print("\n[dry-run] 只读完成，未落库、未调用 embedding（加 --apply 才实际执行）")
        await mysql.close()
        return

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ── 0. 确保 question.difficulty 属性存在 ──
    await hg.ensure_vertex_property("question", "difficulty", "INT")

    # ── 1. 清理旧 id 顶点（雪花 id 遗留，级联删除其边）──
    if old_ids:
        removed = 0
        for vid in old_ids:
            if await hg.delete_vertex(vid):
                removed += 1
        log.info("清理旧 id 顶点 %d/%d 个", removed, len(old_ids))

    # ── 2. HugeGraph 写入 ──
    type_cache = await hg.preload_question_types()

    report = {"paper_created": 0, "paper_dup": 0, "paper_fail": 0,
              "question_created": 0, "question_dup": 0, "question_fail": 0,
              "edge_created": 0, "edge_dup": 0, "edge_fail": 0}

    def _record_edge(created: bool, dup: bool) -> None:
        if created:
            report["edge_created"] += 1
        elif dup:
            report["edge_dup"] += 1
        else:
            report["edge_fail"] += 1

    for p in papers:
        props = build_paper_props(p, now)
        created, dup = await hg.create_vertex(
            Vertex(label="exam_paper", id=p["id"], properties=props)
        )
        if created:
            report["paper_created"] += 1
        elif dup:
            report["paper_dup"] += 1
        else:
            report["paper_fail"] += 1

    for q in questions:
        props = build_question_props(q, paper_hash_map, now)
        created, dup = await hg.create_vertex(
            Vertex(label="question", id=q["id"], properties=props)
        )
        if created:
            report["question_created"] += 1
        elif dup:
            report["question_dup"] += 1
        else:
            report["question_fail"] += 1

        # contains: paper -[contains]-> question
        if q.get("exam_paper_id"):
            c, d = await hg.create_edge(Edge(
                label="contains", outV=q["exam_paper_id"], inV=q["id"],
                properties={"create_time": now},
            ))
            _record_edge(c, d)

        # belongs_to_type: question -[belongs_to_type]-> question_type
        type_vid = type_cache.get(q.get("question_type"))
        if type_vid:
            c, d = await hg.create_edge(Edge(
                label="belongs_to_type", outV=q["id"], inV=type_vid,
                properties={"create_time": now},
            ))
            _record_edge(c, d)
        else:
            report["edge_fail"] += 1
            log.warning("题型顶点不存在，跳过 belongs_to_type: %s", q.get("question_type"))

        # examines: question -[examines]-> level_4_{name}
        seen_kp: set[str] = set()
        for kp_id in q_l4_kp_ids.get(q["id"], []):
            node = kp_by_id[kp_id]
            kp_vid = f"level_4_{node['name']}"
            if kp_vid in seen_kp:
                continue
            seen_kp.add(kp_vid)
            c, d = await hg.create_edge(Edge(
                label="examines", outV=q["id"], inV=kp_vid,
                properties={"create_time": now},
            ))
            _record_edge(c, d)

    log.info(
        "HugeGraph 写入完成: paper=%s/%s/%s question=%s/%s/%s edge=%s/%s/%s",
        report["paper_created"], report["paper_dup"], report["paper_fail"],
        report["question_created"], report["question_dup"], report["question_fail"],
        report["edge_created"], report["edge_dup"], report["edge_fail"],
    )

    # ── 3. Milvus ──（惰性导入：dry-run 无需 pymilvus/embedding 依赖）
    from libs.milvus import MilvusRepository
    from service.embedding import EmbeddingService

    embed_svc = EmbeddingService(settings)
    milvus = MilvusRepository(settings)
    await milvus.ensure_collections()

    await _backfill_kps(kp_by_id, embed_svc, milvus)
    await _backfill_questions(
        papers, questions, paper_hash_map, kp_by_id, q_l4_kp_ids, embed_svc, milvus
    )
    await milvus.close()

    print(
        f"\n同步完成：清理旧顶点 {len(old_ids)} 个；"
        f"HG 顶点(paper {report['paper_created']} 新/{report['paper_dup']} 重, "
        f"question {report['question_created']} 新/{report['question_dup']} 重)，"
        f"边 {report['edge_created']} 新/{report['edge_dup']} 重/{report['edge_fail']} 失败"
    )
    await mysql.close()


async def _backfill_kps(kp_by_id, embed_svc, milvus) -> None:
    """把全部知识点写入 Milvus kp collection（kp_id=level_{level}_{name}，含 path）。"""
    rows: list[dict] = []
    for kp_id, node in kp_by_id.items():
        level = node.get("level") or 0
        name = node.get("name") or ""
        if not name:
            continue
        chain = build_kp_chain(kp_by_id, kp_id)
        path = build_kp_path(chain)
        description = str_or_none(node.get("description"), 1024)
        embed_text = " | ".join(p for p in [name, path, description or ""] if p)
        rows.append({
            "kp_id": f"level_{level}_{name}",
            "name": name,
            "level": level,
            "subject": clip(node.get("subject"), 16),
            "description": description,
            "path": clip(path, 512),
            "_embed_text": embed_text or f"level_{level}_{name}",
        })

    for start in range(0, len(rows), _BATCH_SIZE):
        batch = rows[start:start + _BATCH_SIZE]
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
        await milvus.upsert_kp(data)
        log.info("知识点已回填 %d/%d", min(start + _BATCH_SIZE, len(rows)), len(rows))


async def _backfill_questions(
    papers, questions, paper_hash_map, kp_by_id, q_l4_kp_ids, embed_svc, milvus
) -> None:
    """把全部题目写入 Milvus question collection（含 L1~L4 层级数组）。"""
    paper_info = {
        p["id"]: {"subject": p.get("subject") or "数学", "grade": p.get("grade")}
        for p in papers
    }

    rows: list[dict] = []
    for q in questions:
        q_id = q["id"]
        content = clip(q.get("content"), 65535)

        # 汇总 L1~L4 的 name + id
        buckets: dict[int, tuple[list[str], list[str]]] = {
            lvl: ([], []) for lvl in (1, 2, 3, 4)
        }
        for kp_id in q_l4_kp_ids.get(q_id, []):
            chain = build_kp_chain(kp_by_id, kp_id)
            for node in chain:
                lvl = node.get("level")
                if lvl not in buckets:
                    continue
                name = node.get("name")
                if not name:
                    continue
                names, ids = buckets[lvl]
                if name not in names:
                    names.append(name)
                    ids.append(f"level_{lvl}_{name}")

        info = paper_info.get(q.get("exam_paper_id"), {"subject": "数学", "grade": None})
        rows.append({
            "question_id": q_id,
            "paper_id": q.get("exam_paper_id") or "",
            "number": clip(q.get("number"), 16),
            "content": content,
            "answer": str_or_none(q.get("answer"), 65535),
            "question_type": clip(q.get("question_type"), 16),
            "subject": clip(info["subject"], 16),
            "grade": str_or_none(info["grade"], 16),
            "score": to_int(q.get("score")),
            "kp_names_l1": clip_array(buckets[1][0], KP_ARRAY_CAPACITY[1]),
            "kp_ids_l1": clip_array(buckets[1][1], KP_ARRAY_CAPACITY[1]),
            "kp_names_l2": clip_array(buckets[2][0], KP_ARRAY_CAPACITY[2]),
            "kp_ids_l2": clip_array(buckets[2][1], KP_ARRAY_CAPACITY[2]),
            "kp_names_l3": clip_array(buckets[3][0], KP_ARRAY_CAPACITY[3]),
            "kp_ids_l3": clip_array(buckets[3][1], KP_ARRAY_CAPACITY[3]),
            "kp_names_l4": clip_array(buckets[4][0], KP_ARRAY_CAPACITY[4]),
            "kp_ids_l4": clip_array(buckets[4][1], KP_ARRAY_CAPACITY[4]),
            "_embed_text": content or q_id,
        })

    for start in range(0, len(rows), _BATCH_SIZE):
        batch = rows[start:start + _BATCH_SIZE]
        vectors = await embed_svc.embed_texts([r["_embed_text"] for r in batch])
        data = [
            {k: r[k] for k in r if k != "_embed_text"} | {"dense_vector": vec}
            for r, vec in zip(batch, vectors)
        ]
        await milvus.upsert_question(data)
        log.info("题目已回填 %d/%d", min(start + _BATCH_SIZE, len(rows)), len(rows))


if __name__ == "__main__":
    asyncio.run(main())

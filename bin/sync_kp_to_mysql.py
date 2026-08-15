# -*- coding: utf-8 -*-
"""把 HugeGraph 的四级知识点层级同步进 MySQL knowledge_points（前置脚本）。

背景
----
MySQL 的 ``knowledge_points`` 目前只有 590 个扁平四级名（``populate_knowledge_points.py``
只插了 level=4、parent_id 为空）。HugeGraph 里已有完整的 L1~L4 层级（``contains_kp`` 边）
和 subject 字段。本脚本把完整层级同步进 MySQL，使 MySQL 成为知识点的完整事实源，供
``bin.sync_mysql_to_hg_milvus.py`` 自包含地回填 HugeGraph / Milvus。

流程
----
1. 经 ``MySqlRepository.init_tables`` 幂等补齐 ``subject``/``description`` 列与
   ``(name, level)`` 唯一键。
2. 读全部 ``knowledge_point`` 顶点 → 按 ``(name, level)`` upsert（含 subject/description）。
3. 读全部 ``contains_kp`` 边（parent -[contains_kp]-> child）→ 回填 ``child.parent_id``。

用法（默认 dry-run 只读不落库）
--------------------------------
    set -a && source .env.prod && set +a
    python -m bin.sync_kp_to_mysql                 # dry-run
    python -m bin.sync_kp_to_mysql --apply
"""
import argparse
import asyncio

from conf.config import Settings
from libs.hugegraph import HugeGraphRepository
from libs.mysql import MySqlRepository
from logs.logging import get_logger

log = get_logger(__name__)

_PAGE = 10000


async def _load_all_vertices(hg_repo: HugeGraphRepository, label: str) -> list[dict]:
    """分页加载某 label 的全部顶点（offset 翻页，防单次 limit 截断）。"""
    vertices: list[dict] = []
    offset = 0
    while True:
        batch = await hg_repo.list_vertices(label, limit=_PAGE, offset=offset)
        vertices.extend(batch)
        if len(batch) < _PAGE:
            break
        offset += _PAGE
    return vertices


async def _load_all_edges(hg_repo: HugeGraphRepository, label: str) -> list[dict]:
    """分页加载某 label 的全部边（offset 翻页）。"""
    edges: list[dict] = []
    offset = 0
    while True:
        batch = await hg_repo.list_edges(label, limit=_PAGE, offset=offset)
        edges.extend(batch)
        if len(batch) < _PAGE:
            break
        offset += _PAGE
    return edges


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="实际落库（默认 dry-run）")
    args = parser.parse_args()

    settings = Settings()
    hg = HugeGraphRepository(settings)
    mysql = MySqlRepository(settings)

    # 1. 读知识点顶点，构建 hg_id -> (name, level)
    vertices = await _load_all_vertices(hg, "knowledge_point")
    name_level_by_hgid: dict[str, tuple[str, int]] = {}
    for v in vertices:
        p = v.get("properties", {})
        name = (p.get("name") or "").strip()
        level = p.get("level")
        if not name or level is None:
            log.warning("知识点顶点缺 name/level，跳过: id=%s", v.get("id"))
            continue
        name_level_by_hgid[v.get("id")] = (name, int(level))

    # 2. 读 contains_kp 边，映射 child -> parent（多父时取第一个，与现有 edges[0] 约定一致）
    edges = await _load_all_edges(hg, "contains_kp")
    parent_by_child: dict[tuple[str, int], tuple[str, int]] = {}
    multi_parent: set[tuple[str, int]] = set()
    for e in edges:
        parent_hgid = e.get("outV", "")
        child_hgid = e.get("inV", "")
        parent_nl = name_level_by_hgid.get(parent_hgid)
        child_nl = name_level_by_hgid.get(child_hgid)
        if not parent_nl or not child_nl:
            log.warning(
                "contains_kp 边端点不在顶点集，跳过: %s -> %s", parent_hgid, child_hgid
            )
            continue
        if child_nl in parent_by_child:
            multi_parent.add(child_nl)
        else:
            parent_by_child[child_nl] = parent_nl

    for child in multi_parent:
        log.warning("知识点存在多个父节点，取第一个: name=%s level=%s", child[0], child[1])

    print(
        f"知识点顶点={len(vertices)} | contains_kp 边={len(edges)} | "
        f"父子链接={len(parent_by_child)}（多父 {len(multi_parent)} 个）"
    )

    if not args.apply:
        print("\n[dry-run] 只读完成，未落库（加 --apply 才实际执行）")
        await mysql.close()
        return

    # 建表 + 幂等补齐 subject/description 列与 (name, level) 唯一键
    await mysql.init_tables()

    # 3. upsert 顶点（name, level, subject, description）
    for v in vertices:
        p = v.get("properties", {})
        name = (p.get("name") or "").strip()
        level = p.get("level")
        if not name or level is None:
            continue
        await mysql.upsert(
            "knowledge_points",
            {
                "name": name,
                "level": int(level),
                "subject": p.get("subject"),
                "description": p.get("description"),
            },
            ["name", "level"],
        )

    # 4. 构建 (name, level) -> mysql id 映射
    rows = await mysql._execute("SELECT id, name, level FROM knowledge_points")
    id_by_name_level = {
        ((r["name"] or "").strip(), int(r["level"])): r["id"] for r in rows
    }

    # 5. 回填 parent_id
    updated = 0
    for (child_nl, parent_nl) in parent_by_child.items():
        child_id = id_by_name_level.get(child_nl)
        parent_id = id_by_name_level.get(parent_nl)
        if child_id is None or parent_id is None:
            log.warning("无法解析 MySQL id: child=%s parent=%s", child_nl, parent_nl)
            continue
        await mysql.upsert(
            "knowledge_points",
            {"name": child_nl[0], "level": child_nl[1], "parent_id": parent_id},
            ["name", "level"],
        )
        updated += 1

    print(f"\n同步完成：知识点 {len(vertices)} 个，父子链接 {updated} 条")
    await mysql.close()


if __name__ == "__main__":
    asyncio.run(main())

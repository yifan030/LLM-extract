# -*- coding: utf-8 -*-
"""MySQL → HugeGraph / Milvus 的字段映射与派生纯函数。

零外部依赖（仅标准库），供 ``bin.sync_mysql_to_hg_milvus.py`` 与单元测试共用，
避免测试连带引入 pymilvus / sqlalchemy 等重依赖。

ID 约定（与 ``service/matcher.py``、``service/mysql_import.py`` 一致）：
- paper_id = ``paper_{content_hash}``（原始文件字节 md5）
- question_id = ``question_{md5(object_key:题号)}``
- 顶点内的 Long 属性：``int(md5hex[:15], 16)``（60-bit 约定）
"""
import json
from typing import Any

# question_type 名称 → id（与 service/extraction.py、service/knowledge.py 一致）
TYPE_MAP: dict[str, int] = {"单选题": 1, "多选题": 2, "填空题": 3, "解答题": 4}

# Milvus question collection 各层级 KP ARRAY 字段容量上限（与 libs/milvus.py 一致）
KP_ARRAY_CAPACITY: dict[int, int] = {1: 8, 2: 16, 3: 32, 4: 32}


def strip_prefix(value: str, prefix: str) -> str:
    """去掉字符串前缀；不带该前缀时原样返回。"""
    return value[len(prefix):] if value.startswith(prefix) else value


def to_int(value: Any) -> int | None:
    """容错转 int：int 直通、数字字符串转换；失败返回 None。"""
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def json_list(value: Any) -> list[str]:
    """JSON 数组列 → list[str]；空值/非法 JSON 返回空列表。"""
    if not value:
        return []
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    except (TypeError, ValueError):
        return []


def paper_content_hash(paper_id: str) -> str:
    """paper_id（``paper_{md5}``）→ 裸 32 位 content_hash。"""
    return strip_prefix(paper_id, "paper_")


def clip(value: Any, max_len: int) -> str:
    """任意值转字符串并截断到 ``max_len`` 字符；None → 空串。"""
    if value is None:
        return ""
    s = str(value)
    return s if len(s) <= max_len else s[:max_len]


def str_or_none(value: Any, max_len: int) -> str | None:
    """可空字符串：None 保持 None；否则转字符串并截断（供 nullable 字段用）。"""
    if value is None:
        return None
    s = str(value)
    return s if len(s) <= max_len else s[:max_len]


def clip_array(items: list[str], max_capacity: int, elem_max: int = 128) -> list[str]:
    """数组字段归一化：截断到容量上限、单元素限长、去重且保持顺序。"""
    out: list[str] = []
    for v in items:
        if len(out) >= max_capacity:
            break
        clipped = v[:elem_max]
        if clipped and clipped not in out:
            out.append(clipped)
    return out


def build_paper_props(row: dict, now: str) -> dict:
    """MySQL ``exam_papers`` 行 → HugeGraph ``exam_paper`` 顶点属性。"""
    content_hash = row.get("content_hash") or paper_content_hash(row["id"])
    props = {
        "exam_paper_id": int(content_hash[:15], 16),
        "title": row.get("title"),
        "subject": row.get("subject"),
        "grade": row.get("grade"),
        "total_score": row.get("total_score"),
        "duration_minutes": row.get("duration_minutes"),
        "created_at": now,
        "updated_at": now,
    }
    return {k: v for k, v in props.items() if v is not None}


def build_question_props(row: dict, paper_hash_map: dict[str, str], now: str) -> dict:
    """MySQL ``questions`` 行 → HugeGraph ``question`` 顶点属性。"""
    q_hash = strip_prefix(row["id"], "question_")
    paper_content_hash = paper_hash_map.get(row["exam_paper_id"], "")
    props = {
        "question_id": int(q_hash[:15], 16),
        "number": row.get("number"),
        "content": row.get("content"),
        "answer": row.get("answer"),
        "score": row.get("score"),
        "difficulty": to_int(row.get("difficulty")),
        "question_type_id": TYPE_MAP.get(row.get("question_type") or "", 0),
        "exam_paper_id": int(paper_content_hash[:15], 16) if paper_content_hash else None,
        "img_urls": json_list(row.get("img_url")),
        "answer_imgs": json_list(row.get("answer_img")),
        "created_at": now,
        "updated_at": now,
    }
    return {k: v for k, v in props.items() if v is not None}


def build_kp_chain(kp_by_id: dict[int, dict], kp_id: int) -> list[dict]:
    """沿 ``parent_id`` 向上走，返回 root(L1)→leaf 的节点列表。

    每个节点即 ``kp_by_id`` 中对应 id 的 dict（含 name/level/parent_id 等）；
    ``kp_by_id`` 为 ``knowledge_points`` 全表按 id 索引。带环保护（seen 集合）。
    """
    chain: list[dict] = []
    cur: int | None = kp_id
    seen: set[int] = set()
    while cur is not None and cur not in seen:
        seen.add(cur)
        node = kp_by_id.get(cur)
        if node is None:
            break
        chain.append(node)
        cur = node.get("parent_id")
    chain.reverse()  # root-first: L1 → ... → 当前节点
    return chain


def build_kp_path(chain: list[dict]) -> str:
    """祖先链 → path，形如 '代数>函数>二次函数>二次函数最值'。"""
    names = [c.get("name") for c in chain if c.get("name")]
    return ">".join(names)

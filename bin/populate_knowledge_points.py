# -*- coding: utf-8 -*-
"""从 prompts/level4_knowledge_points.txt 填充 MySQL knowledge_points 表（仅四级知识点）。

用法:
    python -m bin.populate_knowledge_points

幂等：表内已有知识点时跳过，不重复插入。填充后 import_paper 的
``_load_kp_name_map`` 才能命中，从而同步写入 question_knowledge_point 关联表。
"""
import asyncio
import os

from conf.config import Settings
from libs.mysql import MySqlRepository

_NAME_MAX = 100  # knowledge_points.name VARCHAR(100)


def _project_dir() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_level4_names() -> list[str]:
    path = os.path.join(_project_dir(), "prompts", "level4_knowledge_points.txt")
    with open(path, "r", encoding="utf-8") as f:
        raw = [line.strip() for line in f if line.strip()]
    # 去重保持顺序
    seen: set[str] = set()
    out: list[str] = []
    for n in raw:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


async def main() -> None:
    mysql = MySqlRepository(Settings())
    existing = await mysql._execute("SELECT COUNT(*) AS c FROM knowledge_points")
    count = existing[0]["c"] if existing else 0
    if count > 0:
        print(f"knowledge_points 已有 {count} 行，跳过填充")
        await mysql.close()
        return

    names = _load_level4_names()
    too_long = [n for n in names if len(n) > _NAME_MAX]
    if too_long:
        print(f"警告：{len(too_long)} 个名称超过 {_NAME_MAX} 字符，将被截断")
    inserted = 0
    for name in names:
        await mysql.insert_one(
            "knowledge_points", {"name": name[:_NAME_MAX], "level": 4}
        )
        inserted += 1
        if inserted % 100 == 0:
            print(f"已插入 {inserted}/{len(names)}")
    print(f"knowledge_points 填充完成：共 {inserted} 个四级知识点")
    await mysql.close()


if __name__ == "__main__":
    asyncio.run(main())

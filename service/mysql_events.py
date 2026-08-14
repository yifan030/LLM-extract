# -*- coding: utf-8 -*-
"""MinIO 事件 key 解析 + paper_id 反解（MySQL 自动入库消费者专用）。"""
from core.exceptions import PaperNotReady
from libs.id_gen import gen_paper_id

_ANSWER_CATEGORIES = {"answer", "answer_sheet"}


def parse_event_key(object_key: str) -> tuple[str, str | None]:
    """从 object key 解析 (category, paper_file_id)。

    约定：education/uploads/{category}[/{paper_file_id}]/{file_id}/...
    paper 无 paper_file_id；answer/answer_sheet 必有。
    """
    parts = object_key.strip("/").split("/")
    if len(parts) < 3 or parts[0] != "education" or parts[1] != "uploads":
        raise ValueError(f"无法识别的对象 key: {object_key}")
    category = parts[2]
    paper_file_id: str | None = None
    if category in _ANSWER_CATEGORIES:
        if len(parts) < 4 or not parts[3]:
            raise ValueError(f"{category} 类缺少 paper_file_id: {object_key}")
        paper_file_id = parts[3]
    return category, paper_file_id


async def resolve_paper_id(minio_repo, paper_file_id: str) -> str:
    """列试卷目录，取第一个 .md 派生 paper_id；试卷未就绪抛 PaperNotReady。"""
    prefix = f"education/uploads/paper/{paper_file_id}/"
    items = await minio_repo.list_md_files(prefix=prefix, limit=10)
    if not items:
        raise PaperNotReady(paper_file_id)
    return gen_paper_id(items[0].object_key)

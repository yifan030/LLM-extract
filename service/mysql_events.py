# -*- coding: utf-8 -*-
"""MinIO 事件 key 解析 + paper_id 反解（MySQL 自动入库消费者专用）。"""
from core.exceptions import PaperNotReady
from libs.id_gen import gen_content_hash_bytes, gen_paper_id_from_content_hash

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


def extract_file_id(object_key: str) -> str | None:
    """从对象 key 解析 file_id（解析产物所属的原始文件 file_id）。

    约定：education/uploads/{category}[/{paper_file_id}]/{file_id}/...
    paper 的 file_id 在第 4 段；answer/answer_sheet 的 file_id 在第 5 段。
    """
    parts = object_key.strip("/").split("/")
    if len(parts) < 4 or parts[0] != "education" or parts[1] != "uploads":
        return None
    category = parts[2]
    if category in _ANSWER_CATEGORIES:
        return parts[4] if len(parts) > 4 else None
    return parts[3]


async def resolve_paper_id(mysql_repo, minio_repo, paper_file_id: str) -> str:
    """按 paper_file_id 反解父试卷 paper_id。

    优先查 construct 侧 ``edu_construct_files.content_hash``（上传时已同步算好）；
    老记录缺 content_hash 时下载原始文件补算；都拿不到抛 PaperNotReady。
    """
    row = await mysql_repo.find_one("edu_construct_files", {"file_id": paper_file_id})
    content_hash = row.get("content_hash") if row else None
    if content_hash:
        return gen_paper_id_from_content_hash(content_hash)
    storage = row.get("file_storage_path") if row else None
    if storage:
        raw = await minio_repo.get_object_bytes(storage)
        return gen_paper_id_from_content_hash(gen_content_hash_bytes(raw))
    raise PaperNotReady(paper_file_id)

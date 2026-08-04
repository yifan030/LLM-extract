# -*- coding: utf-8 -*-
"""MinIO SDK 封装 — 异步文件列表、文本读取。"""
from miniopy_async import Minio  # type: ignore

from app.core.config import Settings
from app.core.exceptions import MinioObjectNotFound
from app.core.logging import get_logger
from app.domain.schemas import MinioFileItem

log = get_logger(__name__)


class MinioRepository:
    """Async data-access layer over MinIO (via miniopy_async)."""

    def __init__(self, settings: Settings):
        self._client = Minio(
            endpoint=settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
        )
        self.bucket = settings.minio_bucket

    async def list_md_files(self, prefix: str = "", limit: int = 50) -> list[MinioFileItem]:
        """列出 bucket 下所有 ``.md`` 对象，按 limit 截断。"""
        items: list[MinioFileItem] = []
        objects = await self._client.list_objects(
            self.bucket, prefix=prefix, recursive=True
        )
        for obj in objects:
            if obj.object_name and obj.object_name.endswith(".md"):
                items.append(MinioFileItem(
                    object_key=obj.object_name,
                    size=obj.size or 0,
                    last_modified=str(obj.last_modified) if obj.last_modified else "",
                ))
            if len(items) >= limit:
                break
        log.info("列出 %d 个 .md 文件 (prefix=%r)", len(items), prefix)
        return items

    async def get_object_text(self, object_key: str) -> str:
        """读取对象内容并以 utf-8 解码返回；不存在时抛 MinioObjectNotFound。"""
        try:
            response = await self._client.get_object(self.bucket, object_key)
            if response is None:
                raise MinioObjectNotFound(object_key)
            data = await response.read()
            response.release()
            return data.decode("utf-8")
        except MinioObjectNotFound:
            raise
        except Exception as exc:
            log.error("读取 MinIO 文件失败: %s, err=%s", object_key, exc)
            raise MinioObjectNotFound(object_key) from exc

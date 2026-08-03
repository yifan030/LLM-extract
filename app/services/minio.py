# -*- coding: utf-8 -*-
"""MinIO 业务服务。"""
from app.domain.schemas import MinioFileItem
from app.repositories.minio import MinioRepository


class MinioService:
    def __init__(self, minio_repo: MinioRepository):
        self._minio = minio_repo

    async def list_files(self, prefix: str = "", limit: int = 50) -> list[MinioFileItem]:
        return await self._minio.list_md_files(prefix=prefix, limit=limit)

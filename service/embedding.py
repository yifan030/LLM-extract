# -*- coding: utf-8 -*-
"""Embedding 服务。"""

from conf.config import Settings
from libs.embed_client import EmbedClient
from logs.logging import get_logger


class EmbeddingService:
    def __init__(self, settings: Settings):
        self._client = EmbedClient(
            base_url=settings.embed_base_url,
            endpoint=settings.embed_endpoint,
            load_service=settings.embed_load_service,
            timeout=settings.embed_timeout,
        )
        self._dim = settings.embed_dim
        self._log = get_logger(__name__)

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """批量向量化。返回向量列表，顺序与输入一致。"""
        return await self._client.encode(texts)

    async def embed_one(self, text: str) -> list[float]:
        """向量化单条文本。返回单个向量。"""
        vectors = await self.embed_texts([text])
        return vectors[0]

    async def check_dimension(self) -> tuple[bool, str]:
        """启动自检：嵌入探针文本并校验 len(vector) == embed_dim。
        返回 (ok, message)。"""
        try:
            vec = await self.embed_one("dimension check probe")
            actual = len(vec)
            if actual == self._dim:
                return True, f"OK: embedding dimension {actual} matches config"
            return False, f"MISMATCH: embedding returned dim={actual}, config embed_dim={self._dim}"
        except Exception as e:
            return False, f"Embedding self-check failed: {e}"

# -*- coding: utf-8 -*-
"""BGEM3 embedding HTTP client."""
from typing import Any

import httpx


class EmbedClientError(RuntimeError):
    """Embedding service returned an invalid or unsuccessful response."""


class EmbedClient:
    """Small client for the server's ``/api/bgem3/encoder`` contract."""

    def __init__(
        self,
        base_url: str,
        endpoint: str,
        load_service: str,
        timeout: float = 60.0,
        client: httpx.AsyncClient | None = None,
    ):
        self._endpoint = endpoint
        self._load_service = load_service
        self._client = client or httpx.AsyncClient(base_url=base_url, timeout=timeout)

    async def encode(self, texts: list[str]) -> list[list[float]]:
        """Encode texts and return vectors in the input order."""
        response = await self._client.post(
            self._endpoint,
            json={"text_list": texts, "load_service": self._load_service},
        )
        response.raise_for_status()
        payload: Any = response.json()

        if not isinstance(payload, dict):
            raise EmbedClientError("Embedding response must be a JSON object")
        if payload.get("status") != 200:
            raise EmbedClientError(str(payload.get("message", "Embedding service failed")))

        vectors = payload.get("data")
        if not isinstance(vectors, list) or len(vectors) != len(texts):
            raise EmbedClientError("Embedding response data is invalid")
        if not all(isinstance(vector, list) for vector in vectors):
            raise EmbedClientError("Embedding response data must contain vectors")
        return vectors

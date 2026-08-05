# -*- coding: utf-8 -*-
"""向量搜索服务 — Milvus 混合检索（dense + sparse/BM25）封装。"""
from core.exceptions import SearchServiceError
from logs.logging import get_logger
from libs.milvus import MilvusRepository
from service.embedding import EmbeddingService

log = get_logger(__name__)

# 与 libs/milvus.py question collection 的标量字段一致；不返回 answer/score 等冗余字段
_SEARCH_OUTPUT_FIELDS = [
    "question_id", "paper_id", "number", "content", "question_type",
    "kp_names_l1", "kp_names_l2", "kp_names_l3", "kp_names_l4",
]

# 需要兜底为空列表的 ARRAY 字段（Milvus 返回的 entity 可能缺少或为 None）
_KP_ARRAY_FIELDS = ("kp_names_l1", "kp_names_l2", "kp_names_l3", "kp_names_l4")


class SearchService:
    def __init__(self, milvus_repo: MilvusRepository, embed_svc: EmbeddingService | None):
        self._milvus = milvus_repo
        self._embed = embed_svc

    async def search_questions(
        self,
        query_text: str,
        kp_filter: dict | None = None,  # {"level": 2, "name": "集合"} 或 {"level": 4, "name": "交集"}
        limit: int = 10,
    ) -> list[dict]:
        """混合搜索：embed 查询文本 → hybrid_search（带 KP 标量过滤）。

        返回归一化后的 hit 列表，每项仅含 ``_SEARCH_OUTPUT_FIELDS`` 中定义的字段，
        可直接用于构造 ``model.schemas.SearchHit``。

        依赖不可用时（Embedding 未配置 / Milvus 未部署）抛出
        :class:`SearchServiceError`，由全局异常处理器返回清晰的 503 JSON。
        """
        if self._embed is None:
            raise SearchServiceError(
                "向量搜索不可用: 未配置 Embedding API key",
                detail={"reason": "embedding_not_configured"},
            )

        # 由 KP 过滤条件构造 Milvus 标量预过滤表达式
        expr = None
        if kp_filter:
            level = kp_filter["level"]
            name = kp_filter["name"]
            expr = f'array_contains(kp_names_l{level}, "{name}")'

        try:
            query_vec = await self._embed.embed_one(query_text)
        except Exception as exc:  # noqa: BLE001 - 向调用方暴露可读错误信息
            log.error("向量搜索失败: embed 查询文本出错: %s", exc)
            raise SearchServiceError(
                f"向量化查询文本失败: {exc}",
                detail={"reason": "embedding_failed"},
            ) from exc

        try:
            results = await self._milvus.hybrid_search_questions(
                query_vec=query_vec,
                query_text=query_text,
                expr=expr,
                limit=limit,
                output_fields=_SEARCH_OUTPUT_FIELDS,
            )
        except Exception as exc:  # noqa: BLE001 - Milvus 不可用或查询出错
            log.error("向量搜索失败: Milvus 混合检索出错: %s", exc)
            raise SearchServiceError(
                f"Milvus 向量搜索不可用: {exc}",
                detail={"reason": "milvus_unavailable"},
            ) from exc

        return self._normalize_hits(results)

    @staticmethod
    def _normalize_hits(results: list[dict]) -> list[dict]:
        """将 Milvus hit（``{"id", "distance", "entity": {...}}``）归一化为纯 entity dict。

        ``entity`` 内含请求的 ``output_fields``；同时把可能缺失/为 None 的
        ``kp_names_l*`` ARRAY 字段兜底为空列表，避免 pydantic 校验失败。
        """
        normalized: list[dict] = []
        for hit in results or []:
            if isinstance(hit, dict) and "entity" in hit:
                entity = hit["entity"]
            else:
                entity = hit
            if not isinstance(entity, dict):
                continue
            for key in _KP_ARRAY_FIELDS:
                if not entity.get(key):
                    entity[key] = []
            normalized.append(entity)
        return normalized

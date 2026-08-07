# -*- coding: utf-8 -*-
"""Milvus 向量库封装（async + pymilvus AsyncMilvusClient）。

MilvusRepository 是数据访问层对 Milvus 的封装：基于 pymilvus 的
``AsyncMilvusClient`` 提供完全异步的 collection 管理、数据 upsert 与
向量混合检索（dense + sparse/BM25）。

与 :class:`libs.hugegraph.HugeGraphRepository` 不同，Milvus 客户端是
长连接、重量级对象，因此这里复用一个 client（惰性创建一次），而不是
每次调用都新建。
"""
import asyncio
from functools import wraps

from pymilvus import (
    AnnSearchRequest,
    AsyncMilvusClient,
    DataType,
    Function,
    FunctionType,
    RRFRanker,
)
from pymilvus.exceptions import MilvusException

from conf.config import Settings
from logs.logging import get_logger

log = get_logger(__name__)

# 重试配置：仅对 Milvus gRPC 层瞬时错误重试
_MAX_RETRIES = 3
_RETRY_BACKOFF = [0.1, 0.3, 0.7]  # 秒


def _retry_on_transient_error(func):
    """异步重试装饰器：对 MilvusException / 网络超时等瞬时错误自动重试。

    最多 ``_MAX_RETRIES`` 次，退避间隔见 ``_RETRY_BACKOFF``。
    schema 错误 / 参数错误等非瞬时异常会立即上抛，不浪费重试。
    """

    @wraps(func)
    async def wrapper(*args, **kwargs):
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                return await func(*args, **kwargs)
            except MilvusException as exc:
                last_exc = exc
                if attempt < _MAX_RETRIES - 1:
                    delay = _RETRY_BACKOFF[attempt]
                    log.warning(
                        "Milvus 调用失败 (attempt %d/%d)，%s 后重试: %s",
                        attempt + 1, _MAX_RETRIES, delay, exc,
                    )
                    await asyncio.sleep(delay)
            except asyncio.TimeoutError as exc:
                last_exc = exc
                if attempt < _MAX_RETRIES - 1:
                    delay = _RETRY_BACKOFF[attempt]
                    log.warning(
                        "Milvus 调用超时 (attempt %d/%d)，%s 后重试: %s",
                        attempt + 1, _MAX_RETRIES, delay, exc,
                    )
                    await asyncio.sleep(delay)
        raise last_exc  # type: ignore[misc]

    return wrapper


class MilvusRepository:
    """Async data-access layer over Milvus (via pymilvus AsyncMilvusClient)."""

    def __init__(self, settings: Settings):
        self._settings = settings
        # 长连接 client：惰性创建一次并复用。
        self._client: AsyncMilvusClient | None = None

    def _get_client(self) -> AsyncMilvusClient:
        """Lazily create (once) and return the long-lived async client."""
        if self._client is None:
            self._client = AsyncMilvusClient(
                uri=self._settings.milvus_uri,
                db_name=self._settings.milvus_db,
            )
        return self._client

    async def close(self) -> None:
        """关闭底层 Milvus client（若已创建）。"""
        if self._client is not None:
            await self._client.close()
            self._client = None

    # ── Collection 管理 ────────────────────────────────────────────

    async def ensure_collections(self) -> None:
        """幂等创建两个 collection（schema + 索引 + BM25 Function）并加载。

        collection 已存在则跳过创建；重复调用仍会确保集合已 load，安全幂等。
        """
        client = self._get_client()
        await self._ensure_collection(
            self._settings.milvus_question_collection,
            self._build_question_schema(client),
            self._build_question_index_params(client),
        )
        await self._ensure_collection(
            self._settings.milvus_kp_collection,
            self._build_kp_schema(client),
            self._build_kp_index_params(client),
        )

    async def _ensure_collection(self, name, schema, index_params) -> None:
        client = self._get_client()
        if await self._collection_exists(name):
            log.info("collection 已存在，跳过创建: %s", name)
        else:
            try:
                await client.create_collection(
                    collection_name=name,
                    schema=schema,
                    index_params=index_params,
                )
                log.info("创建 collection 成功: %s", name)
            except Exception as exc:  # noqa: BLE001 - 检查与创建间的并发竞态
                if "already exist" in str(exc).lower():
                    log.info("collection 已存在（并发），跳过创建: %s", name)
                else:
                    raise
        await client.load_collection(name, timeout=60.0)
        log.info("collection 已加载: %s", name)

    async def _collection_exists(self, name: str) -> bool:
        """检查 collection 是否存在（通过 ``list_collections`` 公开 API）。"""
        client = self._get_client()
        collections = await client.list_collections()
        return name in collections

    def _build_question_schema(self, client: AsyncMilvusClient):
        """题目 collection 的 schema（含 ``content`` 的 BM25 Function）。"""
        embed_dim = self._settings.embed_dim
        schema = client.create_schema()
        schema.add_field(
            field_name="question_id", datatype=DataType.VARCHAR,
            is_primary=True, max_length=64,
        )
        schema.add_field(
            field_name="paper_id", datatype=DataType.VARCHAR, max_length=64,
        )
        schema.add_field(
            field_name="number", datatype=DataType.VARCHAR, max_length=16,
        )
        schema.add_field(
            field_name="content", datatype=DataType.VARCHAR, max_length=65535,
            enable_analyzer=True, analyzer_params={"type": "chinese"},
        )
        schema.add_field(
            field_name="answer", datatype=DataType.VARCHAR,
            max_length=65535, nullable=True,
        )
        schema.add_field(
            field_name="question_type", datatype=DataType.VARCHAR, max_length=16,
        )
        schema.add_field(
            field_name="subject", datatype=DataType.VARCHAR, max_length=16,
        )
        schema.add_field(
            field_name="grade", datatype=DataType.VARCHAR,
            max_length=16, nullable=True, default_value=None,
        )
        schema.add_field(
            field_name="score", datatype=DataType.INT64,
            nullable=True, default_value=None,
        )
        schema.add_field(
            field_name="kp_names_l1", datatype=DataType.ARRAY,
            element_type=DataType.VARCHAR, max_capacity=8, max_length=128,
        )
        schema.add_field(
            field_name="kp_ids_l1", datatype=DataType.ARRAY,
            element_type=DataType.VARCHAR, max_capacity=8, max_length=128,
        )
        schema.add_field(
            field_name="kp_names_l2", datatype=DataType.ARRAY,
            element_type=DataType.VARCHAR, max_capacity=16, max_length=128,
        )
        schema.add_field(
            field_name="kp_ids_l2", datatype=DataType.ARRAY,
            element_type=DataType.VARCHAR, max_capacity=16, max_length=128,
        )
        schema.add_field(
            field_name="kp_names_l3", datatype=DataType.ARRAY,
            element_type=DataType.VARCHAR, max_capacity=32, max_length=128,
        )
        schema.add_field(
            field_name="kp_ids_l3", datatype=DataType.ARRAY,
            element_type=DataType.VARCHAR, max_capacity=32, max_length=128,
        )
        schema.add_field(
            field_name="kp_names_l4", datatype=DataType.ARRAY,
            element_type=DataType.VARCHAR, max_capacity=32, max_length=128,
        )
        schema.add_field(
            field_name="kp_ids_l4", datatype=DataType.ARRAY,
            element_type=DataType.VARCHAR, max_capacity=32, max_length=128,
        )
        schema.add_field(
            field_name="dense_vector", datatype=DataType.FLOAT_VECTOR, dim=embed_dim,
        )
        schema.add_field(
            field_name="sparse_vector", datatype=DataType.SPARSE_FLOAT_VECTOR,
        )
        bm25_fn = Function(
            name="content_bm25",
            input_field_names=["content"],
            output_field_names="sparse_vector",
            function_type=FunctionType.BM25,
        )
        schema.add_function(bm25_fn)
        return schema

    def _build_question_index_params(self, client: AsyncMilvusClient):
        index_params = client.prepare_index_params()
        index_params.add_index(
            field_name="dense_vector",
            index_type="HNSW",
            metric_type="COSINE",
            params={"M": 16, "efConstruction": 200},
        )
        index_params.add_index(
            field_name="sparse_vector",
            index_type="SPARSE_INVERTED_INDEX",
            metric_type="BM25",
            params={"bm25_k1": 1.2, "bm25_b": 0.75},
        )
        return index_params

    def _build_kp_schema(self, client: AsyncMilvusClient):
        embed_dim = self._settings.embed_dim
        schema = client.create_schema()
        schema.add_field(
            field_name="kp_id", datatype=DataType.VARCHAR,
            is_primary=True, max_length=128,
        )
        schema.add_field(
            field_name="name", datatype=DataType.VARCHAR, max_length=128,
        )
        schema.add_field(
            field_name="level", datatype=DataType.INT64,
        )
        schema.add_field(
            field_name="subject", datatype=DataType.VARCHAR, max_length=16,
        )
        schema.add_field(
            field_name="description", datatype=DataType.VARCHAR,
            max_length=1024, nullable=True,
        )
        schema.add_field(
            field_name="path", datatype=DataType.VARCHAR, max_length=512,
        )
        schema.add_field(
            field_name="dense_vector", datatype=DataType.FLOAT_VECTOR, dim=embed_dim,
        )
        return schema

    def _build_kp_index_params(self, client: AsyncMilvusClient):
        index_params = client.prepare_index_params()
        index_params.add_index(
            field_name="dense_vector",
            index_type="HNSW",
            metric_type="COSINE",
            params={"M": 16, "efConstruction": 200},
        )
        index_params.add_index(
            field_name="level", index_type="INVERTED",
        )
        return index_params

    # ── 写入 ──────────────────────────────────────────────────────

    @_retry_on_transient_error
    async def upsert_question(self, data: list[dict]) -> None:
        """插入/更新题目行。

        ``data`` 中每个 dict 需含全部标量字段 + ``dense_vector``；
        ``sparse_vector`` 由 BM25 Function 在写入时自动生成，无需传入。
        """
        client = self._get_client()
        await client.upsert(
            collection_name=self._settings.milvus_question_collection,
            data=data,
        )
        log.info("upsert 题目 %d 条", len(data))

    @_retry_on_transient_error
    async def upsert_kp(self, data: list[dict]) -> None:
        """插入/更新知识点行（``data`` 含全部标量字段 + ``dense_vector``）。"""
        client = self._get_client()
        await client.upsert(
            collection_name=self._settings.milvus_kp_collection,
            data=data,
        )
        log.info("upsert 知识点 %d 条", len(data))

    # ── 检索 ──────────────────────────────────────────────────────

    @_retry_on_transient_error
    async def hybrid_search_questions(
        self, query_vec, expr, limit, output_fields, query_text: str = "",
    ) -> list[dict]:
        """Dense + sparse(BM25) 混合检索题目，返回归一化的 hit 列表。

        - ``query_vec``: 查询文本的 dense embedding。
        - ``query_text``: sparse(BM25) 全文检索的查询文本；默认空串。
        - ``expr``: 标量预过滤表达式（如 ``array_contains(kp_names_l2, "集合")``）。
        - ``limit``: 最终返回条数（两个子请求各取 ``limit*5`` 再经 RRF 融合）。
        - ``output_fields``: 需要返回的标量字段。

        hit 结构为 ``{"id", "distance", "entity": {...}}``。
        """
        client = self._get_client()
        fetch_limit = limit * 5
        dense_req = AnnSearchRequest(
            data=[query_vec],
            anns_field="dense_vector",
            param={"metric_type": "COSINE", "params": {"ef": max(64, fetch_limit)}},
            limit=fetch_limit,
            expr=expr,
        )
        sparse_req = AnnSearchRequest(
            data=[query_text],
            anns_field="sparse_vector",
            param={"metric_type": "BM25"},
            limit=fetch_limit,
            expr=expr,
        )
        results = await client.hybrid_search(
            collection_name=self._settings.milvus_question_collection,
            reqs=[dense_req, sparse_req],
            ranker=RRFRanker(k=60),
            limit=limit,
            output_fields=output_fields,
        )
        return self._normalize_hits(results)

    @_retry_on_transient_error
    async def search_kps(self, query_vec, limit, level=4, expr=None) -> list[dict]:
        """按 dense 向量在知识点 collection 中检索。

        默认只召回 ``level == 4`` 的 KP；可传 ``expr`` 追加过滤条件
        （如 ``subject == "math"``），与 level 条件以 AND 组合。
        """
        final_expr = f"level == {level}"
        if expr:
            final_expr += f" and ({expr})"
        client = self._get_client()
        results = await client.search(
            collection_name=self._settings.milvus_kp_collection,
            data=[query_vec],
            anns_field="dense_vector",
            search_params={"metric_type": "COSINE", "params": {"ef": 64}},
            limit=limit,
            filter=final_expr,
            output_fields=["kp_id", "name", "level", "description", "path"],
        )
        return self._normalize_hits(results)

    async def query_questions(self, expr, limit=100, output_fields=None) -> list[dict]:
        """纯标量查询（无向量），列出某 KP 下的全部题目。

        ``expr`` 为 Milvus 标量过滤表达式，如
        ``array_contains(kp_names_l4, "交集")``。
        """
        client = self._get_client()
        return await client.query(
            collection_name=self._settings.milvus_question_collection,
            filter=expr,
            output_fields=output_fields,
            limit=limit,
        )

    async def query_by_kp(self, expr, limit=100, output_fields=None) -> list[dict]:
        """按 KP 过滤表达式列出题目（:meth:`query_questions` 的别名）。"""
        return await self.query_questions(
            expr=expr, limit=limit, output_fields=output_fields,
        )

    @staticmethod
    def _normalize_hits(results: list[list[dict]]) -> list[dict]:
        """search/hybrid_search 返回 ``list[list[dict]]``；单 query 时取首个内层列表。"""
        if not results:
            return []
        return results[0]

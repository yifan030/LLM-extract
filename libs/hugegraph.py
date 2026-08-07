# -*- coding: utf-8 -*-
"""HugeGraph REST API 封装（async + httpx）。

HugeGraphRepository 是数据访问层对 HugeGraph 的封装：基于 httpx.AsyncClient
提供完全异步的顶点/边读写。每个公共方法都通过
``async with await self._client() as client`` 模式获取一个全新的 client，
避免跨请求共享连接，天然适配并发场景。
"""
from typing import Any

import httpx

from conf.config import Settings
from core.exceptions import HugeGraphTimeout
from logs.decorators import log_step
from logs.logging import get_logger
from model.models import Edge, Vertex

log = get_logger(__name__)


@log_step
class HugeGraphRepository:
    """Async data-access layer over HugeGraph's REST API."""

    def __init__(self, settings: Settings):
        self.base_url = settings.hg_base_url
        self.hg_user = settings.hg_user
        self.hg_passwd = settings.hg_passwd

    async def _client(self) -> httpx.AsyncClient:
        """Return a fresh authenticated :class:`httpx.AsyncClient`."""
        return httpx.AsyncClient(
            auth=httpx.BasicAuth(self.hg_user, self.hg_passwd),
            timeout=httpx.Timeout(30.0),
        )

    async def load_level4_names(self) -> list[str]:
        """加载所有 level=4 的知识点名称。"""
        url = f"{self.base_url}/graph/vertices?label=knowledge_point&limit=10000"
        try:
            async with await self._client() as client:
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()
        except httpx.TimeoutException as exc:
            raise HugeGraphTimeout(
                f"HugeGraph GET 顶点列表 超时: {url}",
                detail={"url": url},
            ) from exc
        names: list[str] = []
        for v in data.get("vertices", []):
            props = v.get("properties", {})
            if props.get("level") == 4:
                name = props.get("name", "")
                if name:
                    names.append(name)
        return names

    async def preload_question_types(self) -> dict[str, str]:
        """预加载题型 name -> 物理 id 映射。"""
        url = f"{self.base_url}/graph/vertices?label=question_type"
        cache: dict[str, str] = {}
        try:
            async with await self._client() as client:
                resp = await client.get(url)
                resp.raise_for_status()
                for v in resp.json().get("vertices", []):
                    name = v.get("properties", {}).get("name")
                    if name:
                        cache[name] = v.get("id")
        except httpx.TimeoutException as exc:
            raise HugeGraphTimeout(
                f"HugeGraph GET 顶点列表 超时: {url}",
                detail={"url": url},
            ) from exc
        return cache

    async def create_vertex(self, vertex: Vertex) -> tuple[bool, bool]:
        """创建顶点，返回 ``(created, duplicated)``。

        200/201 -> created；400 且文案含 "already exists" -> duplicated；
        其余情况二者皆 False（schema 拒绝、服务端异常等）。
        """
        payload = {
            "label": vertex.label,
            "id": vertex.id,
            "type": "vertex",
            "properties": vertex.properties,
        }
        url = f"{self.base_url}/graph/vertices"
        try:
            async with await self._client() as client:
                resp = await client.post(url, json=payload)
        except httpx.TimeoutException as exc:
            raise HugeGraphTimeout(
                f"HugeGraph POST vertices 超时: {url}",
                detail={"url": url, "vertex_label": vertex.label, "vertex_id": vertex.id},
            ) from exc
        if resp.status_code in (200, 201):
            log.info("顶点创建成功: %s (%s)", vertex.label, vertex.id)
            return True, False
        if resp.status_code == 400 and "already exists" in resp.text.lower():
            log.debug("顶点已存在，跳过: %s (%s)", vertex.label, vertex.id)
            return False, True
        # 400 非 duplicate / 5xx 等：尝试提取 HugeGraph 返回的错误消息
        reason = resp.text
        try:
            body = resp.json()
            reason = body.get("message", reason)
        except Exception:  # noqa: BLE001
            pass
        log.error(
            "顶点创建失败: label=%s id=%s status=%d reason=%s payload_keys=%s",
            vertex.label, vertex.id, resp.status_code, reason,
            list(vertex.properties.keys()),
        )
        return False, False

    async def create_edge(self, edge: Edge) -> tuple[bool, bool]:
        """创建边，返回 ``(created, duplicated)``。

        200/201 -> created；400 且文案含 "already exists" -> duplicated；
        其余情况二者皆 False。
        """
        url = f"{self.base_url}/graph/edges"
        payload: dict[str, Any] = {
            "label": edge.label,
            "outV": edge.outV,
            "inV": edge.inV,
            "properties": edge.properties,
        }
        try:
            async with await self._client() as client:
                resp = await client.post(url, json=payload)
        except httpx.TimeoutException as exc:
            raise HugeGraphTimeout(
                f"HugeGraph POST edges 超时: {url}",
                detail={"url": url, "edge_label": edge.label},
            ) from exc
        if resp.status_code in (200, 201):
            log.info("边创建成功: %s -[%s]-> %s", edge.outV, edge.label, edge.inV)
            return True, False
        if resp.status_code == 400 and "already exists" in resp.text.lower():
            log.debug("边已存在，跳过: %s -[%s]-> %s", edge.outV, edge.label, edge.inV)
            return False, True
        log.error("边创建失败: %s -[%s]-> %s: %s", edge.outV, edge.label, edge.inV, resp.text)
        return False, False

    async def list_vertices(
        self, label: str, limit: int = 100, offset: int = 0
    ) -> list[dict]:
        """分页列出指定 label 的顶点。"""
        url = f"{self.base_url}/graph/vertices?label={label}&limit={limit}"
        if offset:
            url += f"&offset={offset}"
        try:
            async with await self._client() as client:
                resp = await client.get(url)
                resp.raise_for_status()
                return resp.json().get("vertices", [])
        except httpx.TimeoutException as exc:
            raise HugeGraphTimeout(
                f"HugeGraph GET 顶点列表 超时: {url}",
                detail={"url": url, "label": label},
            ) from exc

    async def count_vertices(self, label: str) -> int:
        """估算指定 label 的顶点总数（依赖响应中的 ``total`` 字段）。"""
        url = f"{self.base_url}/graph/vertices?label={label}&limit=1"
        async with await self._client() as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.json().get("total", 0)

    async def get_vertex(self, vertex_id: str) -> dict | None:
        """按 id 查询顶点；不存在时返回 None。

        HugeGraph CUSTOMIZE_STRING 顶点 ID 在 URL 中必须用双引号包裹，
        否则会被误解析为 Number 类型。
        """
        url = f'{self.base_url}/graph/vertices/"{vertex_id}"'
        try:
            async with await self._client() as client:
                resp = await client.get(url)
                if resp.status_code == 404:
                    return None
                resp.raise_for_status()
                return resp.json()
        except httpx.TimeoutException as exc:
            raise HugeGraphTimeout(
                f"HugeGraph GET 顶点 超时: {url}",
                detail={"url": url, "vertex_id": vertex_id},
            ) from exc

    async def get_vertex_edges(
        self, vertex_id: str, direction: str = "OUT", label: str | None = None
    ) -> list[dict]:
        """查询顶点的出/入边。

        HugeGraph 要求 direction 大写 (OUT/IN/BOTH)，
        CUSTOMIZE_STRING 顶点 ID 需用双引号包裹。
        """
        url = f'{self.base_url}/graph/edges?vertex_id=%22{vertex_id}%22&direction={direction.upper()}'
        if label:
            url += f"&label={label}"
        try:
            async with await self._client() as client:
                resp = await client.get(url)
                resp.raise_for_status()
                return resp.json().get("edges", [])
        except httpx.TimeoutException as exc:
            raise HugeGraphTimeout(
                f"HugeGraph GET 边列表 超时: {url}",
                detail={"url": url, "vertex_id": vertex_id, "direction": direction.upper()},
            ) from exc

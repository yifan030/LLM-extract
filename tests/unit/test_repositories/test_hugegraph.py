# -*- coding: utf-8 -*-
"""Tests for app.repositories.hugegraph.HugeGraphRepository (async + httpx)."""
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.core.config import Settings
from app.domain.models import Edge, Vertex
from app.repositories.hugegraph import HugeGraphRepository


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _make_client(resp: MagicMock) -> AsyncMock:
    """Build an AsyncMock client compatible with the
    ``async with await self._client() as client`` pattern:
    awaiting ``_client`` yields the same object whose ``__aenter__`` returns
    itself, so the ``async with`` block sees the client the test configured.
    """
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.__aexit__.return_value = False
    client.get.return_value = resp
    client.post.return_value = resp
    return client


def _make_resp(status_code: int = 200, json_data: dict | None = None, text: str = "") -> MagicMock:
    """Build a plain (synchronous) httpx.Response stand-in.

    ``Response.json()`` is synchronous in httpx, so the mock uses MagicMock
    (not AsyncMock) to return the payload immediately.
    """
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    resp.json.return_value = json_data or {}
    resp.raise_for_status = MagicMock()
    return resp


def _make_repo(client: AsyncMock) -> HugeGraphRepository:
    """Build a repository instance without calling __init__.

    ``_client`` is stubbed as an AsyncMock that resolves to ``client`` when
    awaited; ``base_url`` is pinned to a known value for URL assertions.
    """
    repo = HugeGraphRepository.__new__(HugeGraphRepository)
    repo._client = AsyncMock(return_value=client)
    repo.base_url = "http://h:8080/gs/g"
    return repo


# --------------------------------------------------------------------------
# load_level4_names
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_load_level4_names_filters_level_4_only():
    mock_resp = _make_resp(json_data={
        "vertices": [
            {"properties": {"name": "交集", "level": 4}},
            {"properties": {"name": "子集", "level": 4}},
            {"properties": {"name": "函数", "level": 3}},
            {"properties": {"name": "无等级", "level": None}},
        ]
    })
    mock_client = _make_client(mock_resp)
    repo = _make_repo(mock_client)

    result = await repo.load_level4_names()

    assert result == ["交集", "子集"]


@pytest.mark.asyncio
async def test_load_level4_names_queries_knowledge_point_label():
    mock_resp = _make_resp(json_data={"vertices": []})
    mock_client = _make_client(mock_resp)
    repo = _make_repo(mock_client)

    await repo.load_level4_names()

    url = mock_client.get.call_args.args[0]
    assert "label=knowledge_point" in url
    assert "limit=10000" in url


@pytest.mark.asyncio
async def test_load_level4_names_drops_blank_names():
    mock_resp = _make_resp(json_data={
        "vertices": [
            {"properties": {"name": "", "level": 4}},
            {"properties": {"level": 4}},
            {"properties": {"name": "有效", "level": 4}},
        ]
    })
    mock_client = _make_client(mock_resp)
    repo = _make_repo(mock_client)

    result = await repo.load_level4_names()

    assert result == ["有效"]


# --------------------------------------------------------------------------
# preload_question_types
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_preload_question_types_builds_name_to_id_cache():
    mock_resp = _make_resp(json_data={
        "vertices": [
            {"id": "qt_7", "properties": {"name": "单选题"}},
            {"id": "qt_8", "properties": {"name": "多选题"}},
            {"id": "qt_9", "properties": {}},
        ]
    })
    mock_client = _make_client(mock_resp)
    repo = _make_repo(mock_client)

    cache = await repo.preload_question_types()

    assert cache == {"单选题": "qt_7", "多选题": "qt_8"}


@pytest.mark.asyncio
async def test_preload_question_types_queries_question_type_label():
    mock_resp = _make_resp(json_data={"vertices": []})
    mock_client = _make_client(mock_resp)
    repo = _make_repo(mock_client)

    await repo.preload_question_types()

    url = mock_client.get.call_args.args[0]
    assert "label=question_type" in url


# --------------------------------------------------------------------------
# create_vertex
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_create_vertex_success():
    mock_resp = _make_resp(status_code=201, text="")
    mock_client = _make_client(mock_resp)
    repo = _make_repo(mock_client)

    v = Vertex(label="exam_paper", id="paper_1", properties={"title": "test"})
    created, duplicated = await repo.create_vertex(v)

    assert created is True
    assert duplicated is False


@pytest.mark.asyncio
async def test_create_vertex_accepts_200_as_success():
    mock_resp = _make_resp(status_code=200, text="")
    mock_client = _make_client(mock_resp)
    repo = _make_repo(mock_client)

    v = Vertex(label="exam_paper", id="paper_1", properties={"title": "test"})
    created, duplicated = await repo.create_vertex(v)

    assert created is True
    assert duplicated is False


@pytest.mark.asyncio
async def test_create_vertex_duplicated():
    mock_resp = _make_resp(status_code=400, text="Vertex id \"paper_1\" already exists")
    mock_client = _make_client(mock_resp)
    repo = _make_repo(mock_client)

    v = Vertex(label="exam_paper", id="paper_1", properties={"title": "test"})
    created, duplicated = await repo.create_vertex(v)

    assert created is False
    assert duplicated is True


@pytest.mark.asyncio
async def test_create_vertex_failure_counts_neither():
    mock_resp = _make_resp(status_code=500, text="server error")
    mock_client = _make_client(mock_resp)
    repo = _make_repo(mock_client)

    v = Vertex(label="exam_paper", id="paper_1", properties={"title": "test"})
    created, duplicated = await repo.create_vertex(v)

    assert created is False
    assert duplicated is False


@pytest.mark.asyncio
async def test_create_vertex_posts_expected_payload():
    mock_resp = _make_resp(status_code=201, text="")
    mock_client = _make_client(mock_resp)
    repo = _make_repo(mock_client)

    v = Vertex(label="exam_paper", id="paper_1", properties={"title": "test"})
    await repo.create_vertex(v)

    url = mock_client.post.call_args.args[0]
    payload = mock_client.post.call_args.kwargs["json"]
    assert url == "http://h:8080/gs/g/graph/vertices"
    assert payload == {
        "label": "exam_paper",
        "id": "paper_1",
        "type": "vertex",
        "properties": {"title": "test"},
    }


# --------------------------------------------------------------------------
# create_edge
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_create_edge_success():
    mock_resp = _make_resp(status_code=201, text="")
    mock_client = _make_client(mock_resp)
    repo = _make_repo(mock_client)

    e = Edge(label="belongs_to", outV="question_1", inV="kp_1", properties={})
    ok = await repo.create_edge(e)

    assert ok is True


@pytest.mark.asyncio
async def test_create_edge_failure():
    mock_resp = _make_resp(status_code=400, text="bad edge")
    mock_client = _make_client(mock_resp)
    repo = _make_repo(mock_client)

    e = Edge(label="belongs_to", outV="question_1", inV="kp_1", properties={})
    ok = await repo.create_edge(e)

    assert ok is False


@pytest.mark.asyncio
async def test_create_edge_posts_expected_payload():
    mock_resp = _make_resp(status_code=201, text="")
    mock_client = _make_client(mock_resp)
    repo = _make_repo(mock_client)

    e = Edge(label="belongs_to", outV="question_1", inV="kp_1", properties={"weight": 1})
    await repo.create_edge(e)

    url = mock_client.post.call_args.args[0]
    payload = mock_client.post.call_args.kwargs["json"]
    assert url == "http://h:8080/gs/g/graph/edges"
    assert payload == {
        "label": "belongs_to",
        "outV": "question_1",
        "inV": "kp_1",
        "properties": {"weight": 1},
    }


# --------------------------------------------------------------------------
# list_vertices
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_list_vertices_returns_vertices():
    mock_resp = _make_resp(json_data={"vertices": [{"id": "v1"}, {"id": "v2"}]})
    mock_client = _make_client(mock_resp)
    repo = _make_repo(mock_client)

    result = await repo.list_vertices("question", limit=50)

    assert result == [{"id": "v1"}, {"id": "v2"}]


@pytest.mark.asyncio
async def test_list_vertices_uses_label_and_limit_and_offset():
    mock_resp = _make_resp(json_data={"vertices": []})
    mock_client = _make_client(mock_resp)
    repo = _make_repo(mock_client)

    await repo.list_vertices("question", limit=50, offset=100)

    url = mock_client.get.call_args.args[0]
    assert "label=question" in url
    assert "limit=50" in url
    assert "offset=100" in url


@pytest.mark.asyncio
async def test_list_vertices_omits_offset_when_zero():
    mock_resp = _make_resp(json_data={"vertices": []})
    mock_client = _make_client(mock_resp)
    repo = _make_repo(mock_client)

    await repo.list_vertices("question")

    url = mock_client.get.call_args.args[0]
    assert "offset=" not in url


# --------------------------------------------------------------------------
# get_vertex
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_vertex_returns_vertex():
    mock_resp = _make_resp(json_data={"id": "v1", "label": "question", "properties": {}})
    mock_client = _make_client(mock_resp)
    repo = _make_repo(mock_client)

    result = await repo.get_vertex("v1")

    assert result == {"id": "v1", "label": "question", "properties": {}}
    url = mock_client.get.call_args.args[0]
    assert url == "http://h:8080/gs/g/graph/vertices/v1"


@pytest.mark.asyncio
async def test_get_vertex_not_found_returns_none():
    mock_resp = _make_resp(status_code=404, json_data={})
    mock_client = _make_client(mock_resp)
    repo = _make_repo(mock_client)

    result = await repo.get_vertex("missing")

    assert result is None
    # 404 must not bubble up as an HTTP error
    mock_resp.raise_for_status.assert_not_called()


# --------------------------------------------------------------------------
# get_vertex_edges
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_vertex_edges_returns_edges():
    mock_resp = _make_resp(json_data={"edges": [{"id": "e1"}, {"id": "e2"}]})
    mock_client = _make_client(mock_resp)
    repo = _make_repo(mock_client)

    result = await repo.get_vertex_edges("v1")

    assert result == [{"id": "e1"}, {"id": "e2"}]


@pytest.mark.asyncio
async def test_get_vertex_edges_uses_direction_and_label():
    mock_resp = _make_resp(json_data={"edges": []})
    mock_client = _make_client(mock_resp)
    repo = _make_repo(mock_client)

    await repo.get_vertex_edges("v1", direction="in", label="belongs_to")

    url = mock_client.get.call_args.args[0]
    assert "vertex_id=v1" in url
    assert "direction=in" in url
    assert "label=belongs_to" in url


@pytest.mark.asyncio
async def test_get_vertex_edges_omits_label_when_none():
    mock_resp = _make_resp(json_data={"edges": []})
    mock_client = _make_client(mock_resp)
    repo = _make_repo(mock_client)

    await repo.get_vertex_edges("v1", direction="out")

    url = mock_client.get.call_args.args[0]
    assert "label=" not in url


# --------------------------------------------------------------------------
# count_vertices
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_count_vertices_returns_total():
    mock_resp = _make_resp(json_data={"total": 42, "vertices": []})
    mock_client = _make_client(mock_resp)
    repo = _make_repo(mock_client)

    total = await repo.count_vertices("question")

    assert total == 42


# --------------------------------------------------------------------------
# _client construction
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_client_uses_basic_auth_and_base_url():
    settings = Settings()
    repo = HugeGraphRepository(settings)

    client = await repo._client()

    assert isinstance(client, httpx.AsyncClient)
    assert isinstance(client.auth, httpx.BasicAuth)
    assert repo.base_url == settings.hg_base_url
    await client.aclose()

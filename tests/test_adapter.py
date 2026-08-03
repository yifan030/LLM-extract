# -*- coding: utf-8 -*-
"""Tests for the Stage 3 HugeGraph adapter."""
from unittest.mock import MagicMock, patch

from exam_extract.adapter import HugeGraphAdapter
from exam_extract.models import Edge, IntermediateJson, Metadata, Vertex


def _make_intermediate(vertices=None, edges=None) -> IntermediateJson:
    return IntermediateJson(
        metadata=Metadata(source_file="test.md", generated_at="2026-08-02T10:00:00"),
        vertices=vertices or [],
        edges=edges or [],
        unmatched=[],
    )


def _ok_response() -> MagicMock:
    resp = MagicMock()
    resp.status_code = 201
    resp.text = ""
    return resp


def test_import_skips_existing_question_vertex():
    intermediate = _make_intermediate(
        vertices=[Vertex(label="question", id="question_123",
                         properties={"question_id": 123, "content": "x"})],
    )
    adapter = HugeGraphAdapter("localhost", 8080, "admin", "admin")

    with patch("exam_extract.adapter.requests.get") as mock_get, \
            patch.object(adapter, "_post_vertex") as mock_post:
        mock_get.return_value.json.return_value = {"vertices": []}
        mock_post.return_value = MagicMock(
            status_code=400,
            text='{"message":"Vertex id \\"question_123\\" already exists"}',
        )
        report = adapter.import_data(intermediate)
        assert report["vertices_created"] == 0
        assert report["vertices_duplicated"] == 1


def test_import_creates_vertex():
    intermediate = _make_intermediate(
        vertices=[Vertex(label="question", id="question_1", properties={"content": "x"})],
    )
    adapter = HugeGraphAdapter("localhost", 8080, "admin", "admin")

    with patch("exam_extract.adapter.requests.get") as mock_get, \
            patch.object(adapter, "_post_vertex") as mock_post:
        mock_get.return_value.json.return_value = {"vertices": []}
        mock_post.return_value = _ok_response()
        report = adapter.import_data(intermediate)

    assert report["vertices_total"] == 1
    assert report["vertices_created"] == 1
    assert report["vertices_duplicated"] == 0
    payload = mock_post.call_args[0][0]
    assert payload["label"] == "question"
    assert payload["id"] == "question_1"
    assert payload["type"] == "vertex"
    assert payload["properties"] == {"content": "x"}


def test_import_vertex_unexpected_failure_counts_neither():
    intermediate = _make_intermediate(
        vertices=[Vertex(label="question", id="question_1", properties={})],
    )
    adapter = HugeGraphAdapter("localhost", 8080, "admin", "admin")

    with patch("exam_extract.adapter.requests.get") as mock_get, \
            patch.object(adapter, "_post_vertex") as mock_post:
        mock_get.return_value.json.return_value = {"vertices": []}
        mock_post.return_value = MagicMock(status_code=500, text="server error")
        report = adapter.import_data(intermediate)

    assert report["vertices_created"] == 0
    assert report["vertices_duplicated"] == 0


def test_import_creates_edge():
    intermediate = _make_intermediate(
        edges=[Edge(label="belongs_to", outV="question_1", inV="kp_1", properties={})],
    )
    adapter = HugeGraphAdapter("localhost", 8080, "admin", "admin")

    with patch("exam_extract.adapter.requests.get") as mock_get, \
            patch("exam_extract.adapter.requests.post") as mock_post:
        mock_get.return_value.json.return_value = {"vertices": []}
        mock_post.return_value = _ok_response()
        report = adapter.import_data(intermediate)

    assert report["edges_total"] == 1
    assert report["edges_created"] == 1
    assert report["edges_failed"] == 0
    payload = mock_post.call_args.kwargs["json"]
    assert payload == {"label": "belongs_to", "outV": "question_1", "inV": "kp_1", "properties": {}}


def test_import_resolves_belongs_to_type_via_cache():
    intermediate = _make_intermediate(
        edges=[Edge(label="belongs_to_type", outV="question_1", inV="单选题", properties={})],
    )
    adapter = HugeGraphAdapter("localhost", 8080, "admin", "admin")

    with patch("exam_extract.adapter.requests.get") as mock_get, \
            patch("exam_extract.adapter.requests.post") as mock_post:
        mock_get.return_value.json.return_value = {
            "vertices": [{"id": "qt_7", "properties": {"name": "单选题"}}]
        }
        mock_post.return_value = _ok_response()
        report = adapter.import_data(intermediate)

    assert report["edges_created"] == 1
    assert mock_post.call_args.kwargs["json"]["inV"] == "qt_7"


def test_import_belongs_to_type_missing_from_cache_fails_without_post():
    intermediate = _make_intermediate(
        edges=[Edge(label="belongs_to_type", outV="question_1", inV="论述题", properties={})],
    )
    adapter = HugeGraphAdapter("localhost", 8080, "admin", "admin")

    with patch("exam_extract.adapter.requests.get") as mock_get, \
            patch("exam_extract.adapter.requests.post") as mock_post:
        mock_get.return_value.json.return_value = {"vertices": []}
        report = adapter.import_data(intermediate)

    assert report["edges_created"] == 0
    assert report["edges_failed"] == 1
    mock_post.assert_not_called()


def test_import_edge_http_failure_counts_failed():
    intermediate = _make_intermediate(
        edges=[Edge(label="belongs_to", outV="question_1", inV="kp_1", properties={})],
    )
    adapter = HugeGraphAdapter("localhost", 8080, "admin", "admin")

    with patch("exam_extract.adapter.requests.get") as mock_get, \
            patch("exam_extract.adapter.requests.post") as mock_post:
        mock_get.return_value.json.return_value = {"vertices": []}
        mock_post.return_value = MagicMock(status_code=400, text="bad edge")
        report = adapter.import_data(intermediate)

    assert report["edges_created"] == 0
    assert report["edges_failed"] == 1

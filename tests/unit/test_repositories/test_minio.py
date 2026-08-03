# -*- coding: utf-8 -*-
"""Tests for app.repositories.minio.MinioRepository (async + miniopy_async)."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import MinioObjectNotFound
from app.repositories.minio import MinioRepository


def _make_repo() -> MinioRepository:
    """Build a repository instance without calling __init__.

    ``_client`` is stubbed as an AsyncMock and ``bucket`` pinned to a known
    value so each test exercises the real code path (no AttributeError on
    ``self.bucket``).
    """
    repo = MinioRepository.__new__(MinioRepository)
    repo._client = AsyncMock()
    repo.bucket = "exams"
    return repo


# --------------------------------------------------------------------------
# list_md_files
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_list_md_files_filters_by_extension():
    repo = _make_repo()
    mock_obj1 = MagicMock()
    mock_obj1.object_name = "exams/test.md"
    mock_obj1.size = 1024
    mock_obj1.last_modified = "2026-08-03T10:00:00Z"
    mock_obj2 = MagicMock()
    mock_obj2.object_name = "exams/other.pdf"
    mock_obj2.size = 2048
    repo._client.list_objects.return_value = [mock_obj1, mock_obj2]

    result = await repo.list_md_files(prefix="exams/")

    assert len(result) == 1
    assert result[0].object_key == "exams/test.md"
    assert result[0].size == 1024
    assert result[0].last_modified == "2026-08-03T10:00:00Z"


@pytest.mark.asyncio
async def test_list_md_files_respects_limit():
    repo = _make_repo()
    objs = []
    for i in range(5):
        mock_obj = MagicMock()
        mock_obj.object_name = f"exams/file{i}.md"
        mock_obj.size = i
        mock_obj.last_modified = None
        objs.append(mock_obj)
    repo._client.list_objects.return_value = objs

    result = await repo.list_md_files(prefix="exams/", limit=2)

    assert len(result) == 2
    assert [item.object_key for item in result] == ["exams/file0.md", "exams/file1.md"]


@pytest.mark.asyncio
async def test_list_md_files_passes_bucket_prefix_recursive():
    repo = _make_repo()
    repo._client.list_objects.return_value = []

    await repo.list_md_files(prefix="exams/")

    repo._client.list_objects.assert_awaited_once_with(
        "exams", prefix="exams/", recursive=True
    )


# --------------------------------------------------------------------------
# get_object_text
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_object_text_returns_decoded_content():
    repo = _make_repo()
    resp = AsyncMock()
    resp.read = AsyncMock(
        return_value="# 试题标题\n\n1. 第一题\n".encode("utf-8")
    )
    resp.close = AsyncMock()
    resp.release_conn = AsyncMock()
    repo._client.get_object.return_value = resp

    text = await repo.get_object_text("exams/test.md")

    assert text == "# 试题标题\n\n1. 第一题\n"
    resp.close.assert_awaited_once()
    resp.release_conn.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_object_text_not_found():
    repo = _make_repo()
    repo._client.get_object.side_effect = Exception("NoSuchKey")

    with pytest.raises(MinioObjectNotFound):
        await repo.get_object_text("nonexistent.md")

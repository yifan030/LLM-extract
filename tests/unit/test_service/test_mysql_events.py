# -*- coding: utf-8 -*-
import pytest
from unittest.mock import AsyncMock

from core.exceptions import PaperNotReady
from libs.id_gen import gen_content_hash_bytes, gen_paper_id_from_content_hash
from service.mysql_events import extract_file_id, parse_event_key, resolve_paper_id


def test_parse_paper_key():
    assert parse_event_key("education/uploads/paper/f1/foo_parsed/foo.md") == ("paper", None)


def test_parse_answer_key():
    assert parse_event_key("education/uploads/answer/p1/f2/foo_parsed/foo.md") == ("answer", "p1")


def test_parse_answer_sheet_key():
    assert parse_event_key("education/uploads/answer_sheet/p1/f2/foo_parsed/foo.md") == ("answer_sheet", "p1")


def test_parse_key_invalid_prefix():
    with pytest.raises(ValueError):
        parse_event_key("other/prefix/paper/f1/x.md")


def test_parse_answer_key_missing_paper_file_id():
    with pytest.raises(ValueError):
        parse_event_key("education/uploads/answer")


def test_extract_file_id_paper():
    assert extract_file_id("education/uploads/paper/f1/foo_parsed/foo.md") == "f1"


def test_extract_file_id_answer():
    assert extract_file_id("education/uploads/answer/p1/f2/foo_parsed/foo.md") == "f2"


def test_extract_file_id_invalid():
    assert extract_file_id("papers/test.md") is None


@pytest.mark.asyncio
async def test_resolve_paper_id_from_content_hash():
    mysql_repo = AsyncMock()
    mysql_repo.find_one.return_value = {"file_id": "p1", "content_hash": "abc123"}
    assert await resolve_paper_id(mysql_repo, AsyncMock(), "p1") == "paper_abc123"


@pytest.mark.asyncio
async def test_resolve_paper_id_legacy_downloads_raw():
    mysql_repo = AsyncMock()
    mysql_repo.find_one.return_value = {
        "file_id": "p1", "file_storage_path": "education/uploads/paper/p1/x.pdf",
    }
    minio_repo = AsyncMock()
    minio_repo.get_object_bytes.return_value = b"raw"
    expected = gen_paper_id_from_content_hash(gen_content_hash_bytes(b"raw"))
    assert await resolve_paper_id(mysql_repo, minio_repo, "p1") == expected
    minio_repo.get_object_bytes.assert_awaited_once_with(
        "education/uploads/paper/p1/x.pdf"
    )


@pytest.mark.asyncio
async def test_resolve_paper_id_not_ready():
    mysql_repo = AsyncMock()
    mysql_repo.find_one.return_value = None
    with pytest.raises(PaperNotReady):
        await resolve_paper_id(mysql_repo, AsyncMock(), "p1")

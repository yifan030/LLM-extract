# -*- coding: utf-8 -*-
import pytest
from unittest.mock import AsyncMock

from core.exceptions import PaperNotReady
from libs.id_gen import gen_paper_id
from model.schemas import MinioFileItem
from service.mysql_events import parse_event_key, resolve_paper_id


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


@pytest.mark.asyncio
async def test_resolve_paper_id_found():
    minio_repo = AsyncMock()
    md_key = "education/uploads/paper/p1/foo_parsed/foo.md"
    minio_repo.list_md_files.return_value = [
        MinioFileItem(object_key=md_key, size=10, last_modified="")
    ]
    assert await resolve_paper_id(minio_repo, "p1") == gen_paper_id(md_key)
    minio_repo.list_md_files.assert_awaited_once_with(
        prefix="education/uploads/paper/p1/", limit=10
    )


@pytest.mark.asyncio
async def test_resolve_paper_id_not_ready():
    minio_repo = AsyncMock()
    minio_repo.list_md_files.return_value = []
    with pytest.raises(PaperNotReady):
        await resolve_paper_id(minio_repo, "p1")

# -*- coding: utf-8 -*-
"""Tests for app.services.llm.LlmService (async + AsyncOpenAI)."""
import json

import pytest
from unittest.mock import AsyncMock, MagicMock

from core.exceptions import LlmApiCallError
from service.llm import LlmService


def _make_service(
    content: str | None, finish_reason: str = "stop", exc: Exception | None = None
) -> tuple[LlmService, AsyncMock]:
    """Build a LlmService wired to a mock AsyncOpenAI client.

    ``__init__`` is skipped so tests never touch ``Settings``.
    """
    svc = LlmService.__new__(LlmService)
    svc._config = MagicMock()
    svc._config.model = "gpt-4o"
    svc._config.temperature = 0.0
    svc._config.max_tokens = 8192

    mock_choice = MagicMock()
    mock_choice.finish_reason = finish_reason
    mock_choice.message.content = content

    mock_client = AsyncMock()
    mock_create = mock_client.chat.completions.create
    mock_create.return_value = MagicMock(choices=[mock_choice])
    mock_create.side_effect = exc
    svc._client = mock_client
    return svc, mock_client


_VALID_PAYLOAD = {
    "exam_paper": {"title": "test", "subject": "数学"},
    "question_types": [{"name": "单选题"}],
    "questions": [
        {
            "number": "1",
            "content": "题干",
            "question_type": "单选题",
            "candidate_knowledge_points": ["交集"],
        }
    ],
}


@pytest.mark.asyncio
async def test_extract_parses_valid_json():
    svc, mock_client = _make_service(json.dumps(_VALID_PAYLOAD, ensure_ascii=False))

    result = await svc.extract("prompt")

    assert result.exam_paper.title == "test"
    assert result.exam_paper.subject == "数学"
    assert len(result.questions) == 1
    assert result.questions[0].candidate_knowledge_points == ["交集"]
    # 必须走 chat.completions.create
    mock_client.chat.completions.create.assert_awaited_once()
    call = mock_client.chat.completions.create.call_args
    assert call.kwargs["model"] == "gpt-4o"
    assert call.kwargs["messages"][1]["content"] == "prompt"


@pytest.mark.asyncio
async def test_extract_handles_fenced_json():
    svc, _ = _make_service("```json\n" + json.dumps(_VALID_PAYLOAD) + "\n```")

    result = await svc.extract("prompt")

    assert result.exam_paper.title == "test"


@pytest.mark.asyncio
async def test_extract_invalid_schema_raises():
    svc, _ = _make_service('{"invalid": true}')

    with pytest.raises(LlmApiCallError, match="结构校验失败"):
        await svc.extract("prompt")


@pytest.mark.asyncio
async def test_extract_wraps_api_exception():
    svc, _ = _make_service(content=None, exc=RuntimeError("network down"))

    with pytest.raises(LlmApiCallError, match="LLM API 调用失败.*network down"):
        await svc.extract("prompt")


@pytest.mark.asyncio
async def test_extract_raises_when_content_none():
    svc, _ = _make_service(content=None)

    with pytest.raises(LlmApiCallError, match="返回内容为空"):
        await svc.extract("prompt")


def test_extract_json_payload_direct_json():
    assert LlmService._extract_json_payload('{"a": 1}') == {"a": 1}


def test_extract_json_payload_fenced():
    text = '```json\n{"a": 1}\n```'
    assert LlmService._extract_json_payload(text) == {"a": 1}


def test_extract_json_payload_plain_fence():
    text = '```\n{"a": 1}\n```'
    assert LlmService._extract_json_payload(text) == {"a": 1}


def test_extract_json_payload_with_surrounding_text():
    text = '好的，这是结果：\n```json\n{"a": 1}\n```\n请查收。'
    assert LlmService._extract_json_payload(text) == {"a": 1}


def test_extract_json_payload_braces_fallback():
    text = '前缀说明 {"a": 1} 后缀说明'
    assert LlmService._extract_json_payload(text) == {"a": 1}


def test_extract_json_payload_unparseable():
    with pytest.raises(LlmApiCallError, match="无法从 LLM 输出中解析"):
        LlmService._extract_json_payload("hello world")


def test_extract_json_payload_invalid_fence_raises():
    with pytest.raises(LlmApiCallError, match="不是合法 JSON"):
        LlmService._extract_json_payload('```json\n{invalid}\n```')

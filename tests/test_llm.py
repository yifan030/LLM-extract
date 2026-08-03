# -*- coding: utf-8 -*-
import json
import os

import pytest

from exam_extract.llm import (
    LlmApiError,
    LlmConfig,
    call_llm,
    extract_json_payload,
    run_llm_extraction,
)
from exam_extract.models import LlmExtractResult


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content, finish_reason="stop"):
        self.message = _FakeMessage(content)
        self.finish_reason = finish_reason


class _FakeResponse:
    def __init__(self, content, finish_reason="stop"):
        self.choices = [_FakeChoice(content, finish_reason)]


class _FakeClient:
    def __init__(self, content=None, finish_reason="stop", exc=None):
        self.content = content
        self.finish_reason = finish_reason
        self.exc = exc
        self.calls = []

    def chat_completions_create(self, **kwargs):
        self.calls.append(kwargs)
        if self.exc is not None:
            raise self.exc
        return _FakeResponse(self.content, self.finish_reason)


def _make_client(content=None, finish_reason="stop", exc=None):
    fake = _FakeClient(content, finish_reason, exc)

    class Completions:
        create = fake.chat_completions_create

    class Chat:
        completions = Completions()

    class Client:
        chat = Chat()

    return Client(), fake


def test_extract_json_payload_plain():
    data = {"a": 1}
    assert extract_json_payload('{"a": 1}') == data


def test_extract_json_payload_with_json_fence():
    text = "```json\n{\"a\": 1}\n```"
    assert extract_json_payload(text) == {"a": 1}


def test_extract_json_payload_with_plain_fence():
    text = "```\n{\"a\": 1}\n```"
    assert extract_json_payload(text) == {"a": 1}


def test_extract_json_payload_with_surrounding_text():
    text = "好的，这是抽取结果：\n```json\n{\"a\": 1}\n```\n请查收。"
    assert extract_json_payload(text) == {"a": 1}


def test_extract_json_payload_invalid_json_raises():
    with pytest.raises(LlmApiError):
        extract_json_payload("not json")


def test_call_llm_passes_parameters_and_returns_content():
    config = LlmConfig(api_key="sk-test", model="gpt-4o")
    client, recorder = _make_client(content='{"ok": true}')
    result = call_llm("prompt text", config, client=client)
    assert result == '{"ok": true}'
    assert len(recorder.calls) == 1
    call = recorder.calls[0]
    assert call["model"] == "gpt-4o"
    assert call["temperature"] == 0.0
    assert call["max_tokens"] == 8192
    assert len(call["messages"]) == 2
    assert call["messages"][1]["content"] == "prompt text"


def test_call_llm_wraps_exception():
    config = LlmConfig(api_key="sk-test", model="gpt-4o")
    client, _ = _make_client(exc=RuntimeError("network down"))
    with pytest.raises(LlmApiError, match="network down"):
        call_llm("prompt", config, client=client)


def test_call_llm_logs_warning_on_length_finish_reason(caplog):
    config = LlmConfig(api_key="sk-test", model="gpt-4o", max_tokens=100)
    client, _ = _make_client(content='{"a": 1}', finish_reason="length")
    import logging

    from exam_extract import llm as llm_module

    with caplog.at_level(logging.WARNING, logger=llm_module.__name__):
        call_llm("prompt", config, client=client)
    assert "因长度被截断" in caplog.text


def test_run_llm_extraction_returns_valid_result():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    fixture_path = os.path.join(base_dir, "fixtures", "sample_exam.llm.json")
    with open(fixture_path, "r", encoding="utf-8") as f:
        fixture = json.load(f)

    config = LlmConfig(api_key="sk-test", model="gpt-4o")
    client, _ = _make_client(content=json.dumps(fixture))
    result = run_llm_extraction("prompt", config, client=client)
    assert isinstance(result, LlmExtractResult)
    assert result.exam_paper.title
    assert len(result.questions) > 0


def test_run_llm_extraction_invalid_schema_raises():
    config = LlmConfig(api_key="sk-test", model="gpt-4o")
    client, _ = _make_client(content='{"invalid": true}')
    with pytest.raises(LlmApiError, match="结构校验失败"):
        run_llm_extraction("prompt", config, client=client)

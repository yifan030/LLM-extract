# -*- coding: utf-8 -*-
import json
import os
import sys

import pytest

from exam_extract.llm import LlmApiError
from exam_extract.models import LlmExtractResult


def _load_sample_llm_result() -> LlmExtractResult:
    base_dir = os.path.dirname(os.path.abspath(__file__))
    fixture_path = os.path.join(base_dir, "fixtures", "sample_exam.llm.json")
    with open(fixture_path, "r", encoding="utf-8") as f:
        return LlmExtractResult.model_validate(json.load(f))


def test_auto_mode_writes_llm_json_and_output(monkeypatch, tmp_path):
    import exam_extract.cli as cli

    md_path = tmp_path / "paper.md"
    md_path.write_text("# 测试卷\n1. 题目", encoding="utf-8")
    monkeypatch.setattr("exam_extract.paths.get_tmp_dir", lambda: str(tmp_path))
    output_path = tmp_path / "out.json"
    llm_json_path = tmp_path / "paper.llm.json"

    sample = _load_sample_llm_result()
    monkeypatch.setattr(
        cli,
        "load_level4_knowledge_points",
        lambda *args, **kwargs: ["交集", "并集", "子集"],
    )
    monkeypatch.setattr(cli, "run_llm_extraction", lambda prompt, config: sample)

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "exam_extract.cli",
            "--markdown",
            str(md_path),
            "--output",
            str(output_path),
            "--llm-api-key",
            "sk-test",
            "--llm-model",
            "gpt-4o",
        ],
    )

    cli.main()

    assert llm_json_path.exists()
    with open(llm_json_path, "r", encoding="utf-8") as f:
        saved = json.load(f)
    assert saved["exam_paper"]["title"] == sample.exam_paper.title

    assert output_path.exists()
    with open(output_path, "r", encoding="utf-8") as f:
        intermediate = json.load(f)
    assert intermediate["metadata"]["source_file"] == str(md_path)


def test_manual_mode_without_llm_json_prints_hint(monkeypatch, tmp_path, capsys):
    import exam_extract.cli as cli

    md_path = tmp_path / "paper.md"
    md_path.write_text("# 测试卷\n1. 题目", encoding="utf-8")
    monkeypatch.setattr("exam_extract.paths.get_tmp_dir", lambda: str(tmp_path))
    output_path = tmp_path / "out.json"

    monkeypatch.setattr(
        cli,
        "load_level4_knowledge_points",
        lambda *args, **kwargs: ["交集", "并集", "子集"],
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "exam_extract.cli",
            "--markdown",
            str(md_path),
            "--output",
            str(output_path),
        ],
    )

    cli.main()

    captured = capsys.readouterr()
    assert "请将 LLM 输出保存到" in captured.out
    assert not output_path.exists()


def test_auto_mode_api_failure_exits_without_writing_files(monkeypatch, tmp_path):
    import exam_extract.cli as cli

    md_path = tmp_path / "paper.md"
    md_path.write_text("# 测试卷\n1. 题目", encoding="utf-8")
    monkeypatch.setattr("exam_extract.paths.get_tmp_dir", lambda: str(tmp_path))
    output_path = tmp_path / "out.json"
    llm_json_path = tmp_path / "paper.llm.json"

    def _raise(*args, **kwargs):
        raise LlmApiError("API error")

    monkeypatch.setattr(
        cli,
        "load_level4_knowledge_points",
        lambda *args, **kwargs: ["交集", "并集", "子集"],
    )
    monkeypatch.setattr(cli, "run_llm_extraction", _raise)

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "exam_extract.cli",
            "--markdown",
            str(md_path),
            "--output",
            str(output_path),
            "--llm-api-key",
            "sk-test",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 1
    assert not llm_json_path.exists()
    assert not output_path.exists()

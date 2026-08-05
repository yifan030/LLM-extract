# -*- coding: utf-8 -*-
import os

import pytest

from utils import paths


def test_get_project_root_finds_readme(monkeypatch, tmp_path):
    fake_root = tmp_path / "fake_project"
    fake_root.mkdir()
    (fake_root / "README.md").write_text("# fake", encoding="utf-8")
    monkeypatch.setattr(paths, "__file__", str(fake_root / "exam_extract" / "paths.py"))
    assert paths.get_project_root() == str(fake_root)


def test_get_project_root_raises_when_no_readme(monkeypatch, tmp_path):
    fake_root = tmp_path / "fake_project"
    fake_root.mkdir()
    monkeypatch.setattr(paths, "__file__", str(fake_root / "exam_extract" / "paths.py"))
    with pytest.raises(RuntimeError, match="无法找到项目根目录"):
        paths.get_project_root()


def test_get_tmp_dir_auto_creates(monkeypatch, tmp_path):
    fake_root = tmp_path / "fake_project"
    fake_root.mkdir()
    (fake_root / "README.md").write_text("# fake", encoding="utf-8")
    monkeypatch.setattr(paths, "get_project_root", lambda: str(fake_root))
    result = paths.get_tmp_dir()
    assert result == str(fake_root / "tmp")
    assert os.path.isdir(result)


def test_get_llm_output_path(monkeypatch, tmp_path):
    fake_root = tmp_path / "fake_project"
    fake_root.mkdir()
    monkeypatch.setattr(paths, "get_tmp_dir", lambda: str(fake_root / "tmp"))
    assert paths.get_llm_output_path("/some/where/试卷.md") == str(
        fake_root / "tmp" / "试卷.llm.json"
    )


def test_get_default_output_path(monkeypatch, tmp_path):
    fake_root = tmp_path / "fake_project"
    fake_root.mkdir()
    monkeypatch.setattr(paths, "get_tmp_dir", lambda: str(fake_root / "tmp"))
    assert paths.get_default_output_path("/some/where/试卷.md") == str(
        fake_root / "tmp" / "试卷.intermediate.json"
    )

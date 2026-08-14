# -*- coding: utf-8 -*-
"""matcher 单元测试 — paper_id 内容派生（content_hash）与路径派生回退。"""
import hashlib

from model.models import ExamPaper, LlmExtractResult, Question
from service.matcher import MatcherService


def _make_llm_result() -> LlmExtractResult:
    return LlmExtractResult(
        exam_paper=ExamPaper(title="测试卷", subject="数学", grade="高一"),
        question_types=[],
        questions=[
            Question(number="1", content="题目", question_type="单选题"),
        ],
    )


def test_match_uses_content_hash_for_paper_id():
    """传入 content_hash 时，paper 顶点 id 用内容派生，而非 md5(source_file)。"""
    source = "education/uploads/paper/f1/foo_parsed/foo.md"
    content_hash = "a" * 32
    inter = MatcherService().match(
        _make_llm_result(), source_file=source, level4_names=[], content_hash=content_hash
    )
    paper_v = inter.vertices[0]
    assert paper_v.id == f"paper_{content_hash}"


def test_match_falls_back_to_path_derivation():
    """未传 content_hash 时，退回 md5(source_file) 路径派生（向后兼容）。"""
    source = "education/uploads/paper/f1/foo_parsed/foo.md"
    inter = MatcherService().match(
        _make_llm_result(), source_file=source, level4_names=[]
    )
    expected = "paper_" + hashlib.md5(source.encode()).hexdigest()
    assert inter.vertices[0].id == expected

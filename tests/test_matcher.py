# -*- coding: utf-8 -*-
"""Tests for the Stage 2 strict matcher."""
from exam_extract.matcher import Matcher
from exam_extract.models import (
    ExamPaper,
    LlmExtractResult,
    Question,
    QuestionType,
)
from exam_extract.snowflake import Snowflake


def _build_llm_result() -> LlmExtractResult:
    return LlmExtractResult(
        exam_paper=ExamPaper(title="测试卷", subject="数学"),
        question_types=[QuestionType(name="单选题")],
        questions=[Question(
            number="1",
            content="题干",
            answer="A",
            score=5,
            question_type="单选题",
            candidate_knowledge_points=["子集", "不存在知识点"],
        )],
    )


def test_match_question_to_existing_kp():
    llm_result = _build_llm_result()
    matcher = Matcher(level4_names=["子集", "交集"])
    result = matcher.match(llm_result, source_file="test.md")

    assert len(result.vertices) == 2  # exam_paper + question
    assert len(result.edges) == 3     # contains + belongs_to_type + examines
    assert len(result.unmatched) == 1
    assert result.unmatched[0].candidate == "不存在知识点"

    examines_edges = [e for e in result.edges if e.label == "examines"]
    assert len(examines_edges) == 1
    assert examines_edges[0].inV == "level_4_子集"


def test_match_metadata_and_vertex_labels():
    matcher = Matcher(level4_names=["子集"])
    result = matcher.match(_build_llm_result(), source_file="test.md")

    assert result.metadata.source_file == "test.md"
    assert result.metadata.matching_mode == "strict"
    assert result.metadata.generated_at

    paper_vertex = result.vertices[0]
    question_vertex = result.vertices[1]
    assert paper_vertex.label == "exam_paper"
    assert question_vertex.label == "question"
    assert paper_vertex.properties["title"] == "测试卷"
    assert question_vertex.properties["exam_paper_id"] == \
        paper_vertex.properties["exam_paper_id"]
    assert question_vertex.properties["question_type_id"] == 1


def test_contains_and_belongs_to_type_edges():
    matcher = Matcher(level4_names=["子集"])
    result = matcher.match(_build_llm_result(), source_file="test.md")

    contains = [e for e in result.edges if e.label == "contains"]
    belongs = [e for e in result.edges if e.label == "belongs_to_type"]
    assert len(contains) == 1
    assert len(belongs) == 1
    assert contains[0].outV == result.vertices[0].id
    assert contains[0].inV == result.vertices[1].id
    assert belongs[0].inV == "单选题"


def test_unmatched_item_records_question_id_and_number():
    matcher = Matcher(level4_names=["子集"])
    result = matcher.match(_build_llm_result(), source_file="test.md")

    item = result.unmatched[0]
    assert item.number == "1"
    assert item.question_id == result.vertices[1].id
    assert item.reason == "NOT_IN_LEVEL4_LIST"


def test_candidate_names_are_stripped_before_matching():
    llm_result = LlmExtractResult(
        exam_paper=ExamPaper(title="测试卷", subject="数学"),
        question_types=[QuestionType(name="单选题")],
        questions=[Question(
            number="1",
            content="题干",
            question_type="单选题",
            candidate_knowledge_points=[" 子集 "],
        )],
    )
    matcher = Matcher(level4_names=["子集"])
    result = matcher.match(llm_result, source_file="test.md")

    examines = [e for e in result.edges if e.label == "examines"]
    assert len(examines) == 1
    assert result.unmatched == []


def test_snowflake_generates_unique_increasing_ids():
    gen = Snowflake()
    ids = [gen.next_id() for _ in range(1000)]
    assert len(set(ids)) == 1000
    assert ids == sorted(ids)

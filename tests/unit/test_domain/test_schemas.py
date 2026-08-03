# -*- coding: utf-8 -*-
"""Tests for app.domain.schemas API request/response DTOs."""
from app.domain.schemas import (
    ExtractRequest,
    ExtractResult,
    MinioFileItem,
    PaperSummary,
    PaperDetail,
    QuestionSummary,
    QuestionDetail,
    KnowledgePointItem,
    KnowledgePointDetail,
    PaginatedResponse,
)


# ── 请求 DTO ──

def test_extract_request_valid():
    req = ExtractRequest(object_key="exams/test.md")
    assert req.object_key == "exams/test.md"


# ── 基础响应 DTO ──

def test_extract_result_fields():
    result = ExtractResult(paper_id="paper_123", question_count=20, matched_kp=76)
    assert result.paper_id == "paper_123"
    assert result.question_count == 20
    assert result.matched_kp == 76


def test_minio_file_item():
    item = MinioFileItem(
        object_key="exams/test.md", size=1024, last_modified="2026-08-03T10:00:00"
    )
    assert item.object_key == "exams/test.md"
    assert item.size == 1024
    assert item.last_modified == "2026-08-03T10:00:00"


def test_paper_summary():
    p = PaperSummary(
        paper_id="paper_1", title="测试卷", subject="数学", grade="高一", question_count=22
    )
    assert p.paper_id == "paper_1"
    assert p.title == "测试卷"
    assert p.subject == "数学"
    assert p.grade == "高一"
    assert p.question_count == 22


def test_paper_summary_grade_optional():
    p = PaperSummary(paper_id="paper_1", title="测试卷", subject="数学", question_count=1)
    assert p.grade is None


# ── 嵌套 / 详情 DTO ──

def test_paper_detail_nested_questions():
    detail = PaperDetail(
        paper_id="paper_1",
        title="测试卷",
        subject="数学",
        total_score=150,
        duration_minutes=120,
        questions=[
            {
                "question_id": "q_1",
                "number": "1",
                "content": "题干",
                "question_type": "单选题",
                "knowledge_points": ["交集"],
            }
        ],
    )
    assert detail.questions[0].question_id == "q_1"
    assert detail.questions[0].knowledge_points == ["交集"]


def test_paper_detail_questions_default_empty():
    detail = PaperDetail(paper_id="p", title="t", subject="s")
    assert detail.questions == []


def test_question_summary_defaults():
    q = QuestionSummary(question_id="q_1", number="1", content="题干", question_type="单选题")
    assert q.knowledge_points == []


def test_question_detail_fields():
    q = QuestionDetail(
        question_id="q_1",
        number="1",
        content="题干",
        answer="A",
        score=5,
        question_type="单选题",
        exam_paper_id="paper_1",
        exam_paper_title="测试卷",
        knowledge_points=["子集"],
    )
    assert q.answer == "A"
    assert q.score == 5
    assert q.exam_paper_id == "paper_1"
    assert q.exam_paper_title == "测试卷"
    assert q.knowledge_points == ["子集"]


def test_question_detail_optional_defaults():
    q = QuestionDetail(
        question_id="q_1",
        number="1",
        content="题干",
        question_type="单选题",
        exam_paper_id="paper_1",
        exam_paper_title="测试卷",
    )
    assert q.answer is None
    assert q.score is None
    assert q.knowledge_points == []


# ── 知识点 DTO ──

def test_knowledge_point_item():
    kp = KnowledgePointItem(kp_id="kp_1", name="交集", level=4, subject="数学")
    assert kp.kp_id == "kp_1"
    assert kp.name == "交集"
    assert kp.level == 4
    assert kp.subject == "数学"


def test_knowledge_point_item_optional_fields():
    kp = KnowledgePointItem(kp_id="kp_1", name="交集")
    assert kp.level is None
    assert kp.subject is None


def test_knowledge_point_detail_related_questions():
    kp = KnowledgePointDetail(
        kp_id="kp_1",
        name="交集",
        level=4,
        subject="数学",
        description="集合基本运算",
        related_questions=[
            {"question_id": "q_1", "number": "1", "content": "题干", "question_type": "单选题"}
        ],
    )
    assert kp.description == "集合基本运算"
    assert kp.related_questions[0].question_id == "q_1"


# ── 分页通用 DTO ──

def test_paginated_response():
    resp = PaginatedResponse(items=[], total=0, limit=20, offset=0)
    assert resp.total == 0
    assert resp.limit == 20
    assert resp.offset == 0
    assert resp.items == []


def test_paginated_response_generic_typed():
    resp = PaginatedResponse[PaperSummary](
        items=[
            {
                "paper_id": "p1",
                "title": "卷A",
                "subject": "数学",
                "question_count": 10,
            }
        ],
        total=1,
        limit=20,
        offset=0,
    )
    assert resp.items[0].paper_id == "p1"
    assert isinstance(resp.items[0], PaperSummary)
    assert resp.total == 1


def test_paginated_response_json_dump():
    resp = PaginatedResponse(items=[{"paper_id": "p1", "title": "t", "subject": "s", "question_count": 1}], total=1, limit=20, offset=0)
    data = resp.model_dump()
    assert data["items"][0]["paper_id"] == "p1"
    assert data["total"] == 1

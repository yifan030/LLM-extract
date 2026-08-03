# -*- coding: utf-8 -*-
"""API 请求/响应 DTO，与领域模型独立演进。"""
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


# ── 请求 ──
class ExtractRequest(BaseModel):
    object_key: str


# ── 响应 ──
class ExtractResult(BaseModel):
    paper_id: str
    question_count: int
    matched_kp: int


class MinioFileItem(BaseModel):
    object_key: str
    size: int
    last_modified: str


class PaperSummary(BaseModel):
    paper_id: str
    title: str
    subject: str
    grade: str | None = None
    question_count: int


class PaperDetail(BaseModel):
    paper_id: str
    title: str
    subject: str
    grade: str | None = None
    total_score: int | None = None
    duration_minutes: int | None = None
    questions: list["QuestionSummary"] = Field(default_factory=list)


class QuestionSummary(BaseModel):
    question_id: str
    number: str
    content: str
    question_type: str
    knowledge_points: list[str] = Field(default_factory=list)


class QuestionDetail(BaseModel):
    question_id: str
    number: str
    content: str
    answer: str | None = None
    score: int | None = None
    question_type: str
    exam_paper_id: str
    exam_paper_title: str
    knowledge_points: list[str] = Field(default_factory=list)


class KnowledgePointItem(BaseModel):
    kp_id: str
    name: str
    level: int | None = None
    subject: str | None = None


class KnowledgePointDetail(BaseModel):
    kp_id: str
    name: str
    level: int | None = None
    subject: str | None = None
    description: str | None = None
    related_questions: list[QuestionSummary] = Field(default_factory=list)


class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int

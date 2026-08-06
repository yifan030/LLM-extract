# -*- coding: utf-8 -*-
"""领域模型 — 纯 Pydantic 数据定义，零项目依赖。"""
from typing import Any

from pydantic import BaseModel, Field


class ExamPaper(BaseModel):
    title: str
    subject: str = "数学"
    grade: str | None = None
    total_score: int | None = None
    duration_minutes: int | None = None


class QuestionType(BaseModel):
    name: str
    description: str | None = None


class Question(BaseModel):
    number: str
    content: str
    answer: str | None = None
    score: int | None = None
    question_type: str
    candidate_knowledge_points: list[str] = Field(default_factory=list)
    img_url: list[str] = Field(default_factory=list)
    answer_img: list[str] = Field(default_factory=list)


class LlmExtractResult(BaseModel):
    exam_paper: ExamPaper
    question_types: list[QuestionType]
    questions: list[Question]


class Vertex(BaseModel):
    label: str
    id: str
    properties: dict[str, Any]


class Edge(BaseModel):
    label: str
    outV: str
    inV: str
    properties: dict[str, Any]


class UnmatchedItem(BaseModel):
    question_id: str
    number: str
    candidate: str
    reason: str = "NOT_IN_LEVEL4_LIST"


class Metadata(BaseModel):
    source_file: str
    generated_at: str
    matching_mode: str = "strict"


class IntermediateJson(BaseModel):
    metadata: Metadata
    vertices: list[Vertex]
    edges: list[Edge]
    unmatched: list[UnmatchedItem]

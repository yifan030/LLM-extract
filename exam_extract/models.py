# -*- coding: utf-8 -*-
"""Pydantic models for the exam extraction pipeline.

Stage 1 (LLM extraction) produces :class:`LlmExtractResult`.
Stage 2 (knowledge point linking) produces :class:`IntermediateJson`.
"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ExamPaper(BaseModel):
    title: str
    subject: str = "数学"
    grade: Optional[str] = None
    total_score: Optional[int] = None
    duration_minutes: Optional[int] = None


class QuestionType(BaseModel):
    name: str
    description: Optional[str] = None


class Question(BaseModel):
    number: str
    content: str
    answer: Optional[str] = None
    score: Optional[int] = None
    question_type: str
    candidate_knowledge_points: List[str] = Field(default_factory=list)


class LlmExtractResult(BaseModel):
    exam_paper: ExamPaper
    question_types: List[QuestionType]
    questions: List[Question]


class Vertex(BaseModel):
    label: str
    id: str
    properties: Dict[str, Any]


class Edge(BaseModel):
    label: str
    outV: str
    inV: str
    properties: Dict[str, Any]


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
    vertices: List[Vertex]
    edges: List[Edge]
    unmatched: List[UnmatchedItem]

# -*- coding: utf-8 -*-
"""MySQL 导入/导出 API 请求/响应 DTO。"""
from pydantic import BaseModel, Field


class PaperImportRequest(BaseModel):
    object_key: str = Field(..., description="MinIO 中的试卷 markdown 对象 key")


class PaperImportResponse(BaseModel):
    paper_id: str
    title: str
    question_count: int
    imported: bool = True


class AnswerImportRequest(BaseModel):
    object_key: str = Field(..., description="MinIO 中的答案 markdown 对象 key")
    paper_id: str = Field(..., description="目标试卷 ID，格式 paper_{md5hex}")


class AnswerImportResponse(BaseModel):
    paper_id: str
    updated_count: int


class AnswerSheetImportRequest(BaseModel):
    object_key: str = Field(..., description="MinIO 中的答题卡图片对象 key")
    paper_id: str = Field(..., description="目标试卷 ID，格式 paper_{md5hex}")


class AnswerSheetImportResponse(BaseModel):
    student_id: int
    student_name: str
    paper_id: str
    scored_count: int
    total_obtained: float = 0.0


class CsvExportRequest(BaseModel):
    tables: list[str] = Field(..., description="要导出的表名列表")
    paper_id: str | None = Field(default=None, description="按试卷 ID 过滤（可选）")


class WeakKnowledgePoint(BaseModel):
    kp_id: int
    kp_name: str
    total: int
    correct: int
    accuracy: float


class RecommendRequest(BaseModel):
    student_id: int
    exam_paper_id: str
    accuracy_threshold: float = Field(default=0.6, ge=0.0, le=1.0)


class RecommendQuestion(BaseModel):
    id: str
    number: str
    content: str
    question_type: str
    difficulty: int | None = None


class RecommendResponse(BaseModel):
    student_id: int
    exam_paper_id: str
    weak_knowledge_points: list[WeakKnowledgePoint] = Field(default_factory=list)
    recommended_questions: list[RecommendQuestion] = Field(default_factory=list)

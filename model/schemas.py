# -*- coding: utf-8 -*-
"""API 请求/响应 DTO，与领域模型独立演进。"""
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


# ── 请求 ──
class ExtractRequest(BaseModel):
    object_key: str
    save_artifacts: bool = False
    import_to_hg: bool = True


# ── 响应 ──
class ExtractResult(BaseModel):
    paper_id: str
    question_count: int
    matched_kp: int
    unmatched_count: int = 0
    artifact_dir: str | None = None
    imported: bool = False


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
    img_url: list[str] = Field(default_factory=list)
    answer_img: list[str] = Field(default_factory=list)


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
    img_url: list[str] = Field(default_factory=list)
    answer_img: list[str] = Field(default_factory=list)


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


class KnowledgePointRelationsResponse(BaseModel):
    """知识点关系查询响应。

    包含：
    - related: 与此知识点具有相关关系的四级知识点
    - ancestors: 与此知识点具有直接包含关系的一级、二级、三级知识点
    """
    kp_id: str
    name: str
    level: int | None = None
    related: list[KnowledgePointItem] = Field(default_factory=list)
    ancestors: list[KnowledgePointItem] = Field(default_factory=list)


class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


# ── 试卷判分 ──

class ScoringRequest(BaseModel):
    paper_id: str | None = Field(
        default=None,
        description="试卷 ID（可选；提供时为答题卡模式，否则为完整试卷模式）",
    )


class QuestionScore(BaseModel):
    number: str = Field(..., description="题号")
    question_id: str = Field(default="", description="试题 ID（数据库主键）")
    content: str = Field(default="", description="题目内容")
    # image_urls: list[str] = Field(default_factory=list, description="题目中的图片 URL（从 OCR markdown 提取）")
    student_answer: str | None = Field(default=None, description="学生作答")
    standard_answer: str | None = Field(default=None, description="标准答案（来自数据库或参考答案）")
    score: int | None = Field(default=None, description="本题分值")
    question_type: str = Field(default="", description="题型：单选题/多选题/填空题/解答题")
    exam_paper_id: str = Field(default="", description="所属试卷 ID")
    exam_paper_title: str = Field(default="", description="所属试卷标题")
    knowledge_points: list[str] = Field(default_factory=list, description="关联知识点（由后续流程填充）")
    img_url: list[str] = Field(default_factory=list, description="试题图片 URL（数据库存储）")
    answer_img: list[str] = Field(default_factory=list, description="答案图片 URL（数据库存储）")
    student_img: list[str] = Field(default_factory=list, description="学生答题卡图片 URL")


class ScoringResponse(BaseModel):
    paper_title: str = Field(default="", description="试卷标题")
    paper_id: str = Field(default="", description="试卷 ID")
    total_score: int | None = Field(default=None, description="试卷总分")
    questions: list[QuestionScore] = Field(default_factory=list)
    ocr_markdown: str = Field(default="", description="OCR 原始 markdown（调试用）")


# ── 向量搜索 ──

class SearchRequest(BaseModel):
    query: str = Field(..., description="搜索查询文本")
    kp_level: int | None = Field(default=None, ge=1, le=4, description="知识点层级过滤 (1-4)")
    kp_name: str | None = Field(default=None, description="知识点名称过滤")
    limit: int = Field(default=10, ge=1, le=100, description="返回结果数量")


class SearchHit(BaseModel):
    question_id: str
    paper_id: str
    number: str
    content: str
    question_type: str
    kp_names_l1: list[str] = Field(default_factory=list)
    kp_names_l2: list[str] = Field(default_factory=list)
    kp_names_l3: list[str] = Field(default_factory=list)
    kp_names_l4: list[str] = Field(default_factory=list)


class SearchResponse(BaseModel):
    query: str
    kp_filter: str | None = None
    hits: list[SearchHit]
    total: int

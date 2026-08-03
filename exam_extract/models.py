# -*- coding: utf-8 -*-
"""Re-export domain models for backward compatibility."""
from app.domain.models import (  # noqa: F401
    ExamPaper,
    QuestionType,
    Question,
    LlmExtractResult,
    Vertex,
    Edge,
    UnmatchedItem,
    IntermediateJson,
    Metadata,
)

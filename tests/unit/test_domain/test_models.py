# -*- coding: utf-8 -*-
"""Tests for app.domain.models domain models."""
import pytest

from app.domain.models import LlmExtractResult, IntermediateJson, Vertex, Edge


def test_llm_extract_result_parsing():
    raw = {
        "exam_paper": {
            "title": "测试卷",
            "subject": "数学",
            "grade": "高一",
            "total_score": 150,
            "duration_minutes": 120
        },
        "question_types": [{"name": "单选题", "description": ""}],
        "questions": [{
            "number": "1",
            "content": "测试题干",
            "answer": "A",
            "score": 5,
            "question_type": "单选题",
            "candidate_knowledge_points": ["子集"]
        }]
    }
    result = LlmExtractResult.model_validate(raw)
    assert result.exam_paper.title == "测试卷"
    assert result.questions[0].candidate_knowledge_points == ["子集"]


def test_intermediate_json_serialization():
    data = {
        "metadata": {
            "source_file": "test.md",
            "generated_at": "2026-08-02T10:00:00",
            "matching_mode": "strict"
        },
        "vertices": [
            {
                "label": "question",
                "id": "question_123",
                "properties": {"question_id": 123, "content": "test"}
            }
        ],
        "edges": [
            {
                "label": "examines",
                "outV": "question_123",
                "inV": "level_4_子集",
                "properties": {"create_time": "2026-08-02 10:00:00"}
            }
        ],
        "unmatched": []
    }
    result = IntermediateJson.model_validate(data)
    assert result.vertices[0].id == "question_123"
    assert result.edges[0].inV == "level_4_子集"

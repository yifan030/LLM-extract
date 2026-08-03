import pytest
from unittest.mock import AsyncMock, MagicMock

from app.domain.models import (
    Edge,
    ExamPaper,
    IntermediateJson,
    LlmExtractResult,
    Metadata,
    Vertex,
)
from app.services.extraction import ExtractionService


@pytest.mark.asyncio
async def test_extraction_run_returns_report():
    svc = ExtractionService.__new__(ExtractionService)
    svc._minio = AsyncMock()
    svc._hg = AsyncMock()
    svc._llm = AsyncMock()
    svc._prompt = AsyncMock()
    svc._matcher = MagicMock()

    svc._minio.get_object_text.return_value = "# 试卷内容"
    svc._hg.load_level4_names.return_value = ["交集"]
    svc._hg.preload_question_types.return_value = {"单选题": "qt_1"}
    svc._hg.create_vertex.return_value = (True, False)
    svc._hg.create_edge.return_value = True

    svc._prompt.build_prompt.return_value = "prompt text"

    svc._llm.extract.return_value = LlmExtractResult(
        exam_paper=ExamPaper(title="test", subject="数学"),
        question_types=[],
        questions=[],
    )

    paper_v = Vertex(
        label="exam_paper", id="paper_123", properties={"title": "test"}
    )
    svc._matcher.match.return_value = IntermediateJson(
        metadata=Metadata(source_file="x", generated_at="2026-01-01T00:00:00"),
        vertices=[paper_v],
        edges=[],
        unmatched=[],
    )

    report = await svc.run("exams/test.md")

    assert report["paper_id"] == "paper_123"
    assert report["question_count"] == 0
    assert report["matched_kp"] == 0
    svc._minio.get_object_text.assert_awaited_once_with("exams/test.md")
    svc._hg.load_level4_names.assert_awaited_once()

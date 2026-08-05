import json
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock

import pytest

from model.models import (
    Edge,
    ExamPaper,
    IntermediateJson,
    LlmExtractResult,
    Metadata,
    Question,
    QuestionType,
    UnmatchedItem,
    Vertex,
)
from service.extraction import ExtractionService


@pytest.mark.asyncio
async def test_extraction_run_returns_report():
    svc = ExtractionService.__new__(ExtractionService)
    svc._minio = AsyncMock()
    svc._hg = AsyncMock()
    svc._llm = AsyncMock()
    svc._prompt = AsyncMock()
    svc._matcher = MagicMock()
    svc._output_dir = "tmp/extractions"

    svc._minio.get_object_text.return_value = "# 试卷内容"
    svc._hg.load_level4_names.return_value = ["交集"]
    svc._hg.preload_question_types.return_value = {"单选题": "qt_1"}
    svc._hg.create_vertex.return_value = (True, False)
    svc._hg.create_edge.return_value = (True, False)

    svc._prompt.build_prompt_sync.return_value = "prompt text"

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
    assert report["imported"] is True
    svc._minio.get_object_text.assert_awaited_once_with("exams/test.md")
    svc._hg.load_level4_names.assert_awaited_once()


@pytest.mark.asyncio
async def test_skip_import_saves_artifacts():
    """save_artifacts=True, import_to_hg=False → 产物落盘，不导入。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        svc = ExtractionService.__new__(ExtractionService)
        svc._minio = AsyncMock()
        svc._hg = AsyncMock()
        svc._llm = AsyncMock()
        svc._prompt = AsyncMock()
        svc._matcher = MagicMock()
        svc._output_dir = tmpdir

        svc._minio.get_object_text.return_value = "# 试卷内容"
        svc._hg.load_level4_names.return_value = ["交集", "子集"]

        svc._prompt.build_prompt_sync.return_value = "prompt text"

        svc._llm.extract.return_value = LlmExtractResult(
            exam_paper=ExamPaper(title="测试卷", subject="数学"),
            question_types=[QuestionType(name="单选题")],
            questions=[
                Question(
                    number="1", content="题干", answer="A", score=5,
                    question_type="单选题",
                    candidate_knowledge_points=["交集", "未命中项"],
                )
            ],
        )

        paper_v = Vertex(
            label="exam_paper", id="paper_abc123def456", properties={"title": "测试卷"}
        )
        question_v = Vertex(
            label="question", id="question_xyz",
            properties={"question_id": "xyz", "content": "题干"}
        )
        svc._matcher.match.return_value = IntermediateJson(
            metadata=Metadata(source_file="test.md", generated_at="2026-01-01T00:00:00"),
            vertices=[paper_v, question_v],
            edges=[
                Edge(label="contains", outV="paper_abc", inV="question_xyz", properties={}),
                Edge(label="examines", outV="question_xyz", inV="level_4_交集", properties={}),
            ],
            unmatched=[
                UnmatchedItem(question_id="question_xyz", number="1", candidate="未命中项"),
            ],
        )

        report = await svc.run("test.md", save_artifacts=True, import_to_hg=False)

        assert report["paper_id"] == "paper_abc123def456"
        assert report["question_count"] == 1
        assert report["matched_kp"] == 1
        assert report["unmatched_count"] == 1
        assert report["imported"] is False
        assert report["artifact_dir"] is not None

        # 验证文件落盘
        artifact_dir = report["artifact_dir"]
        assert os.path.isdir(artifact_dir)

        with open(os.path.join(artifact_dir, "llm_response.json"), "r") as f:
            llm_data = json.load(f)
            assert llm_data["exam_paper"]["title"] == "测试卷"

        with open(os.path.join(artifact_dir, "intermediate.json"), "r") as f:
            inter_data = json.load(f)
            assert len(inter_data["unmatched"]) == 1
            assert inter_data["unmatched"][0]["candidate"] == "未命中项"

        # 导入报告不应存在
        assert not os.path.exists(os.path.join(artifact_dir, "import_report.json"))

        # HugeGraph 不应被调用
        svc._hg.create_vertex.assert_not_called()
        svc._hg.create_edge.assert_not_called()

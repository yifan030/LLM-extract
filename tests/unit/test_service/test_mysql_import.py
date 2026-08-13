# -*- coding: utf-8 -*-
"""MySqlImportService 单元测试 — Mock 外部依赖（MinIO / MySQL / LLM / Prompt）。

不连接真实 MySQL/MinIO，所有依赖均为 AsyncMock/MagicMock。
"""
import json
import os
import zipfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.exceptions import AppError, PaperNotFound
from libs.id_gen import gen_paper_id
from model.mysql_schemas import (
    AnswerImportResponse,
    AnswerSheetImportResponse,
    PaperImportResponse,
    RecommendResponse,
)
from model.schemas import MinioFileItem
from service import mysql_import  # 模块级 _batch_jobs 注册表
from service.mysql_import import MySqlImportService


@pytest.fixture
def mock_deps():
    """构造所有 mock 依赖。"""
    minio_repo = AsyncMock()
    minio_repo.get_object_text.return_value = "# 测试试卷\n..."
    mysql_repo = AsyncMock()
    mysql_repo.find_one.return_value = {"id": "paper_test", "title": "测试"}
    mysql_repo.find_all.return_value = [
        {"id": "q_001", "number": "1", "content": "test"}
    ]
    mysql_repo.upsert.return_value = 1
    llm_svc = AsyncMock()
    # Mock LLM 返回的 extracted 对象（字段对齐 model.models.LlmExtractResult）
    extracted = MagicMock()
    extracted.exam_paper.title = "测试试卷"
    extracted.exam_paper.grade = "高一"
    extracted.exam_paper.subject = "数学"
    extracted.exam_paper.total_score = 100
    extracted.exam_paper.duration_minutes = 90
    q1 = MagicMock()
    q1.number = "1"
    q1.content = "题目内容"
    q1.answer = "答案"
    q1.score = 10
    q1.question_type = "单选题"
    q1.candidate_knowledge_points = ["交集", "并集"]
    q1.img_url = []
    q1.answer_img = []
    extracted.questions = [q1]
    llm_svc.extract.return_value = extracted
    prompt_svc = MagicMock()
    prompt_svc.build_prompt_sync.return_value = "system prompt + content"
    return minio_repo, mysql_repo, llm_svc, prompt_svc


@pytest.mark.asyncio
class TestMySqlImportService:
    async def test_import_paper(self, mock_deps):
        """试卷导入：LLM 抽取 + 写入 exam_papers + questions。"""
        minio_repo, mysql_repo, llm_svc, prompt_svc = mock_deps
        svc = MySqlImportService(minio_repo, mysql_repo, llm_svc, prompt_svc)

        result = await svc.import_paper("papers/test.md")

        assert isinstance(result, PaperImportResponse)
        assert result.imported is True
        assert result.title == "测试试卷"
        assert result.question_count == 1
        assert result.paper_id == gen_paper_id("papers/test.md")
        assert result.paper_id.startswith("paper_")

        # MinIO 读取 + Prompt 构建 + LLM 抽取均被调用
        minio_repo.get_object_text.assert_called_once_with("papers/test.md")
        prompt_svc.build_prompt_sync.assert_called_once_with("# 测试试卷\n...")
        llm_svc.extract.assert_called_once()

        # exam_papers 与 questions 各 UPSERT 一次
        upsert_tables = [c.args[0] for c in mysql_repo.upsert.call_args_list]
        assert upsert_tables.count("exam_papers") == 1
        assert upsert_tables.count("questions") == 1

        # 校验写入的题目数据（知识点名称 JSON 序列化进 knowledge_point_ids 列）
        q_args = next(
            c.args[1] for c in mysql_repo.upsert.call_args_list
            if c.args[0] == "questions"
        )
        assert q_args["exam_paper_id"] == result.paper_id
        assert q_args["number"] == "1"
        assert q_args["sort_order"] == 1
        assert json.loads(q_args["knowledge_point_ids"]) == ["交集", "并集"]
        assert q_args["img_url"] is None  # 空列表落库为 NULL
        assert q_args["answer_img"] is None

    async def test_import_answers_paper_not_found(self, mock_deps):
        """答案导入：试卷不存在时抛 PaperNotFound。"""
        minio_repo, mysql_repo, llm_svc, prompt_svc = mock_deps
        mysql_repo.find_one.return_value = None  # 试卷不存在
        svc = MySqlImportService(minio_repo, mysql_repo, llm_svc, prompt_svc)

        with pytest.raises(PaperNotFound):
            await svc.import_answers("answers/test.md", "paper_nonexistent")

    async def test_import_answers_updates_questions(self, mock_deps):
        """答案导入成功：解析答题卡表格并按题号 UPDATE questions.answer。"""
        minio_repo, mysql_repo, llm_svc, prompt_svc = mock_deps
        minio_repo.get_object_text.return_value = (
            "<table>"
            "<tr><td>题号</td><td>1</td><td>2</td></tr>"
            "<tr><td>答案</td><td>A</td><td>B</td></tr>"
            "</table>"
        )
        paper_id = gen_paper_id("papers/test.md")

        async def fake_find_one(table, where):
            if table == "exam_papers":
                return {"id": paper_id, "title": "测试"}
            if table == "questions":
                return {"id": f"question_{where['number']}", "number": where["number"]}
            return None

        mysql_repo.find_one.side_effect = fake_find_one
        svc = MySqlImportService(minio_repo, mysql_repo, llm_svc, prompt_svc)

        result = await svc.import_answers("answers/test.md", paper_id)

        assert isinstance(result, AnswerImportResponse)
        assert result.paper_id == paper_id
        assert result.updated_count == 2
        minio_repo.get_object_text.assert_called_once_with("answers/test.md")

        # 两题各一次 UPSERT，answer 与解析结果一致
        q_upserts = [
            c.args[1] for c in mysql_repo.upsert.call_args_list
            if c.args[0] == "questions"
        ]
        assert len(q_upserts) == 2
        assert {d["answer"] for d in q_upserts} == {"A", "B"}

    async def test_import_answer_sheet(self, mock_deps):
        """答题卡导入：MinIO 取图 → OCR → 写 students + answer_sheets。"""
        minio_repo, mysql_repo, llm_svc, prompt_svc = mock_deps
        paper_id = gen_paper_id("papers/test.md")

        # MinIO 图片响应（aiohttp ClientResponse：read 异步、release 同步）
        img_response = AsyncMock()
        img_response.read.return_value = b"\xff\xd8fake-jpeg"
        img_response.release = MagicMock()
        minio_repo._client.get_object.return_value = img_response

        async def fake_find_one(table, where):
            if table == "exam_papers":
                return {"id": paper_id, "grade": "高一", "title": "测试"}
            if table == "students":
                return {"id": 5, "name": "张三"}
            return None

        mysql_repo.find_one.side_effect = fake_find_one
        mysql_repo.find_all.return_value = [{"id": "q_1", "number": "1"}]
        svc = MySqlImportService(minio_repo, mysql_repo, llm_svc, prompt_svc)

        ocr_text = (
            "<table>"
            "<tr><td>题号</td><td>1</td></tr>"
            "<tr><td>答案</td><td>A 5分</td></tr>"
            "</table>"
        )

        class FakeOcrClient:
            """模拟 httpx.AsyncClient —— 仅 stub 掉 OCR 的 HTTP 调用。"""

            def __init__(self, *args, **kwargs):
                self.post = AsyncMock()
                # 响应是同步读的（resp.json()/raise_for_status()），用普通 Mock
                resp = MagicMock()
                self.post.return_value = resp
                resp.raise_for_status.return_value = None
                resp.json.return_value = {"markdown": ocr_text}

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

        fake_client = FakeOcrClient()
        # service 内局部 import httpx，直接 patch 模块属性
        with patch("httpx.AsyncClient", return_value=fake_client):
            result = await svc.import_answer_sheet("sheets/s1.jpg", paper_id)

        assert isinstance(result, AnswerSheetImportResponse)
        assert result.student_id == 5
        assert result.scored_count == 1
        assert result.total_obtained == 5.0

        # 图片读取 + OCR 调用
        minio_repo._client.get_object.assert_called_once()
        img_response.read.assert_awaited_once()
        fake_client.post.assert_awaited_once()

        # students 与 answer_sheets 各 UPSERT
        upsert_tables = [c.args[0] for c in mysql_repo.upsert.call_args_list]
        assert upsert_tables.count("students") == 1
        assert upsert_tables.count("answer_sheets") == 1

        # 校验 answer_sheets 写入内容（含解析出的得分）
        sheet_upserts = [
            c.args[1] for c in mysql_repo.upsert.call_args_list
            if c.args[0] == "answer_sheets"
        ]
        assert len(sheet_upserts) == 1
        assert sheet_upserts[0]["student_answer"] == "A 5分"
        assert sheet_upserts[0]["score_obtained"] == 5.0

    async def test_import_answer_sheet_paper_not_found(self, mock_deps):
        """答题卡导入：试卷不存在时抛 PaperNotFound。"""
        minio_repo, mysql_repo, llm_svc, prompt_svc = mock_deps
        mysql_repo.find_one.return_value = None
        svc = MySqlImportService(minio_repo, mysql_repo, llm_svc, prompt_svc)

        with pytest.raises(PaperNotFound):
            await svc.import_answer_sheet("sheets/s1.jpg", "paper_nonexistent")

    async def test_export_csv(self, mock_deps):
        """CSV 导出：按表查询并打包为 ZIP。"""
        minio_repo, mysql_repo, llm_svc, prompt_svc = mock_deps
        paper_id = gen_paper_id("papers/test.md")
        mysql_repo.find_one.return_value = {
            "id": paper_id, "title": "测试", "subject": "数学",
        }
        mysql_repo.find_all.side_effect = [
            [  # questions
                {"id": "q_1", "number": "1", "content": "题目"},
                {"id": "q_2", "number": "2", "content": "题目2"},
            ],
            [  # answer_sheets
                {"id": 1, "student_id": 5, "question_id": "q_1"},
            ],
        ]
        svc = MySqlImportService(minio_repo, mysql_repo, llm_svc, prompt_svc)

        zip_path = await svc.export_csv(
            ["exam_papers", "questions", "answer_sheets"], paper_id
        )

        assert zip_path.endswith(".zip")
        assert os.path.exists(zip_path)
        try:
            with zipfile.ZipFile(zip_path) as zf:
                names = zf.namelist()
                assert "exam_papers.csv" in names
                assert "questions.csv" in names
                assert "answer_sheets.csv" in names
                questions_csv = zf.read("questions.csv").decode("utf-8")
                assert "number" in questions_csv
                assert "q_1" in questions_csv
        finally:
            os.remove(zip_path)

    async def test_get_weak_kp_recommend(self, mock_deps):
        """薄弱知识点推荐：按得分率阈值筛选知识点并推荐同类题。"""
        minio_repo, mysql_repo, llm_svc, prompt_svc = mock_deps
        mysql_repo._execute.side_effect = [
            [  # 薄弱知识点（score_rate < 0.6）
                {"id": 1, "name": "交集", "total_score": 4.0,
                 "full_score": 8.0, "score_rate": 0.5},
            ],
            [  # 推荐题目
                {"id": "q_rec1", "number": "1", "content": "x" * 300,
                 "question_type": "解答题", "difficulty": 3},
            ],
        ]
        svc = MySqlImportService(minio_repo, mysql_repo, llm_svc, prompt_svc)

        result = await svc.get_weak_kp_recommend(5, "paper_x", 0.6)

        assert isinstance(result, RecommendResponse)
        assert len(result.weak_knowledge_points) == 1
        kp = result.weak_knowledge_points[0]
        assert kp.kp_id == 1
        assert kp.kp_name == "交集"
        assert kp.total_score == 4.0
        assert kp.full_score == 8.0
        assert kp.score_rate == 0.5

        assert len(result.recommended_questions) == 1
        rec = result.recommended_questions[0]
        assert rec.id == "q_rec1"
        assert rec.question_type == "解答题"
        assert len(rec.content) == 200  # content 截断到 200 字符

        # 两次 SQL 执行：薄弱知识点查询 + 推荐题目查询，阈值参数透传
        assert mysql_repo._execute.call_count == 2
        assert mysql_repo._execute.call_args_list[0].args[1]["threshold"] == 0.6
        assert mysql_repo._execute.call_args_list[0].args[1]["student_id"] == 5

    async def test_start_batch_import_skips_existing(self, mock_deps):
        """批量增量导入：已入库的 paper_id 被跳过，仅导入未入库文件。"""
        minio_repo, mysql_repo, llm_svc, prompt_svc = mock_deps
        mysql_import._batch_jobs.clear()
        minio_repo.list_md_files.return_value = [
            MinioFileItem(object_key="papers/a.md", size=1, last_modified=""),
            MinioFileItem(object_key="papers/b.md", size=1, last_modified=""),
            MinioFileItem(object_key="papers/c.md", size=1, last_modified=""),
        ]
        # exam_papers 已存在 a、b
        mysql_repo._execute.return_value = [
            {"id": gen_paper_id("papers/a.md")},
            {"id": gen_paper_id("papers/b.md")},
        ]
        svc = MySqlImportService(minio_repo, mysql_repo, llm_svc, prompt_svc)
        svc.import_paper = AsyncMock(return_value=PaperImportResponse(
            paper_id=gen_paper_id("papers/c.md"), title="", question_count=0,
        ))

        resp = await svc.start_batch_import()
        await mysql_import._batch_jobs[resp.job_id]["task"]

        assert resp.total == 3
        assert resp.skipped == 2
        assert resp.status == "running"

        status = svc.get_batch_status(resp.job_id)
        assert status.total == 3
        assert status.skipped == 2
        assert status.succeeded == 1
        assert status.failed == 0
        assert status.finished is True
        assert status.status == "completed"
        assert len(status.results) == 1
        assert status.results[0].object_key == "papers/c.md"
        assert status.results[0].status == "succeeded"

        # 只有 c 被导入
        svc.import_paper.assert_called_once_with("papers/c.md")

    async def test_start_batch_import_single_failure_continues(self, mock_deps):
        """单个文件失败不中断整批，继续导入后续文件。"""
        minio_repo, mysql_repo, llm_svc, prompt_svc = mock_deps
        mysql_import._batch_jobs.clear()
        minio_repo.list_md_files.return_value = [
            MinioFileItem(object_key="papers/a.md", size=1, last_modified=""),
            MinioFileItem(object_key="papers/b.md", size=1, last_modified=""),
        ]
        mysql_repo._execute.return_value = []  # 都未入库
        svc = MySqlImportService(minio_repo, mysql_repo, llm_svc, prompt_svc)
        svc.import_paper = AsyncMock(side_effect=[
            Exception("LLM 抽取失败"),
            PaperImportResponse(
                paper_id=gen_paper_id("papers/b.md"), title="", question_count=1,
            ),
        ])

        resp = await svc.start_batch_import()
        await mysql_import._batch_jobs[resp.job_id]["task"]

        status = svc.get_batch_status(resp.job_id)
        assert status.succeeded == 1
        assert status.failed == 1
        assert status.finished is True
        assert status.results[0].status == "failed"
        assert "LLM 抽取失败" in status.results[0].error
        assert status.results[1].status == "succeeded"
        assert svc.import_paper.call_count == 2

    async def test_get_batch_status_not_found(self, mock_deps):
        """轮询不存在的 job_id 抛 AppError(404)。"""
        minio_repo, mysql_repo, llm_svc, prompt_svc = mock_deps
        svc = MySqlImportService(minio_repo, mysql_repo, llm_svc, prompt_svc)

        with pytest.raises(AppError) as exc_info:
            svc.get_batch_status("nonexistent_job")
        assert exc_info.value.status_code == 404

    async def test_start_batch_import_truncation_warns(self, mock_deps, caplog):
        """列桶达到上限时：响应标记 truncated=True 并记录 warning。"""
        minio_repo, mysql_repo, llm_svc, prompt_svc = mock_deps
        mysql_import._batch_jobs.clear()
        minio_repo.list_md_files.return_value = [
            MinioFileItem(object_key=f"papers/{i}.md", size=1, last_modified="")
            for i in range(3)
        ]
        mysql_repo._execute.return_value = []
        svc = MySqlImportService(minio_repo, mysql_repo, llm_svc, prompt_svc)
        svc.import_paper = AsyncMock(return_value=PaperImportResponse(
            paper_id="paper_x", title="", question_count=0,
        ))

        with patch.object(mysql_import, "_LIST_MD_LIMIT", 3), \
                caplog.at_level("WARNING"):
            resp = await svc.start_batch_import()

        assert resp.truncated is True
        assert any("达到列桶上限" in r.message for r in caplog.records)

# -*- coding: utf-8 -*-
"""MySQL 导入编排服务 — 独立于 HugeGraph/Milvus 流水线。"""
import asyncio
import csv
import io
import json
import os
import re
import tempfile
import uuid
import zipfile

from core.exceptions import AppError
from model.mysql_schemas import (
    AnswerImportResponse,
    AnswerSheetImportResponse,
    BatchFileResult,
    BatchImportResponse,
    BatchImportStatusResponse,
    PaperImportResponse,
    RecommendQuestion,
    RecommendResponse,
    WeakKnowledgePoint,
)
from libs.id_gen import gen_paper_id, gen_question_id
from libs.minio import MinioRepository
from libs.mysql import MySqlRepository
from service.llm import LlmService
from service.prompt import PromptService
from logs.decorators import log_step
from logs.logging import get_logger

log = get_logger(__name__)

# 进程内批量导入 job 注册表（重启即失，一次性操作可重跑）
_batch_jobs: dict[str, dict] = {}

_LIST_MD_LIMIT = 100000  # list_md_files 列桶上限（达到即可能截断）


@log_step
class MySqlImportService:
    """MySQL 导入编排 — 从 MinIO 读取文件，LLM/OCR 抽取，写入 MySQL。

    不依赖 HugeGraph、Milvus、Redis Stream。仅复用：
    - MinioRepository（读文件）
    - PromptService + LlmService（LLM 抽取试卷）
    - OCR 服务（答题卡识别）
    - hashlib.md5() ID 派生逻辑
    """

    def __init__(
        self,
        minio_repo: MinioRepository,
        mysql_repo: MySqlRepository,
        llm_svc: LlmService,
        prompt_svc: PromptService,
    ):
        self._minio = minio_repo
        self._mysql = mysql_repo
        self._llm = llm_svc
        self._prompt = prompt_svc

    async def import_paper(self, object_key: str) -> PaperImportResponse:
        """从 MinIO 读取试卷 markdown，LLM 抽取后写入 exam_papers + questions。

        流程：MinIO 取文件 → LLM 抽取 → 写 exam_papers + questions
        """
        log.info("MySQL 试卷导入开始: object_key=%s", object_key)

        # 1. 从 MinIO 读取
        markdown = await self._minio.get_object_text(object_key)

        # 2. LLM 抽取（复用 prompt + llm 服务，不连 HugeGraph/Milvus）
        prompt = self._prompt.build_prompt_sync(markdown)
        extracted = await self._llm.extract(prompt)

        # 3. 生成 ID 并写入 exam_papers
        paper_id = gen_paper_id(object_key)
        # 注意：LlmExtractResult.ExamPaper 无 exam_type/year 字段（LLM 输出 schema 不含），
        # 对应列可空，置 None 由数据库存 NULL。
        paper_data = {
            "id": paper_id,
            "title": extracted.exam_paper.title or "",
            "grade": extracted.exam_paper.grade,
            "subject": extracted.exam_paper.subject or "数学",
            "total_score": extracted.exam_paper.total_score,
            "duration_minutes": extracted.exam_paper.duration_minutes,
            "exam_type": None,
            "paper_year": None,
        }
        await self._mysql.upsert("exam_papers", paper_data, ["id"])
        log.info("试卷已写入 MySQL: %s", paper_id)

        # 4. 逐题写入 questions
        questions_written = 0
        for idx, q in enumerate(extracted.questions):
            question_id = gen_question_id(object_key, q.number)
            # 注意：Question 模型字段为 candidate_knowledge_points（四级知识点名称列表），
            # 映射写入 knowledge_point_ids JSON 列；difficulty 不在 LLM 输出 schema 中，置 None。
            q_data = {
                "id": question_id,
                "exam_paper_id": paper_id,
                "number": q.number,
                "content": q.content or "",
                "answer": q.answer,
                "score": q.score,
                "question_type": q.question_type or "",
                "difficulty": None,
                "knowledge_point_ids": json.dumps(q.candidate_knowledge_points)
                if q.candidate_knowledge_points else None,
                "img_url": json.dumps(q.img_url) if q.img_url else None,
                "answer_img": json.dumps(q.answer_img) if q.answer_img else None,
                "sort_order": idx + 1,
            }
            await self._mysql.upsert("questions", q_data, ["id"])
            questions_written += 1

        log.info(
            "MySQL 试卷导入完成: paper_id=%s, questions=%d",
            paper_id, questions_written,
        )
        return PaperImportResponse(
            paper_id=paper_id,
            title=extracted.exam_paper.title or "",
            question_count=questions_written,
            imported=True,
        )

    async def import_answers(
        self, object_key: str, paper_id: str
    ) -> AnswerImportResponse:
        """从 MinIO 读取答案 markdown，解析后 UPDATE 已有题目的 answer 字段。

        流程：MinIO 取文件 → 解析答案表格/文本 → UPDATE questions.answer
        """
        log.info("MySQL 答案导入开始: object_key=%s, paper_id=%s", object_key, paper_id)

        # 1. 验证试卷存在
        paper = await self._mysql.find_one("exam_papers", {"id": paper_id})
        if not paper:
            from core.exceptions import PaperNotFound
            raise PaperNotFound(paper_id)

        # 2. 从 MinIO 读取答案文件
        answers_md = await self._minio.get_object_text(object_key)

        # 3. 简化的答案解析：按题号匹配（复用 scoring 模块的 HTML 表格解析）
        from service.scoring.table_parser import _parse_html_table
        from service.scoring.extraction import _extract_student_answers

        parsed_answers = _extract_student_answers(answers_md)

        if not parsed_answers:
            log.warning("未检测到答题卡表格格式，尝试 markdown 切分...")
            # Try markdown-based extraction as fallback for standard answer formats
            try:
                from service.scoring.extraction import _extract_answers_from_markdown
                questions = await self._mysql.find_all(
                    "questions", {"exam_paper_id": paper_id}, limit=100
                )
                numbers = [q["number"] for q in questions]
                if numbers:
                    parsed_answers = _extract_answers_from_markdown(answers_md, numbers)
            except Exception:
                pass

        # 4. 批量 UPDATE questions.answer
        updated = 0
        for number, answer_text in parsed_answers.items():
            question_id = gen_question_id(object_key.rsplit("/", 1)[-1], number)
            # 尝试用从 paper_id 查找的题目来更新
            q = await self._mysql.find_one(
                "questions", {"exam_paper_id": paper_id, "number": number}
            )
            if q:
                await self._mysql.upsert(
                    "questions",
                    {"id": q["id"], "answer": answer_text},
                    ["id"],
                )
                updated += 1

        log.info("MySQL 答案导入完成: updated=%d", updated)
        return AnswerImportResponse(paper_id=paper_id, updated_count=updated)

    async def import_answer_sheet(
        self, object_key: str, paper_id: str
    ) -> AnswerSheetImportResponse:
        """从 MinIO 读取答题卡图片，OCR 识别后写入 students + answer_sheets。

        流程：MinIO 取图片 → OCR → 提取学生信息 → UPSERT students → 写 answer_sheets
        """
        log.info(
            "MySQL 答题卡导入开始: object_key=%s, paper_id=%s",
            object_key, paper_id,
        )

        # 1. 验证试卷存在
        paper = await self._mysql.find_one("exam_papers", {"id": paper_id})
        if not paper:
            from core.exceptions import PaperNotFound
            raise PaperNotFound(paper_id)

        # 2. 从 MinIO 获取答题卡图片（二进制）
        #    注意 MinioRepository.get_object_text 返回文本，图片需 get_object 返回 bytes
        try:
            response = await self._minio._client.get_object(
                self._minio.bucket, object_key
            )
            image_bytes = await response.read()
            response.release()  # aiohttp 的 release() 是同步方法（见 libs/minio.py 同款用法）
        except Exception as exc:
            from core.exceptions import MinioObjectNotFound
            raise MinioObjectNotFound(object_key) from exc

        # 3. 调用 OCR 服务
        import httpx
        from conf.config import Settings
        settings = Settings()
        ocr_result_text = ""
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                files = {"file": (os.path.basename(object_key), image_bytes, "image/jpeg")}
                resp = await client.post(settings.ocr_service_url, files=files)
                resp.raise_for_status()
                ocr_data = resp.json()
                ocr_result_text = ocr_data.get("markdown", "") or ocr_data.get("text", "")
        except Exception as exc:
            from core.exceptions import OcrServiceError
            raise OcrServiceError(f"OCR 识别失败: {exc}") from exc

        # 4. 从 OCR 结果中提取学生信息和各题得分
        #    复用 scoring 模块的模块级解析函数（ScoringService 依赖 HugeGraph，这里不使用）
        from service.scoring.meta import _extract_paper_meta
        from service.scoring.extraction import _extract_student_answers

        student_name = _extract_paper_meta(ocr_result_text).get("student_name", "未知")
        student_answers = _extract_student_answers(ocr_result_text)

        # 5. UPSERT students（school_name + student_no 唯一约束）
        student_data = {
            "name": student_name,
            "grade": paper.get("grade"),
            "school_name": "未知学校",  # OCR 可能提取，先设默认
            "student_no": object_key,   # 临时用 object_key 做学号
        }
        await self._mysql.upsert("students", student_data, ["school_name", "student_no"])

        # 查询刚才 upsert 的 student_id
        student_row = await self._mysql.find_one(
            "students",
            {"school_name": "未知学校", "student_no": object_key},
        )
        student_id = student_row["id"] if student_row else 0

        # 6. 查询试卷的所有题目
        questions = await self._mysql.find_all(
            "questions", {"exam_paper_id": paper_id}, limit=100
        )

        # 7. 写入 answer_sheets
        scored_count = 0
        total_obtained = 0.0
        for q in questions:
            answer_text = student_answers.get(q["number"])
            score_str = None
            # 如果答案中包含分数标注（如 "5分"），尝试提取
            if answer_text:
                score_match = re.search(r"(\d+)\s*分", answer_text)
                if score_match:
                    score_str = score_match.group(1)

            sheet_data = {
                "student_id": student_id,
                "exam_paper_id": paper_id,
                "question_id": q["id"],
                "student_answer": answer_text,
                "score_obtained": float(score_str) if score_str else None,
                "is_correct": None,  # 未分析
                "answer_img": json.dumps([object_key]),
                "marked_at": None,
            }
            await self._mysql.upsert(
                "answer_sheets", sheet_data,
                ["student_id", "question_id", "exam_paper_id"],
            )
            if score_str:
                scored_count += 1
                total_obtained += float(score_str)

        log.info(
            "MySQL 答题卡导入完成: student_id=%d, scored=%d",
            student_id, scored_count,
        )
        return AnswerSheetImportResponse(
            student_id=student_id,
            student_name=student_name,
            paper_id=paper_id,
            scored_count=scored_count,
            total_obtained=total_obtained,
        )

    async def export_csv(
        self, tables: list[str], paper_id: str | None = None
    ) -> str:
        """导出指定表为 CSV，打包为 ZIP 文件，返回 zip 文件路径。"""
        zip_path = tempfile.mktemp(suffix=".zip")

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for table in tables:
                if table == "exam_papers":
                    if paper_id:
                        rows = [await self._mysql.find_one("exam_papers", {"id": paper_id})]
                        rows = [r for r in rows if r]
                    else:
                        rows = await self._mysql.find_all("exam_papers")
                elif table == "questions":
                    where = {"exam_paper_id": paper_id} if paper_id else None
                    rows = await self._mysql.find_all("questions", where, limit=500)
                elif table == "answer_sheets":
                    where = {"exam_paper_id": paper_id} if paper_id else None
                    rows = await self._mysql.find_all("answer_sheets", where, limit=2000)
                elif table == "students":
                    rows = await self._mysql.find_all("students", limit=500)
                elif table == "knowledge_points":
                    rows = await self._mysql.find_all("knowledge_points", limit=500)
                elif table == "formulas_theorems":
                    rows = await self._mysql.find_all("formulas_theorems", limit=500)
                else:
                    log.warning("未知表名，跳过: %s", table)
                    continue

                if not rows:
                    log.info("表 %s 无数据", table)
                    continue

                output = io.StringIO()
                writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()))
                writer.writeheader()
                writer.writerows(rows)
                zf.writestr(f"{table}.csv", output.getvalue())

        log.info("CSV 导出完成: tables=%s, zip=%s", tables, zip_path)
        return zip_path

    async def get_weak_kp_recommend(
        self,
        student_id: int,
        exam_paper_id: str,
        accuracy_threshold: float = 0.6,
    ) -> RecommendResponse:
        """薄弱知识点推荐：找到正确率 < threshold 的知识点并推荐同类题。

        注意：questions.knowledge_point_ids 存的是 LLM 抽取的知识点名称字符串
        （如 ["交集", "并集"]），因此与 knowledge_points 表按 name 关联。
        """
        # 查询薄弱知识点
        # JSON_TABLE 按名称展开 knowledge_point_ids，与 knowledge_points.name 关联
        weak_sql = """
        SELECT kp.id, kp.name,
               COUNT(*) AS total,
               SUM(a.is_correct) AS correct,
               ROUND(SUM(a.is_correct) / COUNT(*), 2) AS accuracy
        FROM answer_sheets a
        JOIN questions q ON a.question_id = q.id
        JOIN JSON_TABLE(q.knowledge_point_ids, '$[*]'
             COLUMNS (kp_name VARCHAR(100) PATH '$')) jt
        JOIN knowledge_points kp ON kp.name = jt.kp_name
        WHERE a.student_id = :student_id
          AND a.exam_paper_id = :exam_paper_id
          AND a.is_correct IS NOT NULL
        GROUP BY kp.id, kp.name
        HAVING accuracy < :threshold
        """
        weak_rows = await self._mysql._execute(weak_sql, {
            "student_id": student_id,
            "exam_paper_id": exam_paper_id,
            "threshold": accuracy_threshold,
        })

        weak_kps = [
            WeakKnowledgePoint(
                kp_id=r["id"],
                kp_name=r["name"],
                total=r["total"],
                correct=r["correct"],
                accuracy=r["accuracy"],
            )
            for r in weak_rows
        ]

        # 为每个薄弱知识点推荐同类题（按知识点名称匹配）
        all_recommended: list[RecommendQuestion] = []
        seen_ids: set[str] = set()
        for kp in weak_kps:
            rec_sql = """
            SELECT q.id, q.number, q.content, q.question_type, q.difficulty
            FROM questions q
            WHERE JSON_CONTAINS(q.knowledge_point_ids, :kp_name_json)
              AND q.id NOT IN (
                  SELECT question_id FROM answer_sheets WHERE student_id = :student_id
              )
            ORDER BY q.difficulty
            LIMIT 5
            """
            rec_rows = await self._mysql._execute(rec_sql, {
                "kp_name_json": json.dumps(kp.kp_name),
                "student_id": student_id,
            })
            for r in rec_rows:
                if r["id"] not in seen_ids:
                    seen_ids.add(r["id"])
                    all_recommended.append(RecommendQuestion(
                        id=r["id"],
                        number=r["number"],
                        content=r["content"][:200] if r["content"] else "",
                        question_type=r["question_type"],
                        difficulty=r["difficulty"],
                    ))

        log.info(
            "薄弱知识点推荐完成: student_id=%d, weak_kps=%d, recommended=%d",
            student_id, len(weak_kps), len(all_recommended),
        )
        return RecommendResponse(
            student_id=student_id,
            exam_paper_id=exam_paper_id,
            weak_knowledge_points=weak_kps,
            recommended_questions=all_recommended,
        )

    async def start_batch_import(self) -> BatchImportResponse:
        """一键批量增量导入：列出桶内全部 .md，跳过已入库，后台逐个 import_paper。"""
        md_files = await self._minio.list_md_files(prefix="", limit=_LIST_MD_LIMIT)
        truncated = len(md_files) >= _LIST_MD_LIMIT
        if truncated:
            log.warning("桶内 .md 文件数达到列桶上限 %d，可能存在未列出的文件", _LIST_MD_LIMIT)
        existing_rows = await self._mysql._execute("SELECT id FROM exam_papers")
        existing_ids = {row["id"] for row in existing_rows}

        to_import = [
            f.object_key for f in md_files
            if gen_paper_id(f.object_key) not in existing_ids
        ]
        skipped = len(md_files) - len(to_import)
        job_id = uuid.uuid4().hex

        _batch_jobs[job_id] = {
            "task": asyncio.create_task(self._run_batch(job_id, to_import)),
            "status": "running",
            "total": len(md_files),
            "succeeded": 0,
            "failed": 0,
            "skipped": skipped,
            "finished": False,
            "results": [],
        }
        log.info(
            "批量增量导入已启动: job_id=%s, total=%d, skipped=%d, to_import=%d",
            job_id, len(md_files), skipped, len(to_import),
        )
        return BatchImportResponse(
            job_id=job_id, total=len(md_files), skipped=skipped,
            truncated=truncated,
        )

    async def _run_batch(self, job_id: str, object_keys: list[str]) -> None:
        """后台顺序导入；单个文件失败记录后继续，不中断整批。"""
        job = _batch_jobs[job_id]
        for key in object_keys:
            try:
                result = await self.import_paper(key)
                job["succeeded"] += 1
                job["results"].append({
                    "object_key": key,
                    "paper_id": result.paper_id,
                    "status": "succeeded",
                    "error": None,
                })
            except Exception as exc:
                job["failed"] += 1
                job["results"].append({
                    "object_key": key,
                    "paper_id": gen_paper_id(key),
                    "status": "failed",
                    "error": str(exc),
                })
                log.warning("批量导入单文件失败: %s, err=%s", key, exc)
        job["status"] = "completed"
        job["finished"] = True
        log.info(
            "批量增量导入完成: job_id=%s, succeeded=%d, failed=%d",
            job_id, job["succeeded"], job["failed"],
        )

    def get_batch_status(self, job_id: str) -> BatchImportStatusResponse:
        """查询批量导入进度；job 不存在抛 AppError(404)。"""
        job = _batch_jobs.get(job_id)
        if job is None:
            raise AppError(
                f"批量导入任务不存在: {job_id}",
                status_code=404,
                detail={"job_id": job_id},
            )
        return BatchImportStatusResponse(
            job_id=job_id,
            status=job["status"],
            total=job["total"],
            succeeded=job["succeeded"],
            failed=job["failed"],
            skipped=job["skipped"],
            finished=job["finished"],
            results=[BatchFileResult(**r) for r in job["results"]],
        )

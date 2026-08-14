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
from service.mysql_events import parse_event_key, resolve_paper_id
from logs.decorators import log_step
from logs.logging import get_logger

log = get_logger(__name__)

# 进程内批量导入 job 注册表（重启即失，一次性操作可重跑）
_batch_jobs: dict[str, dict] = {}

_LIST_MD_LIMIT = 100000  # list_md_files 列桶上限（达到即可能截断）

# 纯答案卷判定：文件名含「答案」且不含「完整带答案卷」类标记 → 视为纯答案卷，批量导入时跳过。
# 保留「周末测试卷含答案」「试卷+答案」「答案带题」等完整卷；「无答案」为无答案的完整试卷，也保留。
_ANSWER_KEEP_MARKERS = (
    "含答案", "及答案", "答案带题", "试卷+答案", "试题和答案", "学生版+答案", "无答案",
)


def _is_answer_only(object_key: str) -> bool:
    """判断 MinIO 对象是否为纯答案卷（仅依据文件名启发式）。"""
    name = object_key.rsplit("/", 1)[-1]
    if any(m in name for m in _ANSWER_KEEP_MARKERS):
        return False
    return "答案" in name


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

    async def handle_event(self, object_key: str) -> dict:
        """消费 extract:events 事件，按 category 路由到对应导入方法。

        answer/answer_sheet 依赖 paper_id，由 paper_file_id 反解；失败抛异常不 ack（交 Redis 重试）。
        """
        category, paper_file_id = parse_event_key(object_key)

        if category == "paper":
            result = await self.import_paper(object_key)
            return {"category": "paper", "paper_id": result.paper_id}

        if category not in ("answer", "answer_sheet"):
            raise ValueError(f"未知 category: {category}")

        paper_id = await resolve_paper_id(self._minio, paper_file_id)

        if category == "answer":
            result = await self.import_answers(object_key, paper_id)
            return {"category": "answer", "updated": result.updated_count}

        if category == "answer_sheet":
            ocr_text = await self._minio.get_object_text(object_key)
            result = await self.import_answer_sheet_from_text(ocr_text, paper_id, source_key=object_key)
            return {"category": "answer_sheet", "student_id": result.student_id}

        raise ValueError(f"未知 category: {category}")

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
        kp_id_map = await self._load_kp_name_map()
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

            # 写题目-知识点关联表（名称 → id，解析失败跳过并记日志）
            for kp_name in (q.candidate_knowledge_points or []):
                kp_id = kp_id_map.get(kp_name.strip())
                if kp_id is None:
                    log.warning(
                        "知识点名称未匹配，跳过关联: paper=%s question=%s kp=%s",
                        paper_id, q.number, kp_name,
                    )
                    continue
                await self._mysql.upsert(
                    "question_knowledge_point",
                    {"question_id": question_id, "knowledge_point_id": kp_id},
                    ["question_id", "knowledge_point_id"],
                )

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
        """从 MinIO 读取答题卡图片，OCR 识别后委托 import_answer_sheet_from_text。"""
        log.info("MySQL 答题卡导入开始: object_key=%s, paper_id=%s", object_key, paper_id)

        # 1. 验证试卷存在（先于读图/OCR，fail-fast）
        paper = await self._mysql.find_one("exam_papers", {"id": paper_id})
        if not paper:
            from core.exceptions import PaperNotFound
            raise PaperNotFound(paper_id)

        # 2. 从 MinIO 获取答题卡图片（二进制）
        try:
            response = await self._minio._client.get_object(self._minio.bucket, object_key)
            image_bytes = await response.read()
            response.release()
        except Exception as exc:
            from core.exceptions import MinioObjectNotFound
            raise MinioObjectNotFound(object_key) from exc

        # 3. 调用 OCR 服务
        import httpx
        from conf.config import Settings
        settings = Settings()
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

        return await self.import_answer_sheet_from_text(ocr_result_text, paper_id, source_key=object_key)

    async def import_answer_sheet_from_text(
        self, ocr_text: str, paper_id: str, source_key: str | None = None
    ) -> AnswerSheetImportResponse:
        """给定 OCR 文本，提取学生信息与各题得分，写入 students + answer_sheets + student_kp_scores。"""
        log.info("MySQL 答题卡文本入库开始: paper_id=%s", paper_id)

        paper = await self._mysql.find_one("exam_papers", {"id": paper_id})
        if not paper:
            from core.exceptions import PaperNotFound
            raise PaperNotFound(paper_id)

        from service.scoring.meta import _extract_paper_meta
        from service.scoring.extraction import _extract_student_answers, _extract_student_scores

        student_name = _extract_paper_meta(ocr_text).get("student_name") or "未知"
        student_answers = _extract_student_answers(ocr_text)
        student_scores = _extract_student_scores(ocr_text)

        student_no = source_key or paper_id
        student_data = {
            "name": student_name,
            "grade": paper.get("grade"),
            "school_name": "未知学校",
            "student_no": student_no,
        }
        await self._mysql.upsert("students", student_data, ["school_name", "student_no"])

        student_row = await self._mysql.find_one(
            "students", {"school_name": "未知学校", "student_no": student_no}
        )
        student_id = student_row["id"] if student_row else 0

        questions = await self._mysql.find_all(
            "questions", {"exam_paper_id": paper_id}, limit=100
        )

        scored_count = 0
        total_obtained = 0.0
        q_score_map: dict[str, float] = {}
        for q in questions:
            answer_text = student_answers.get(q["number"])
            score_str = None
            if answer_text:
                score_match = re.search(r"(\d+)\s*分", answer_text)
                if score_match:
                    score_str = score_match.group(1)
            # 兜底：旧 OCR 无 "题号/答案" 表时，从 PaddleVL markdown 提取主观题得分
            if score_str is None and q["number"] in student_scores:
                score_str = str(student_scores[q["number"]])

            q_score_map[q["id"]] = float(score_str) if score_str else 0.0

            sheet_data = {
                "student_id": student_id,
                "exam_paper_id": paper_id,
                "question_id": q["id"],
                "student_answer": answer_text,
                "score_obtained": float(score_str) if score_str else None,
                "is_correct": None,
                "answer_img": json.dumps([source_key]) if source_key else None,
                "marked_at": None,
            }
            await self._mysql.upsert(
                "answer_sheets", sheet_data,
                ["student_id", "question_id", "exam_paper_id"],
            )
            if score_str:
                scored_count += 1
                total_obtained += float(score_str)

        await self._upsert_student_kp_scores(student_id, paper_id, questions, q_score_map)

        log.info(
            "MySQL 答题卡文本入库完成: student_id=%d, scored=%d", student_id, scored_count
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
        score_rate_threshold: float = 0.6,
    ) -> RecommendResponse:
        """薄弱知识点推荐：按得分率 < threshold 筛知识点并推荐同类题。

        数据来源为 student_kp_scores（导入答题卡时预聚合的学生-知识点得分），
        推荐同类题走 question_knowledge_point 关联表，不再依赖名称字符串 JOIN。
        """
        # 查询薄弱知识点（得分率低于阈值）
        weak_sql = """
        SELECT s.knowledge_point_id AS id, kp.name,
               s.total_score, s.full_score, s.score_rate
        FROM student_kp_scores s
        JOIN knowledge_points kp ON kp.id = s.knowledge_point_id
        WHERE s.student_id = :student_id
          AND s.exam_paper_id = :exam_paper_id
          AND s.full_score > 0
          AND s.score_rate < :threshold
        """
        weak_rows = await self._mysql._execute(weak_sql, {
            "student_id": student_id,
            "exam_paper_id": exam_paper_id,
            "threshold": score_rate_threshold,
        })

        weak_kps = [
            WeakKnowledgePoint(
                kp_id=r["id"],
                kp_name=r["name"],
                total_score=float(r["total_score"]),
                full_score=float(r["full_score"]),
                score_rate=float(r["score_rate"]),
            )
            for r in weak_rows
        ]

        # 为每个薄弱知识点推荐同类题（通过关联表按知识点 id 匹配）
        all_recommended: list[RecommendQuestion] = []
        seen_ids: set[str] = set()
        for kp in weak_kps:
            rec_sql = """
            SELECT q.id, q.number, q.content, q.question_type, q.difficulty
            FROM questions q
            JOIN question_knowledge_point qkp ON qkp.question_id = q.id
            WHERE qkp.knowledge_point_id = :kp_id
              AND q.id NOT IN (
                  SELECT question_id FROM answer_sheets WHERE student_id = :student_id
              )
            ORDER BY q.difficulty
            LIMIT 5
            """
            rec_rows = await self._mysql._execute(rec_sql, {
                "kp_id": kp.kp_id,
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

    async def _load_kp_name_map(self) -> dict[str, int]:
        """加载 knowledge_points 表 name → id 映射（同名多级时优先 level==4）。"""
        rows = await self._mysql._execute("SELECT id, name, level FROM knowledge_points")
        kp_map: dict[str, int] = {}
        for r in rows:
            name = (r.get("name") or "").strip()
            if not name:
                continue
            level = r.get("level")
            if name in kp_map and level != 4:
                continue
            kp_map[name] = r["id"]
        return kp_map

    async def _upsert_student_kp_scores(
        self,
        student_id: int,
        paper_id: str,
        questions: list[dict],
        q_score_map: dict[str, float],
    ) -> None:
        """按知识点聚合学生得分（得分率），写入 student_kp_scores（三键）。

        一道题挂多个知识点时，该题的得分与满分同时计入每个知识点（不做分摊）。
        """
        q_full_map = {
            q["id"]: float(q["score"]) if q.get("score") is not None else 0.0
            for q in questions
        }
        rows = await self._mysql._execute(
            """
            SELECT qkp.question_id, qkp.knowledge_point_id
            FROM question_knowledge_point qkp
            JOIN questions q ON q.id = qkp.question_id
            WHERE q.exam_paper_id = :paper_id
            """,
            {"paper_id": paper_id},
        )
        agg: dict[int, dict[str, float]] = {}
        for r in rows:
            kpid = r["knowledge_point_id"]
            bucket = agg.setdefault(kpid, {"total": 0.0, "full": 0.0, "count": 0})
            bucket["total"] += q_score_map.get(r["question_id"], 0.0)
            bucket["full"] += q_full_map.get(r["question_id"], 0.0)
            bucket["count"] += 1

        for kpid, b in agg.items():
            if b["full"] <= 0:
                continue
            await self._mysql.upsert(
                "student_kp_scores",
                {
                    "student_id": student_id,
                    "knowledge_point_id": kpid,
                    "exam_paper_id": paper_id,
                    "total_score": b["total"],
                    "full_score": b["full"],
                    "score_rate": round(b["total"] / b["full"], 4),
                    "question_count": int(b["count"]),
                },
                ["student_id", "knowledge_point_id", "exam_paper_id"],
            )

    async def start_batch_import(self) -> BatchImportResponse:
        """一键批量增量导入：列出桶内全部 .md，跳过纯答案卷与已入库，后台逐个 import_paper。"""
        md_files = await self._minio.list_md_files(prefix="", limit=_LIST_MD_LIMIT)
        truncated = len(md_files) >= _LIST_MD_LIMIT
        if truncated:
            log.warning("桶内 .md 文件数达到列桶上限 %d，可能存在未列出的文件", _LIST_MD_LIMIT)
        existing_rows = await self._mysql._execute("SELECT id FROM exam_papers")
        existing_ids = {row["id"] for row in existing_rows}

        answer_only = [f.object_key for f in md_files if _is_answer_only(f.object_key)]
        to_import = [
            f.object_key for f in md_files
            if not _is_answer_only(f.object_key)
            and gen_paper_id(f.object_key) not in existing_ids
        ]
        skipped = len(md_files) - len(to_import)
        if answer_only:
            log.info("跳过纯答案卷 %d 份", len(answer_only))
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

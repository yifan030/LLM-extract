# -*- coding: utf-8 -*-
"""试卷判分服务 —— 纯 markdown 解析，不走模型逻辑。"""
import re

from logs.logging import get_logger
from model.schemas import QuestionScore, ScoringResponse, SectionScore
from model.schemas import QuestionDetail  # noqa: F401 — 类型标注引用
from libs.hugegraph import HugeGraphRepository
from service.knowledge import KnowledgeService

from service.scoring.constants import _DB_TYPE_TO_SECTION, _SECTION_ORDER
from service.scoring.extraction import (
    _extract_student_answers,
    _extract_answers_from_markdown,
    _extract_images_from_markdown,
    _extract_image_urls,
)
from service.scoring.meta import (
    _extract_paper_meta,
    _find_section_ranges,
    _extract_questions_from_range,
)

log = get_logger(__name__)


def _num_sort_key(number: str) -> tuple:
    """题号排序 key：优先按数值排序（1 < 2 < 10），非数字题号排在后面。"""
    m = re.match(r"^(\d+)", number.strip())
    if m:
        return (0, int(m.group(1)), number)
    return (1, 0, number)


def _derive_section_score(scores: list[int]) -> int | None:
    """从分值列表推导每题分值：取众数，平手取最大值；无分值返回 None。"""
    if not scores:
        return None
    counts: dict[int, int] = {}
    for s in scores:
        counts[s] = counts.get(s, 0) + 1
    return max(counts, key=lambda k: (counts[k], k))


class ScoringService:
    """试卷判分服务 —— 纯规则解析 markdown，不调用 LLM。"""

    def __init__(self, hg_repo: HugeGraphRepository):
        self._knowledge = KnowledgeService(hg_repo)

    async def parse(self, markdown: str, paper_id: str | None = None) -> ScoringResponse:
        """解析 OCR markdown 为结构化 JSON，不调用 LLM。

        两种模式：
        - 答题卡模式：传入 paper_id，结合数据库题目与答题卡学生答案；
        - 完整试卷模式：不传 paper_id，纯 markdown 解析（无标准答案/知识点）。
        """
        if paper_id:
            return await self._parse_answer_card(markdown, paper_id)
        return self._parse_full_paper(markdown)

    # ── 答题卡模式：数据库为题目来源 ────────────────────────────

    async def _parse_answer_card(self, markdown: str, paper_id: str) -> ScoringResponse:
        """答题卡模式：从数据库读取题目，从答题卡表格提取学生答案。"""
        # 1. 提取学生答案（优先答题卡表格，回退到手写作答区域切分）
        student_answers = _extract_student_answers(markdown)

        # 2. 从数据库查询试卷全部试题（含标准答案、知识点）
        try:
            db_questions = await self._knowledge.list_paper_questions(paper_id)
        except Exception:
            log.warning("从数据库查询试题失败，paper_id=%s", paper_id, exc_info=True)
            db_questions = []

        # 3. 如果答题卡表格没提取到答案，回退到手写试卷切分（仅解答题）
        if not student_answers and db_questions:
            # 只对解答题做 markdown 切分——选择题/填空题的答案嵌在试题正文 OCR 中，
            # 无法通过题号切分来提取
            essay_numbers = [
                q.number for q in db_questions
                if _DB_TYPE_TO_SECTION.get(q.question_type, "") == "解答题"
            ]
            if essay_numbers:
                essay_answers = _extract_answers_from_markdown(markdown, essay_numbers)
                if essay_answers:
                    student_answers.update(essay_answers)
                    log.info(
                        "手写试卷模式：从 markdown 切分出 %d 道解答题的学生答案",
                        len(essay_answers),
                    )

        # 3.5 从 OCR markdown 提取图片 URL（DB 可能未存，答题卡图片在 markdown 中）
        markdown_images: dict[str, list[str]] = {}
        if db_questions:
            all_numbers = [q.number for q in db_questions]
            markdown_images = _extract_images_from_markdown(markdown, all_numbers)

        # 4. 按题型分组（单选题/多选题 归入 选择题）
        grouped: dict[str, list[QuestionDetail]] = {}
        for q in db_questions:
            sec_type = _DB_TYPE_TO_SECTION.get(q.question_type, q.question_type or "")
            grouped.setdefault(sec_type, []).append(q)

        # 5. 组装 section（固定题型顺序，题目按题号排序）
        sections: list[SectionScore] = []
        ordered_types = [t for t in _SECTION_ORDER if t in grouped]
        ordered_types += [t for t in grouped if t not in _SECTION_ORDER]
        for sec_type in ordered_types:
            qs = sorted(grouped[sec_type], key=lambda q: _num_sort_key(q.number))
            q_scores = [
                QuestionScore(
                    number=q.number,
                    content=q.content or "",
                    image_urls=_extract_image_urls(q.content or "")
                    + markdown_images.get(q.number, []),
                    student_answer=student_answers.get(q.number),
                    standard_answer=q.answer,
                    knowledge_points=list(q.knowledge_points),
                )
                for q in qs
            ]
            score_per_q = _derive_section_score(
                [q.score for q in qs if q.score is not None],
            )
            sections.append(SectionScore(
                type=sec_type,
                score_per_question=score_per_q,
                questions=q_scores,
            ))

        # 6. 试卷标题：优先数据库试卷标题，其次 markdown 标题
        paper_title = db_questions[0].exam_paper_title if db_questions else ""
        if not paper_title:
            paper_title = _extract_paper_meta(markdown).get("title", "")

        # 7. 总分：累加 DB 题目分值
        all_scores = [q.score for q in db_questions if q.score is not None]
        total_score = sum(all_scores) if all_scores else None

        return ScoringResponse(
            paper_title=paper_title,
            paper_id=paper_id,
            total_score=total_score,
            sections=sections,
        )

    # ── 完整试卷模式：纯 markdown 解析，不走数据库 ──────────────

    def _parse_full_paper(self, markdown: str) -> ScoringResponse:
        """完整试卷模式：纯 markdown 解析，不走数据库。"""
        # 1. 提取元信息
        meta = _extract_paper_meta(markdown)

        # 2. 提取学生答案（答题卡表格）
        student_answers = _extract_student_answers(markdown)

        # 3. 按题型分区
        section_ranges = _find_section_ranges(markdown)

        # 4. 构建 section 输出
        sections: list[SectionScore] = []

        for section_type, sec_start, sec_end in section_ranges:
            questions_raw = _extract_questions_from_range(
                markdown, sec_start, sec_end, section_type,
            )

            q_scores: list[QuestionScore] = []
            for q in questions_raw:
                num = q["number"]
                content = q.get("content", "")
                stu_ans = student_answers.get(num)
                image_urls = _extract_image_urls(content)

                q_scores.append(QuestionScore(
                    number=num,
                    content=content,
                    image_urls=image_urls,
                    student_answer=stu_ans,
                    standard_answer=None,
                    knowledge_points=[],
                ))

            # 从 section 标题提取每题原始分值，如 "每小题4分"
            score_per_q: int | None = None
            chunk = markdown[sec_start:sec_start + 200]
            spm = re.search(r"每(?:小)?题\s*(\d+)\s*分", chunk)
            if spm:
                score_per_q = int(spm.group(1))

            sections.append(SectionScore(
                type=section_type,
                score_per_question=score_per_q,
                questions=q_scores,
            ))

        return ScoringResponse(
            paper_title=meta["title"],
            paper_id="",
            total_score=meta["total_score"],
            sections=sections,
        )

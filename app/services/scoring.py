# -*- coding: utf-8 -*-
"""试卷判分服务 —— 纯 markdown 解析，不走模型逻辑。"""
import re
from html.parser import HTMLParser

from app.core.logging import get_logger
from app.domain.schemas import QuestionScore, ScoringResponse, SectionScore
from app.repositories.hugegraph import HugeGraphRepository
from app.services.knowledge import KnowledgeService

log = get_logger(__name__)

# 题型 section 标题模式
_SECTION_PATTERNS = [
    (re.compile(r"(?:一|1)[、.].*?选择"), "选择题"),
    (re.compile(r"(?:二|2)[、.].*?填空"), "填空题"),
    (re.compile(r"(?:三|3)[、.].*?解答"), "解答题"),
    (re.compile(r"(?:四|4)[、.].*?解答"), "解答题"),
]

# 题号行: "1. ..." 或 "1．..." 或 "1、..."
_QUESTION_NUM_RE = re.compile(r"^(\d{1,2})\s*[.．、]\s*")

# 选项行: "A. ..." 或 "A．..."
_OPTION_RE = re.compile(r"^([A-D])\s*[.．、]\s*(.+)")

# 试卷元信息
_TITLE_RE = re.compile(r"^#\s+(.+?)(?:\s*\d{4}\s*级)?(?:高一|高二|高三|初一|初二|初三)?\s*(?:入学|期末|期中|月考|模拟)?\s*(?:检测|考试)?\s*(?:试卷|试题)?")
_SUBJECT_RE = re.compile(r"(?:数学|语文|英语|物理|化学|生物|政治|历史|地理)")
_DURATION_RE = re.compile(r"时量\s*[:：]\s*(\d+)\s*分钟")
_TOTAL_SCORE_RE = re.compile(r"(?:满分|总分)\s*[:：]\s*(\d+)\s*分")


class _TableParser(HTMLParser):
    """解析 HTML <table>，提取二维数组 [[cell, ...], ...]."""

    def __init__(self):
        super().__init__()
        self.rows: list[list[str]] = []
        self._current_row: list[str] = []
        self._current_cell: str = ""
        self._in_td = False

    def handle_starttag(self, tag: str, attrs):
        if tag == "tr":
            self._current_row = []
        elif tag in ("td", "th"):
            self._in_td = True
            self._current_cell = ""

    def handle_endtag(self, tag: str):
        if tag in ("td", "th"):
            self._in_td = False
            self._current_row.append(self._current_cell.strip())
        elif tag == "tr":
            if self._current_row:
                self.rows.append(self._current_row)
            self._current_row = []

    def handle_data(self, data: str):
        if self._in_td:
            self._current_cell += data


def _parse_html_table(html: str) -> list[list[str]]:
    parser = _TableParser()
    parser.feed(html)
    return parser.rows


def _extract_student_answers(markdown: str) -> dict[str, str]:
    """从答题卡 <table> 中提取学生答案，返回 {题号: 答案}。"""
    # 匹配答题卡区域的表格
    table_re = re.compile(r"<table[^>]*>.*?</table>", re.DOTALL)
    # 先找所有表格，再筛选包含"题号"和"答案"的
    for m in table_re.finditer(markdown):
        table_html = m.group(0)
        rows = _parse_html_table(table_html)
        if not rows or len(rows) < 2:
            continue
        # 检查是否是答题卡：第一行包含"题号"，第二行包含"答案"
        header = "".join(rows[0])
        answer_row_label = "".join(rows[1]) if len(rows) > 1 else ""
        if "题号" in header and "答案" in answer_row_label:
            answers: dict[str, str] = {}
            # 第一行是题号列表，第二行是对应答案
            numbers = rows[0][1:]  # 跳过"题号"标签
            values = rows[1][1:]   # 跳过"答案"标签
            for i, num in enumerate(numbers):
                num = num.strip()
                if not num:
                    continue
                val = values[i].strip() if i < len(values) else ""
                if val:
                    answers[num] = val
            return answers
    return {}



def _extract_paper_meta(markdown: str) -> dict:
    """从 markdown 提取试卷元信息。"""
    meta: dict = {"title": "", "subject": "", "duration": None, "total_score": None}

    # 标题: 第一个 # 标题行
    title_m = re.search(r"^#\s+(.+)", markdown, re.MULTILINE)
    if title_m:
        meta["title"] = title_m.group(1).strip()

    # 科目
    subj_m = _SUBJECT_RE.search(markdown[:200] if title_m else markdown[:500])
    if subj_m:
        meta["subject"] = subj_m.group(0)

    # 时长
    dur_m = _DURATION_RE.search(markdown[:500])
    if dur_m:
        meta["duration"] = int(dur_m.group(1))

    # 总分
    score_m = _TOTAL_SCORE_RE.search(markdown[:500])
    if score_m:
        meta["total_score"] = int(score_m.group(1))

    return meta


def _find_boundary(markdown: str) -> int:
    """找到试题区域结束位置（参考答案之前）。"""
    boundary = len(markdown)
    for kw in ("# 参考答案", "# 数学参考答案", "答案与解析"):
        idx = markdown.find(kw)
        if idx != -1:
            boundary = min(boundary, idx)
    return boundary


def _find_section_ranges(markdown: str) -> list[tuple[str, int, int]]:
    """找到各题型 section 的起止位置，返回 [(type_name, start, end), ...]。
    只在试题区域搜索，不搜索参考答案区域。"""
    boundary = _find_boundary(markdown)
    search_md = markdown[:boundary]

    sections: list[tuple[str, int, int]] = []

    for pattern, type_name in _SECTION_PATTERNS:
        for m in pattern.finditer(search_md):
            sections.append((type_name, m.start(), m.end()))

    # 按位置排序
    sections.sort(key=lambda x: x[1])

    # 去重：同一起始位置只保留第一个
    seen: set[int] = set()
    unique: list[tuple[str, int, int]] = []
    for tname, start, end in sections:
        if start not in seen:
            seen.add(start)
            unique.append((tname, start, end))

    # 添加结束位置
    result: list[tuple[str, int, int]] = []
    for i, (tname, start, _) in enumerate(unique):
        if i + 1 < len(unique):
            end = unique[i + 1][1]
        else:
            end = boundary
        result.append((tname, start, end))

    return result


def _extract_questions_from_range(
    markdown: str, start: int, end: int, section_type: str
) -> list[dict]:
    """从 markdown 切片中提取题目列表。"""
    chunk = markdown[start:end]
    questions: list[dict] = []

    lines = chunk.split("\n")
    current_q: dict | None = None
    current_content_lines: list[str] = []

    for line in lines:
        stripped = line.strip()

        # 遇到 HTML table 或 "答题卡" 标记则停止提取内容
        if stripped.startswith("<table") or stripped.startswith("## 答题卡") or stripped.startswith("# 参考"):
            if current_q is not None:
                current_q["content"] = "\n".join(current_content_lines).strip()
                questions.append(current_q)
                current_q = None
                current_content_lines = []
            continue

        # 遇到新的 section 标题（如 "## 二、"）停止
        if re.match(r"^#{1,3}\s+(?:二|三|四|[一二三四])", stripped):
            if current_q is not None:
                current_q["content"] = "\n".join(current_content_lines).strip()
                questions.append(current_q)
                current_q = None
                current_content_lines = []
            continue

        qm = _QUESTION_NUM_RE.match(stripped)
        if qm:
            # 保存上一题
            if current_q is not None:
                current_q["content"] = "\n".join(current_content_lines).strip()
                questions.append(current_q)

            num = qm.group(1)
            rest = stripped[qm.end():]
            current_q = {"number": num, "content_lines": [rest]}
            current_content_lines = [rest]
        elif current_q is not None:
            current_content_lines.append(line)

    # 最后一题
    if current_q is not None:
        current_q["content"] = "\n".join(current_content_lines).strip()
        questions.append(current_q)

    return questions


# 图片 URL 提取
_IMG_SRC_RE = re.compile(r'<img[^>]+src="([^"]+)"')


def _extract_image_urls(text: str) -> list[str]:
    """从文本中提取所有 img 标签的 src URL。"""
    return _IMG_SRC_RE.findall(text)



class ScoringService:
    """试卷判分服务 —— 纯规则解析 markdown，不调用 LLM。"""

    def __init__(self, hg_repo: HugeGraphRepository):
        self._knowledge = KnowledgeService(hg_repo)

    async def parse(self, markdown: str, paper_id: str) -> ScoringResponse:
        """解析 OCR markdown 为结构化 JSON，不调用 LLM。"""
        # 1. 提取元信息
        meta = _extract_paper_meta(markdown)

        # 2. 提取学生答案（答题卡表格）
        student_answers = _extract_student_answers(markdown)

        # 3. 按题型分区
        section_ranges = _find_section_ranges(markdown)

        # 4. 从数据库查询标准答案和题目内容
        db_answers: dict[str, str] = {}
        db_contents: dict[str, str] = {}
        try:
            db_questions = await self._knowledge.list_paper_questions(paper_id)
            for q in db_questions:
                num = q.number
                if q.answer:
                    db_answers[num] = q.answer
                if q.content:
                    db_contents[num] = q.content
        except Exception:
            log.warning("从数据库查询试题失败，paper_id=%s", paper_id, exc_info=True)

        # 5. 构建 section 输出
        sections: list[SectionScore] = []

        for section_type, sec_start, sec_end in section_ranges:
            questions_raw = _extract_questions_from_range(
                markdown, sec_start, sec_end, section_type,
            )

            q_scores: list[QuestionScore] = []
            for q in questions_raw:
                num = q["number"]
                std_ans = db_answers.get(num)

                stu_ans = student_answers.get(num)
                content = db_contents.get(num) or q.get("content", "")
                image_urls = _extract_image_urls(content)

                q_scores.append(QuestionScore(
                    number=num,
                    content=content,
                    image_urls=image_urls,
                    student_answer=stu_ans,
                    standard_answer=std_ans,
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
            paper_id=paper_id,
            total_score=meta["total_score"],
            sections=sections,
        )

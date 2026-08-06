# -*- coding: utf-8 -*-
"""试卷结构解析 —— 元信息、section 边界、题目切分。"""
import re

from service.scoring.constants import (
    _SECTION_PATTERNS,
    _SUBJECT_RE,
    _DURATION_RE,
    _TOTAL_SCORE_RE,
    _QUESTION_NUM_RE,
)
from service.scoring.extraction import _extract_image_urls


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

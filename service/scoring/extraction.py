# -*- coding: utf-8 -*-
"""Markdown 文本提取 —— 学生答案、图片、页脚清洗。"""
import re

from service.scoring.constants import (
    _IMG_SRC_RE,
    _PAGE_FOOTER_LINES,
    _SUB_Q_RE,
)
from service.scoring.table_parser import _parse_html_table


def _clean_page_noise(text: str) -> str:
    """移除答题卡/试卷的固定页脚提示和页码行。"""
    lines = text.split("\n")
    kept: list[str] = []
    for line in lines:
        stripped = line.strip()
        # 跳过纯页脚提示
        if stripped in _PAGE_FOOTER_LINES:
            continue
        # 跳过纯页码行（"第X页 共Y页"）
        if re.match(r"^第\s*\d+\s*页\s*共\s*\d+\s*页\s*$", stripped):
            continue
        # 跳过全角数字 + 空格 + 纯数字组合（噪声）
        kept.append(line)
    return "\n".join(kept)


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


def _extract_student_scores(markdown: str) -> dict[str, float]:
    """从 PaddleVL 答题卡 markdown 提取主观题得分 {题号: 得分}。

    主观题区域形如 "14.(10分)"（题号+满分），区域内独立成行的 "8分" 为实际得分。
    与 _extract_student_answers 互补：后者面向旧 OCR 的 "题号/答案" 表格，
    本函数面向 8083 PaddleVL 的答题卡 markdown。
    """
    scores: dict[str, float] = {}
    q_pat = re.compile(
        r"(?:^|\n)\s*(\d{1,2})\s*[.．、]\s*[（(]\d+\s*分[）)]",
        re.MULTILINE,
    )
    positions = [(m.group(1), m.start()) for m in q_pat.finditer(markdown)]
    for i, (num, start) in enumerate(positions):
        end = positions[i + 1][1] if i + 1 < len(positions) else len(markdown)
        chunk = markdown[start:end]
        sm = re.search(r"(?:^|\n)\s*(\d+(?:\.\d+)?)\s*分\s*(?:\n|$)", chunk)
        if sm:
            scores[num] = float(sm.group(1))
    return scores


def _parent_number(number: str) -> str:
    """提取大题号：'14(1)' → '14'，'14' → '14'。"""
    m = _SUB_Q_RE.match(number.strip())
    return m.group(1) if m else number.strip()


def _extract_answers_from_markdown(
    markdown: str, question_numbers: list[str],
) -> dict[str, str]:
    """手写试卷回退策略：按题号从 OCR markdown 中切分各题的作答区域。

    当 _extract_student_answers 找不到答题卡表格时调用。
    对于选择题/填空题，OCR 输出的答案已嵌入试题正文中，无法通过切分提取，
    因此只对解答题（题号 >= 解答题起始号）生效。

    子题（如 "14(1)"）共享父题号 "14" 的作答区域。
    """
    if not question_numbers:
        return {}

    cleaned = _clean_page_noise(markdown)

    # 去重父题号，保持顺序
    seen: set[str] = set()
    parent_numbers: list[str] = []
    for num in question_numbers:
        parent = _parent_number(num)
        if parent not in seen:
            seen.add(parent)
            parent_numbers.append(parent)

    # 找到所有父题号在 markdown 中的位置
    # OCR 可能会把 "16." 转义为 "16\." 防止 markdown 列表解析
    positions: list[tuple[str, int]] = []
    for num in parent_numbers:
        escaped = re.escape(num)
        # 行首题号标记："14." "15．" "16\." "14 (10分)" 后跟内容
        pattern = re.compile(
            rf"(?:^|\n)\s*{escaped}\s*(?:\\?[.．、])\s*(?:\(?\d+\s*分\)?)?\s*\S",
            re.MULTILINE,
        )
        m = pattern.search(cleaned)
        if m:
            line_start = cleaned.rfind("\n", 0, m.start())
            positions.append((num, line_start + 1 if line_start != -1 else 0))
        else:
            # 宽松匹配：题号可能出现在 markdown 标题或文本中间
            loose = re.compile(
                rf"(?:^|\n)[^\n]*\b{escaped}\s*(?:\\?[.．、])\s*(?:\(?\d+\s*分\)?)?[^\n]*",
                re.MULTILINE,
            )
            lm = loose.search(cleaned)
            if lm:
                line_start = cleaned.rfind("\n", 0, lm.start())
                positions.append((num, line_start + 1 if line_start != -1 else 0))

    if not positions:
        return {}

    # 按位置排序
    positions.sort(key=lambda x: x[1])

    # 为每个父题号切分作答区域
    parent_answers: dict[str, str] = {}
    for i, (num, start) in enumerate(positions):
        if i + 1 < len(positions):
            end = positions[i + 1][1]
        else:
            end = len(cleaned)

        chunk = cleaned[start:end]

        # 去掉题号行本身（"14. (10分)" "14\." "14．" 等变体）
        chunk = re.sub(
            rf"^\s*{re.escape(num)}\s*(?:\\?[.．、])\s*(?:\(?\d+\s*分\)?)?\s*\n?",
            "", chunk,
        )

        # 去掉 "## 四、 解答题" 等 section 标题行
        chunk = re.sub(r"^#{1,3}\s*(?:一|二|三|四|五|六|[一二三四五六])[、.].*?(?:题)?\s*\n?", "", chunk, flags=re.MULTILINE)

        # 清理首尾空白和末尾页码
        chunk = chunk.strip()
        chunk = re.sub(r"\n?第\s*\d+\s*页\s*(?:共\s*\d+\s*页)?\s*$", "", chunk)

        if chunk:
            parent_answers[num] = chunk

    # 把父题号答案映射回子题号
    answers: dict[str, str] = {}
    for num in question_numbers:
        parent = _parent_number(num)
        if parent in parent_answers:
            answers[num] = parent_answers[parent]

    return answers


def _extract_images_from_markdown(
    markdown: str, question_numbers: list[str],
) -> dict[str, list[str]]:
    """从 OCR markdown 中按题号切分区域提取图片 URL。

    与 _extract_answers_from_markdown 使用相同的父题号定位逻辑，
    返回 {题号: [图片URL列表]}。
    """
    if not question_numbers:
        return {}

    cleaned = _clean_page_noise(markdown)

    # 去重父题号
    seen: set[str] = set()
    parent_numbers: list[str] = []
    for num in question_numbers:
        parent = _parent_number(num)
        if parent not in seen:
            seen.add(parent)
            parent_numbers.append(parent)

    # 找到所有父题号位置
    positions: list[tuple[str, int]] = []
    for num in parent_numbers:
        escaped = re.escape(num)
        pattern = re.compile(
            rf"(?:^|\n)\s*{escaped}\s*(?:\\?[.．、])\s*(?:\(?\d+\s*分\)?)?\s*\S",
            re.MULTILINE,
        )
        m = pattern.search(cleaned)
        if m:
            line_start = cleaned.rfind("\n", 0, m.start())
            positions.append((num, line_start + 1 if line_start != -1 else 0))
        else:
            loose = re.compile(
                rf"(?:^|\n)[^\n]*\b{escaped}\s*(?:\\?[.．、])\s*(?:\(?\d+\s*分\)?)?[^\n]*",
                re.MULTILINE,
            )
            lm = loose.search(cleaned)
            if lm:
                line_start = cleaned.rfind("\n", 0, lm.start())
                positions.append((num, line_start + 1 if line_start != -1 else 0))

    if not positions:
        return {}

    positions.sort(key=lambda x: x[1])

    # 为每个父题号提取区域内的图片 URL
    parent_images: dict[str, list[str]] = {}
    for i, (num, start) in enumerate(positions):
        end = positions[i + 1][1] if i + 1 < len(positions) else len(cleaned)
        chunk = cleaned[start:end]
        urls = _extract_image_urls(chunk)
        if urls:
            parent_images[num] = urls

    # 映射回子题号
    images: dict[str, list[str]] = {}
    for num in question_numbers:
        parent = _parent_number(num)
        if parent in parent_images:
            images[num] = parent_images[parent]

    return images


def _extract_image_urls(text: str) -> list[str]:
    """从文本中提取所有 img 标签的 src URL。"""
    return _IMG_SRC_RE.findall(text)

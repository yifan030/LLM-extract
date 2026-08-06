# -*- coding: utf-8 -*-
"""判分模块 —— 正则模式与常量。"""
import re

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

# 页脚噪声行模式（答题卡/试卷的固定提示文字）
_PAGE_FOOTER_LINES = {
    "请在各题目的作答区域内作答",
    "超出矩形边框限定区域的答案无效",
    "请保持答题卡干净整洁",
    "不要污损",
    "请在各题目的答题区域内作答",
    "超出黑色矩形边框限定区域的答案无效",
    "请在各题目对应的答题区域内作答",
    "超出答题区域的答案无效",
}

# 题号定位模式（用于手写试卷答案切分）
_QUESTION_NUM_STRONG_RE = re.compile(
    r"(?:^|\n)\s*(\d{1,2})\s*[.．、]\s*(?:\(?\d+\s*分\)?)?",
    re.MULTILINE,
)

# 子题号: "14(1)" → 父题号 "14"
_SUB_Q_RE = re.compile(r"^(\d+)\(\d+\)$")

# 图片 URL 提取
_IMG_SRC_RE = re.compile(r'<img[^>]+src="([^"]+)"')

# 数据库题型 → 输出 section 类型映射
_DB_TYPE_TO_SECTION: dict[str, str] = {
    "单选题": "选择题",
    "多选题": "选择题",
    "填空题": "填空题",
    "解答题": "解答题",
}

# 答题卡模式下 section 输出顺序
_SECTION_ORDER = ["选择题", "填空题", "解答题"]

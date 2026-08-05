# -*- coding: utf-8 -*-
"""ScoringService 单元测试。"""
import pytest

from service.scoring import (
    _extract_paper_meta,
    _extract_student_answers,
    _find_section_ranges,
    _parse_html_table,
)

SAMPLE_MARKDOWN = r"""# 长郡中学 2023 级高一入学检测试卷

# 数 学

时量:90 分钟 满分:100 分

得分___

### 一、 选择题:本题共8小题,每小题4分,共32分.在每小题给出的四个选项中,只有一个选项是符合题目要求的

1. 已知 a 是 $ \sqrt{13} $ 的小数部分，则 $ a(a+6) $ 的值为

A. $ \sqrt{13} $ B. 4

C. $ 4-\sqrt{13} $ D. $ 3\sqrt{13}-6 $

2. 如果不等式 $ 3x - m \leqslant 0 $ 的正整数解是 1, 2, 3, 4, 那么 m 的取值范围是

A. $ 12 \leqslant m < 15 $ B. $ 12 < m \leqslant 15 $

C. m<15 D. $ m \geqslant 12 $

## 答题卡

<table border=1 style='margin: auto; word-wrap: break-word;'><tr><td style='text-align: center; word-wrap: break-word;'>题号</td><td style='text-align: center; word-wrap: break-word;'>1</td><td style='text-align: center; word-wrap: break-word;'>2</td></tr><tr><td style='text-align: center; word-wrap: break-word;'>答案</td><td style='text-align: center; word-wrap: break-word;'>B</td><td style='text-align: center; word-wrap: break-word;'>A</td></tr></table>

## 二、 填空题：本题共4小题，每小题4分，共16分

9. 设点 $ P(x, y) $ 在第二象限内，且 $ |x| = 3 $，$ |y| = 2 $，则点 P 关于原点的对称点为 ___.

10. 关于 x, y 的二元一次方程组 $ \left\{\begin{aligned}&2x+y=3a,\\ &x-2y=9a\end{aligned}\right. $ 的解是二元一次方程 $ x+3y=24 $ 的一个解，则 a= ___.

# 长郡中学 2023 级高一入学检测试卷

# 数学参考答案

### 一、 选择题

<table border=1 style='margin: auto; word-wrap: break-word;'><tr><td style='text-align: center; word-wrap: break-word;'>题号</td><td style='text-align: center; word-wrap: break-word;'>1</td><td style='text-align: center; word-wrap: break-word;'>2</td></tr><tr><td style='text-align: center; word-wrap: break-word;'>答案</td><td style='text-align: center; word-wrap: break-word;'>B</td><td style='text-align: center; word-wrap: break-word;'>A</td></tr></table>

## 二、 填空题

9. $ (3,-2) $

10. -4
"""


class TestHtmlTableParser:
    def test_parse_answer_sheet(self):
        html = (
            '<table border=1>'
            '<tr><td>题号</td><td>1</td><td>2</td><td>3</td></tr>'
            '<tr><td>答案</td><td>B</td><td>A</td><td>D</td></tr>'
            '</table>'
        )
        rows = _parse_html_table(html)
        assert len(rows) == 2
        assert rows[0] == ["题号", "1", "2", "3"]
        assert rows[1] == ["答案", "B", "A", "D"]


class TestExtractStudentAnswers:
    def test_extract_from_answer_sheet(self):
        answers = _extract_student_answers(SAMPLE_MARKDOWN)
        assert answers == {"1": "B", "2": "A"}



class TestExtractPaperMeta:
    def test_extract_title_and_score(self):
        meta = _extract_paper_meta(SAMPLE_MARKDOWN)
        assert "长郡中学" in meta["title"]
        assert meta["total_score"] == 100
        assert meta["duration"] == 90


class TestSectionRanges:
    def test_find_choice_and_fill(self):
        sections = _find_section_ranges(SAMPLE_MARKDOWN)
        types = [s[0] for s in sections]
        assert "选择题" in types
        assert "填空题" in types

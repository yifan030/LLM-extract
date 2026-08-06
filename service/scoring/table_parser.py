# -*- coding: utf-8 -*-
"""HTML <table> 解析 —— 提取二维数组 [[cell, ...], ...]."""
from html.parser import HTMLParser


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

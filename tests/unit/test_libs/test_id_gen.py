# -*- coding: utf-8 -*-
"""libs.id_gen 单元测试 — content hash 归一化与确定性。"""
from libs.id_gen import gen_content_hash


class TestGenContentHash:
    def test_normalizes_line_endings(self):
        """\r\n 与 \r 统一为 \n 后 hash 一致。"""
        assert gen_content_hash("第一题\r\n第二题") == gen_content_hash("第一题\n第二题")
        assert gen_content_hash("第一题\r第二题") == gen_content_hash("第一题\n第二题")

    def test_strips_surrounding_whitespace(self):
        """首尾空白不影响 hash。"""
        assert gen_content_hash("  正文\n内容  ") == gen_content_hash("正文\n内容")

    def test_different_content_hashes_differ(self):
        """不同内容产生不同 hash。"""
        assert gen_content_hash("试卷A") != gen_content_hash("试卷B")

    def test_returns_32_char_hex(self):
        """返回 32 位十六进制字符串（md5 裸 hex，无前缀）。"""
        h = gen_content_hash("任意内容")
        assert len(h) == 32
        int(h, 16)  # 不抛异常即全为十六进制字符

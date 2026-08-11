# -*- coding: utf-8 -*-
"""统一 ID 派生逻辑 — 桥接 MySQL / HugeGraph / Milvus 三套存储。

Paper and question IDs are derived from ``hashlib.md5(source_file)``
so that the same MinIO object always produces the same IDs across all
three storage backends.
"""
import hashlib


def gen_paper_id(source_file: str) -> str:
    """从源文件路径派生试卷 ID，格式 ``paper_{md5hex}``。"""
    paper_hash = hashlib.md5(source_file.encode()).hexdigest()
    return f"paper_{paper_hash}"


def gen_question_id(source_file: str, number: str) -> str:
    """从源文件路径 + 题号派生题目 ID，格式 ``question_{md5hex}``。"""
    q_hash = hashlib.md5(f"{source_file}:{number}".encode()).hexdigest()
    return f"question_{q_hash}"

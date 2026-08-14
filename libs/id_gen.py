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


def gen_content_hash(markdown: str) -> str:
    """从 markdown 内容派生内容指纹（裸 32 位 hex，无前缀）。

    归一化：统一换行符（``\\r\\n``/``\\r`` → ``\\n``）+ 去首尾空白，
    使同一份卷仅因尾部换行等无意义差异也不影响去重判定。
    """
    text = markdown.replace("\r\n", "\n").replace("\r", "\n").strip()
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def gen_content_hash_bytes(raw: bytes) -> str:
    """从原始文件字节派生内容指纹（裸 32 位 hex，无前缀）。

    用于 paper_id 与去重：与上传的原始文件（PDF/图片）字节一一对应，
    可在上传阶段同步计算。区别于 :func:`gen_content_hash`（语义去重，需 OCR 后异步）。
    """
    return hashlib.md5(raw).hexdigest()


def gen_paper_id_from_content_hash(content_hash: str) -> str:
    """内容指纹 → 试卷 ID，格式 ``paper_{32 位 hex}``。

    与 :func:`gen_paper_id`（路径派生，仅保留给迁移脚本计算旧 ID）不同，
    本函数派生的是内容稳定、上传即可同步算出的 paper_id。
    """
    return f"paper_{content_hash}"

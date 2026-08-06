# -*- coding: utf-8 -*-
"""请求调用链上下文 — correlation_id 通过 contextvars 在协程间自动传递。"""
import uuid
from contextvars import ContextVar

_correlation_id: ContextVar[str] = ContextVar("correlation_id", default="-")


def set_correlation_id(cid: str | None = None) -> str:
    """设置当前协程的 correlation_id；未传时自动生成 12 位 hex 短码。"""
    cid = cid or uuid.uuid4().hex[:12]
    _correlation_id.set(cid)
    return cid


def get_correlation_id() -> str:
    """获取当前协程的 correlation_id，未设置时返回 "-"。"""
    return _correlation_id.get()

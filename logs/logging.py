# -*- coding: utf-8 -*-
"""日志配置。"""
import logging

from logs.context import get_correlation_id

_CONFIGURED = False


class _CorrelIdFilter(logging.Filter):
    """将当前协程的 correlation_id 注入到每一条 LogRecord 的 cid 属性。"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.cid = get_correlation_id()
        return True


def get_logger(name: str) -> logging.Logger:
    global _CONFIGURED
    if not _CONFIGURED:
        fmt = "%(asctime)s [%(levelname)s] [%(cid)s] %(name)s: %(message)s"
        logging.basicConfig(
            level=logging.INFO,
            format=fmt,
        )
        # Attach to root handler so third-party loggers (httpx, redis, etc.) never
        # hit KeyError on %(cid)s — the handler-level filter runs for every record.
        for handler in logging.getLogger().handlers:
            handler.addFilter(_CorrelIdFilter())
        _CONFIGURED = True

    return logging.getLogger(name)

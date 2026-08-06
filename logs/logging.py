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
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] [%(cid)s] %(name)s: %(message)s",
        )
        _CONFIGURED = True

    logger = logging.getLogger(name)
    if not any(isinstance(f, _CorrelIdFilter) for f in logger.filters):
        logger.addFilter(_CorrelIdFilter())
    return logger

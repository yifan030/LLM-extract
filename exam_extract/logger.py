# -*- coding: utf-8 -*-
"""Minimal logging fallback.

The production project provides ``libs.logger.get_logger``; that package is
not available in this environment, so this module supplies an equivalent
``get_logger(name)`` built on the standard :mod:`logging` module.
"""
import logging

_CONFIGURED = False


def get_logger(name: str) -> logging.Logger:
    global _CONFIGURED
    if not _CONFIGURED:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        )
        _CONFIGURED = True
    return logging.getLogger(name)

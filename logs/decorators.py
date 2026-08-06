# -*- coding: utf-8 -*-
"""@log_step 装饰器 — 自动记录方法调用、耗时与异常。

方法级:
    @log_step
    async def fetch(self, url): ...

    @log_step(skip=True)       # 完全不记录
    def simple_getter(self): ...

类级:
    @log_step
    class MyService:
        def do_work(self): ...      # 自动记录
        def _internal(self): ...    # _ 开头, 自动跳过
"""
from __future__ import annotations

import inspect
import time
from functools import wraps
from typing import Any, Callable

from logs.logging import get_logger

_log = get_logger(__name__)


def _summarize_arg(value: Any, max_len: int = 200) -> str:
    """生成参数的简短摘要，避免大对象刷屏。"""
    if value is None:
        return "None"
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        if len(value) > max_len:
            return repr(value[:max_len] + "...")
        return repr(value)
    if isinstance(value, (list, set, frozenset)):
        return f"{type(value).__name__}(len={len(value)})"
    if isinstance(value, tuple):
        return f"tuple(len={len(value)})"
    if isinstance(value, dict):
        return f"dict(len={len(value)})"
    if isinstance(value, bytes):
        return f"bytes(len={len(value)})"
    return f"<{type(value).__name__}>"


def _build_args_repr(args: tuple, kwargs: dict, bound_method: bool) -> str:
    """构建参数摘要字符串。实例方法的 self/cls 自动省略。"""
    parts: list[str] = []
    start = 1 if bound_method else 0
    for v in args[start:]:
        parts.append(_summarize_arg(v))
    for k, v in kwargs.items():
        parts.append(f"{k}={_summarize_arg(v)}")
    return ", ".join(parts) if parts else "-"


def _should_wrap(attr_name: str, attr_value: Any) -> bool:
    """判断类的某个属性是否应该被 @log_step 自动包装。"""
    if attr_name.startswith("_"):
        return False
    if not callable(attr_value):
        return False
    return inspect.isfunction(attr_value) or inspect.iscoroutinefunction(attr_value)


def _is_bound_method(func: Callable) -> bool:
    """判断函数是否属于实例/类方法（首个参数为 self 或 cls）。

    用于决定参数摘要是否应省略绑定参数。独立函数装饰时返回 False。
    """
    try:
        params = list(inspect.signature(func).parameters.values())
    except (ValueError, TypeError):
        return False
    if not params:
        return False
    return params[0].name in ("self", "cls")


def _wrap_method(
    func: Callable,
    *,
    skip: bool,
    log_args: bool,
    log_result: bool,
    level: str,
    qualname: str,
) -> Callable:
    """包装单个方法，注入日志逻辑。"""
    if skip:
        return func

    is_async = inspect.iscoroutinefunction(func)
    log_level = getattr(_log, level.lower(), _log.info)
    bound_method = _is_bound_method(func)

    if is_async:
        @wraps(func)
        async def _wrapper(*args: Any, **kwargs: Any) -> Any:
            t0 = time.monotonic()
            args_str = (
                _build_args_repr(args, kwargs, bound_method=bound_method)
                if log_args else "-"
            )
            _log.debug("→ %s | args: (%s)", qualname, args_str)
            try:
                result = await func(*args, **kwargs)
                elapsed = time.monotonic() - t0
                extra = (
                    f" | result: {_summarize_arg(result)}"
                    if log_result else ""
                )
                log_level(
                    "← %s | done | elapsed: %.2fs%s",
                    qualname, elapsed, extra,
                )
                return result
            except Exception as exc:
                elapsed = time.monotonic() - t0
                _log.exception(
                    "✗ %s | failed: %s | elapsed: %.2fs",
                    qualname, type(exc).__name__, elapsed,
                )
                raise
    else:
        @wraps(func)
        def _wrapper(*args: Any, **kwargs: Any) -> Any:
            t0 = time.monotonic()
            args_str = (
                _build_args_repr(args, kwargs, bound_method=bound_method)
                if log_args else "-"
            )
            _log.debug("→ %s | args: (%s)", qualname, args_str)
            try:
                result = func(*args, **kwargs)
                elapsed = time.monotonic() - t0
                extra = (
                    f" | result: {_summarize_arg(result)}"
                    if log_result else ""
                )
                log_level(
                    "← %s | done | elapsed: %.2fs%s",
                    qualname, elapsed, extra,
                )
                return result
            except Exception as exc:
                elapsed = time.monotonic() - t0
                _log.exception(
                    "✗ %s | failed: %s | elapsed: %.2fs",
                    qualname, type(exc).__name__, elapsed,
                )
                raise

    return _wrapper


def _decorate_class(
    cls: type,
    skip: bool,
    log_args: bool,
    log_result: bool,
    level: str,
) -> type:
    """为类中所有 public 方法自动添加 @log_step 包装。"""
    for attr_name, attr_value in list(cls.__dict__.items()):
        if _should_wrap(attr_name, attr_value):
            wrapped = _wrap_method(
                attr_value,
                skip=skip,
                log_args=log_args,
                log_result=log_result,
                level=level,
                qualname=f"{cls.__name__}.{attr_name}",
            )
            setattr(cls, attr_name, wrapped)
    return cls


def log_step(
    obj=None,
    *,
    skip: bool = False,
    log_args: bool = True,
    log_result: bool = False,
    level: str = "info",
):
    """方法/类装饰器：自动记录调用、耗时与异常。

    方法级:
        @log_step
        async def fetch(self, url): ...

    类级（自动包装所有 public 方法）:
        @log_step
        class MyService:
            def do_work(self): ...

    参数:
        skip:       True 时完全不记录
        log_args:   是否记录参数摘要（默认 True）
        log_result: 是否记录返回值摘要（默认 False，避免大对象）
        level:      正常完成时的日志级别（默认 "info"）
    """
    def _decorate(target):
        if isinstance(target, type):
            return _decorate_class(
                target,
                skip=skip,
                log_args=log_args,
                log_result=log_result,
                level=level,
            )
        qualname = getattr(target, "__name__", target.__qualname__)
        return _wrap_method(
            target,
            skip=skip,
            log_args=log_args,
            log_result=log_result,
            level=level,
            qualname=qualname,
        )

    if obj is None:
        return _decorate
    return _decorate(obj)

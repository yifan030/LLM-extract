# 日志模块 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为全项目提供统一的结构化日志、调用链追踪（correlation_id）和边界异常体系。

**Architecture:** `contextvars` 传递 correlation_id → `logging.Filter` 注入每条日志 → `@log_step` 装饰器自动记录方法进入/退出/耗时/异常 → `ExternalServiceError` 子类为每个外部服务提供明确的超时异常。

**Tech Stack:** Python 标准库 (`logging`, `contextvars`, `inspect`, `time`, `functools`)，无新增依赖。

## Global Constraints

- 不改动现有业务逻辑
- 日志输出保持 stdout/stderr，Docker 友好
- Python 3.10+（与项目现有一致）

---

## Task 1: `logs/context.py` — correlation_id 上下文

**Files:**
- Create: `logs/context.py`
- Create: `tests/unit/test_logs_context.py`

**Interfaces:**
- Produces: `set_correlation_id(cid: str | None = None) -> str`, `get_correlation_id() -> str`

- [ ] **Step 1: 创建 `logs/context.py`**

```python
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
```

- [ ] **Step 2: 创建 `tests/unit/test_logs_context.py`**

```python
# -*- coding: utf-8 -*-
"""Tests for logs.context — correlation_id 上下文传递。"""
import asyncio

from logs.context import set_correlation_id, get_correlation_id


class TestCorrelationId:
    def test_default_is_dash(self):
        assert get_correlation_id() == "-"

    def test_set_and_get(self):
        cid = set_correlation_id("abc123")
        assert cid == "abc123"
        assert get_correlation_id() == "abc123"

    def test_auto_generate_when_none(self):
        cid = set_correlation_id()
        assert len(cid) == 12
        assert get_correlation_id() == cid

    def test_override(self):
        set_correlation_id("first")
        set_correlation_id("second")
        assert get_correlation_id() == "second"

    def test_concurrent_tasks_isolated(self):
        """验证不同 asyncio task 之间的 contextvars 隔离。"""

        async def task_a():
            set_correlation_id("task-a")
            await asyncio.sleep(0.01)
            return get_correlation_id()

        async def task_b():
            set_correlation_id("task-b")
            await asyncio.sleep(0.01)
            return get_correlation_id()

        results = asyncio.run(asyncio.gather(task_a(), task_b()))
        assert results == ["task-a", "task-b"]
```

- [ ] **Step 3: 运行测试验证通过**

Run: `python -m pytest tests/unit/test_logs_context.py -v`
Expected: 5 passed

- [ ] **Step 4: Commit**

```bash
git add logs/context.py tests/unit/test_logs_context.py
git commit -m "feat: add logs/context.py — correlation_id via contextvars"
```

---

## Task 2: `logs/logging.py` — CorrelIdFilter + 格式更新

**Files:**
- Modify: `logs/logging.py`

**Interfaces:**
- Consumes: `get_correlation_id()` from `logs.context`
- Produces: `get_logger(name: str) -> logging.Logger`（行为不变）

- [ ] **Step 1: 替换 `logs/logging.py`**

```python
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
```

- [ ] **Step 2: 验证现有测试仍然通过**

Run: `python -m pytest tests/unit/ -v --timeout=30`
Expected: 全部通过，日志输出中 `[cid]` 字段显示为 `[-]`（未设置时默认值）

- [ ] **Step 3: Commit**

```bash
git add logs/logging.py
git commit -m "feat: add CorrelIdFilter to inject correlation_id into log records"
```

---

## Task 3: `logs/decorators.py` — `@log_step` 装饰器

**Files:**
- Create: `logs/decorators.py`
- Create: `tests/unit/test_logs_decorators.py`

**Interfaces:**
- Consumes: `get_logger` from `logs.logging`
- Produces: `log_step(obj=None, *, skip=False, log_args=True, log_result=False, level="info")`

- [ ] **Step 1: 创建 `logs/decorators.py`**

```python
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

    if is_async:
        @wraps(func)
        async def _wrapper(*args: Any, **kwargs: Any) -> Any:
            t0 = time.monotonic()
            args_str = (
                _build_args_repr(args, kwargs, bound_method=True)
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
                _build_args_repr(args, kwargs, bound_method=True)
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
        qualname = getattr(target, "__qualname__", target.__name__)
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
```

- [ ] **Step 2: 创建 `tests/unit/test_logs_decorators.py`**

```python
# -*- coding: utf-8 -*-
"""Tests for logs.decorators — @log_step 装饰器。"""
import asyncio
import logging

import pytest

from logs.decorators import log_step, _summarize_arg, _should_wrap


# ── _summarize_arg ────────────────────────────────────────

class TestSummarizeArg:
    def test_none(self):
        assert _summarize_arg(None) == "None"

    def test_bool(self):
        assert _summarize_arg(True) == "True"
        assert _summarize_arg(False) == "False"

    def test_int_float(self):
        assert _summarize_arg(42) == "42"
        assert _summarize_arg(3.14) == "3.14"

    def test_short_string(self):
        assert _summarize_arg("hello") == "'hello'"

    def test_long_string_truncated(self):
        s = "x" * 300
        result = _summarize_arg(s)
        assert result.startswith("'")
        assert "..." in result
        assert len(result) < 250

    def test_list(self):
        assert _summarize_arg([1, 2, 3]) == "list(len=3)"

    def test_dict(self):
        assert _summarize_arg({"a": 1}) == "dict(len=1)"

    def test_custom_object(self):
        obj = object()
        assert _summarize_arg(obj) == "<object>"


# ── should_wrap ───────────────────────────────────────────

class TestShouldWrap:
    def test_wraps_public_function(self):
        def foo(self):
            pass
        assert _should_wrap("foo", foo) is True

    def test_skips_private(self):
        def _bar(self):
            pass
        assert _should_wrap("_bar", _bar) is False

    def test_skips_dunder(self):
        def __len__(self):
            pass
        assert _should_wrap("__len__", __len__) is False

    def test_skips_non_callable(self):
        assert _should_wrap("name", "value") is False


# ── 方法级装饰器 ──────────────────────────────────────────

class TestMethodDecoration:
    def test_logs_enter_and_exit(self, caplog):
        @log_step
        def add(x, y):
            return x + y

        with caplog.at_level(logging.DEBUG):
            result = add(1, 2)

        assert result == 3
        assert "→ add" in caplog.text
        assert "← add" in caplog.text
        assert "elapsed" in caplog.text

    def test_logs_exception(self, caplog):
        @log_step
        def boom():
            raise ValueError("BOOM")

        with caplog.at_level(logging.ERROR):
            with pytest.raises(ValueError, match="BOOM"):
                boom()

        assert "✗ boom" in caplog.text
        assert "ValueError" in caplog.text

    def test_skip_disables_logging(self, caplog):
        @log_step(skip=True)
        def quiet():
            pass

        with caplog.at_level(logging.DEBUG):
            quiet()

        assert "quiet" not in caplog.text

    def test_log_args_summarized(self, caplog):
        @log_step(log_args=True)
        def fn(data, n):
            return len(data)

        with caplog.at_level(logging.DEBUG):
            fn([1, 2, 3], 5)

        assert "list(len=3)" in caplog.text
        assert "5" in caplog.text

    def test_log_args_disabled(self, caplog):
        @log_step(log_args=False)
        def fn(data, n):
            return len(data)

        with caplog.at_level(logging.DEBUG):
            fn([1, 2, 3], 5)

        assert "args: (-)" in caplog.text

    def test_log_result_enabled(self, caplog):
        @log_step(log_result=True, level="debug")
        def fn():
            return 42

        with caplog.at_level(logging.DEBUG):
            fn()

        assert "result: 42" in caplog.text

    def test_async_method(self, caplog):
        @log_step
        async def fetch():
            return "ok"

        with caplog.at_level(logging.DEBUG):
            result = asyncio.run(fetch())

        assert result == "ok"
        assert "→ fetch" in caplog.text
        assert "← fetch" in caplog.text


# ── 类级装饰器 ────────────────────────────────────────────

class TestClassDecoration:
    def test_wraps_public_methods(self, caplog):
        @log_step
        class Worker:
            def task(self, x):
                return x * 2

        svc = Worker()
        with caplog.at_level(logging.DEBUG):
            result = svc.task(5)

        assert result == 10
        assert "→ Worker.task" in caplog.text

    def test_skips_private_methods(self, caplog):
        @log_step
        class Worker:
            def _hidden(self):
                pass

        svc = Worker()
        with caplog.at_level(logging.DEBUG):
            svc._hidden()

        assert "Worker._hidden" not in caplog.text

    def test_async_class_method(self, caplog):
        @log_step
        class Fetcher:
            async def get(self):
                return "data"

        svc = Fetcher()
        with caplog.at_level(logging.DEBUG):
            result = asyncio.run(svc.get())

        assert result == "data"
        assert "→ Fetcher.get" in caplog.text
        assert "← Fetcher.get" in caplog.text
```

- [ ] **Step 3: 运行测试验证通过**

Run: `python -m pytest tests/unit/test_logs_decorators.py -v`
Expected: 全部通过

- [ ] **Step 4: Commit**

```bash
git add logs/decorators.py tests/unit/test_logs_decorators.py
git commit -m "feat: add @log_step decorator with method/class-level support"
```

---

## Task 4: `core/exceptions.py` — 边界异常子类

**Files:**
- Modify: `core/exceptions.py`
- Modify: `tests/unit/test_core_exceptions.py`

**Interfaces:**
- Produces: `ExternalServiceError`, `HugeGraphTimeout`, `MilvusTimeout`, `MinioTimeout`, `OcrServiceError`, `RedisTimeout`

- [ ] **Step 1: 在 `core/exceptions.py` 末尾追加**

```python
class ExternalServiceError(AppError):
    """外部服务调用失败（超时/连接拒绝/DNS 解析失败等）。"""
    def __init__(self, service: str, message: str, detail: dict | None = None):
        d = detail or {}
        d["service"] = service
        super().__init__(message, status_code=502, detail=d)


class HugeGraphTimeout(ExternalServiceError):
    def __init__(self, message: str, detail: dict | None = None):
        super().__init__("hugegraph", message, detail)


class MilvusTimeout(ExternalServiceError):
    def __init__(self, message: str, detail: dict | None = None):
        super().__init__("milvus", message, detail)


class MinioTimeout(ExternalServiceError):
    def __init__(self, message: str, detail: dict | None = None):
        super().__init__("minio", message, detail)


class OcrServiceError(ExternalServiceError):
    def __init__(self, message: str, detail: dict | None = None):
        super().__init__("ocr", message, detail)


class RedisTimeout(ExternalServiceError):
    def __init__(self, message: str, detail: dict | None = None):
        super().__init__("redis", message, detail)
```

- [ ] **Step 2: 在 `tests/unit/test_core_exceptions.py` 末尾追加**

```python
from core.exceptions import (
    ExternalServiceError,
    HugeGraphTimeout,
    MilvusTimeout,
    MinioTimeout,
    OcrServiceError,
    RedisTimeout,
)


@pytest.mark.parametrize("exc_cls,service_name", [
    (HugeGraphTimeout, "hugegraph"),
    (MilvusTimeout, "milvus"),
    (MinioTimeout, "minio"),
    (OcrServiceError, "ocr"),
    (RedisTimeout, "redis"),
])
def test_external_service_error_detail(exc_cls, service_name):
    err = exc_cls("timeout")
    assert err.status_code == 502
    assert err.detail["service"] == service_name


def test_external_service_error_with_custom_detail():
    err = HugeGraphTimeout("timeout", detail={"endpoint": "/graph/edges"})
    assert err.detail["service"] == "hugegraph"
    assert err.detail["endpoint"] == "/graph/edges"
```

- [ ] **Step 3: 运行测试验证**

Run: `python -m pytest tests/unit/test_core_exceptions.py -v`
Expected: 全部通过

- [ ] **Step 4: Commit**

```bash
git add core/exceptions.py tests/unit/test_core_exceptions.py
git commit -m "feat: add ExternalServiceError + timeout subclasses for each service"
```

---

## Task 5: `main.py` — correlation_id middleware + 异常处理器增强

**Files:**
- Modify: `main.py`

**Interfaces:**
- Consumes: `set_correlation_id`, `get_correlation_id` from `logs.context`
- Produces: correlation_id 自动注入请求/响应

- [ ] **Step 1: 修改 `main.py`**

在现有 import 块中添加:

```python
import uuid

from logs.context import set_correlation_id, get_correlation_id
```

在 `create_app()` 中，`app_.include_router(...)` 之前插入 middleware:

```python
    @app_.middleware("http")
    async def correlation_id_middleware(request: Request, call_next):
        cid = request.headers.get("X-Correlation-Id") or uuid.uuid4().hex[:12]
        set_correlation_id(cid)
        response = await call_next(request)
        response.headers["X-Correlation-Id"] = cid
        return response
```

修改 `app_error_handler` 以在 detail 中返回 correlation_id:

```python
    @app_.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        detail = dict(exc.detail)
        detail["correlation_id"] = get_correlation_id()
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.message, "detail": detail},
        )
```

修改 `unhandled_error_handler`:

```python
    @app_.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception):
        cid = get_correlation_id()
        log.exception("未处理异常 [cid=%s]", cid)
        return JSONResponse(
            status_code=500,
            content={"error": "内部服务错误", "correlation_id": cid},
        )
```

- [ ] **Step 2: 运行测试验证**

Run: `python -m pytest tests/unit/ -v --timeout=30`
Expected: 全部通过（不阻塞启动，集成验证见后续）

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat: add correlation_id middleware and enhance error handlers"
```

---

## Task 6: `libs/` 集成 — hugegraph + minio

**Files:**
- Modify: `libs/hugegraph.py`
- Modify: `libs/minio.py`

**Interfaces:**
- Consumes: `log_step` from `logs.decorators`, `HugeGraphTimeout`, `MinioTimeout` from `core.exceptions`

- [ ] **Step 1: 修改 `libs/hugegraph.py`**

在现有 import 块中添加:

```python
from core.exceptions import HugeGraphTimeout
from logs.decorators import log_step
```

类定义加装饰器:

```python
@log_step
class HugeGraphRepository:
```

`_client()` 改为捕获 `httpx.TimeoutException`:

```python
    async def _client(self) -> httpx.AsyncClient:
        """Return a fresh authenticated :class:`httpx.AsyncClient`."""
        return httpx.AsyncClient(
            auth=httpx.BasicAuth(self.hg_user, self.hg_passwd),
            timeout=httpx.Timeout(30.0),
        )
```

在每个公开方法（`load_level4_names`, `preload_question_types`, `create_vertex`, `create_edge`, `list_vertices`, `get_vertex`, `get_vertex_edges`）的现有请求逻辑外围增加超时捕获。以 `create_edge` 为例 — 修改 `async with` 块:

```python
    async def create_edge(self, edge: Edge) -> tuple[bool, bool]:
        url = f"{self.base_url}/graph/edges"
        payload: dict[str, Any] = {
            "label": edge.label,
            "outV": edge.outV,
            "inV": edge.inV,
            "properties": edge.properties,
        }
        try:
            async with await self._client() as client:
                resp = await client.post(url, json=payload)
        except httpx.TimeoutException as exc:
            raise HugeGraphTimeout(
                f"HugeGraph POST edges 超时: {url}",
                detail={"url": url, "edge_label": edge.label},
            ) from exc
        if resp.status_code in (200, 201):
            log.info("边创建成功: %s -[%s]-> %s", edge.outV, edge.label, edge.inV)
            return True, False
        if resp.status_code == 400 and "already exists" in resp.text.lower():
            log.debug("边已存在，跳过: %s -[%s]-> %s", edge.outV, edge.label, edge.inV)
            return False, True
        log.error("边创建失败: %s -[%s]-> %s: %s", edge.outV, edge.label, edge.inV, resp.text)
        return False, False
```

对 `create_vertex`、`load_level4_names`、`preload_question_types`、`list_vertices`、`get_vertex`、`get_vertex_edges` 的所有 `async with await self._client() as client:` 块做同样的 try/except 包装。

- [ ] **Step 2: 修改 `libs/minio.py`**

在现有 import 块中添加:

```python
from core.exceptions import MinioTimeout
from logs.decorators import log_step
```

类定义加装饰器:

```python
@log_step
class MinioRepository:
```

`get_object_text` 中捕获连接超时:

```python
    async def get_object_text(self, object_key: str) -> str:
        """读取对象内容并以 utf-8 解码返回；不存在时抛 MinioObjectNotFound。"""
        try:
            response = await self._client.get_object(self.bucket, object_key)
            if response is None:
                raise MinioObjectNotFound(object_key)
            data = await response.read()
            response.release()
            return data.decode("utf-8")
        except MinioObjectNotFound:
            raise
        except Exception as exc:
            # 区分连接超时与真正的 MinIO 错误
            err_str = str(exc).lower()
            if "timeout" in err_str or "timed out" in err_str:
                raise MinioTimeout(
                    f"MinIO 连接超时: {object_key}",
                    detail={"object_key": object_key},
                ) from exc
            log.error("读取 MinIO 文件失败: %s, err=%s", object_key, exc)
            raise MinioObjectNotFound(object_key) from exc
```

- [ ] **Step 3: 运行测试**

Run: `python -m pytest tests/unit/ -v --timeout=30`
Expected: 全部通过

- [ ] **Step 4: Commit**

```bash
git add libs/hugegraph.py libs/minio.py
git commit -m "feat: add @log_step and timeout exceptions to hugegraph/minio clients"
```

---

## Task 7: `service/` 集成 — extraction + llm + scoring

**Files:**
- Modify: `service/extraction.py`
- Modify: `service/llm.py`
- Modify: `service/scoring/service.py`

**Interfaces:**
- Consumes: `log_step` from `logs.decorators`

- [ ] **Step 1: 修改 `service/extraction.py`**

在现有 import 块中添加:

```python
from logs.decorators import log_step
```

类定义加装饰器:

```python
@log_step
class ExtractionService:
```

`_save_artifacts`、`_write_json`、`_dedupe` 以 `_` 开头，自动跳过，无需改动。

- [ ] **Step 2: 修改 `service/llm.py`**

在现有 import 块中添加:

```python
from logs.decorators import log_step
```

类定义加装饰器:

```python
@log_step
class LlmService:
```

- [ ] **Step 3: 修改 `service/scoring/service.py`**

先读取文件确认类名，然后加 `@log_step` 类装饰器。

- [ ] **Step 4: 运行测试**

Run: `python -m pytest tests/unit/ -v --timeout=30`
Expected: 全部通过

- [ ] **Step 5: Commit**

```bash
git add service/extraction.py service/llm.py service/scoring/service.py
git commit -m "feat: add @log_step to extraction, llm, and scoring services"
```

---

## Task 8: `core/events.py` — Redis 消费者 correlation_id

**Files:**
- Modify: `core/events.py`

**Interfaces:**
- Consumes: `set_correlation_id` from `logs.context`

- [ ] **Step 1: 修改 `core/events.py`**

在现有 import 块中添加:

```python
from logs.context import set_correlation_id
```

在消息消费循环中，处理每条消息前设置 cid:

```python
            for stream, entries in messages:
                for msg_id, fields in entries:
                    object_key = fields.get(b"object_key", b"").decode()
                    if not object_key:
                        continue
                    set_correlation_id()  # 每条消息生成新的 cid
                    log.info("消费事件: %s → %s", msg_id, object_key)
```

- [ ] **Step 2: 运行测试**

Run: `python -m pytest tests/unit/ -v --timeout=30`
Expected: 全部通过

- [ ] **Step 3: Commit**

```bash
git add core/events.py
git commit -m "feat: inject correlation_id into Redis consumer message processing"
```

---

## Task 9: `logs/__init__.py` — 公开导出

**Files:**
- Modify: `logs/__init__.py`

- [ ] **Step 1: 更新 `logs/__init__.py`**

```python
# -*- coding: utf-8 -*-
"""日志与调用链追踪模块。"""
from logs.context import set_correlation_id, get_correlation_id
from logs.decorators import log_step
from logs.logging import get_logger

__all__ = [
    "get_logger",
    "log_step",
    "set_correlation_id",
    "get_correlation_id",
]
```

- [ ] **Step 2: 运行全量测试**

Run: `python -m pytest tests/unit/ -v --timeout=30`
Expected: 全部通过

- [ ] **Step 3: Commit**

```bash
git add logs/__init__.py
git commit -m "feat: export log_step, correlation_id helpers from logs package"
```

---

## Task 10: 端到端验证

**Files:**
- （验证性步骤，不产生代码变更）

- [ ] **Step 1: 启动服务**

```bash
docker compose up -d api
```

- [ ] **Step 2: 调用 extract 端点，检查响应头中的 `X-Correlation-Id`**

```bash
curl -s -D- -X POST \
  'http://localhost:8000/api/v1/extract' \
  -H 'Content-Type: application/json' \
  -d '{"object_key": "test.md", "save_artifacts": false, "import_to_hg": false}' | grep -i x-correlation-id
```

Expected: 响应头中包含 `X-Correlation-Id: <12-char-hex>`

- [ ] **Step 3: 检查 Docker 日志中的 `[cid]` 字段**

```bash
docker logs exam-extract --tail 50 | grep -E "\[[a-f0-9]{12}\]"
```

Expected: 日志中包含 `[cid值]` 字段，与响应头一致

- [ ] **Step 4: 查看 `@log_step` 步骤日志**

```bash
docker logs exam-extract --tail 100 | grep -E "[→←✗]"
```

Expected: 看到 `→ ExtractionService.run`、`← ExtractionService.run | done | elapsed: ...` 等步骤日志

- [ ] **Step 5: 最终 Commit（如有调整）**

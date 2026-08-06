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

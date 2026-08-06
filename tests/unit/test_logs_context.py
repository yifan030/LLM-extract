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

        async def run_both():
            return await asyncio.gather(task_a(), task_b())

        results = asyncio.run(run_both())
        assert results == ["task-a", "task-b"]

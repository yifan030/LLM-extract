# -*- coding: utf-8 -*-
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import redis

import core.events as events


@pytest.mark.asyncio
async def test_start_consumer_delegates_to_run_consumer():
    svc = MagicMock()
    with patch.object(events, "_run_consumer", new=AsyncMock()) as m:
        await events.start_consumer("redis://x", svc)
    m.assert_awaited_once_with(
        "redis://x", events.CONSUMER_GROUP, events.CONSUMER_NAME, events.STREAM_KEY, svc.run
    )


@pytest.mark.asyncio
async def test_start_mysql_consumer_delegates():
    svc = MagicMock()
    with patch.object(events, "_run_consumer", new=AsyncMock()) as m:
        await events.start_mysql_consumer("redis://x", svc)
    m.assert_awaited_once_with(
        "redis://x", events.MYSQL_CONSUMER_GROUP, events.MYSQL_CONSUMER_NAME,
        events.STREAM_KEY, svc.handle_event,
    )


@pytest.mark.asyncio
async def test_reclaim_pending_returns_messages():
    r = AsyncMock()
    r.xautoclaim.return_value = [[[b"1-1", {b"object_key": b"papers/x.md"}]], b"1-1"]
    result = await events._reclaim_pending(r, "s", "g", "c")
    assert result == [[b"1-1", {b"object_key": b"papers/x.md"}]]


@pytest.mark.asyncio
async def test_reclaim_pending_unsupported():
    r = AsyncMock()
    r.xautoclaim.side_effect = redis.ResponseError("ERR")
    result = await events._reclaim_pending(r, "s", "g", "c")
    assert result == []

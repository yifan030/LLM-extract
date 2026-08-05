# -*- coding: utf-8 -*-
"""Redis Streams 生产者/消费者 — MinIO 事件 → Stream → 抽取流水线。"""
import asyncio

import redis.asyncio as redis

from logs.logging import get_logger

log = get_logger(__name__)

STREAM_KEY = "extract:events"
CONSUMER_GROUP = "exam-extract"
CONSUMER_NAME = "worker-1"

# ── 生产者 ──────────────────────────────────────────────────


async def publish_event(redis_url: str, object_key: str) -> str | None:
    """将 MinIO 对象事件写入 Redis Stream，返回消息 ID；失败返回 None。"""
    try:
        r = redis.from_url(redis_url)
        msg_id = await r.xadd(STREAM_KEY, {"object_key": object_key}, maxlen=10000)
        log.info("已发布事件: %s → %s", object_key, msg_id)
        await r.close()
        return msg_id
    except Exception as exc:
        log.error("发布事件失败: %s, err=%s", object_key, exc)
        return None


# ── 消费者 ──────────────────────────────────────────────────


async def start_consumer(redis_url: str, extraction_svc):
    """后台消费 Redis Stream 中的 MinIO 事件。"""
    r = redis.from_url(redis_url)

    try:
        await r.xgroup_create(STREAM_KEY, CONSUMER_GROUP, id="0", mkstream=True)
    except redis.ResponseError:
        pass

    log.info("Redis Stream 消费者已启动: %s/%s", STREAM_KEY, CONSUMER_GROUP)

    while True:
        try:
            messages = await r.xreadgroup(
                CONSUMER_GROUP,
                CONSUMER_NAME,
                streams={STREAM_KEY: ">"},
                count=1,
                block=5000,
            )
            for stream, entries in messages:
                for msg_id, fields in entries:
                    object_key = fields.get(b"object_key", b"").decode()
                    if not object_key:
                        continue
                    log.info("消费事件: %s → %s", msg_id, object_key)
                    try:
                        await extraction_svc.run(object_key)
                        await r.xack(STREAM_KEY, CONSUMER_GROUP, msg_id)
                        log.info("消费完成: %s", object_key)
                    except Exception as exc:
                        log.error("抽取失败: %s, err=%s", object_key, exc)
                        # 不 ack，消息会保留在 pending 列表用于重试
        except asyncio.CancelledError:
            log.info("消费者被取消，正在停止...")
            break
        except Exception as exc:
            log.error("消费者循环异常: %s", exc)
            await asyncio.sleep(5)

    await r.close()
    log.info("消费者连接已关闭")

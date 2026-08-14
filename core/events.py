# -*- coding: utf-8 -*-
"""Redis Streams 生产者/消费者 — MinIO 事件 → Stream → 抽取流水线。"""
import asyncio

import redis.asyncio as redis

from logs.context import set_correlation_id
from logs.logging import get_logger

log = get_logger(__name__)

STREAM_KEY = "extract:events"
CONSUMER_GROUP = "exam-extract"
CONSUMER_NAME = "worker-1"
MYSQL_CONSUMER_GROUP = "mysql-import"
MYSQL_CONSUMER_NAME = "mysql-worker-1"

# ── 生产者 ──────────────────────────────────────────────────


async def publish_event(redis_url: str, object_key: str) -> str | None:
    """将 MinIO 对象事件写入 Redis Stream，返回消息 ID；失败返回 None。"""
    try:
        r = redis.from_url(redis_url, socket_keepalive=True)
        msg_id = await r.xadd(STREAM_KEY, {"object_key": object_key}, maxlen=10000)
        log.info("已发布事件: %s → %s", object_key, msg_id)
        await r.close()
        return msg_id
    except Exception as exc:
        log.error("发布事件失败: %s, err=%s", object_key, exc)
        return None


async def _reclaim_pending(r, stream_key: str, group: str, consumer_name: str) -> list:
    """回收 idle 超过 30s 的 pending 消息（失败不 ack 后的重试机制）。

    返回 [(msg_id, fields_dict), ...]；服务器不支持 XAUTOCLAIM 时返回空列表（静默降级）。
    """
    try:
        result = await r.xautoclaim(
            stream_key, group, consumer_name,
            min_idle_time=30_000, start_id="0-0", count=10,
        )
    except (redis.ResponseError, AttributeError):
        return []
    if not result:
        return []
    return result[1]


# ── 消费者 ──────────────────────────────────────────────────


async def _run_consumer(redis_url: str, group: str, consumer_name: str, stream_key: str, handler) -> None:
    """通用消费者循环：逐个调用 handler(object_key)；失败不 ack，交 pending 重试。"""
    r = redis.from_url(redis_url, socket_keepalive=True, health_check_interval=30)

    try:
        await r.xgroup_create(stream_key, group, id="0", mkstream=True)
    except redis.ResponseError:
        pass

    log.info("Redis Stream 消费者已启动: %s/%s", stream_key, group)

    while True:
        try:
            messages = await r.xreadgroup(
                group, consumer_name, streams={stream_key: ">"}, count=1, block=5000
            )
            for _, entries in messages:
                for msg_id, fields in entries:
                    object_key = fields.get(b"object_key", b"").decode()
                    if not object_key:
                        continue
                    set_correlation_id()
                    log.info("消费事件: %s → %s", msg_id, object_key)
                    try:
                        await handler(object_key)
                        await r.xack(stream_key, group, msg_id)
                        log.info("消费完成: %s", object_key)
                    except Exception as exc:
                        log.error("处理失败: %s, err=%s", object_key, exc)
            # 回收 pending 消息（重试机制）：失败未 ack 的消息 idle 超时后重新投递
            for msg_id, fields in await _reclaim_pending(r, stream_key, group, consumer_name):
                object_key = fields.get(b"object_key", b"").decode()
                if not object_key:
                    continue
                set_correlation_id()
                log.info("回收重试消息: %s → %s", msg_id, object_key)
                try:
                    await handler(object_key)
                    await r.xack(stream_key, group, msg_id)
                    log.info("重试消费完成: %s", object_key)
                except Exception as exc:
                    log.error("重试处理失败: %s, err=%s", object_key, exc)
        except asyncio.CancelledError:
            log.info("消费者被取消，正在停止...")
            break
        except (TimeoutError, redis.TimeoutError, ConnectionError, OSError) as exc:
            await asyncio.sleep(1)
        except Exception as exc:
            log.error("消费者循环异常: %s", exc)
            await asyncio.sleep(5)

    await r.close()
    log.info("消费者连接已关闭")


async def start_consumer(redis_url: str, extraction_svc) -> None:
    """后台消费 Redis Stream 中的 MinIO 事件（HugeGraph/Milvus 抽取）。"""
    await _run_consumer(redis_url, CONSUMER_GROUP, CONSUMER_NAME, STREAM_KEY, extraction_svc.run)


async def start_mysql_consumer(redis_url: str, mysql_import_svc) -> None:
    """后台消费 Redis Stream 中的 MinIO 事件（MySQL 自动入库，独立 group）。"""
    await _run_consumer(
        redis_url, MYSQL_CONSUMER_GROUP, MYSQL_CONSUMER_NAME, STREAM_KEY,
        mysql_import_svc.handle_event,
    )

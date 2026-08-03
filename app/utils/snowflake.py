# -*- coding: utf-8 -*-
"""Simple snowflake ID generator."""
import threading
import time


class Snowflake:
    """简易雪花 ID 生成器（适合单机场景）。"""

    def __init__(self, datacenter_id: int = 0, worker_id: int = 0):
        self.datacenter_id = datacenter_id
        self.worker_id = worker_id
        self.sequence = 0
        self.last_timestamp = -1
        self.lock = threading.Lock()

    def _til_next_millis(self, last_timestamp: int) -> int:
        timestamp = int(time.time() * 1000)
        while timestamp <= last_timestamp:
            timestamp = int(time.time() * 1000)
        return timestamp

    def next_id(self) -> int:
        with self.lock:
            timestamp = int(time.time() * 1000)
            if timestamp < self.last_timestamp:
                raise Exception("Clock moved backwards")
            if timestamp == self.last_timestamp:
                self.sequence = (self.sequence + 1) & 4095
                if self.sequence == 0:
                    timestamp = self._til_next_millis(self.last_timestamp)
            else:
                self.sequence = 0
            self.last_timestamp = timestamp
            return ((timestamp - 1288834974657) << 22) | \
                   (self.datacenter_id << 17) | \
                   (self.worker_id << 12) | \
                   self.sequence

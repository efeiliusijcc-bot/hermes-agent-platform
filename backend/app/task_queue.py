from __future__ import annotations

import time
from functools import lru_cache
from uuid import UUID

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.config import Settings, get_settings


class TaskQueueError(RuntimeError):
    pass


class TaskQueue:
    def __init__(self, settings: Settings) -> None:
        self.key = settings.task_queue_key
        self.redis = Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            db=settings.redis_db,
            password=settings.redis_password.get_secret_value(),
            socket_connect_timeout=settings.redis_socket_timeout_seconds,
            socket_timeout=settings.redis_socket_timeout_seconds,
            decode_responses=True,
        )

    async def ping(self) -> None:
        try:
            if not await self.redis.ping():
                raise TaskQueueError("task queue did not acknowledge ping")
        except RedisError as exc:
            raise TaskQueueError("task queue is unavailable") from exc

    async def enqueue(self, task_id: UUID | str, priority: int) -> None:
        if not 0 <= priority <= 9:
            raise ValueError("task priority must be between 0 and 9")
        # Redis pops the smallest score. The leading band makes priority
        # dominate, and the epoch component preserves FIFO inside each band.
        score = (9 - priority) * 10_000_000_000_000 + time.time_ns() / 1_000_000
        try:
            await self.redis.zadd(self.key, {str(task_id): score}, nx=True)
        except RedisError as exc:
            raise TaskQueueError("task could not be enqueued") from exc

    async def dequeue(self) -> UUID | None:
        try:
            values = await self.redis.zpopmin(self.key, count=1)
        except RedisError as exc:
            raise TaskQueueError("task could not be dequeued") from exc
        if not values:
            return None
        try:
            return UUID(str(values[0][0]))
        except ValueError as exc:
            raise TaskQueueError("task queue contains an invalid task id") from exc

    async def remove(self, task_id: UUID | str) -> None:
        try:
            await self.redis.zrem(self.key, str(task_id))
        except RedisError as exc:
            raise TaskQueueError("task could not be removed from queue") from exc

    async def close(self) -> None:
        await self.redis.aclose()


@lru_cache
def get_task_queue() -> TaskQueue:
    return TaskQueue(get_settings())

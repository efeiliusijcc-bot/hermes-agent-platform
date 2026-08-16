from __future__ import annotations

import json
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.config import Settings, get_settings


class AgentMessageBusError(RuntimeError):
    pass


class AgentMessageBus:
    def __init__(self, settings: Settings) -> None:
        self.key = settings.agent_message_stream_key
        self.max_length = settings.agent_message_max_length
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
                raise AgentMessageBusError("Agent message bus did not acknowledge ping")
        except RedisError as exc:
            raise AgentMessageBusError("Agent message bus is unavailable") from exc

    async def publish(
        self,
        *,
        from_agent: str,
        to_agent: str,
        message_type: str,
        payload: dict[str, Any],
        task_id: str | None = None,
    ) -> str:
        fields = {
            "from": from_agent,
            "to": to_agent,
            "type": message_type,
            "payload": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            "task_id": task_id or "",
        }
        try:
            return str(
                await self.redis.xadd(
                    self.key, fields, maxlen=self.max_length, approximate=True
                )
            )
        except RedisError as exc:
            raise AgentMessageBusError("Agent message could not be published") from exc

    async def list(
        self,
        *,
        after_id: str = "-",
        to_agent: str | None = None,
        count: int = 100,
    ) -> list[dict[str, Any]]:
        start = "-" if after_id == "-" else f"({after_id}"
        try:
            values = await self.redis.xrange(self.key, min=start, max="+", count=count)
        except RedisError as exc:
            raise AgentMessageBusError("Agent messages could not be read") from exc
        messages: list[dict[str, Any]] = []
        for message_id, fields in values:
            if to_agent and fields.get("to") != to_agent:
                continue
            try:
                payload = json.loads(fields.get("payload") or "{}")
            except ValueError:
                payload = {"raw": fields.get("payload")}
            timestamp_ms = int(str(message_id).split("-", 1)[0])
            messages.append(
                {
                    "id": str(message_id),
                    "from_agent": str(fields.get("from") or ""),
                    "to_agent": str(fields.get("to") or ""),
                    "message_type": str(fields.get("type") or "event"),
                    "payload": payload if isinstance(payload, dict) else {"value": payload},
                    "task_id": fields.get("task_id") or None,
                    "created_at": datetime.fromtimestamp(
                        timestamp_ms / 1000, tz=timezone.utc
                    ),
                }
            )
        return messages

    async def close(self) -> None:
        await self.redis.aclose()


@lru_cache
def get_agent_message_bus() -> AgentMessageBus:
    return AgentMessageBus(get_settings())

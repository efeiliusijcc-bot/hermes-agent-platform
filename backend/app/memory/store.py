from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.config import Settings, get_settings


class AgentMemoryError(RuntimeError):
    pass


@dataclass(frozen=True)
class MemoryMessage:
    role: str
    content: str


class AgentMemoryStore:
    key_prefix = "hermes:agent-memory:v1"

    def __init__(self, settings: Settings) -> None:
        self.max_messages = settings.agent_memory_max_turns * 2
        self.ttl_seconds = settings.agent_memory_ttl_seconds
        self.max_message_chars = settings.agent_memory_max_message_chars
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
                raise AgentMemoryError("Agent memory store did not acknowledge ping")
        except RedisError as exc:
            raise AgentMemoryError("Agent memory store is unavailable") from exc

    async def load(self, agent_id: str, session_id: str) -> list[MemoryMessage]:
        try:
            values = await self.redis.lrange(self._key(agent_id, session_id), -self.max_messages, -1)
        except RedisError as exc:
            raise AgentMemoryError("Agent memory could not be loaded") from exc

        messages: list[MemoryMessage] = []
        for value in values:
            try:
                item = json.loads(value)
            except (TypeError, json.JSONDecodeError) as exc:
                raise AgentMemoryError("Agent memory contains invalid JSON") from exc
            if (
                not isinstance(item, dict)
                or item.get("role") not in {"user", "assistant"}
                or not isinstance(item.get("content"), str)
            ):
                raise AgentMemoryError("Agent memory contains an invalid message")
            messages.append(MemoryMessage(role=item["role"], content=item["content"]))
        return messages

    async def append_turn(self, agent_id: str, session_id: str, user_input: str, assistant_output: str) -> None:
        key = self._key(agent_id, session_id)
        messages = [
            json.dumps(
                {"role": "user", "content": user_input[: self.max_message_chars]},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            json.dumps(
                {"role": "assistant", "content": assistant_output[: self.max_message_chars]},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        ]
        try:
            async with self.redis.pipeline(transaction=True) as pipeline:
                pipeline.rpush(key, *messages)
                pipeline.ltrim(key, -self.max_messages, -1)
                pipeline.expire(key, self.ttl_seconds)
                await pipeline.execute()
        except RedisError as exc:
            raise AgentMemoryError("Agent memory could not be persisted") from exc

    async def clear_agent(self, agent_id: str) -> None:
        pattern = f"{self.key_prefix}:{agent_id}:*"
        try:
            keys = [key async for key in self.redis.scan_iter(match=pattern, count=100)]
            if keys:
                await self.redis.delete(*keys)
        except RedisError as exc:
            raise AgentMemoryError("Agent memory could not be cleared") from exc

    async def close(self) -> None:
        await self.redis.aclose()

    def _key(self, agent_id: str, session_id: str) -> str:
        return f"{self.key_prefix}:{agent_id}:{session_id}"


@lru_cache
def get_memory_store() -> AgentMemoryStore:
    return AgentMemoryStore(get_settings())

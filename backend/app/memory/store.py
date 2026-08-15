from __future__ import annotations

import json
import hashlib
import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any, Protocol

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert

from app.config import Settings, get_settings
from app.db.models import AgentMemory
from app.db.session import SessionFactory


NAMESPACE_PART = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class AgentMemoryError(RuntimeError):
    pass


@dataclass(frozen=True)
class MemoryMessage:
    role: str
    content: str


@dataclass(frozen=True)
class MemoryNamespace:
    agent_id: str
    session_id: str
    memory_type: str = "short-term"

    def __post_init__(self) -> None:
        for label, value, limit in (
            ("agent_id", self.agent_id, 64),
            ("session_id", self.session_id, 128),
            ("memory_type", self.memory_type, 64),
        ):
            if len(value) > limit or not NAMESPACE_PART.fullmatch(value):
                raise AgentMemoryError(f"invalid memory namespace {label}")

    @property
    def value(self) -> str:
        return f"{self.agent_id}/{self.session_id}/{self.memory_type}"


class MemoryProvider(Protocol):
    name: str

    async def ping(self) -> None: ...
    async def get(self, namespace: MemoryNamespace, key: str) -> Any | None: ...
    async def set(self, namespace: MemoryNamespace, key: str, value: Any, ttl_seconds: int) -> None: ...
    async def delete(self, namespace: MemoryNamespace, key: str) -> None: ...
    async def clear(self, *, agent_id: str, session_id: str | None = None, memory_type: str | None = None) -> None: ...
    async def close(self) -> None: ...


class RedisMemoryProvider:
    name = "redis"
    key_prefix = "hermes:agent-memory:v2"

    def __init__(self, settings: Settings) -> None:
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
                raise AgentMemoryError("memory provider did not acknowledge ping")
        except RedisError as exc:
            raise AgentMemoryError("Redis memory provider is unavailable") from exc

    async def get(self, namespace: MemoryNamespace, key: str) -> Any | None:
        try:
            value = await self.redis.get(self._key(namespace, key))
            if value is not None:
                return json.loads(value)
            if key == "messages":
                legacy = await self.redis.lrange(
                    f"hermes:agent-memory:v1:{namespace.agent_id}:{namespace.session_id}", 0, -1
                )
                if legacy:
                    migrated = [json.loads(item) for item in legacy]
                    await self.set(namespace, key, migrated, 2_592_000)
                    return migrated
            return None
        except (RedisError, json.JSONDecodeError) as exc:
            raise AgentMemoryError("Redis memory value could not be loaded") from exc

    async def set(self, namespace: MemoryNamespace, key: str, value: Any, ttl_seconds: int) -> None:
        try:
            await self.redis.set(
                self._key(namespace, key),
                json.dumps(value, ensure_ascii=False, separators=(",", ":")),
                ex=ttl_seconds,
            )
        except RedisError as exc:
            raise AgentMemoryError("Redis memory value could not be persisted") from exc

    async def delete(self, namespace: MemoryNamespace, key: str) -> None:
        try:
            await self.redis.delete(self._key(namespace, key))
        except RedisError as exc:
            raise AgentMemoryError("Redis memory value could not be deleted") from exc

    async def clear(self, *, agent_id: str, session_id: str | None = None, memory_type: str | None = None) -> None:
        parts = [self.key_prefix, agent_id, session_id or "*", memory_type or "*", "*"]
        try:
            keys = [key async for key in self.redis.scan_iter(match=":".join(parts), count=100)]
            if keys:
                await self.redis.delete(*keys)
            legacy = [
                key async for key in self.redis.scan_iter(
                    match=f"hermes:agent-memory:v1:{agent_id}:{session_id or '*'}", count=100
                )
            ]
            if legacy:
                await self.redis.delete(*legacy)
        except RedisError as exc:
            raise AgentMemoryError("Redis memory namespace could not be cleared") from exc

    async def close(self) -> None:
        await self.redis.aclose()

    def _key(self, namespace: MemoryNamespace, key: str) -> str:
        return f"{self.key_prefix}:{namespace.agent_id}:{namespace.session_id}:{namespace.memory_type}:{key}"


class PostgresMemoryProvider:
    name = "postgres"

    async def ping(self) -> None:
        async with SessionFactory() as session:
            await session.execute(text("SELECT 1"))

    async def get(self, namespace: MemoryNamespace, key: str) -> Any | None:
        async with SessionFactory() as session:
            item = await session.scalar(
                select(AgentMemory).where(
                    AgentMemory.agent_id == namespace.agent_id,
                    AgentMemory.session_id == namespace.session_id,
                    AgentMemory.memory_type == namespace.memory_type,
                    AgentMemory.key == key,
                )
            )
            if item is None or (item.expires_at is not None and item.expires_at <= datetime.now(timezone.utc)):
                return None
            return item.value

    async def set(self, namespace: MemoryNamespace, key: str, value: Any, ttl_seconds: int) -> None:
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
        statement = insert(AgentMemory).values(
            agent_id=namespace.agent_id,
            session_id=namespace.session_id,
            memory_type=namespace.memory_type,
            key=key,
            value=value,
            expires_at=expires_at,
        ).on_conflict_do_update(
            constraint="uq_agent_memories_namespace_key",
            set_={"value": value, "expires_at": expires_at, "updated_at": datetime.now(timezone.utc)},
        )
        async with SessionFactory() as session:
            await session.execute(statement)
            await session.commit()

    async def delete(self, namespace: MemoryNamespace, key: str) -> None:
        async with SessionFactory() as session:
            await session.execute(
                delete(AgentMemory).where(
                    AgentMemory.agent_id == namespace.agent_id,
                    AgentMemory.session_id == namespace.session_id,
                    AgentMemory.memory_type == namespace.memory_type,
                    AgentMemory.key == key,
                )
            )
            await session.commit()

    async def clear(self, *, agent_id: str, session_id: str | None = None, memory_type: str | None = None) -> None:
        statement = delete(AgentMemory).where(AgentMemory.agent_id == agent_id)
        if session_id is not None:
            statement = statement.where(AgentMemory.session_id == session_id)
        if memory_type is not None:
            statement = statement.where(AgentMemory.memory_type == memory_type)
        async with SessionFactory() as session:
            await session.execute(statement)
            await session.commit()

    async def close(self) -> None:
        return None


class VectorMemoryProvider:
    name = "vector"

    async def ping(self) -> None:
        async with SessionFactory() as session:
            await session.execute(text("SELECT 1 FROM agent_memory_vectors LIMIT 1"))

    async def get(self, namespace: MemoryNamespace, key: str) -> Any | None:
        return await PostgresMemoryProvider().get(namespace, key)

    async def set(self, namespace: MemoryNamespace, key: str, value: Any, ttl_seconds: int) -> None:
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        vector = _vector_literal(_embed_text(encoded))
        statement = insert(AgentMemory).values(
            agent_id=namespace.agent_id,
            session_id=namespace.session_id,
            memory_type=namespace.memory_type,
            key=key,
            value=value,
            expires_at=expires_at,
        ).on_conflict_do_update(
            constraint="uq_agent_memories_namespace_key",
            set_={"value": value, "expires_at": expires_at, "updated_at": datetime.now(timezone.utc)},
        ).returning(AgentMemory.id)
        async with SessionFactory() as session:
            memory_id = await session.scalar(statement)
            await session.execute(
                text(
                    "INSERT INTO agent_memory_vectors (memory_id, embedding) "
                    "VALUES (:memory_id, CAST(:embedding AS vector)) "
                    "ON CONFLICT (memory_id) DO UPDATE SET embedding = EXCLUDED.embedding"
                ),
                {"memory_id": memory_id, "embedding": vector},
            )
            await session.commit()

    async def delete(self, namespace: MemoryNamespace, key: str) -> None:
        await PostgresMemoryProvider().delete(namespace, key)

    async def clear(self, *, agent_id: str, session_id: str | None = None, memory_type: str | None = None) -> None:
        await PostgresMemoryProvider().clear(
            agent_id=agent_id, session_id=session_id, memory_type=memory_type
        )

    async def close(self) -> None:
        return None


class AgentMemoryStore:
    messages_key = "messages"

    def __init__(self, settings: Settings, provider: MemoryProvider | None = None) -> None:
        self.max_messages = settings.agent_memory_max_turns * 2
        self.ttl_seconds = settings.agent_memory_ttl_seconds
        self.max_message_chars = settings.agent_memory_max_message_chars
        self.memory_type = settings.memory_type
        if provider is not None:
            self.provider = provider
        elif settings.memory_provider == "postgres":
            self.provider = PostgresMemoryProvider()
        elif settings.memory_provider == "vector":
            self.provider = VectorMemoryProvider()
        else:
            self.provider = RedisMemoryProvider(settings)

    async def ping(self) -> None:
        await self.provider.ping()

    async def load(self, agent_id: str, session_id: str) -> list[MemoryMessage]:
        value = await self.provider.get(self.namespace(agent_id, session_id), self.messages_key)
        if value is None:
            return []
        if not isinstance(value, list):
            raise AgentMemoryError("Agent memory contains an invalid message collection")
        messages: list[MemoryMessage] = []
        for item in value[-self.max_messages:]:
            if (
                not isinstance(item, dict)
                or item.get("role") not in {"user", "assistant"}
                or not isinstance(item.get("content"), str)
            ):
                raise AgentMemoryError("Agent memory contains an invalid message")
            messages.append(MemoryMessage(role=item["role"], content=item["content"]))
        return messages

    async def append_turn(self, agent_id: str, session_id: str, user_input: str, assistant_output: str) -> None:
        namespace = self.namespace(agent_id, session_id)
        current = await self.provider.get(namespace, self.messages_key)
        if current is None:
            current = []
        if not isinstance(current, list):
            raise AgentMemoryError("Agent memory contains an invalid message collection")
        current.extend([
            {"role": "user", "content": user_input[: self.max_message_chars]},
            {"role": "assistant", "content": assistant_output[: self.max_message_chars]},
        ])
        await self.provider.set(namespace, self.messages_key, current[-self.max_messages:], self.ttl_seconds)

    async def get(self, namespace: MemoryNamespace, key: str) -> Any | None:
        self._key(key)
        return await self.provider.get(namespace, key)

    async def set(self, namespace: MemoryNamespace, key: str, value: Any) -> None:
        self._key(key)
        await self.provider.set(namespace, key, value, self.ttl_seconds)

    async def delete(self, namespace: MemoryNamespace, key: str) -> None:
        self._key(key)
        await self.provider.delete(namespace, key)

    async def clear_agent(self, agent_id: str) -> None:
        MemoryNamespace(agent_id=agent_id, session_id="validation", memory_type=self.memory_type)
        await self.provider.clear(agent_id=agent_id)

    async def close(self) -> None:
        await self.provider.close()

    def namespace(self, agent_id: str, session_id: str, memory_type: str | None = None) -> MemoryNamespace:
        return MemoryNamespace(agent_id=agent_id, session_id=session_id, memory_type=memory_type or self.memory_type)

    @staticmethod
    def _key(key: str) -> str:
        if len(key) > 128 or not NAMESPACE_PART.fullmatch(key):
            raise AgentMemoryError("invalid memory key")
        return key


@lru_cache
def get_memory_store() -> AgentMemoryStore:
    return AgentMemoryStore(get_settings())


def _embed_text(value: str, dimensions: int = 384) -> list[float]:
    vector = [0.0] * dimensions
    compact = value.casefold()
    for index in range(max(1, len(compact) - 2)):
        feature = compact[index:index + 3] or "empty"
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        position = int.from_bytes(digest[:4], "big") % dimensions
        vector[position] += 1.0 if digest[4] & 1 else -1.0
    norm = math.sqrt(sum(item * item for item in vector))
    if norm == 0:
        vector[0] = 1.0
        return vector
    return [item / norm for item in vector]


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{value:.9f}" for value in vector) + "]"

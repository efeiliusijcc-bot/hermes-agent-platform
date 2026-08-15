from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import uuid4

import pytest

from app.api.schema_versions import _transition
from app.config import Settings
from app.memory import AgentMemoryError, AgentMemoryStore, MemoryNamespace
from app.memory.store import _embed_text, _vector_literal
from app.storage.artifacts import ArtifactStorage, ArtifactStorageError, FilesystemStorageProvider


class FakeMemoryProvider:
    name = "fake"

    def __init__(self) -> None:
        self.values: dict[tuple[str, str], object] = {}

    async def ping(self) -> None:
        return None

    async def get(self, namespace: MemoryNamespace, key: str):
        return self.values.get((namespace.value, key))

    async def set(self, namespace: MemoryNamespace, key: str, value: object, ttl_seconds: int) -> None:
        self.values[(namespace.value, key)] = value

    async def delete(self, namespace: MemoryNamespace, key: str) -> None:
        self.values.pop((namespace.value, key), None)

    async def clear(self, *, agent_id: str, session_id: str | None = None, memory_type: str | None = None) -> None:
        prefix = f"{agent_id}/"
        self.values = {item: value for item, value in self.values.items() if not item[0].startswith(prefix)}

    async def close(self) -> None:
        return None


def settings(tmp_path: Path) -> Settings:
    return Settings(
        postgres_password="postgres",
        redis_password="redis",
        minio_root_password="minio",
        hermes_api_key="hermes",
        mcp_gateway_signing_key="x" * 32,
        artifact_storage_provider="local",
        artifact_local_root=str(tmp_path),
    )


@pytest.mark.asyncio
async def test_artifact_storage_save_get_exists_delete_and_sha256(tmp_path: Path) -> None:
    storage = ArtifactStorage(FilesystemStorageProvider(tmp_path, storage_type="local"), max_bytes=1024)
    session_id = uuid4()
    saved = await storage.save(
        agent_id="report-agent",
        session_id=session_id,
        filename="report.txt",
        content=b"verified",
        content_type="text/plain",
    )
    assert saved.storage_path == f"report-agent/{session_id}/report.txt"
    assert saved.sha256 == hashlib.sha256(b"verified").hexdigest()
    assert await storage.exists(saved.storage_path)
    assert await storage.get(saved.storage_path, expected_sha256=saved.sha256) == b"verified"
    with pytest.raises(ArtifactStorageError, match="integrity"):
        await storage.get(saved.storage_path, expected_sha256="0" * 64)
    await storage.delete(saved.storage_path)
    assert not await storage.exists(saved.storage_path)


@pytest.mark.parametrize("filename", ["../secret", "nested/file", "/absolute", "."])
@pytest.mark.asyncio
async def test_artifact_storage_rejects_path_escape(tmp_path: Path, filename: str) -> None:
    storage = ArtifactStorage(FilesystemStorageProvider(tmp_path, storage_type="local"), max_bytes=1024)
    with pytest.raises(ArtifactStorageError):
        await storage.save(
            agent_id="report-agent",
            session_id=uuid4(),
            filename=filename,
            content=b"blocked",
            content_type="text/plain",
        )


@pytest.mark.asyncio
async def test_memory_namespace_isolates_agent_session_and_type(tmp_path: Path) -> None:
    provider = FakeMemoryProvider()
    memory = AgentMemoryStore(settings(tmp_path), provider=provider)
    a = memory.namespace("report-agent", "session-1", "short-term")
    b = memory.namespace("review-agent", "session-1", "short-term")
    c = memory.namespace("report-agent", "session-2", "short-term")
    d = memory.namespace("report-agent", "session-1", "long-term")
    await memory.set(a, "facts", {"value": "A"})
    assert await memory.get(a, "facts") == {"value": "A"}
    assert await memory.get(b, "facts") is None
    assert await memory.get(c, "facts") is None
    assert await memory.get(d, "facts") is None


def test_memory_namespace_rejects_invalid_components() -> None:
    with pytest.raises(AgentMemoryError):
        MemoryNamespace(agent_id="../agent", session_id="session-1")


def test_schema_lifecycle_blocks_mutating_backwards() -> None:
    _transition("draft", "testing")
    _transition("testing", "published")
    _transition("published", "deprecated")
    _transition("deprecated", "disabled")
    with pytest.raises(Exception):
        _transition("published", "draft")
    with pytest.raises(Exception):
        _transition("draft", "published")


def test_phase31_migration_defines_version_and_storage_contracts() -> None:
    migration = Path("backend/alembic/versions/0007_schema_storage_abstraction.py").read_text()
    for table in ("agent_schema_versions", "agent_api_versions", "agent_memories"):
        assert f'"{table}"' in migration
    for column in ("storage_type", "storage_path"):
        assert f'"{column}"' in migration
    assert "INSERT INTO agent_schema_versions" in migration
    assert "'v1'" in migration
    assert "agent_memory_vectors" in migration


def test_vector_memory_embedding_is_deterministic_and_dimensioned() -> None:
    first = _embed_text('{"fact":"verified"}')
    second = _embed_text('{"fact":"verified"}')
    assert first == second
    assert len(first) == 384
    assert _vector_literal(first).startswith("[")

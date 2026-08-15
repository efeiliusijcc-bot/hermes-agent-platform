from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from app.api import publications
from app.api.agents import AgentExecutionContext
from app.runtime.hermes import HermesRunResult


@dataclass
class FakeAgent:
    id: str = "public-agent"
    name: str = "Public Agent"
    status: str = "active"
    api_enabled: bool = True
    current_version_id: UUID = uuid4()
    response_mode: str = "sync"
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None
    model: str = "qwen-32b"
    model_adapter: str = "qwen"

    def __post_init__(self) -> None:
        self.input_schema = self.input_schema or {
            "type": "object",
            "properties": {"topic": {"type": "string"}},
            "required": ["topic"],
            "additionalProperties": False,
        }
        self.output_schema = self.output_schema or {
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
            "additionalProperties": False,
        }


@dataclass
class FakePublication:
    agent: FakeAgent
    agent_id: str = "public-agent"
    status: str = "published"
    api_key_hash: str = hashlib.sha256(b"secret-key").hexdigest()
    api_key_prefix: str = "secret"
    call_count: int = 0
    last_called_at: datetime | None = None
    created_at: datetime = datetime(2026, 1, 1, tzinfo=timezone.utc)
    updated_at: datetime = datetime(2026, 1, 1, tzinfo=timezone.utc)


@dataclass
class FakeSchemaVersion:
    version: str = "v1"
    status: str = "published"
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        self.input_schema = self.input_schema or {}
        self.output_schema = self.output_schema or {}


@dataclass
class FakeAPIVersion:
    schema_version: FakeSchemaVersion
    status: str = "published"


@dataclass
class FakeExecution:
    id: UUID


@dataclass
class FakeClient:
    id: UUID
    status: str = "active"
    rate_limit_per_minute: int = 60


@dataclass
class FakeKey:
    id: UUID
    client_id: UUID
    status: str = "active"


class FakeSession:
    async def get(self, model: object, identifier: object) -> FakeExecution:
        return FakeExecution(id=UUID(str(identifier)))


class SessionFactory:
    async def __aenter__(self) -> FakeSession:
        return FakeSession()

    async def __aexit__(self, *args: object) -> None:
        return None


async def _install_gateway_fakes(monkeypatch: pytest.MonkeyPatch, agent: FakeAgent) -> FakePublication:
    publication = FakePublication(agent=agent)
    client = FakeClient(id=uuid4())
    api_key = FakeKey(id=uuid4(), client_id=client.id)
    authentication = publications.production_repository.APIKeyAuthentication(
        client=client,  # type: ignore[arg-type]
        api_key=api_key,  # type: ignore[arg-type]
    )

    async def get_publication(session: object, agent_id: str) -> FakePublication:
        return publication

    async def get_agent(session: object, agent_id: str) -> FakeAgent:
        return agent

    async def get_api_version(session: object, agent_id: str, api_version: str) -> FakeAPIVersion:
        return FakeAPIVersion(
            schema_version=FakeSchemaVersion(
                version=api_version,
                input_schema=agent.input_schema,
                output_schema=agent.output_schema,
            )
        )

    async def prepare(*args: object, **kwargs: object) -> AgentExecutionContext:
        execution = FakeExecution(id=uuid4())
        return AgentExecutionContext(
            agent=agent,  # type: ignore[arg-type]
            execution=execution,  # type: ignore[arg-type]
            prompt="prompt",
            messages=[{"role": "user", "content": "prompt"}],
            loaded_skills=[],
            mcp_servers=[],
            knowledge_sources=[],
            knowledge_summary=[],
            memory_scope={},
            orchestration_session_id=None,
            workspace=None,
        )

    async def execute(*args: object, output_validator: Any = None, **kwargs: object) -> Any:
        output = '{"summary":"ok"}'
        if output_validator:
            output_validator(output)
        return type(
            "Run",
            (),
            {"execution_id": uuid4(), "output": output, "hermes_run_id": "run-sync"},
        )()

    async def record_public_call(session: object, **kwargs: object) -> object:
        if kwargs.get("increment_publication"):
            publication.call_count += 1
        return type("Audit", (), kwargs)()

    async def authenticate_api_key(
        session: object, *, agent_id: str, presented_key: str
    ) -> object | None:
        if agent_id == agent.id and presented_key == "secret-key":
            return authentication
        return None

    async def authenticate_client_key(
        session: object, *, presented_key: str
    ) -> object | None:
        return authentication if presented_key == "secret-key" else None

    async def has_invoke_permission(
        session: object, *, client_id: UUID, agent_id: str
    ) -> bool:
        return client_id == client.id and agent_id == agent.id

    async def enforce_rate_limit(
        redis: object, *, client_id: UUID, limit_per_minute: int
    ) -> tuple[bool, int, int]:
        return True, max(0, limit_per_minute - 1), 60

    monkeypatch.setattr(publications.repository, "get_publication", get_publication)
    monkeypatch.setattr(publications.agent_repository, "get_agent", get_agent)
    monkeypatch.setattr(publications.schema_repository, "get_api_version", get_api_version)
    monkeypatch.setattr(publications, "_prepare_agent_execution", prepare)
    monkeypatch.setattr(publications, "execute_agent_sync", execute)
    monkeypatch.setattr(publications.production_repository, "record_public_call", record_public_call)
    monkeypatch.setattr(
        publications.production_repository, "authenticate_api_key", authenticate_api_key
    )
    monkeypatch.setattr(
        publications.production_repository, "authenticate_client_key", authenticate_client_key
    )
    monkeypatch.setattr(
        publications.production_repository, "has_invoke_permission", has_invoke_permission
    )
    monkeypatch.setattr(
        publications.production_repository, "enforce_rate_limit", enforce_rate_limit
    )
    monkeypatch.setattr(
        publications,
        "get_task_queue",
        lambda: SimpleNamespace(redis=object()),
    )
    monkeypatch.setattr(publications, "SessionFactory", SessionFactory)
    return publication


@pytest.mark.asyncio
async def test_public_gateway_sync_v2_envelope_validates_input_and_output(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = FakeAgent()
    publication = await _install_gateway_fakes(monkeypatch, agent)
    response = await publications._execute_public_agent(
        agent_id=agent.id,
        payload={"input": {"topic": "AI"}, "stream": False},
        response_mode=None,
        forced_mode=None,
        x_api_key="secret-key",
        authorization=None,
        session=FakeSession(),  # type: ignore[arg-type]
        memory_store=object(),  # type: ignore[arg-type]
    )
    assert response.status == "success"
    assert response.result == {"summary": "ok"}
    assert response.trace[0]["stage"] == "schema_input"
    assert publication.call_count == 1


@pytest.mark.asyncio
async def test_public_gateway_rejects_invalid_input_before_model_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = FakeAgent()
    await _install_gateway_fakes(monkeypatch, agent)
    with pytest.raises(HTTPException) as caught:
        await publications._execute_public_agent(
            agent_id=agent.id,
            payload={"input": {}, "stream": False},
            response_mode=None,
            forced_mode=None,
            x_api_key="secret-key",
            authorization=None,
            session=FakeSession(),  # type: ignore[arg-type]
            memory_store=object(),  # type: ignore[arg-type]
        )
    assert caught.value.status_code == 422


@pytest.mark.asyncio
async def test_public_stream_endpoint_emits_contract_event_order(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = FakeAgent(response_mode="stream")
    publication = await _install_gateway_fakes(monkeypatch, agent)

    async def stream_prepared(*args: object, output_validator: Any = None, **kwargs: object):
        yield {"event": "run.created", "run_id": "run-stream"}
        yield {"event": "message.delta", "delta": '{"summary":"ok"}'}
        output = '{"summary":"ok"}'
        if output_validator:
            output_validator(output)
        yield {"event": "run.completed", "run_id": "run-stream", "output": output}

    monkeypatch.setattr(publications, "stream_prepared_agent", stream_prepared)
    response = await publications._execute_public_agent(
        agent_id=agent.id,
        payload={"input": {"topic": "AI"}, "stream": True},
        response_mode=None,
        forced_mode=None,
        x_api_key="secret-key",
        authorization=None,
        session=FakeSession(),  # type: ignore[arg-type]
        memory_store=object(),  # type: ignore[arg-type]
    )
    chunks = [chunk async for chunk in response.body_iterator]
    body = "".join(chunk.decode() if isinstance(chunk, bytes) else chunk for chunk in chunks)
    names = [line.removeprefix("event: ") for line in body.splitlines() if line.startswith("event: ")]
    assert names == ["start", "trace", "trace", "token", "trace", "end"]
    end_payload = [json.loads(line.removeprefix("data: ")) for line in body.splitlines() if line.startswith("data: ")][-1]
    assert end_payload["result"] == {"summary": "ok"}
    assert publication.call_count == 1


@pytest.mark.asyncio
async def test_public_stream_schema_failure_returns_error_without_end(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = FakeAgent(response_mode="stream")
    publication = await _install_gateway_fakes(monkeypatch, agent)

    async def invalid_stream(*args: object, output_validator: Any = None, **kwargs: object):
        yield {"event": "message.delta", "delta": "invalid"}
        if output_validator:
            output_validator("invalid")

    monkeypatch.setattr(publications, "stream_prepared_agent", invalid_stream)
    response = await publications._execute_public_agent(
        agent_id=agent.id,
        payload={"input": {"topic": "AI"}},
        response_mode=None,
        forced_mode="stream",
        x_api_key="secret-key",
        authorization=None,
        session=FakeSession(),  # type: ignore[arg-type]
        memory_store=object(),  # type: ignore[arg-type]
    )
    chunks = [chunk async for chunk in response.body_iterator]
    body = "".join(chunk.decode() if isinstance(chunk, bytes) else chunk for chunk in chunks)
    assert "event: error" in body
    assert "event: end" not in body
    assert publication.call_count == 0

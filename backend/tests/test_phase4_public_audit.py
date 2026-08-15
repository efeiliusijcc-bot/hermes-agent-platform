from __future__ import annotations

import hashlib
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api import publications
from app.api.agents import AgentExecutionContext
from app.memory import AgentMemoryError


class FakeSession:
    pass


def _agent() -> SimpleNamespace:
    return SimpleNamespace(
        id="phase4-public",
        status="active",
        api_enabled=True,
        current_version_id=uuid4(),
        response_mode="sync",
        input_schema={},
        output_schema={},
    )


def _publication(agent: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(
        agent=agent,
        agent_id=agent.id,
        status="published",
        api_key_hash=hashlib.sha256(b"legacy-key").hexdigest(),
    )


async def _base_fakes(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    agent = _agent()
    publication = _publication(agent)
    records: list[dict[str, object]] = []

    async def get_agent(session: object, agent_id: str):
        return agent

    async def get_publication(session: object, agent_id: str):
        return publication

    async def record_public_call(session: object, **values: object):
        records.append(values)

    monkeypatch.setattr(publications.agent_repository, "get_agent", get_agent)
    monkeypatch.setattr(publications.repository, "get_publication", get_publication)
    monkeypatch.setattr(publications.production_repository, "record_public_call", record_public_call)
    return records


@pytest.mark.asyncio
async def test_unbound_client_key_is_audited_once_as_forbidden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = await _base_fakes(monkeypatch)
    client_id = uuid4()
    key_id = uuid4()
    authentication = SimpleNamespace(
        client=SimpleNamespace(id=client_id, rate_limit_per_minute=60),
        api_key=SimpleNamespace(id=key_id),
    )

    async def authenticate_api_key(*args: object, **kwargs: object):
        return None

    async def authenticate_client_key(*args: object, **kwargs: object):
        return authentication

    async def has_invoke_permission(*args: object, **kwargs: object) -> bool:
        return False

    monkeypatch.setattr(publications.production_repository, "authenticate_api_key", authenticate_api_key)
    monkeypatch.setattr(publications.production_repository, "authenticate_client_key", authenticate_client_key)
    monkeypatch.setattr(publications.production_repository, "has_invoke_permission", has_invoke_permission)

    with pytest.raises(HTTPException) as caught:
        await publications._execute_public_agent(
            agent_id="phase4-public",
            payload={},
            response_mode=None,
            forced_mode=None,
            x_api_key="client-key",
            authorization=None,
            session=FakeSession(),  # type: ignore[arg-type]
            memory_store=object(),  # type: ignore[arg-type]
        )
    assert caught.value.status_code == 403
    assert len(records) == 1
    assert records[0]["status"] == "rejected"
    assert records[0]["error_code"] == "invoke_permission_denied"
    assert records[0]["client_id"] == client_id
    assert records[0]["api_key_id"] == key_id


@pytest.mark.asyncio
async def test_rate_limited_client_is_audited_once_with_429(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = await _base_fakes(monkeypatch)
    authentication = SimpleNamespace(
        client=SimpleNamespace(id=uuid4(), rate_limit_per_minute=1),
        api_key=SimpleNamespace(id=uuid4()),
    )

    async def authenticate_api_key(*args: object, **kwargs: object):
        return authentication

    async def enforce_rate_limit(*args: object, **kwargs: object):
        return False, 0, 17

    monkeypatch.setattr(publications.production_repository, "authenticate_api_key", authenticate_api_key)
    monkeypatch.setattr(publications.production_repository, "enforce_rate_limit", enforce_rate_limit)
    monkeypatch.setattr(publications, "get_task_queue", lambda: SimpleNamespace(redis=object()))

    with pytest.raises(HTTPException) as caught:
        await publications._execute_public_agent(
            agent_id="phase4-public",
            payload={},
            response_mode=None,
            forced_mode=None,
            x_api_key="client-key",
            authorization=None,
            session=FakeSession(),  # type: ignore[arg-type]
            memory_store=object(),  # type: ignore[arg-type]
        )
    assert caught.value.status_code == 429
    assert caught.value.headers == {"Retry-After": "17"}
    assert len(records) == 1
    assert records[0]["status"] == "rejected"
    assert records[0]["error_code"] == "rate_limit_exceeded"


def test_execution_observability_uses_explicit_tokens_and_real_mcp_list() -> None:
    assert publications._explicit_token_usage({"usage": {"total_tokens": 29}}) == 29
    assert publications._explicit_token_usage({"token_usage": 0}) == 0
    assert publications._explicit_token_usage({"prompt_tokens": 9}) is None
    assert publications._explicit_token_usage({"total_tokens": "29"}) is None


@pytest.mark.asyncio
async def test_sse_dependency_failure_is_redacted_and_audited_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records: list[dict[str, object]] = []
    execution_id = uuid4()
    execution = SimpleNamespace(id=execution_id, details={})
    agent = SimpleNamespace(id="phase4-public", output_schema={})
    context = AgentExecutionContext(
        agent=agent,  # type: ignore[arg-type]
        execution=execution,  # type: ignore[arg-type]
        prompt="",
        messages=[],
        loaded_skills=[],
        mcp_servers=[],
        knowledge_sources=[],
        knowledge_summary=[],
        memory_scope={},
    )

    class StreamSession:
        async def get(self, model: object, identifier: object):
            return execution

    class Factory:
        async def __aenter__(self):
            return StreamSession()

        async def __aexit__(self, *args: object):
            return None

    async def failing_stream(*args: object, **kwargs: object):
        raise AgentMemoryError("secret-memory-detail")
        yield  # pragma: no cover

    async def record_public_call(session: object, **values: object):
        records.append(values)

    monkeypatch.setattr(publications, "SessionFactory", Factory)
    monkeypatch.setattr(publications, "stream_prepared_agent", failing_stream)
    monkeypatch.setattr(publications.production_repository, "record_public_call", record_public_call)
    audit = publications.PublicAuditContext(request_id="request-1", started_at=0, agent_id=agent.id)
    chunks = [
        value
        async for value in publications._public_sse_events(
            context,
            SimpleNamespace(),  # type: ignore[arg-type]
            SimpleNamespace(),  # type: ignore[arg-type]
            object(),  # type: ignore[arg-type]
            audit,
            {},
        )
    ]
    body = "".join(chunks)
    assert "event: error" in body
    assert "Agent execution failed" in body
    assert "secret-memory-detail" not in body
    assert len(records) == 1
    assert records[0]["status"] == "failed"
    assert records[0]["error_code"] == "stream_dependency_failed"

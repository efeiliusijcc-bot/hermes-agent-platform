from __future__ import annotations

import hashlib
import inspect
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.schemas.production import (
    APIKeyCreate,
    AgentBindingCreate,
    AgentVersionCreate,
    LifecycleUpdate,
)
from app.schemas.agent import AgentCreate


def test_phase4_migration_has_hash_only_authorization_audit_metrics_and_versions() -> None:
    migration = (
        Path(__file__).parents[1] / "alembic/versions/0008_production_agent_runtime.py"
    ).read_text()
    for table in (
        "api_clients",
        "agent_api_clients",
        "api_keys",
        "audit_logs",
        "agent_metrics",
        "agent_versions",
    ):
        assert f'"{table}"' in migration
    assert 'sa.Column("key_hash"' in migration
    assert 'sa.Column("prefix"' in migration
    assert 'sa.Column("api_key"' not in migration
    assert 'sa.Column("input"' not in migration.split('"audit_logs"', 1)[1].split(")\n    op.create_index", 1)[0]


def test_phase4_schema_enforces_invoke_only_and_hash_secret_shape() -> None:
    assert AgentBindingCreate(agent_id="production-agent").permission == "invoke"
    with pytest.raises(ValueError):
        AgentBindingCreate(agent_id="production-agent", permission="admin")  # type: ignore[arg-type]
    assert APIKeyCreate(name="backend-service").name == "backend-service"
    assert LifecycleUpdate(status="active").status == "active"
    with pytest.raises(ValueError):
        LifecycleUpdate(status="published")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        AgentVersionCreate(version="unsafe/version")


def test_legacy_agent_lifecycle_values_are_safely_normalized() -> None:
    active = AgentCreate(
        id="legacy-active-agent",
        name="Legacy active",
        role="tester",
        system_prompt="test",
        status="active",
    )
    disabled = AgentCreate(
        id="legacy-disabled-agent",
        name="Legacy disabled",
        role="tester",
        system_prompt="test",
        status="disabled",
    )
    assert active.status == "active"
    assert disabled.status == "inactive"


def test_production_repository_never_persists_plaintext_api_key_or_audit_input() -> None:
    from app.repositories import production

    source = inspect.getsource(production)
    assert "key_hash=" in source
    assert "hashlib.sha256" in source
    assert "AuditLog(" in source
    audit_constructor = source.split("AuditLog(", 1)[1].split("\n        )", 1)[0]
    assert "input=" not in audit_constructor


@pytest.mark.asyncio
async def test_lifecycle_rejects_illegal_transition(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api import production

    with pytest.raises((HTTPException, ValueError)):
        production._transition("draft", "published")


@pytest.mark.asyncio
async def test_client_key_authentication_requires_active_client_key_and_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.repositories import production

    plain_key = "hap_client_contract_secret"
    client_id = uuid4()
    key = SimpleNamespace(
        id=uuid4(),
        client_id=client_id,
        key_hash=hashlib.sha256(plain_key.encode()).hexdigest(),
        status="active",
        expires_at=None,
    )
    client = SimpleNamespace(id=client_id, status="active")
    binding = SimpleNamespace(client_id=client_id, agent_id="production-agent", permission="invoke")

    class Result:
        def first(self):
            if binding.permission != "invoke":
                return None
            return client, key

    async def execute(statement: object):
        return Result()

    session = SimpleNamespace(execute=execute, commit=_async_noop)
    authenticated = await production.authenticate_api_key(
        session, agent_id="production-agent", presented_key=plain_key  # type: ignore[arg-type]
    )
    assert authenticated.api_key.id == key.id
    assert authenticated.client.id == client.id

    binding.permission = "denied"
    assert await production.authenticate_api_key(  # type: ignore[arg-type]
        session, agent_id="production-agent", presented_key=plain_key
    ) is None


@pytest.mark.asyncio
async def test_record_public_call_tracks_success_failure_latency_tokens_and_mcp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.db.models import AgentMetric, AuditLog
    from app.repositories import production

    added: list[object] = []

    class Session:
        async def scalar(self, statement: object):
            return None

        def add(self, value: object) -> None:
            added.append(value)

        async def execute(self, statement: object) -> None:
            metric = AgentMetric(
                agent_id="production-agent",
                metric_date=datetime.now(timezone.utc).date(),
                call_count=1,
                success_count=1,
                failure_count=0,
                total_latency_ms=125,
                total_token_usage=19,
                token_usage_observed_count=1,
                mcp_call_count=2,
            )
            added.append(metric)

        async def commit(self) -> None:
            return None

        async def refresh(self, value: object) -> None:
            return None

    await production.record_public_call(
        Session(),  # type: ignore[arg-type]
        request_id="phase4-success",
        agent_id="production-agent",
        status="succeeded",
        latency_ms=125,
        token_usage=19,
        mcp_call_count=2,
        client_id=uuid4(),
        api_key_id=uuid4(),
    )
    audit = next(value for value in added if isinstance(value, AuditLog))
    metric = next(value for value in added if isinstance(value, AgentMetric))
    assert audit.status == "succeeded"
    assert audit.latency_ms == 125
    assert audit.token_usage == 19
    assert audit.mcp_call_count == 2
    assert not hasattr(audit, "input")
    assert metric.call_count == 1
    assert metric.success_count == 1
    assert metric.failure_count == 0
    assert metric.total_latency_ms == 125
    assert metric.total_token_usage == 19
    assert metric.mcp_call_count == 2


def test_failed_call_metric_contract_counts_failure_and_keeps_unknown_tokens_null() -> None:
    from app.repositories import production

    source = inspect.getsource(production.record_public_call)
    assert 'failure = 0 if success else 1' in source
    assert 'token_usage_observed_count=1 if token_usage is not None else 0' in source
    assert '"token_usage": int(row.total_token_usage or 0) if observed == call_count and call_count else None' in inspect.getsource(production._metric_read)


@pytest.mark.asyncio
async def test_rate_limit_rejects_second_call_in_same_window() -> None:
    from app.repositories import production

    class Redis:
        count = 0

        async def eval(self, script: str, keys: int, key: str, ttl: int) -> int:
            self.count += 1
            return self.count

    redis = Redis()
    allowed, remaining, _ = await production.enforce_rate_limit(
        redis, client_id=uuid4(), limit_per_minute=1  # type: ignore[arg-type]
    )
    assert allowed and remaining == 0
    allowed, remaining, retry_after = await production.enforce_rate_limit(
        redis, client_id=uuid4(), limit_per_minute=1  # type: ignore[arg-type]
    )
    assert not allowed and remaining == 0 and retry_after > 0


def test_agent_execution_lifecycle_contract_distinguishes_internal_and_public() -> None:
    from app.api import agents, orchestration, publications

    active_agent_source = inspect.getsource(agents._active_agent)
    task_source = inspect.getsource(orchestration.submit_task)
    public_source = inspect.getsource(publications._execute_public_agent)
    assert 'agent.status != "active"' in active_agent_source
    assert 'agent.status != "active"' in task_source
    assert 'agent.status != "active"' in public_source


@pytest.mark.parametrize("status_value", ["archived"])
def test_published_and_archived_agents_reject_direct_configuration_edits(status_value: str) -> None:
    from app.api.agents import _ensure_agent_editable

    with pytest.raises(HTTPException) as caught:
        _ensure_agent_editable(SimpleNamespace(status=status_value, current_version_id=None))  # type: ignore[arg-type]
    assert caught.value.status_code == 409


@pytest.mark.parametrize("status_value", ["active", "inactive"])
def test_non_published_agent_can_prepare_next_version(status_value: str) -> None:
    from app.api.agents import _ensure_agent_editable

    _ensure_agent_editable(SimpleNamespace(status=status_value, current_version_id=None))  # type: ignore[arg-type]


def test_every_mutating_agent_route_applies_edit_lock() -> None:
    from app.api import agents

    functions = (
        agents.update_agent_schema,
        agents.update_agent_response_mode,
        agents.update_agent_configuration,
        agents.bind_agent_skill,
        agents.unbind_agent_skill,
        agents.bind_agent_mcp_server,
        agents.unbind_agent_mcp_server,
        agents.bind_agent_knowledge_source,
        agents.unbind_agent_knowledge_source,
    )
    for function in functions:
        assert "_ensure_agent_editable(agent)" in inspect.getsource(function), function.__name__


@pytest.mark.asyncio
async def test_version_snapshot_and_rollback_restore_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.repositories import production

    old_snapshot = {
        "format_version": 1,
        "prompt": {
            "role": "analyst",
            "system_prompt": "old prompt",
            "prompt_template": "{{input}}",
        },
        "model": {"name": "old-model", "adapter": "qwen", "config": {"temperature": 0}},
        "runtime": {"response_mode": "sync"},
        "schema": {
            "version": "v1",
            "input_schema": {"type": "object"},
            "output_schema": {"type": "object"},
        },
        "api": {"version": "v1", "status": "published"},
        "skill_ids": ["skill-v1"],
        "mcp_ids": ["mcp-v1"],
        "schema_version": "v1",
    }
    agent = SimpleNamespace(
        id="production-agent",
        name="Production Agent",
        description="changed",
        role="analyst",
        system_prompt="changed prompt",
        model="new-model",
        model_adapter="qwen",
        model_settings={"temperature": 1},
        prompt_template="{{input}}",
        response_mode="sync",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        skills=[],
        mcp_servers=[],
        status="active",
        current_version_id=None,
    )
    version = SimpleNamespace(
        id=uuid4(),
        agent_id=agent.id,
        version="v1.0",
        snapshot=old_snapshot,
        status="deprecated",
        deprecated_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
        published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    class Session:
        scalar_calls = 0

        def __init__(self) -> None:
            self.scalars_calls = 0
            self.publication = SimpleNamespace(agent_id=agent.id, status="disabled")

        async def commit(self) -> None:
            return None

        async def refresh(self, value: object) -> None:
            return None

        async def execute(self, statement: object):
            return None

        async def scalars(self, statement: object):
            self.scalars_calls += 1
            return ["skill-v1"] if self.scalars_calls == 1 else ["mcp-v1"]

        async def get(self, model: object, key: object):
            return self.publication if getattr(model, "__name__", "") == "AgentPublication" else None

        def add(self, value: object) -> None:
            self.publication = value

        async def scalar(self, statement: object):
            self.scalar_calls += 1
            if self.scalar_calls == 1:
                return SimpleNamespace(
                    id=uuid4(),
                    version="v1",
                    input_schema={"type": "object"},
                    output_schema={"type": "object"},
                    status="deprecated",
                    published_at=None,
                )
            return SimpleNamespace(
                schema_version_id=uuid4(),
                status="deprecated",
                published_at=None,
            )

    session = Session()
    rolled_back = await production.rollback_agent_version(  # type: ignore[arg-type]
        session, agent=agent, version=version
    )
    assert rolled_back is agent
    assert agent.system_prompt == "old prompt"
    assert agent.model == "old-model"
    assert agent.model_settings == {"temperature": 0}
    assert session.publication.status == "published"


def test_public_gateway_has_no_publication_hash_authentication_bypass() -> None:
    from app.api import publications

    source = inspect.getsource(publications._execute_public_agent)
    assert "authenticate_api_key" in source
    assert "authenticate_client_key" in source
    assert "has_invoke_permission" in source
    assert "publication.api_key_hash" not in source
    assert "compare_digest" not in source


async def _async_noop(*args: object, **kwargs: object) -> None:
    return None

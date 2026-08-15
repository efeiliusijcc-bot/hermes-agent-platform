from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest


@pytest.mark.asyncio
async def test_publish_agent_synchronizes_public_contract_and_version() -> None:
    from app.db.models import AgentAPIVersion, AgentPublication
    from app.repositories import production

    agent = SimpleNamespace(
        id="phase4-publish",
        status="active",
        api_enabled=False,
        current_version_id=None,
        role="analyst",
        system_prompt="system",
        prompt_template="{{input}}",
        model="qwen-32b",
        model_adapter="qwen",
        model_settings={},
        input_schema={},
        output_schema={},
        response_mode="sync",
    )
    schema = SimpleNamespace(
        id=uuid4(),
        agent_id=agent.id,
        version="v1",
        status="testing",
        published_at=None,
    )
    version = SimpleNamespace(
        id=uuid4(),
        agent_id=agent.id,
        snapshot={
            "prompt": {"role": "analyst", "system_prompt": "system", "prompt_template": "{{input}}"},
            "model": {"name": "qwen-32b", "adapter": "qwen", "config": {}},
            "schema": {"version": "v1"},
            "api": {"version": "v1", "status": "testing"},
            "runtime": {"response_mode": "sync"},
            "skill_ids": [],
            "mcp_ids": [],
        },
        status="release_candidate",
        published_at=None,
        deprecated_at=None,
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    added: list[object] = []

    class Session:
        scalar_calls = 0

        async def scalar(self, statement: object):
            self.scalar_calls += 1
            return schema if self.scalar_calls in {1, 3} else None

        async def get(self, model: object, key: object):
            return None

        def add(self, value: object) -> None:
            added.append(value)

        async def execute(self, statement: object):
            return None

        async def commit(self) -> None:
            return None

        async def refresh(self, value: object) -> None:
            return None

    published = await production.publish_agent(  # type: ignore[arg-type]
        Session(), agent=agent, version=version
    )
    assert published is version
    assert agent.status == "active" and agent.api_enabled is True
    assert agent.current_version_id == version.id
    assert schema.status == "published" and schema.published_at is not None
    api = next(value for value in added if isinstance(value, AgentAPIVersion))
    publication = next(value for value in added if isinstance(value, AgentPublication))
    assert api.api_version == "v1" and api.schema_version_id == schema.id
    assert api.status == "published" and api.published_at is not None
    assert publication.agent_id == agent.id and publication.status == "published"
    assert version.status == "published" and isinstance(version.published_at, datetime)
    assert version.published_at.tzinfo == timezone.utc

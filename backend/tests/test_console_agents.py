from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.api import console as console_api


class ScalarRows:
    def __init__(self, values: list[object]) -> None:
        self.values = values

    def __iter__(self):
        return iter(self.values)


def agent_summary(agent_id: str, version_id=None):
    return SimpleNamespace(
        id=agent_id,
        name=f"Agent {agent_id}",
        description="测试 Agent",
        agent_type="worker",
        role="analysis",
        model="test-model",
        status="active",
        runtime_type="hermes",
        current_version_id=version_id,
        skills=[SimpleNamespace(id="skill-b", name="Beta"), SimpleNamespace(id="skill-a", name="Alpha")],
        mcp_servers=[SimpleNamespace(id="mcp-a", name="Filesystem")],
        updated_at="2026-08-20T00:00:00Z",
    )


@pytest.mark.asyncio
async def test_console_agents_uses_batched_summaries_without_default_preflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_version_id = uuid4()
    second_version_id = uuid4()
    agents = [agent_summary("a", first_version_id), agent_summary("b", second_version_id)]
    versions = [
        SimpleNamespace(id=first_version_id, version="1.2.0"),
        SimpleNamespace(id=second_version_id, version="2.0.0"),
    ]
    session = SimpleNamespace(
        scalars=AsyncMock(side_effect=[ScalarRows(agents), ScalarRows(versions)])
    )
    draft = AsyncMock()
    resolver = AsyncMock()
    monkeypatch.setattr(console_api, "_draft_version", draft)
    monkeypatch.setattr(console_api, "resolve_agent_capabilities", resolver)

    values = await console_api.console_agents(session=session)

    assert session.scalars.await_count == 2
    draft.assert_not_awaited()
    resolver.assert_not_awaited()
    assert [item["version"] for item in values] == ["1.2.0", "2.0.0"]
    assert values[0]["skills"] == [
        {"id": "skill-a", "name": "Alpha"},
        {"id": "skill-b", "name": "Beta"},
    ]
    assert values[0]["mcps"] == [{"id": "mcp-a", "name": "Filesystem"}]
    assert values[0]["preflight_state"] is None


@pytest.mark.asyncio
async def test_console_agents_preserves_explicit_preflight_behavior(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = SimpleNamespace(scalars=AsyncMock(return_value=ScalarRows([agent_summary("a")])))
    draft_value = SimpleNamespace(id=uuid4())
    draft = AsyncMock(return_value=draft_value)
    resolver = AsyncMock(return_value=SimpleNamespace(ready=True))
    monkeypatch.setattr(console_api, "_draft_version", draft)
    monkeypatch.setattr(console_api, "resolve_agent_capabilities", resolver)

    values = await console_api.console_agents(session=session, include_preflight=True)

    draft.assert_awaited_once_with(session, "a", create=False)
    resolver.assert_awaited_once_with(session, draft_value)
    assert values[0]["preflight_state"] == "READY"

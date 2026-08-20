from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api import multi_agent as api
from app.schemas.multi_agent import TeamConversationMessageRequest


def test_team_conversation_migration_is_additive_and_rollback_compatible() -> None:
    migration = Path(
        "backend/alembic/versions/0018_team_conversation_context.py"
    ).read_text()
    assert 'sa.Column("session_id", sa.String(length=128), nullable=True)' in migration
    assert "legacy-" in migration
    assert "ix_workflow_runs_team_session_created" in migration
    assert "uq_workflow_runs_active_team_session" in migration
    assert "status IN ('pending', 'running', 'human_review')" in migration


@pytest.mark.asyncio
async def test_team_conversation_rejects_workflow_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    team_id = uuid4()
    locked_workflow_id = uuid4()
    monkeypatch.setattr(api, "_active_team", AsyncMock(return_value=SimpleNamespace(id=team_id)))
    monkeypatch.setattr(
        api.repository,
        "conversation_mode",
        AsyncMock(return_value=(True, locked_workflow_id)),
    )

    with pytest.raises(HTTPException, match="execution mode is locked") as failure:
        await api.send_team_conversation_message(
            team_id=team_id,
            session_id="team-chat-1",
            payload=TeamConversationMessageRequest(input="继续分析", workflow_id=None),
            session=SimpleNamespace(),
            queue=SimpleNamespace(),
            bus=SimpleNamespace(),
        )

    assert failure.value.status_code == 409


@pytest.mark.asyncio
async def test_team_conversation_rejects_a_second_active_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    team_id = uuid4()
    monkeypatch.setattr(api, "_active_team", AsyncMock(return_value=SimpleNamespace(id=team_id)))
    monkeypatch.setattr(api.repository, "conversation_mode", AsyncMock(return_value=(True, None)))
    monkeypatch.setattr(
        api.repository,
        "list_runs",
        AsyncMock(return_value=[SimpleNamespace(id=uuid4(), status="running")]),
    )

    with pytest.raises(HTTPException, match="already has an active Run") as failure:
        await api.send_team_conversation_message(
            team_id=team_id,
            session_id="team-chat-1",
            payload=TeamConversationMessageRequest(input="并发消息"),
            session=SimpleNamespace(),
            queue=SimpleNamespace(),
            bus=SimpleNamespace(),
        )

    assert failure.value.status_code == 409


@pytest.mark.asyncio
async def test_team_conversation_sends_the_path_session_to_the_orchestrator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    team_id = uuid4()
    run_id = uuid4()
    team = SimpleNamespace(id=team_id)
    submit = AsyncMock(
        return_value=SimpleNamespace(
            id=run_id,
            workflow_id=None,
            team_id=team_id,
            session_id="team-chat-stable",
            status="running",
            input="第一轮",
            output=None,
            error=None,
            created_at="2026-08-20T00:00:00Z",
            started_at="2026-08-20T00:00:00Z",
            finished_at=None,
        )
    )
    monkeypatch.setattr(api, "_active_team", AsyncMock(return_value=team))
    monkeypatch.setattr(api.repository, "conversation_mode", AsyncMock(return_value=(False, None)))
    monkeypatch.setattr(api.repository, "list_runs", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        api,
        "AgentOrchestrator",
        lambda _queue, _bus: SimpleNamespace(submit_team_run=submit),
    )

    result = await api.send_team_conversation_message(
        team_id=team_id,
        session_id="team-chat-stable",
        payload=TeamConversationMessageRequest(input="第一轮"),
        session=SimpleNamespace(),
        queue=SimpleNamespace(),
        bus=SimpleNamespace(),
    )

    submitted_payload = submit.await_args.kwargs["payload"]
    assert submitted_payload.session_id == "team-chat-stable"
    assert result.session_id == "team-chat-stable"

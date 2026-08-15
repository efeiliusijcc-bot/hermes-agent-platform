from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest

from app.concurrency import LocalConcurrencyGate
from app.schemas.orchestration import TaskSubmitRequest
from app.workspace import WorkspaceBoundaryError, WorkspaceManager


def test_workspace_is_scoped_to_agent_and_internal_session(tmp_path: Path) -> None:
    manager = WorkspaceManager(tmp_path)
    session_id = uuid4()

    workspace = manager.create_session("report-agent", session_id)

    assert workspace.root == (tmp_path / "report-agent" / "sessions" / str(session_id)).resolve()
    assert workspace.input.is_dir()
    assert workspace.output.is_dir()
    assert workspace.temp.is_dir()
    assert manager.write_output(workspace, "report.md", b"verified").read_bytes() == b"verified"


@pytest.mark.parametrize("agent_id", ["../other", "agent/other", "/absolute", "agent.."])
def test_workspace_rejects_agent_path_traversal(tmp_path: Path, agent_id: str) -> None:
    with pytest.raises(WorkspaceBoundaryError):
        WorkspaceManager(tmp_path).create_session(agent_id, uuid4())


@pytest.mark.parametrize("filename", ["../secret", "folder/report.md", "/tmp/report.md", "."])
def test_workspace_rejects_artifact_path_traversal(tmp_path: Path, filename: str) -> None:
    manager = WorkspaceManager(tmp_path)
    workspace = manager.create_session("report-agent", uuid4())
    with pytest.raises(WorkspaceBoundaryError):
        manager.write_output(workspace, filename, b"blocked")


def test_task_priority_is_bounded() -> None:
    assert TaskSubmitRequest(input="run", priority=9).priority == 9
    with pytest.raises(ValueError):
        TaskSubmitRequest(input="run", priority=10)


@pytest.mark.asyncio
async def test_concurrency_gate_limits_parallel_model_calls() -> None:
    gate = LocalConcurrencyGate(limit=2)
    active = 0
    peak = 0

    async def run() -> None:
        nonlocal active, peak
        async with gate.slot(timeout_seconds=1):
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.02)
            active -= 1

    await asyncio.gather(*(run() for _ in range(6)))
    assert peak == 2


@pytest.mark.asyncio
async def test_concurrency_gate_times_out_when_capacity_is_exhausted() -> None:
    gate = LocalConcurrencyGate(limit=1)
    async with gate.slot(timeout_seconds=1):
        with pytest.raises(TimeoutError, match="concurrency capacity"):
            async with gate.slot(timeout_seconds=0.01):
                pass

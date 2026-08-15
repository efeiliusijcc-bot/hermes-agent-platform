from __future__ import annotations

from io import BytesIO
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.session import get_session
from app.repositories import agents as agent_repository
from app.repositories import orchestration as repository
from app.schemas.orchestration import ArtifactRead, SessionRead, TaskRead, TaskSubmitRequest
from app.task_queue import TaskQueue, TaskQueueError, get_task_queue
from app.workspace import WorkspaceBoundaryError, WorkspaceManager
from app.storage import ArtifactStorageError, get_artifact_storage


router = APIRouter(tags=["orchestration"])


@router.post("/api/agents/{agent_id}/tasks", response_model=TaskRead, status_code=status.HTTP_202_ACCEPTED)
async def submit_task(
    agent_id: str,
    payload: TaskSubmitRequest,
    session: AsyncSession = Depends(get_session),
    queue: TaskQueue = Depends(get_task_queue),
) -> TaskRead:
    agent = await agent_repository.get_agent(session, agent_id)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="agent not found")
    if agent.status != "active":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Agent is not active")
    session_id = uuid4()
    manager = WorkspaceManager(get_settings().workspace_root)
    try:
        workspace = manager.create_session(agent_id, session_id)
    except (OSError, WorkspaceBoundaryError) as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="workspace creation failed") from exc
    task = await repository.create_task(
        session,
        agent_id=agent_id,
        input_text=payload.input,
        memory_session_id=payload.session_id,
        user_id=payload.user_id,
        priority=payload.priority,
        max_attempts=get_settings().task_max_attempts,
        workspace_path=manager.relative(workspace.root),
        internal_session_id=session_id,
        input_json={
            "task": payload.input,
            "parameters": payload.parameters or {},
            "runtime_options": (
                {"temperature": payload.temperature} if payload.temperature is not None else {}
            ),
        },
        agent_version_id=agent.current_version_id,
    )
    try:
        await queue.enqueue(task.id, task.priority)
    except TaskQueueError as exc:
        task.status = "failed"
        task.error = "task queue unavailable"
        task.session.status = "failed"
        if task.execution_id:
            from app.db.models import ExecutionLog

            execution = await session.get(ExecutionLog, task.execution_id)
            if execution is not None:
                execution.status = "failed"
                execution.error = "task queue unavailable"
        await session.commit()
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="task queue unavailable") from exc
    return TaskRead.model_validate(task)


@router.get("/api/tasks", response_model=list[TaskRead])
async def list_tasks(
    agent_id: str | None = Query(default=None),
    task_status: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
) -> list[TaskRead]:
    return [
        TaskRead.model_validate(item)
        for item in await repository.list_tasks(session, agent_id=agent_id, status=task_status, limit=limit)
    ]


@router.get("/api/tasks/{task_id}", response_model=TaskRead)
async def get_task(task_id: UUID, session: AsyncSession = Depends(get_session)) -> TaskRead:
    task = await repository.get_task(session, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    return TaskRead.model_validate(task)


@router.delete("/api/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_task(
    task_id: UUID,
    session: AsyncSession = Depends(get_session),
    queue: TaskQueue = Depends(get_task_queue),
) -> Response:
    task = await repository.get_task(session, task_id, lock=True)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    if task.status not in {"pending", "retrying"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="only queued tasks can be cancelled")
    await queue.remove(task.id)
    task.status = "cancelled"
    task.session.status = "cancelled"
    cancelled_at = datetime.now(timezone.utc)
    task.finished_at = cancelled_at
    task.session.finished_at = cancelled_at
    if task.execution_id:
        from app.db.models import ExecutionLog

        execution = await session.get(ExecutionLog, task.execution_id)
        if execution is not None:
            execution.status = "cancelled"
            execution.finished_at = cancelled_at
            execution.duration_ms = max(
                0, int((cancelled_at - execution.started_at).total_seconds() * 1000)
            )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/api/sessions", response_model=list[SessionRead])
async def list_sessions(
    agent_id: str | None = Query(default=None),
    session_status: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
) -> list[SessionRead]:
    return [
        SessionRead.model_validate(item)
        for item in await repository.list_sessions(session, agent_id=agent_id, status=session_status, limit=limit)
    ]


@router.get("/api/sessions/{session_id}", response_model=SessionRead)
async def get_agent_session(session_id: UUID, session: AsyncSession = Depends(get_session)) -> SessionRead:
    value = await repository.get_agent_session(session, session_id)
    if value is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
    return SessionRead.model_validate(value)


@router.get("/api/artifacts", response_model=list[ArtifactRead])
async def list_artifacts(
    agent_id: str | None = Query(default=None),
    session_id: UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
) -> list[ArtifactRead]:
    return [
        ArtifactRead.model_validate(item)
        for item in await repository.list_artifacts(session, agent_id=agent_id, session_id=session_id, limit=limit)
    ]


@router.get("/api/artifacts/{artifact_id}", response_model=ArtifactRead)
async def get_artifact(artifact_id: UUID, session: AsyncSession = Depends(get_session)) -> ArtifactRead:
    value = await repository.get_artifact(session, artifact_id)
    if value is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="artifact not found")
    return ArtifactRead.model_validate(value)


@router.delete("/api/artifacts/{artifact_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_artifact(artifact_id: UUID, session: AsyncSession = Depends(get_session)) -> Response:
    value = await repository.get_artifact(session, artifact_id)
    if value is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="artifact not found")
    try:
        await get_artifact_storage(value.storage_type).delete(value.storage_path)
    except ArtifactStorageError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="artifact storage is unavailable") from exc
    await repository.delete_artifact(session, value)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/api/artifacts/{artifact_id}/download", response_class=StreamingResponse)
async def download_artifact(artifact_id: UUID, session: AsyncSession = Depends(get_session)) -> StreamingResponse:
    value = await repository.get_artifact(session, artifact_id)
    if value is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="artifact not found")
    storage = get_artifact_storage(value.storage_type)
    try:
        content = await storage.get(value.storage_path, expected_sha256=value.sha256)
    except ArtifactStorageError as exc:
        if "integrity" in str(exc):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="artifact integrity check failed") from exc
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="artifact file is unavailable") from exc
    safe_filename = value.filename.replace('"', "")
    return StreamingResponse(
        BytesIO(content),
        media_type=value.content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{safe_filename}"',
            "Content-Length": str(len(content)),
            "X-Artifact-SHA256": value.sha256,
        },
    )


@router.get("/api/agents/{agent_id}/workspace")
async def get_workspace(agent_id: str, session: AsyncSession = Depends(get_session)) -> dict[str, int | str]:
    if await agent_repository.get_agent(session, agent_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="agent not found")
    session_count, artifact_count, size_bytes = await repository.workspace_summary(session, agent_id)
    return {
        "agent_id": agent_id,
        "root": f"{agent_id}/sessions",
        "session_count": session_count,
        "artifact_count": artifact_count,
        "size_bytes": size_bytes,
    }

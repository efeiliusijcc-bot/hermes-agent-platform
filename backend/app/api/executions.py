from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import ExecutionLog
from app.db.session import get_session
from app.repositories import executions as repository
from app.repositories import orchestration as orchestration_repository
from app.repositories import runtimes as runtime_repository
from app.runtime import RuntimeAdapterError, get_runtime_adapter
from app.capabilities.revocation import revoke_execution_capability_token
from app.schemas.execution import (
    ExecutionDetail,
    ExecutionListRead,
    ExecutionMetrics,
    ExecutionRetryRequest,
    ExecutionStepRead,
    ExecutionSummary,
    ExecutionStopRead,
    ExecutionTraceRead,
    TraceMetrics,
)
from app.schemas.orchestration import ArtifactRead, TaskRead
from app.task_queue import TaskQueue, TaskQueueError, get_task_queue
from app.workspace import WorkspaceBoundaryError, WorkspaceManager
from app.runtime.capabilities import normalize_capability_profile


router = APIRouter(prefix="/api/executions", tags=["executions"])


@router.get("", response_model=ExecutionListRead)
async def list_executions(
    agent_id: str | None = Query(default=None),
    execution_status: Literal["queued", "running", "succeeded", "failed", "cancelled"] | None = Query(
        default=None, alias="status"
    ),
    search: str | None = Query(default=None, max_length=255),
    started_from: datetime | None = Query(default=None),
    started_to: datetime | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> ExecutionListRead:
    items, total = await repository.list_executions(
        session,
        agent_id=agent_id,
        status=execution_status,
        search=search,
        started_from=started_from,
        started_to=started_to,
        limit=limit,
        offset=offset,
    )
    counts = await repository.get_execution_metrics(
        session,
        agent_id=agent_id,
        status=execution_status,
        search=search,
        started_from=started_from,
        started_to=started_to,
    )
    completed = counts["succeeded"] + counts["failed"]
    return ExecutionListRead(
        items=[_summary(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
        metrics=ExecutionMetrics(
            total_executions=counts["total"],
            running=counts["running"],
            succeeded=counts["succeeded"],
            failed=counts["failed"],
            cancelled=counts["cancelled"],
            success_rate=(round(counts["succeeded"] / completed * 100, 2) if completed else None),
        ),
    )


@router.get("/{execution_id}", response_model=ExecutionDetail)
async def get_execution(
    execution_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> ExecutionDetail:
    execution = await repository.get_execution(session, execution_id)
    if execution is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="execution not found")
    queue_task = await repository.get_task_for_execution(session, execution.id)
    summary = _summary(execution)
    details = execution.details if isinstance(execution.details, dict) else {}
    return ExecutionDetail(
        **summary.model_dump(),
        input=execution.input,
        input_json=execution.input_json,
        output=execution.output,
        output_json=execution.output_json,
        error=execution.error,
        details=details,
        model=_text(details.get("model")),
        model_adapter=_text(details.get("model_adapter")),
        schema_version=_text(details.get("schema_version")),
        steps=[ExecutionStepRead.model_validate(item) for item in execution.steps],
        artifacts=[ArtifactRead.model_validate(item) for item in execution.artifacts],
        queue_task=TaskRead.model_validate(queue_task) if queue_task else None,
    )


@router.get("/{execution_id}/trace", response_model=ExecutionTraceRead)
async def get_execution_trace(
    execution_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> ExecutionTraceRead:
    execution = await repository.get_execution(session, execution_id)
    if execution is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="execution not found")
    return _trace(execution)


@router.post("/{execution_id}/retry", response_model=TaskRead, status_code=status.HTTP_202_ACCEPTED)
async def retry_execution(
    execution_id: UUID,
    payload: ExecutionRetryRequest | None = None,
    session: AsyncSession = Depends(get_session),
    queue: TaskQueue = Depends(get_task_queue),
) -> TaskRead:
    source = await repository.get_execution(session, execution_id)
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="execution not found")
    if source.status in {"queued", "running"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="active execution cannot be retried")
    if getattr(source.agent, "status", None) != "active":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Agent is not active")
    request = payload or ExecutionRetryRequest()
    priority = request.priority if request.priority is not None else (source.priority if source.priority is not None else 5)
    memory_session_id = request.session_id or (
        source.session.memory_session_id if source.session is not None else f"retry-{execution_id.hex[:12]}"
    )
    internal_session_id = uuid4()
    manager = WorkspaceManager(get_settings().workspace_root)
    capability_profile = normalize_capability_profile(
        getattr(source.agent, "capability_profile", {}) or {},
        runtime_type=getattr(source.agent, "runtime_type", "hermes"),
    )
    workspace_type = str(capability_profile["workspace_type"])
    try:
        workspace = manager.create_session(
            source.agent_id,
            internal_session_id,
            workspace_type=workspace_type,
        )
    except (OSError, WorkspaceBoundaryError) as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="workspace creation failed",
        ) from exc
    task = await orchestration_repository.create_task(
        session,
        agent_id=source.agent_id,
        input_text=source.input,
        input_json=source.input_json,
        memory_session_id=memory_session_id,
        user_id=None,
        priority=priority,
        max_attempts=get_settings().task_max_attempts,
        workspace_path=manager.relative(workspace.root),
        internal_session_id=internal_session_id,
        retry_of_execution_id=source.id,
        agent_version_id=source.agent_version_id,
        runtime_type=getattr(source.agent, "runtime_type", "hermes"),
        workspace_type=workspace_type,
    )
    try:
        await queue.enqueue(task.id, task.priority)
    except TaskQueueError as exc:
        task.status = "failed"
        task.error = "task queue unavailable"
        task.session.status = "failed"
        retry = await session.get(ExecutionLog, task.execution_id)
        if retry is not None:
            retry.status = "failed"
            retry.error = "task queue unavailable"
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="task queue unavailable",
        ) from exc
    return TaskRead.model_validate(task)


@router.post("/{execution_id}/stop", response_model=ExecutionStopRead)
async def stop_execution(
    execution_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> ExecutionStopRead:
    execution = await repository.get_execution(session, execution_id)
    if execution is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="execution not found")
    if execution.status != "running":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="only running executions can be stopped")
    runtime_type = getattr(execution, "runtime_type", "hermes")
    runtime_record = (
        await runtime_repository.get_runtime(session, execution.runtime_id)
        if execution.runtime_id is not None
        else await runtime_repository.resolve_runtime(
            session,
            runtime_type=runtime_type,
            runtime_config=getattr(execution.agent, "runtime_config", {}) or {},
        )
    )
    details = execution.details if isinstance(execution.details, dict) else {}
    runtime_run_id = str(details.get("runtime_run_id") or execution.id)
    try:
        await get_runtime_adapter(
            runtime_type,
            endpoint=runtime_record.endpoint if runtime_record is not None else None,
            version=runtime_record.version if runtime_record is not None else None,
            config=runtime_record.config if runtime_record is not None else {},
        ).stop(runtime_run_id)
    except RuntimeAdapterError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Runtime stop failed") from exc

    finished_at = datetime.now(timezone.utc)
    execution.status = "cancelled"
    execution.error = None
    execution.finished_at = finished_at
    execution.duration_ms = max(
        0, int((finished_at - execution.started_at).total_seconds() * 1000)
    )
    if execution.session is not None:
        execution.session.status = "cancelled"
        execution.session.finished_at = finished_at
    task = await repository.get_task_for_execution(session, execution.id)
    if task is not None and task.status in {"pending", "retrying", "running"}:
        task.status = "cancelled"
        task.error = None
        task.finished_at = finished_at
    await session.commit()
    await revoke_execution_capability_token(details)
    await repository.cancel_running_steps(session, execution.id)
    return ExecutionStopRead(
        execution_id=execution.id,
        status="cancelled",
        runtime_type=runtime_type,
        runtime_run_id=runtime_run_id,
    )


def _summary(execution: ExecutionLog) -> ExecutionSummary:
    details = execution.details if isinstance(execution.details, dict) else {}
    mcp_calls = details.get("mcp_calls")
    skills = details.get("skills_loaded")
    memory_scope = details.get("memory_scope")
    input_json = execution.input_json if isinstance(execution.input_json, dict) else {}
    steps = list(getattr(execution, "steps", []) or [])
    task = input_json.get("task") if isinstance(input_json.get("task"), str) else execution.input
    return ExecutionSummary(
        id=execution.id,
        agent_id=execution.agent_id,
        agent_name=getattr(execution.agent, "name", execution.agent_id),
        session_id=execution.session_id,
        memory_session_id=(execution.session.memory_session_id if execution.session else None),
        status=execution.status,
        task=task,
        response_mode=execution.response_mode,
        runtime_type=getattr(execution, "runtime_type", "hermes"),
        runtime_id=getattr(execution, "runtime_id", None),
        runtime_version=getattr(execution, "runtime_version", None),
        priority=execution.priority,
        duration_ms=execution.duration_ms,
        token_usage=execution.token_usage,
        skill_count=len(skills) if isinstance(skills, list) else 0,
        mcp_call_count=len(mcp_calls) if isinstance(mcp_calls, list) else 0,
        memory_read_count=(
            int(memory_scope.get("history_messages_loaded") or 0)
            if isinstance(memory_scope, dict)
            else 0
        ),
        artifact_count=len(execution.artifacts),
        trace_step_count=len(steps),
        failed_step_count=sum(1 for step in steps if step.status == "failed"),
        model_call_count=sum(1 for step in steps if _is_model_call(step)),
        retry_of_execution_id=execution.retry_of_execution_id,
        agent_version_id=getattr(execution, "agent_version_id", None),
        agent_version=(
            execution.agent_version.version
            if getattr(execution, "agent_version", None)
            else None
        ),
        started_at=execution.started_at,
        finished_at=execution.finished_at,
    )


def _trace(execution: ExecutionLog) -> ExecutionTraceRead:
    details = execution.details if isinstance(execution.details, dict) else {}
    steps = list(execution.steps)
    latencies = [int(step.latency_ms) for step in steps if step.latency_ms is not None]
    artifacts = [ArtifactRead.model_validate(item) for item in execution.artifacts]
    return ExecutionTraceRead(
        execution_id=execution.id,
        agent_id=execution.agent_id,
        agent_name=getattr(execution.agent, "name", execution.agent_id),
        agent_version_id=getattr(execution, "agent_version_id", None),
        agent_version=(
            execution.agent_version.version
            if getattr(execution, "agent_version", None)
            else None
        ),
        session_id=execution.session_id,
        memory_session_id=(execution.session.memory_session_id if execution.session else None),
        status=execution.status,
        runtime_type=getattr(execution, "runtime_type", "hermes"),
        runtime_id=getattr(execution, "runtime_id", None),
        runtime_version=getattr(execution, "runtime_version", None),
        model=_text(details.get("model")),
        model_adapter=_text(details.get("model_adapter")),
        token_usage=execution.token_usage,
        duration_ms=execution.duration_ms,
        error=execution.error,
        started_at=execution.started_at,
        finished_at=execution.finished_at,
        nodes=[ExecutionStepRead.model_validate(item) for item in steps],
        artifacts=artifacts,
        metrics=TraceMetrics(
            total_nodes=len(steps),
            failed_nodes=sum(1 for step in steps if step.status == "failed"),
            skill_nodes=sum(1 for step in steps if step.step_type == "skill"),
            mcp_calls=sum(1 for step in steps if _is_mcp_call(step)),
            model_calls=sum(1 for step in steps if _is_model_call(step)),
            artifact_nodes=sum(1 for step in steps if step.step_type == "artifact"),
            total_latency_ms=sum(latencies),
            slowest_node_ms=max(latencies) if latencies else None,
        ),
    )


def _is_mcp_call(step: object) -> bool:
    return getattr(step, "step_type", None) == "mcp" and str(
        getattr(step, "step_key", "")
    ).startswith("mcp_call_")


def _is_model_call(step: object) -> bool:
    step_key = str(getattr(step, "step_key", ""))
    step_name = str(getattr(step, "step_name", ""))
    return getattr(step, "step_type", None) == "runtime" or step_key.startswith(
        ("hermes_runtime", "pi_runtime")
    ) or (getattr(step, "step_type", None) == "model" and "call" in step_name.lower())


def _text(value: object) -> str | None:
    return str(value) if value is not None else None

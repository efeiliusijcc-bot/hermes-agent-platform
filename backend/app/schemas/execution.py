from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.orchestration import ArtifactRead, TaskRead


ExecutionStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]
ExecutionStepStatus = Literal["pending", "running", "succeeded", "failed", "skipped", "cancelled"]
ExecutionStepType = Literal[
    "request", "schema", "memory", "skill", "mcp", "knowledge", "model", "artifact", "runtime",
    "plan", "repository", "code", "test", "git",
]


class ExecutionStepRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    execution_id: UUID
    step_key: str
    sequence: int
    step_type: ExecutionStepType
    step_name: str
    status: ExecutionStepStatus
    input_data: dict[str, Any]
    output_data: dict[str, Any]
    error: str | None
    latency_ms: int | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class ExecutionMetrics(BaseModel):
    total_executions: int
    running: int
    succeeded: int
    failed: int
    cancelled: int
    success_rate: float | None


class ExecutionSummary(BaseModel):
    id: UUID
    agent_id: str
    agent_name: str
    session_id: UUID | None
    memory_session_id: str | None
    status: ExecutionStatus
    task: str
    response_mode: Literal["sync", "stream", "async"]
    runtime_type: Literal["hermes", "pi", "deepseek"]
    runtime_id: UUID | None
    runtime_version: str | None
    priority: int | None
    duration_ms: int | None
    token_usage: int | None
    skill_count: int
    mcp_call_count: int
    memory_read_count: int
    artifact_count: int
    trace_step_count: int
    failed_step_count: int
    model_call_count: int
    retry_of_execution_id: UUID | None
    agent_version_id: UUID | None
    agent_version: str | None
    started_at: datetime
    finished_at: datetime | None


class ExecutionListRead(BaseModel):
    items: list[ExecutionSummary]
    total: int
    limit: int
    offset: int
    metrics: ExecutionMetrics


class ExecutionDetail(ExecutionSummary):
    input: str
    input_json: dict[str, Any]
    output: str | None
    output_json: Any | None
    error: str | None
    details: dict[str, Any]
    model: str | None
    model_adapter: str | None
    schema_version: str | None
    steps: list[ExecutionStepRead]
    artifacts: list[ArtifactRead]
    queue_task: TaskRead | None


class TraceMetrics(BaseModel):
    total_nodes: int
    failed_nodes: int
    history_messages_loaded: int
    skill_nodes: int
    mcp_calls: int
    model_calls: int
    artifact_nodes: int
    total_latency_ms: int
    slowest_node_ms: int | None


class ExecutionTraceRead(BaseModel):
    execution_id: UUID
    agent_id: str
    agent_name: str
    agent_version_id: UUID | None
    agent_version: str | None
    session_id: UUID | None
    memory_session_id: str | None
    status: ExecutionStatus
    runtime_type: Literal["hermes", "pi", "deepseek"]
    runtime_id: UUID | None
    runtime_version: str | None
    model: str | None
    model_adapter: str | None
    token_usage: int | None
    duration_ms: int | None
    error: str | None
    started_at: datetime
    finished_at: datetime | None
    nodes: list[ExecutionStepRead]
    artifacts: list[ArtifactRead]
    metrics: TraceMetrics


class ExecutionRetryRequest(BaseModel):
    session_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    priority: int | None = Field(default=None, ge=0, le=9)


class ExecutionStopRead(BaseModel):
    execution_id: UUID
    status: Literal["cancelled"]
    runtime_type: Literal["hermes", "pi", "deepseek"]
    runtime_run_id: str

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator

from . import __version__
from .harness import (
    HarnessCancelledError,
    HarnessProcess,
    HarnessProtocolError,
    HarnessResult,
    HarnessTransportError,
    _runtime_launch,
)


logger = logging.getLogger("deepseek-runtime")
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
TOOL_ALIAS = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,127}$")
TEST_COMMAND = re.compile(
    r"(?:^|[;&|]\s*|\s)(pytest|python\s+-m\s+(?:pytest|unittest)|npm\s+(?:run\s+)?test|pnpm\s+(?:run\s+)?test|yarn\s+test|go\s+test|cargo\s+test|mvn\s+test|gradle\s+test)(?:\s|$)",
    re.IGNORECASE,
)
SCAN_COMMAND = re.compile(
    r"(?:^|[;&|]\s*|\s)(rg|grep|find|fd|ls|tree|cat|sed|head|tail)(?:\s|$)",
    re.IGNORECASE,
)
GIT_COMMAND = re.compile(r"(?:^|[;&|]\s*|\s)git\s+(diff|status|show|log)(?:\s|$)", re.IGNORECASE)


def _secret(name: str) -> str:
    value = os.getenv(name, "")
    if len(value) < 32:
        raise RuntimeError(f"{name} must contain at least 32 characters")
    return value


def _integer(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    value = default if raw in {None, ""} else int(raw)
    if value < minimum or value > maximum:
        raise RuntimeError(f"{name} must be between {minimum} and {maximum}")
    return value


def _http_url(name: str, value: str) -> str:
    normalized = value.rstrip("/")
    authority = normalized.split("//", 1)[-1].split("/", 1)[0]
    if not normalized.startswith(("http://", "https://")) or "@" in authority:
        raise RuntimeError(f"{name} must be an HTTP(S) URL without embedded credentials")
    return normalized


class RuntimeMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str = Field(min_length=1, max_length=1_000_000)


class SessionCreate(BaseModel):
    agent_id: str = Field(min_length=1, max_length=128)
    execution_id: str = Field(min_length=1, max_length=128)
    metadata: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)


class RuntimeExecution(BaseModel):
    messages: list[RuntimeMessage] = Field(min_length=1, max_length=200)
    model: str = Field(min_length=1, max_length=255)
    model_adapter: str = Field(default="hermes", max_length=64)
    agent_id: str = Field(min_length=1, max_length=128)
    execution_id: str = Field(min_length=1, max_length=128)
    options: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)

    @field_validator("execution_id")
    @classmethod
    def safe_execution_id(cls, value: str) -> str:
        if not SAFE_ID.fullmatch(value):
            raise ValueError("execution_id contains unsupported characters")
        return value


@dataclass(frozen=True)
class Settings:
    api_key: str | None
    workspace_root: Path
    session_root: Path
    model_base_url: str
    model_api_key: str
    capability_gateway_endpoint: str
    provider: str
    runtime_bin: str | None
    cordis_config: str | None
    max_concurrency: int
    queue_timeout_seconds: float
    request_timeout_seconds: float
    max_output_tokens: int
    max_artifact_bytes: int
    max_request_bytes: int
    max_sessions: int
    session_ttl_seconds: int
    execution_uid_min: int
    execution_uid_max: int

    @classmethod
    def load(cls) -> "Settings":
        raw_api_key = os.getenv("DEEPSEEK_RUNTIME_API_KEY", "")
        api_key = _secret("DEEPSEEK_RUNTIME_API_KEY") if raw_api_key else None
        model_api_key = os.getenv("DEEPSEEK_MODEL_PROXY_TOKEN", "proxy-transport-only")
        workspace_root = Path(os.getenv("WORKSPACE_ROOT", "/data/workspaces")).resolve()
        session_root = Path(os.getenv("DEEPSEEK_SESSION_ROOT", "/data/deepseek-sessions")).resolve()
        workspace_root.mkdir(parents=True, exist_ok=True)
        session_root.mkdir(parents=True, exist_ok=True)
        return cls(
            api_key=api_key,
            workspace_root=workspace_root,
            session_root=session_root,
            model_base_url=_http_url(
                "MODEL_GATEWAY_ENDPOINT",
                os.getenv(
                    "MODEL_GATEWAY_ENDPOINT",
                    "http://deepseek-runtime:8770/model/v1",
                ),
            ),
            model_api_key=model_api_key,
            capability_gateway_endpoint=_http_url(
                "CAPABILITY_GATEWAY_ENDPOINT",
                os.getenv(
                    "CAPABILITY_GATEWAY_ENDPOINT",
                    "http://deepseek-runtime:8770/capability/invoke",
                ),
            ),
            provider=os.getenv("DEEPSEEK_HARNESS_PROVIDER", "deepseek-official"),
            runtime_bin=os.getenv("DEEPSEEK_HARNESS_RUNTIME_BIN") or None,
            cordis_config=os.getenv("DEEPSEEK_HARNESS_CORDIS_CONFIG") or None,
            max_concurrency=_integer("DEEPSEEK_RUNTIME_MAX_CONCURRENCY", 2, 1, 32),
            queue_timeout_seconds=float(_integer("DEEPSEEK_RUNTIME_QUEUE_TIMEOUT_SECONDS", 60, 1, 1800)),
            request_timeout_seconds=float(_integer("DEEPSEEK_RUNTIME_REQUEST_TIMEOUT_SECONDS", 900, 10, 7200)),
            max_output_tokens=_integer("DEEPSEEK_RUNTIME_MAX_OUTPUT_TOKENS", 8192, 128, 131072),
            max_artifact_bytes=_integer("DEEPSEEK_RUNTIME_MAX_ARTIFACT_BYTES", 2_097_152, 1024, 20_971_520),
            max_request_bytes=_integer("DEEPSEEK_RUNTIME_REQUEST_MAX_BYTES", 2_097_152, 1024, 20_971_520),
            max_sessions=_integer("DEEPSEEK_RUNTIME_MAX_SESSIONS", 1000, 1, 10000),
            session_ttl_seconds=_integer("DEEPSEEK_RUNTIME_SESSION_TTL_SECONDS", 1800, 60, 86400),
            execution_uid_min=_integer("DEEPSEEK_RUNTIME_EXECUTION_UID_MIN", 20000, 10000, 60000),
            execution_uid_max=_integer("DEEPSEEK_RUNTIME_EXECUTION_UID_MAX", 60000, 20000, 65533),
        )


@dataclass
class RuntimeSessionState:
    id: str
    context: dict[str, Any]
    created_at: float = field(default_factory=time.monotonic)
    last_used_at: float = field(default_factory=time.monotonic)


@dataclass
class ActiveRun:
    id: str
    session_id: str
    process: HarnessProcess | None = None
    cancelled: bool = False


class EventCollector:
    def __init__(self, run_id: str, emit: Callable[[dict[str, Any]], Awaitable[None]] | None) -> None:
        self.run_id = run_id
        self.emit = emit
        self.trace: list[dict[str, Any]] = []
        self.calls: dict[str, dict[str, Any]] = {}
        self.test_report: list[str] = []

    async def consume(self, raw: dict[str, Any]) -> None:
        raw_type = str(raw.get("type") or "")
        data = raw.get("data") if isinstance(raw.get("data"), dict) else {}
        event: dict[str, Any] | None = None
        if raw_type == "turn/start":
            event = self._event("start", "running")
        elif raw_type == "request/header":
            event = self._event("plan", "succeeded")
        elif raw_type == "assistant/chunk":
            chunk = data.get("chunk") if isinstance(data.get("chunk"), dict) else {}
            if chunk.get("type") == "text-delta" and isinstance(chunk.get("text"), str):
                event = {"event": "message.delta", "run_id": self.run_id, "delta": chunk["text"]}
        elif raw_type == "assistant/message":
            event = self._event("model_call", "succeeded")
        elif raw_type == "tool/call":
            call_id = str(data.get("callId") or "")
            arguments = _json_object(data.get("arguments"))
            command = str(arguments.get("command") or "")
            event_type = _tool_event_type(str(data.get("name") or ""), command)
            self.calls[call_id] = {
                "type": event_type,
                "name": str(data.get("name") or "tool"),
                "command": command,
            }
            event = self._event(
                event_type,
                "running",
                tool=str(data.get("name") or "tool"),
                input=arguments,
            )
            if event_type == "test_run":
                self.test_report.append(f"$ {command}")
        elif raw_type == "tool/result":
            call_id, output, failed = _tool_result(data)
            call = self.calls.get(call_id, {})
            event_type = str(call.get("type") or "tool_call")
            event = self._event(
                event_type,
                "failed" if failed else "succeeded",
                tool=str(call.get("name") or "tool"),
                output=output[:16_000],
            )
            if event_type == "test_run":
                self.test_report.append(output[:200_000])
                self.test_report.append("status: failed" if failed else "status: succeeded")
        elif raw_type == "turn/end":
            reason = data.get("reason") if isinstance(data.get("reason"), dict) else {}
            kind = str(reason.get("kind") or "completed")
            event = self._event("end", "failed" if kind == "error" else "succeeded", reason=kind)
        if event is None:
            return
        if event.get("event") != "message.delta":
            self.trace.append(event)
        if self.emit is not None:
            await self.emit(event)

    def _event(self, event: str, status_value: str, **values: Any) -> dict[str, Any]:
        return {"event": event, "run_id": self.run_id, "runtime": "deepseek", "status": status_value, **values}


class RuntimeManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.sessions: dict[str, RuntimeSessionState] = {}
        self.runs: dict[str, ActiveRun] = {}
        self.pending_stops: dict[str, float] = {}
        self.lock = asyncio.Lock()
        self.gate = asyncio.Semaphore(settings.max_concurrency)

    async def create_session(self, payload: SessionCreate) -> RuntimeSessionState:
        async with self.lock:
            self._clean_sessions()
            session_id = str(uuid4())
            value = RuntimeSessionState(id=session_id, context=_session_context(payload.context))
            self.sessions[session_id] = value
            return value

    async def run(
        self,
        session_id: str,
        payload: RuntimeExecution,
        *,
        emit: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
        workspace = self._workspace(payload.context)
        session = await self._session(session_id, payload.context)
        run_id = payload.execution_id
        run = ActiveRun(id=run_id, session_id=session_id)
        async with self.lock:
            if run_id in self.runs:
                raise HTTPException(status_code=409, detail="execution id is already active")
            if any(value.session_id == session_id for value in self.runs.values()):
                raise HTTPException(status_code=409, detail="Runtime session already has an active execution")
            if self.pending_stops.pop(run_id, 0) > time.monotonic():
                run.cancelled = True
            self.runs[run_id] = run
        acquired = False
        process: HarnessProcess | None = None
        try:
            if run.cancelled:
                raise HarnessCancelledError("DeepSeek Harness execution was cancelled")
            try:
                await asyncio.wait_for(self.gate.acquire(), timeout=self.settings.queue_timeout_seconds)
                acquired = True
            except TimeoutError as exc:
                raise HTTPException(status_code=503, detail="DeepSeek Runtime concurrency queue timed out") from exc
            if run.cancelled:
                raise HarnessCancelledError("DeepSeek Harness execution was cancelled")
            system_prompt, prompt = _split_messages(payload.messages)
            max_tokens = payload.options.get("max_tokens", self.settings.max_output_tokens)
            if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or not 128 <= max_tokens <= 131072:
                raise HTTPException(status_code=422, detail="options.max_tokens is invalid")
            execution_uid = await self._execution_uid(workspace)
            capability_token, capability_tools = _capability_context(payload.context)
            process = HarnessProcess(
                cwd=workspace,
                session_root=self.settings.session_root / session.id,
                provider=self.settings.provider,
                model=payload.model,
                max_tokens=max_tokens,
                system_prompt=system_prompt,
                base_url=self.settings.model_base_url,
                api_key=self.settings.model_api_key,
                request_timeout_seconds=self.settings.request_timeout_seconds,
                runtime_bin=self.settings.runtime_bin,
                cordis_config=self.settings.cordis_config,
                execution_uid=execution_uid,
                capability_gateway_endpoint=self.settings.capability_gateway_endpoint,
                capability_token=capability_token,
                capability_tools=capability_tools,
                execution_id=run_id,
            )
            run.process = process
            collector = EventCollector(run_id, emit)
            result = await process.run(session_id=session.id, prompt=prompt, on_event=collector.consume)
            if result.finish_reason == "error":
                suffix = f": {result.error_detail}" if result.error_detail else ""
                raise HarnessProtocolError(f"DeepSeek Harness turn ended with an error{suffix}")
            if not result.output:
                raise HarnessProtocolError("DeepSeek Harness completed without text output")
            artifacts = await _collect_artifacts(
                workspace,
                test_report=collector.test_report,
                maximum_bytes=self.settings.max_artifact_bytes,
            )
            if artifacts:
                artifact_event = {
                    "event": "artifact",
                    "run_id": run_id,
                    "runtime": "deepseek",
                    "status": "succeeded",
                    "artifacts": [value["filename"] for value in artifacts],
                }
                collector.trace.append(artifact_event)
                if emit is not None:
                    await emit(artifact_event)
            return {
                "run_id": run_id,
                "status": "completed",
                "output": result.output,
                "finish_reason": result.finish_reason,
                "usage": {"total_tokens": result.token_usage} if result.token_usage is not None else {},
                "trace": collector.trace[:500],
                "artifacts": artifacts,
            }
        finally:
            if process is not None:
                await process.close()
            if acquired:
                self.gate.release()
            session.last_used_at = time.monotonic()
            async with self.lock:
                self.runs.pop(run_id, None)

    async def stop(self, run_id: str) -> dict[str, str]:
        async with self.lock:
            run = self.runs.get(run_id)
            if run is None:
                self._clean_pending_stops()
                self.pending_stops[run_id] = time.monotonic() + 30
                return {"run_id": run_id, "status": "cancelling"}
            run.cancelled = True
            process = run.process
        if process is not None:
            await process.cancel()
        return {"run_id": run_id, "status": "cancelling"}

    async def _session(self, session_id: str, context: dict[str, Any]) -> RuntimeSessionState:
        if not SAFE_ID.fullmatch(session_id):
            raise HTTPException(status_code=422, detail="invalid Runtime session id")
        async with self.lock:
            value = self.sessions.get(session_id)
            if value is None:
                self._clean_sessions()
                value = RuntimeSessionState(id=session_id, context=_session_context(context))
                self.sessions[session_id] = value
            elif _session_identity(value.context) != _session_identity(context):
                raise HTTPException(
                    status_code=409,
                    detail="Runtime session context does not match its original workspace",
                )
            value.last_used_at = time.monotonic()
            return value

    def _workspace(self, context: dict[str, Any]) -> Path:
        if context.get("workspace_type") != "repository":
            raise HTTPException(status_code=422, detail="DeepSeek Runtime requires a repository workspace")
        raw = context.get("workspace")
        if not isinstance(raw, str) or not raw:
            raise HTTPException(status_code=422, detail="repository workspace is required")
        value = Path(raw).resolve()
        try:
            value.relative_to(self.settings.workspace_root)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="repository workspace escapes the configured root") from exc
        if not value.is_dir():
            raise HTTPException(status_code=422, detail="repository workspace does not exist")
        return value

    async def _execution_uid(self, workspace: Path) -> int:
        async with self.lock:
            return await asyncio.to_thread(
                _assign_workspace_owner,
                workspace,
                self.settings.workspace_root,
                self.settings.execution_uid_min,
                self.settings.execution_uid_max,
            )

    def _clean_sessions(self) -> None:
        threshold = time.monotonic() - self.settings.session_ttl_seconds
        stale = [key for key, value in self.sessions.items() if value.last_used_at < threshold]
        for key in stale:
            self.sessions.pop(key, None)
        while len(self.sessions) >= self.settings.max_sessions:
            oldest = min(self.sessions.values(), key=lambda item: item.last_used_at)
            self.sessions.pop(oldest.id, None)

    def _clean_pending_stops(self) -> None:
        now = time.monotonic()
        for key in [key for key, expires_at in self.pending_stops.items() if expires_at <= now]:
            self.pending_stops.pop(key, None)


def _session_context(context: dict[str, Any]) -> dict[str, Any]:
    """Keep durable Runtime session identity without per-execution authority."""
    value = dict(context)
    value.pop("capability_token", None)
    value.pop("capability_tools", None)
    metadata = value.get("metadata")
    if isinstance(metadata, dict):
        sanitized = dict(metadata)
        sanitized.pop("capability_token", None)
        sanitized.pop("capability_tools", None)
        value["metadata"] = sanitized
    return value


def _capability_context(context: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    metadata = context.get("metadata") if isinstance(context.get("metadata"), dict) else {}
    raw_tools = context.get("capability_tools")
    if not isinstance(raw_tools, list):
        raw_tools = metadata.get("capability_tools")
    tools = [item for item in (raw_tools or []) if isinstance(item, dict)]
    if len(tools) > 100:
        raise HTTPException(status_code=422, detail="too many Capability tools")
    for tool in tools:
        name = tool.get("tool_name")
        schema = tool.get("input_schema")
        if not isinstance(name, str) or not TOOL_ALIAS.fullmatch(name) or not isinstance(schema, dict):
            raise HTTPException(status_code=422, detail="invalid Capability tool contract")
    raw_token = context.get("capability_token") or metadata.get("capability_token") or ""
    token = raw_token if isinstance(raw_token, str) else ""
    if tools and not token:
        raise HTTPException(status_code=422, detail="Capability Token is required")
    return token, tools


settings = Settings.load()
manager = RuntimeManager(settings)
app = FastAPI(title="Hermes DeepSeek Runtime Bridge", version=__version__)


@app.middleware("http")
async def request_size_guard(request: Request, call_next):
    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > settings.max_request_bytes:
        return JSONResponse(status_code=413, content={"detail": "request body is too large"})
    return await call_next(request)


@app.get("/health")
async def health() -> dict[str, Any]:
    try:
        args, _ = _runtime_launch(settings.runtime_bin)
        runtime_path = Path(args[-1] if len(args) > 1 else args[0])
        if not runtime_path.is_file():
            raise FileNotFoundError(str(runtime_path))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="official DeepSeek Harness runtime is unavailable") from exc
    return {
        "status": "ready",
        "version": __version__,
        "harness_version": "0.1.0-rc.6",
        "protocol": "json-rpc-2.0-stdio",
        "active_runs": len(manager.runs),
    }


@app.post("/sessions", status_code=status.HTTP_201_CREATED)
async def create_session(payload: SessionCreate, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    _authorize(authorization)
    value = await manager.create_session(payload)
    return {"id": value.id, "runtime_type": "deepseek"}


@app.post("/sessions/{session_id}/execute")
async def execute(
    session_id: str,
    payload: RuntimeExecution,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _authorize(authorization)
    try:
        return await manager.run(session_id, payload)
    except HarnessCancelledError:
        return JSONResponse(status_code=409, content={"run_id": payload.execution_id, "status": "cancelled"})
    except (HarnessProtocolError, HarnessTransportError) as exc:
        logger.exception("DeepSeek Harness execution failed")
        raise HTTPException(status_code=502, detail="DeepSeek Harness execution failed") from exc


@app.post("/sessions/{session_id}/stream")
async def stream(
    session_id: str,
    payload: RuntimeExecution,
    authorization: str | None = Header(default=None),
) -> StreamingResponse:
    _authorize(authorization)

    async def events() -> AsyncIterator[str]:
        queue: asyncio.Queue[dict[str, Any] | BaseException | None] = asyncio.Queue()

        async def emit(event: dict[str, Any]) -> None:
            await queue.put(event)

        async def run() -> None:
            try:
                result = await manager.run(session_id, payload, emit=emit)
                await queue.put({"event": "run.completed", **result})
            except HarnessCancelledError:
                await queue.put({"event": "run.cancelled", "run_id": payload.execution_id, "status": "cancelled"})
            except BaseException as exc:
                await queue.put(exc)
            finally:
                await queue.put(None)

        task = asyncio.create_task(run())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                if isinstance(item, BaseException):
                    logger.exception("DeepSeek Harness stream failed", exc_info=item)
                    yield _sse({"event": "run.failed", "run_id": payload.execution_id, "error": "DeepSeek Harness execution failed"})
                    break
                yield _sse(item)
        finally:
            if not task.done():
                await manager.stop(payload.execution_id)
            await asyncio.gather(task, return_exceptions=True)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-store", "X-Accel-Buffering": "no"},
    )


@app.post("/stop/{run_id}")
@app.post("/runs/{run_id}/stop")
async def stop(run_id: str, authorization: str | None = Header(default=None)) -> dict[str, str]:
    _authorize(authorization)
    if not SAFE_ID.fullmatch(run_id):
        raise HTTPException(status_code=422, detail="invalid Runtime run id")
    return await manager.stop(run_id)


def _authorize(authorization: str | None) -> None:
    if settings.api_key is None:
        return
    expected = f"Bearer {settings.api_key}"
    if authorization is None or not hmac.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="invalid DeepSeek Runtime key")


def _split_messages(messages: list[RuntimeMessage]) -> tuple[str, str]:
    system_parts = [message.content for message in messages if message.role == "system"]
    system_prompt = "\n\n".join(system_parts).strip() or "You are a coding agent."
    prompt_parts = [
        f"{message.role.upper()}:\n{message.content}"
        for message in messages
        if message.role != "system"
    ]
    return system_prompt, "\n\n".join(prompt_parts) or "Complete the requested coding task."


def _tool_event_type(name: str, command: str) -> str:
    normalized = name.lower()
    if normalized in {"write", "edit", "str_replace_editor"}:
        return "code_edit"
    if TEST_COMMAND.search(command):
        return "test_run"
    if GIT_COMMAND.search(command):
        return "git_diff"
    if normalized in {"read", "view", "search"} or SCAN_COMMAND.search(command):
        return "repository_scan"
    return "tool_call"


def _tool_result(data: dict[str, Any]) -> tuple[str, str, bool]:
    message = data.get("message") if isinstance(data.get("message"), dict) else {}
    source = message.get("source") if isinstance(message.get("source"), dict) else {}
    call_id = str(source.get("callId") or "")
    output_parts: list[str] = []
    failed = False
    for block in message.get("content") if isinstance(message.get("content"), list) else []:
        if not isinstance(block, dict) or block.get("type") != "tool-result":
            continue
        failed = failed or bool(block.get("isError"))
        for item in block.get("content") if isinstance(block.get("content"), list) else []:
            if isinstance(item, dict) and item.get("type") == "text":
                output_parts.append(str(item.get("text") or ""))
    return call_id, "\n".join(output_parts), failed


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


def _session_identity(context: dict[str, Any]) -> tuple[str, ...]:
    return tuple(
        str(context.get(key) or "")
        for key in ("agent_id", "session_id", "workspace", "workspace_type", "memory_namespace")
    )


def _assign_workspace_owner(
    workspace: Path,
    workspace_root: Path,
    uid_min: int,
    uid_max: int,
) -> int:
    if uid_min > uid_max:
        raise RuntimeError("DeepSeek execution UID range is invalid")
    workspace = workspace.resolve()
    workspace_root = workspace_root.resolve()
    current_uid = workspace.stat().st_uid
    used = {
        path.stat().st_uid
        for path in workspace_root.glob("*/sessions/*/repository")
        if path.is_dir() and uid_min <= path.stat().st_uid <= uid_max and path.resolve() != workspace
    }
    if uid_min <= current_uid <= uid_max and current_uid not in used:
        selected_uid = current_uid
    else:
        selected_uid = next((uid for uid in range(uid_min, uid_max + 1) if uid not in used), -1)
        if selected_uid < 0:
            raise RuntimeError("DeepSeek execution UID pool is exhausted")
    _make_workspace_parents_traversable(workspace, workspace_root)
    _chown_repository(workspace, selected_uid)
    return selected_uid


def _make_workspace_parents_traversable(workspace: Path, workspace_root: Path) -> None:
    current = workspace.parent
    while True:
        current.chmod(current.stat().st_mode | 0o001)
        if current == workspace_root:
            return
        current = current.parent


def _chown_repository(workspace: Path, uid: int) -> None:
    for current, directory_names, filenames in os.walk(workspace, followlinks=False):
        current_path = Path(current)
        os.chown(current_path, uid, uid)
        current_path.chmod(0o700)
        for name in directory_names:
            path = current_path / name
            if path.is_symlink():
                os.chown(path, uid, uid, follow_symlinks=False)
        for name in filenames:
            path = current_path / name
            if path.is_symlink():
                os.chown(path, uid, uid, follow_symlinks=False)
                continue
            executable = bool(path.stat().st_mode & 0o111)
            os.chown(path, uid, uid)
            path.chmod(0o700 if executable else 0o600)


async def _collect_artifacts(
    workspace: Path,
    *,
    test_report: list[str],
    maximum_bytes: int,
) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    if (workspace / ".git").exists():
        diff = await _git_diff(workspace, maximum_bytes)
        if diff:
            artifacts.extend(
                [
                    {
                        "filename": "changes.patch",
                        "artifact_type": "code_patch",
                        "content_type": "text/x-diff; charset=utf-8",
                        "content": diff,
                    },
                    {
                        "filename": "git-diff.patch",
                        "artifact_type": "git_diff",
                        "content_type": "text/x-diff; charset=utf-8",
                        "content": diff,
                    },
                ]
            )
    report = "\n\n".join(value for value in test_report if value).strip()
    if report:
        artifacts.append(
            {
                "filename": "test-report.txt",
                "artifact_type": "test_report",
                "content_type": "text/plain; charset=utf-8",
                "content": report.encode()[:maximum_bytes].decode(errors="replace"),
            }
        )
    return artifacts


async def _git_diff(workspace: Path, maximum_bytes: int) -> str:
    tracked = await _git_output(
        workspace,
        maximum_bytes,
        "git",
        "-c",
        "diff.external=",
        "diff",
        "--no-ext-diff",
        "--no-textconv",
        "--binary",
        "--no-color",
        accepted_return_codes={0},
    )
    remaining = maximum_bytes - len(tracked)
    if remaining <= 0:
        return tracked[:maximum_bytes].decode(errors="replace")

    untracked = await _git_output(
        workspace,
        maximum_bytes,
        "git",
        "ls-files",
        "--others",
        "--exclude-standard",
        "-z",
        accepted_return_codes={0},
    )
    patches = [tracked]
    for raw_path in untracked.split(b"\0"):
        if not raw_path:
            continue
        relative_path = os.fsdecode(raw_path)
        candidate = (workspace / relative_path).resolve()
        try:
            candidate.relative_to(workspace.resolve())
        except ValueError:
            continue
        if not candidate.is_file():
            continue
        remaining = maximum_bytes - sum(len(value) for value in patches)
        if remaining <= 0:
            break
        patch = await _git_output(
            workspace,
            remaining,
            "git",
            "-c",
            "diff.external=",
            "diff",
            "--no-index",
            "--no-ext-diff",
            "--no-textconv",
            "--binary",
            "--no-color",
            "--",
            "/dev/null",
            relative_path,
            accepted_return_codes={0, 1},
        )
        if patch:
            patches.append(patch)
    return b"".join(patches)[:maximum_bytes].decode(errors="replace")


async def _git_output(
    workspace: Path,
    maximum_bytes: int,
    *args: str,
    accepted_return_codes: set[int],
) -> bytes:
    command = args
    if args and args[0] == "git":
        command = (
            "git",
            "-c",
            f"safe.directory={workspace.resolve()}",
            *args[1:],
        )
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=str(workspace),
        env={**os.environ, "GIT_EXTERNAL_DIFF": ""},
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=30)
    except TimeoutError:
        process.kill()
        await process.wait()
        return b""
    if process.returncode not in accepted_return_codes:
        return b""
    return stdout[:maximum_bytes]


def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False, separators=(',', ':'))}\n\n"

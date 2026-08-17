from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
from fastapi import status

from app.config import get_settings
from app.runtime.base import (
    RuntimeAdapter,
    RuntimeAdapterError,
    RuntimeCancelledError,
    RuntimeContext,
    RuntimeHealth,
    RuntimeSession,
)
from app.runtime.hermes import HermesRunResult, RuntimeArtifact


class PiRuntimeAdapter(RuntimeAdapter):
    """HTTP adapter for an optional, separately deployed Pi Agent Runtime."""

    runtime_type = "pi"
    runtime_label = "Pi"

    def __init__(
        self,
        *,
        endpoint: str | None = None,
        version: str | None = None,
        config: dict[str, Any] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        settings = get_settings()
        configured_endpoint = endpoint or self._default_endpoint(settings)
        if not configured_endpoint:
            raise RuntimeAdapterError(f"{self.runtime_label} Runtime endpoint is not configured")
        self.endpoint = configured_endpoint.rstrip("/")
        self.version = version
        self.config = config or {}
        configured_timeout = self.config.get("timeout_seconds")
        self.timeout = (
            float(configured_timeout)
            if isinstance(configured_timeout, (int, float)) and not isinstance(configured_timeout, bool)
            else self._default_timeout(settings)
        )
        self.transport = transport
        self.api_key = self._default_api_key(settings)

    async def create_session(
        self,
        *,
        agent_id: str,
        execution_id: str,
        metadata: dict[str, Any] | None = None,
        context: RuntimeContext | None = None,
    ) -> RuntimeSession:
        payload = await self._request(
            "POST",
            "/sessions",
            json={
                "agent_id": agent_id,
                "execution_id": execution_id,
                "metadata": metadata or {},
                "context": context.as_dict() if context else {},
            },
        )
        session_id = payload.get("id") or payload.get("session_id")
        if not session_id:
            raise RuntimeAdapterError(f"{self.runtime_label} Runtime did not return a session id")
        return RuntimeSession(id=str(session_id), runtime_type=self.runtime_type)

    async def execute(
        self,
        messages: list[dict[str, str]],
        *,
        session_id: str,
        model: str,
        model_adapter: str,
        agent_id: str,
        execution_id: str,
        runtime_options: dict[str, Any] | None = None,
        context: RuntimeContext | None = None,
    ) -> HermesRunResult:
        payload = await self._request(
            "POST",
            f"/sessions/{session_id}/execute",
            json={
                "messages": messages,
                "model": model,
                "model_adapter": model_adapter,
                "agent_id": agent_id,
                "execution_id": execution_id,
                "options": runtime_options or {},
                "context": context.as_dict() if context else {},
            },
        )
        output = payload.get("output") or payload.get("output_text") or payload.get("result")
        if not isinstance(output, str):
            raise RuntimeAdapterError(f"{self.runtime_label} Runtime did not return text output")
        usage = payload.get("usage")
        token_usage = usage.get("total_tokens") if isinstance(usage, dict) else None
        if isinstance(token_usage, bool) or not isinstance(token_usage, int):
            token_usage = None
        raw_trace = payload.get("trace") or payload.get("events") or []
        trace = tuple(item for item in raw_trace if isinstance(item, dict)) if isinstance(raw_trace, list) else ()
        return HermesRunResult(
            output=output,
            run_id=str(payload.get("run_id") or payload.get("id") or "") or None,
            status=str(payload.get("status") or "completed"),
            token_usage=token_usage,
            trace=trace[:500],
            artifacts=self.result_artifacts(payload),
        )

    async def stream(
        self,
        messages: list[dict[str, str]],
        *,
        session_id: str,
        model: str,
        model_adapter: str,
        agent_id: str,
        execution_id: str,
        runtime_options: dict[str, Any] | None = None,
        context: RuntimeContext | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        timeout = httpx.Timeout(self.timeout + 10, connect=10)
        try:
            async with httpx.AsyncClient(timeout=timeout, transport=self.transport) as client:
                async with client.stream(
                    "POST",
                    f"{self.endpoint}/sessions/{session_id}/stream",
                    headers=self._headers(),
                    json={
                        "messages": messages,
                        "model": model,
                        "model_adapter": model_adapter,
                        "agent_id": agent_id,
                        "execution_id": execution_id,
                        "options": runtime_options or {},
                        "context": context.as_dict() if context else {},
                    },
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        raw = line[5:].strip()
                        if not raw:
                            continue
                        if raw == "[DONE]":
                            yield {"event": "run.completed"}
                            continue
                        event = json.loads(raw)
                        if not isinstance(event, dict):
                            raise RuntimeAdapterError(
                                f"{self.runtime_label} Runtime returned a non-object event"
                            )
                        yield self._normalize_event(event)
        except (httpx.HTTPError, ValueError) as exc:
            raise RuntimeAdapterError(f"{self.runtime_label} Runtime stream failed: {exc}") from exc

    async def stop(self, run_id: str) -> None:
        try:
            await self._request("POST", f"/stop/{run_id}")
        except RuntimeAdapterError as exc:
            if "404" not in str(exc):
                raise
            await self._request("POST", f"/runs/{run_id}/stop")

    async def health_check(self) -> RuntimeHealth:
        health_path = str(self.config.get("health_path") or "/health")
        payload = await self._request("GET", health_path)
        status = str(payload.get("status") or "ok").lower()
        if status not in {"ok", "online", "healthy", "ready"}:
            raise RuntimeAdapterError(f"{self.runtime_label} Runtime is not healthy: {status}")
        version = payload.get("version") or self.version
        return RuntimeHealth(
            status="online",
            version=str(version) if version else None,
            detail=f"{self.runtime_label} Runtime is online",
        )

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
                response = await client.request(
                    method, f"{self.endpoint}{path}", headers=self._headers(), **kwargs
                )
                if response.status_code == status.HTTP_409_CONFLICT:
                    cancelled = response.json()
                    if isinstance(cancelled, dict) and cancelled.get("status") == "cancelled":
                        raise RuntimeCancelledError(
                            f"{self.runtime_label} Runtime execution was cancelled"
                        )
                response.raise_for_status()
                payload = response.json()
        except RuntimeCancelledError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            suffix = f" ({status_code})" if status_code else ""
            raise RuntimeAdapterError(
                f"{self.runtime_label} Runtime request failed{suffix}: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise RuntimeAdapterError(f"{self.runtime_label} Runtime returned a non-object response")
        return payload

    def result_artifacts(self, payload: dict[str, Any]) -> tuple[RuntimeArtifact, ...]:
        return ()

    @staticmethod
    def _default_endpoint(settings: Any) -> str | None:
        return settings.pi_runtime_endpoint

    @staticmethod
    def _default_timeout(settings: Any) -> float:
        return settings.pi_runtime_timeout_seconds

    @staticmethod
    def _default_api_key(settings: Any) -> str | None:
        return (
            settings.pi_runtime_api_key.get_secret_value()
            if settings.pi_runtime_api_key is not None
            else None
        )

    @staticmethod
    def _normalize_event(event: dict[str, Any]) -> dict[str, Any]:
        event_type = str(event.get("event") or event.get("type") or "").lower()
        normalized = dict(event)
        if event_type in {"token", "delta", "message", "message_delta"}:
            normalized["event"] = "message.delta"
            normalized["delta"] = str(event.get("delta") or event.get("text") or "")
        elif event_type in {"completed", "complete", "done", "success"}:
            normalized["event"] = "run.completed"
            normalized.setdefault(
                "output",
                event.get("output_text") or event.get("result") or event.get("text"),
            )
        elif event_type in {"failed", "error"}:
            normalized["event"] = "run.failed"
        elif event_type in {"cancelled", "canceled"}:
            normalized["event"] = "run.cancelled"
        elif event_type in {"tool_call", "tool.started", "tool_start"}:
            normalized["event"] = "tool.started"
            normalized.setdefault("tool", event.get("name"))
        elif event_type in {"tool_result", "tool.completed", "tool_end"}:
            normalized["event"] = "tool.completed"
            normalized.setdefault("tool", event.get("name"))
        elif not event_type:
            normalized["event"] = "runtime.event"
        else:
            normalized["event"] = event_type
        return normalized

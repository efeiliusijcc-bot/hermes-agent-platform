from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
from urllib.parse import urljoin

from app.model_adapters import get_model_adapter
from app.config import get_settings
from app.runtime.base import (
    RuntimeAdapter,
    RuntimeAdapterError,
    RuntimeContext,
    RuntimeHealth,
    RuntimeSession,
)
from app.runtime.hermes import HermesClient, HermesRunResult, HermesRuntimeError
from app.runtime.pi import PiRuntimeAdapter
from app.runtime.deepseek import DeepSeekRuntimeAdapter


class HermesRuntimeAdapter(RuntimeAdapter):
    runtime_type = "hermes"

    def __init__(
        self,
        *,
        endpoint: str | None = None,
        version: str | None = None,
        config: dict[str, Any] | None = None,
    ) -> None:
        settings = get_settings()
        self.endpoint = (endpoint or settings.hermes_endpoint).rstrip("/")
        self.version = version
        self.config = config or {}

    async def create_session(
        self,
        *,
        agent_id: str,
        execution_id: str,
        metadata: dict[str, Any] | None = None,
        context: RuntimeContext | None = None,
    ) -> RuntimeSession:
        # Hermes creates its native run when execute/stream starts. The stable
        # platform execution id is the Runtime session correlation id.
        return RuntimeSession(id=execution_id, runtime_type=self.runtime_type)

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
        try:
            adapter = get_model_adapter(model_adapter)
            return await HermesClient(endpoint=self.endpoint).run(
                prompt=adapter.render_messages(messages),
                requested_model=model,
                model_adapter=model_adapter,
                agent_id=agent_id,
                execution_id=execution_id,
                runtime_options=runtime_options,
            )
        except (HermesRuntimeError, ValueError) as exc:
            raise RuntimeAdapterError(str(exc)) from exc

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
        try:
            adapter = get_model_adapter(model_adapter)
            async for event in HermesClient(endpoint=self.endpoint).stream(
                prompt=adapter.render_messages(messages),
                requested_model=model,
                model_adapter=model_adapter,
                agent_id=agent_id,
                execution_id=execution_id,
                runtime_options=runtime_options,
            ):
                yield event
        except (HermesRuntimeError, ValueError) as exc:
            raise RuntimeAdapterError(str(exc)) from exc

    async def stop(self, run_id: str) -> None:
        client = HermesClient(endpoint=self.endpoint)
        try:
            async with httpx.AsyncClient(timeout=10) as http:
                response = await http.post(
                    f"{client.runs_url}/{run_id}/stop", headers=client._headers()
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise RuntimeAdapterError(f"Hermes stop failed: {exc}") from exc

    async def health_check(self) -> RuntimeHealth:
        health_path = str(self.config.get("health_path") or "/health")
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(urljoin(f"{self.endpoint}/", health_path))
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise RuntimeAdapterError(f"Hermes Runtime health check failed: {exc}") from exc
        reported_version = payload.get("version") if isinstance(payload, dict) else None
        return RuntimeHealth(
            status="online",
            version=str(reported_version or self.version or "") or None,
            detail="Hermes Runtime is online",
        )


def get_runtime_adapter(
    runtime_type: str,
    *,
    endpoint: str | None = None,
    version: str | None = None,
    config: dict[str, Any] | None = None,
) -> RuntimeAdapter:
    normalized = runtime_type.strip().lower()
    if normalized == "hermes":
        return HermesRuntimeAdapter(endpoint=endpoint, version=version, config=config)
    if normalized == "pi":
        return PiRuntimeAdapter(endpoint=endpoint, version=version, config=config)
    if normalized == "deepseek":
        return DeepSeekRuntimeAdapter(endpoint=endpoint, version=version, config=config)
    raise ValueError(f"unsupported runtime type: {runtime_type}")


def supported_runtime_types() -> tuple[str, ...]:
    return ("hermes", "pi", "deepseek")

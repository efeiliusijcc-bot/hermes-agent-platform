from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentRuntime
from app.repositories import runtimes as runtime_repository
from app.runtime.base import RuntimeAdapter, RuntimeAdapterError


@dataclass(frozen=True)
class RuntimeRoute:
    runtime_type: str
    runtime: AgentRuntime | None
    adapter: RuntimeAdapter


class RuntimeRouter:
    async def resolve(
        self,
        session: AsyncSession,
        *,
        runtime_type: str,
        runtime_id: UUID | str | None = None,
        runtime_config: dict[str, Any] | None = None,
    ) -> RuntimeRoute:
        value = await runtime_repository.resolve_runtime(
            session,
            runtime_type=runtime_type,
            runtime_id=runtime_id,
            runtime_config=runtime_config,
        )
        configured_id = runtime_id or (runtime_config or {}).get("runtime_id")
        if configured_id and value is None:
            raise RuntimeAdapterError("configured Runtime is missing or has a different type")
        if value is not None and value.status in {"offline", "disabled"}:
            raise RuntimeAdapterError(f"configured Runtime is {value.status}")
        if runtime_type == "deepseek" and value is None:
            raise RuntimeAdapterError("DeepSeek Runtime has no registered online instance")
        try:
            adapter = _adapter(
                runtime_type,
                endpoint=value.endpoint if value is not None else None,
                version=value.version if value is not None else None,
                config=value.config if value is not None else runtime_config,
            )
        except ValueError as exc:
            raise RuntimeAdapterError(str(exc)) from exc
        return RuntimeRoute(runtime_type=runtime_type, runtime=value, adapter=adapter)


def _adapter(
    runtime_type: str,
    *,
    endpoint: str | None,
    version: str | None,
    config: dict[str, Any] | None,
) -> RuntimeAdapter:
    from app.runtime.adapters import get_runtime_adapter

    return get_runtime_adapter(
        runtime_type,
        endpoint=endpoint,
        version=version,
        config=config,
    )

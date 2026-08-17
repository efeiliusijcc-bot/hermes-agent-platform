from typing import Any

from app.runtime.base import (
    RuntimeAdapter,
    RuntimeAdapterError,
    RuntimeCancelledError,
    RuntimeContext,
    RuntimeHealth,
    RuntimeSession,
)
from app.runtime.hermes import HermesClient, HermesRunResult


def get_runtime_adapter(
    runtime_type: str,
    *,
    endpoint: str | None = None,
    version: str | None = None,
    config: dict[str, Any] | None = None,
) -> RuntimeAdapter:
    from app.runtime.adapters import get_runtime_adapter as resolve

    return resolve(runtime_type, endpoint=endpoint, version=version, config=config)


def supported_runtime_types() -> tuple[str, ...]:
    from app.runtime.adapters import supported_runtime_types as resolve

    return resolve()

__all__ = [
    "HermesClient",
    "HermesRunResult",
    "RuntimeAdapter",
    "RuntimeAdapterError",
    "RuntimeCancelledError",
    "RuntimeContext",
    "RuntimeHealth",
    "RuntimeSession",
    "get_runtime_adapter",
    "supported_runtime_types",
]

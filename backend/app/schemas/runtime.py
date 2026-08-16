from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


RuntimeType = Literal["hermes", "pi"]
RuntimeStatus = Literal["unknown", "online", "offline", "disabled"]


def _validate_endpoint(value: str) -> str:
    normalized = value.strip().rstrip("/")
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Runtime endpoint must be an http(s) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Runtime endpoint must not contain credentials, query, or fragment")
    return normalized


def validate_public_runtime_config(value: dict[str, Any]) -> dict[str, Any]:
    forbidden_parts = {
        "apikey",
        "authorization",
        "bearer",
        "credential",
        "credentials",
        "password",
        "secret",
    }
    forbidden_suffixes = (*forbidden_parts, "token")
    stack: list[object] = [value]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            for key, item in current.items():
                normalized = re.sub(r"[^a-z0-9]+", "_", str(key).lower()).strip("_")
                compact = normalized.replace("_", "")
                parts = set(normalized.split("_"))
                if parts.intersection(forbidden_parts) or compact.endswith(forbidden_suffixes):
                    raise ValueError("Runtime config must not contain credentials; use environment secrets")
                stack.append(item)
        elif isinstance(current, list):
            stack.extend(current)
    return value


class RuntimeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    type: RuntimeType
    version: str = Field(min_length=1, max_length=64)
    endpoint: str
    config: dict[str, Any] = Field(default_factory=dict)
    status: RuntimeStatus = "unknown"

    _endpoint = field_validator("endpoint")(_validate_endpoint)
    _config = field_validator("config")(validate_public_runtime_config)


class RuntimeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    version: str | None = Field(default=None, min_length=1, max_length=64)
    endpoint: str | None = None
    config: dict[str, Any] | None = None
    status: RuntimeStatus | None = None

    _endpoint = field_validator("endpoint")(
        lambda value: _validate_endpoint(value) if value is not None else value
    )
    _config = field_validator("config")(
        lambda value: validate_public_runtime_config(value) if value is not None else value
    )


class RuntimeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    type: RuntimeType
    version: str
    endpoint: str
    config: dict[str, Any]
    status: RuntimeStatus
    last_health_at: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime


class RuntimeHealthRead(BaseModel):
    id: UUID
    status: Literal["online", "offline"]
    version: str | None
    latency_ms: int
    detail: str

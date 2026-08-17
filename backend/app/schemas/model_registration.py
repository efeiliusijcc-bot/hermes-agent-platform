from __future__ import annotations

from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from app.schemas.agent import ModelAdapterName


ModelProvider = Literal["qwen", "deepseek", "openai", "claude", "custom"]
ModelStatus = Literal["unknown", "online", "offline"]


def normalize_model_base_url(value: str) -> str:
    normalized = value.strip().rstrip("/")
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("模型地址必须是有效的 http(s) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("模型地址不能包含凭据、查询参数或 fragment")
    return normalized


class ModelRegistrationCreate(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9](?:[a-z0-9._-]{0,62}[a-z0-9])?$")
    display_name: str = Field(min_length=1, max_length=255)
    provider: ModelProvider = "custom"
    adapter: ModelAdapterName = "hermes"
    base_url: str
    upstream_model: str = Field(min_length=1, max_length=255)
    api_key: SecretStr | None = Field(default=None, max_length=8192)
    is_enabled: bool = True
    is_default: bool = False
    timeout_seconds: int = Field(default=180, ge=5, le=1800)
    max_retries: int = Field(default=2, ge=0, le=5)

    _base_url = field_validator("base_url")(normalize_model_base_url)

    @model_validator(mode="after")
    def validate_default(self) -> "ModelRegistrationCreate":
        if self.is_default and not self.is_enabled:
            raise ValueError("默认模型必须启用")
        return self


class ModelRegistrationUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    provider: ModelProvider | None = None
    adapter: ModelAdapterName | None = None
    base_url: str | None = None
    upstream_model: str | None = Field(default=None, min_length=1, max_length=255)
    api_key: SecretStr | None = Field(default=None, max_length=8192)
    clear_api_key: bool = False
    is_enabled: bool | None = None
    is_default: bool | None = None
    timeout_seconds: int | None = Field(default=None, ge=5, le=1800)
    max_retries: int | None = Field(default=None, ge=0, le=5)

    _base_url = field_validator("base_url")(
        lambda value: normalize_model_base_url(value) if value is not None else value
    )

    @model_validator(mode="after")
    def validate_secret_operation(self) -> "ModelRegistrationUpdate":
        if self.clear_api_key and self.api_key is not None and self.api_key.get_secret_value():
            raise ValueError("不能同时轮换和清除模型密钥")
        return self


class ModelRegistrationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    display_name: str
    provider: ModelProvider
    adapter: ModelAdapterName
    base_url: str
    upstream_model: str
    api_key_configured: bool
    is_enabled: bool
    is_default: bool
    timeout_seconds: int
    max_retries: int
    status: ModelStatus
    last_health_at: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime


class ModelConnectivityRead(BaseModel):
    id: str
    status: Literal["online", "offline"]
    latency_ms: int
    detail: str

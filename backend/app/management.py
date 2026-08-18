from __future__ import annotations

import secrets

from fastapi import Header, HTTPException, status

from app.config import get_settings


def authorize_platform_management_key(value: str | None) -> None:
    settings = get_settings()
    if not settings.platform_management_api_key_enabled:
        return
    configured = settings.platform_management_api_key
    if configured is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="平台管理密钥未配置，控制台当前为只读模式",
        )
    expected = configured.get_secret_value()
    if value is None or not secrets.compare_digest(value, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="平台管理密钥无效")


def require_platform_management_key(
    value: str | None = Header(default=None, alias="X-Platform-Management-Key"),
) -> None:
    authorize_platform_management_key(value)


def require_platform_management_key_for_capability_control(
    value: str | None = Header(default=None, alias="X-Platform-Management-Key"),
) -> None:
    """Protect legacy control APIs once the capability control plane is enabled.

    This preserves the feature-flag rollback path before cutover, while making
    the old Agent/Runtime/MCP/Skill write routes read-only under the new console.
    """
    settings = get_settings()
    if not (settings.capability_platform_enabled or settings.console_bff_enabled):
        return
    authorize_platform_management_key(value)


def management_mode() -> dict[str, bool]:
    settings = get_settings()
    return {
        "management_key_required": settings.platform_management_api_key_enabled,
        "read_only_without_key": settings.platform_management_api_key_enabled,
    }

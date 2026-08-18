from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid
from typing import Any

from app.config import get_settings


class CapabilityTokenError(ValueError):
    pass


def issue_execution_capability_token(
    *,
    execution_id: str,
    agent_id: str,
    agent_version_id: str,
    runtime_id: str,
    allowed_bindings: list[str],
    resolution_digest: str,
    now: int | None = None,
) -> str:
    issued_at = int(time.time() if now is None else now)
    settings = get_settings()
    claims = {
        "sub": f"execution:{execution_id}",
        "execution_id": execution_id,
        "agent_id": agent_id,
        "agent_version_id": agent_version_id,
        "runtime_id": runtime_id,
        "allowed_bindings": sorted(set(allowed_bindings)),
        "resolution_digest": resolution_digest,
        "iat": issued_at,
        "exp": issued_at + settings.execution_capability_token_ttl_seconds,
        "jti": str(uuid.uuid4()),
    }
    encoded = _base64url(json.dumps(claims, sort_keys=True, separators=(",", ":")).encode())
    signed = f"cap1.{encoded}"
    signature = hmac.new(
        settings.mcp_gateway_signing_key.get_secret_value().encode(),
        signed.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{signed}.{_base64url(signature)}"


def verify_execution_capability_token(
    token: str,
    *,
    now: int | None = None,
) -> dict[str, Any]:
    try:
        prefix, encoded, signature = token.split(".", 2)
    except ValueError as exc:
        raise CapabilityTokenError("malformed execution capability token") from exc
    if prefix != "cap1":
        raise CapabilityTokenError("unsupported execution capability token")
    settings = get_settings()
    expected = hmac.new(
        settings.mcp_gateway_signing_key.get_secret_value().encode(),
        f"{prefix}.{encoded}".encode("ascii"),
        hashlib.sha256,
    ).digest()
    if not hmac.compare_digest(_base64url_decode(signature), expected):
        raise CapabilityTokenError("invalid execution capability token signature")
    try:
        claims = json.loads(_base64url_decode(encoded))
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise CapabilityTokenError("invalid execution capability token payload") from exc
    if not isinstance(claims, dict):
        raise CapabilityTokenError("invalid execution capability token claims")
    required = {
        "execution_id": str,
        "agent_id": str,
        "agent_version_id": str,
        "runtime_id": str,
        "allowed_bindings": list,
        "resolution_digest": str,
        "iat": int,
        "exp": int,
        "jti": str,
    }
    if any(not isinstance(claims.get(key), expected_type) for key, expected_type in required.items()):
        raise CapabilityTokenError("incomplete execution capability token claims")
    current = int(time.time() if now is None else now)
    if claims["exp"] <= current:
        raise CapabilityTokenError("execution capability token expired")
    return claims


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _base64url_decode(value: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, UnicodeEncodeError) as exc:
        raise CapabilityTokenError("malformed execution capability token encoding") from exc

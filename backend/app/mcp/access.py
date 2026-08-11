from __future__ import annotations

import base64
import hashlib
import hmac
import uuid

from app.config import get_settings


def issue_mcp_access_token(
    *,
    execution_id: str,
) -> str:
    settings = get_settings()
    encoded = _base64url(uuid.UUID(execution_id).bytes)
    signed_value = f"mcp2.{encoded}"
    signature = hmac.new(
        settings.mcp_gateway_signing_key.get_secret_value().encode("utf-8"),
        signed_value.encode("ascii"),
        hashlib.sha256,
    ).digest()[:16]
    return f"{signed_value}.{_base64url(signature)}"


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")

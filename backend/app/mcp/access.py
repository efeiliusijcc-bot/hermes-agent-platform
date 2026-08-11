from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

from app.config import get_settings


def issue_mcp_access_token(
    *,
    agent_id: str,
    execution_id: str,
    capabilities: dict[str, str],
) -> str:
    settings = get_settings()
    now = int(time.time())
    payload: dict[str, Any] = {
        "v": 1,
        "agent_id": agent_id,
        "execution_id": execution_id,
        "mcp": capabilities,
        "iat": now,
        "exp": now + settings.mcp_access_token_ttl_seconds,
    }
    encoded = _base64url(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signature = hmac.new(
        settings.mcp_gateway_signing_key.get_secret_value().encode("utf-8"),
        encoded.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"mcp1.{encoded}.{_base64url(signature)}"


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")

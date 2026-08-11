from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any


class MCPAccessDenied(ValueError):
    pass


@dataclass(frozen=True)
class MCPAccessClaims:
    agent_id: str
    execution_id: str
    mcp: dict[str, str]

    def require(self, capability: str) -> str:
        mcp_id = self.mcp.get(capability)
        if not mcp_id:
            raise MCPAccessDenied(f"access denied: {capability} MCP is not bound to this Agent")
        return mcp_id


def verify_mcp_access_token(token: str, signing_key: str) -> MCPAccessClaims:
    try:
        prefix, encoded, encoded_signature = token.split(".", 2)
    except ValueError as exc:
        raise MCPAccessDenied("access denied: malformed MCP access token") from exc
    if prefix != "mcp1":
        raise MCPAccessDenied("access denied: unsupported MCP access token")

    expected_signature = hmac.new(
        signing_key.encode("utf-8"),
        encoded.encode("ascii"),
        hashlib.sha256,
    ).digest()
    try:
        actual_signature = _base64url_decode(encoded_signature)
    except (ValueError, UnicodeError) as exc:
        raise MCPAccessDenied("access denied: malformed MCP signature") from exc
    if not hmac.compare_digest(actual_signature, expected_signature):
        raise MCPAccessDenied("access denied: invalid MCP signature")

    try:
        payload: Any = json.loads(_base64url_decode(encoded))
    except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
        raise MCPAccessDenied("access denied: malformed MCP claims") from exc
    if not isinstance(payload, dict) or payload.get("v") != 1:
        raise MCPAccessDenied("access denied: invalid MCP claims")
    if not isinstance(payload.get("exp"), int) or payload["exp"] < int(time.time()):
        raise MCPAccessDenied("access denied: MCP access token expired")
    if not isinstance(payload.get("agent_id"), str) or not isinstance(payload.get("execution_id"), str):
        raise MCPAccessDenied("access denied: missing MCP identity")
    mcp = payload.get("mcp")
    if not isinstance(mcp, dict) or not all(isinstance(key, str) and isinstance(value, str) for key, value in mcp.items()):
        raise MCPAccessDenied("access denied: invalid MCP permissions")
    return MCPAccessClaims(
        agent_id=payload["agent_id"],
        execution_id=payload["execution_id"],
        mcp=mcp,
    )


def _base64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))

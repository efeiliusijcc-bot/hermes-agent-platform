from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import uuid
from dataclasses import dataclass


class MCPAccessDenied(ValueError):
    pass


@dataclass(frozen=True)
class MCPAccessClaims:
    agent_id: str
    execution_id: str
    mcp: dict[str, dict[str, str]]

    def require(self, capability: str) -> str:
        binding = self.mcp.get(capability)
        # String snapshots were emitted by Phase 6. Accept them only as the
        # historical read-only format while all new executions use explicit
        # permission objects.
        if isinstance(binding, str) and binding:
            return binding
        if not isinstance(binding, dict) or binding.get("permission") != "read_only" or not binding.get("mcp_id"):
            raise MCPAccessDenied(f"access denied: {capability} MCP is not bound to this Agent")
        return binding["mcp_id"]


def verify_mcp_access_token(token: str, signing_key: str) -> str:
    try:
        prefix, encoded, encoded_signature = token.split(".", 2)
    except ValueError as exc:
        raise MCPAccessDenied("access denied: malformed MCP access token") from exc
    if prefix != "mcp2":
        raise MCPAccessDenied("access denied: unsupported MCP access token")

    expected_signature = hmac.new(
        signing_key.encode("utf-8"),
        f"{prefix}.{encoded}".encode("ascii"),
        hashlib.sha256,
    ).digest()[:16]
    try:
        actual_signature = _base64url_decode(encoded_signature)
    except (ValueError, UnicodeError, binascii.Error) as exc:
        raise MCPAccessDenied("access denied: malformed MCP signature") from exc
    if not hmac.compare_digest(actual_signature, expected_signature):
        raise MCPAccessDenied("access denied: invalid MCP signature")

    try:
        raw_execution_id = _base64url_decode(encoded)
        if len(raw_execution_id) != 16:
            raise ValueError("invalid UUID length")
        return str(uuid.UUID(bytes=raw_execution_id))
    except (ValueError, UnicodeError, binascii.Error) as exc:
        raise MCPAccessDenied("access denied: malformed MCP execution id") from exc


def _base64url_decode(value: str) -> bytes:
    padded = value + "=" * (-len(value) % 4)
    return base64.b64decode(padded, altchars=b"-_", validate=True)

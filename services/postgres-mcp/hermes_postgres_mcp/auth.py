from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import time
from typing import Any


class AccessDenied(ValueError):
    pass


def verify_capability_token(token: str, signing_key: str) -> dict[str, Any]:
    try:
        prefix, encoded, encoded_signature = token.split(".", 2)
    except ValueError as exc:
        raise AccessDenied("capability token 格式无效") from exc
    if prefix != "cap1":
        raise AccessDenied("capability token 类型无效")
    signed = f"{prefix}.{encoded}"
    expected = hmac.new(signing_key.encode(), signed.encode("ascii"), hashlib.sha256).digest()
    try:
        actual = _decode(encoded_signature)
        payload = json.loads(_decode(encoded))
    except (ValueError, UnicodeError, binascii.Error, json.JSONDecodeError) as exc:
        raise AccessDenied("capability token 编码无效") from exc
    if not hmac.compare_digest(actual, expected):
        raise AccessDenied("capability token 签名无效")
    if not isinstance(payload, dict) or not isinstance(payload.get("exp"), int) or payload["exp"] <= int(time.time()):
        raise AccessDenied("capability token 已过期")
    for field in ("execution_id", "agent_id", "agent_version_id", "resolution_digest", "jti"):
        if not isinstance(payload.get(field), str) or not payload[field]:
            raise AccessDenied("capability token 声明不完整")
    bindings = payload.get("allowed_bindings")
    if not isinstance(bindings, list) or any(not isinstance(item, str) for item in bindings):
        raise AccessDenied("capability token Binding 无效")
    return payload


def bearer(value: str | None) -> str:
    if not value or not value.startswith("Bearer "):
        raise AccessDenied("缺少 Execution Token")
    return value.removeprefix("Bearer ").strip()


def _decode(value: str) -> bytes:
    padded = value + "=" * (-len(value) % 4)
    decoded = base64.b64decode(padded, altchars=b"-_", validate=True)
    canonical = base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii")
    if not hmac.compare_digest(canonical, value):
        raise ValueError("non-canonical base64url")
    return decoded

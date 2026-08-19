from __future__ import annotations

import base64
import hashlib
import hmac
import json
from time import time

import pytest

from hermes_postgres_mcp.auth import AccessDenied, verify_capability_token
from hermes_postgres_mcp.server import (
    _require_permission,
    _require_response_size,
    _timeouts,
    _validate_analysis,
)
from hermes_postgres_mcp.sql_policy import SQLPolicyError, analyze_select


@pytest.mark.parametrize(
    "sql",
    [
        "WITH changed AS (DELETE FROM public.items RETURNING *) SELECT * FROM changed",
        "SELECT * INTO copied_items FROM public.items",
        "SELECT * FROM public.items FOR UPDATE",
        "SELECT 1; SELECT 2",
        "COPY public.items TO STDOUT",
    ],
)
def test_sql_policy_rejects_writes_locks_and_multiple_statements(sql: str) -> None:
    with pytest.raises(SQLPolicyError):
        analyze_select(sql)


def test_sql_policy_keeps_physical_relations_but_ignores_nested_cte_aliases() -> None:
    analysis = analyze_select(
        "SELECT * FROM (WITH subset AS (SELECT * FROM reporting.items) "
        "SELECT * FROM subset) AS nested"
    )
    assert analysis.relations == (("reporting", "items"),)


@pytest.mark.asyncio
async def test_scope_validation_rejects_cross_scope_and_ambiguous_unqualified_relations() -> None:
    runtime = {
        "scope": {
            "schemas": {
                "public": {"tables": ["items", "shared"], "views": []},
                "reporting": {"tables": ["shared"], "views": ["daily"]},
            },
            "permissions": {"aggregate": True},
        }
    }
    await _validate_analysis(runtime, analyze_select("SELECT * FROM public.items"))
    await _validate_analysis(runtime, analyze_select("SELECT * FROM daily"))
    with pytest.raises(AccessDenied, match="不在 Scope"):
        await _validate_analysis(runtime, analyze_select("SELECT * FROM secret.users"))
    with pytest.raises(AccessDenied, match="不唯一"):
        await _validate_analysis(runtime, analyze_select("SELECT * FROM shared"))
    with pytest.raises(AccessDenied, match="自定义函数"):
        await _validate_analysis(runtime, analyze_select("SELECT public.custom_fn(id) FROM public.items"))


@pytest.mark.asyncio
async def test_transaction_limits_pin_search_path_to_only_scoped_schemas() -> None:
    calls: list[tuple[str, str]] = []

    class Connection:
        async def execute(self, sql: str, value: str) -> None:
            calls.append((sql, value))

    await _timeouts(
        Connection(),  # type: ignore[arg-type]
        {"statement_timeout_ms": 2500, "lock_timeout_ms": 400},
        {"schemas": {"tenant_b": {}, "tenant_a": {}}},
    )
    assert calls[-1] == (
        "SELECT set_config('search_path', $1, true)",
        '"pg_catalog", "tenant_a", "tenant_b"',
    )


def test_permissions_and_response_limit_fail_closed() -> None:
    with pytest.raises(AccessDenied):
        _require_permission({"permissions": {"describe": False}}, "describe")
    with pytest.raises(ValueError, match="响应大小"):
        _require_response_size({"rows": ["x" * 200]}, 32)


def test_capability_token_signature_expiry_and_claims_are_enforced() -> None:
    key = "postgres-mcp-test-signing-key-that-is-long-enough"
    claims = {
        "execution_id": "execution-1",
        "agent_id": "agent-1",
        "agent_version_id": "version-1",
        "resolution_digest": "sha256:test",
        "jti": "jti-1",
        "allowed_bindings": ["binding-1"],
        "exp": int(time()) + 60,
    }
    encoded = base64.urlsafe_b64encode(
        json.dumps(claims, separators=(",", ":")).encode()
    ).rstrip(b"=").decode("ascii")
    signed = f"cap1.{encoded}"
    signature = base64.urlsafe_b64encode(
        hmac.new(key.encode(), signed.encode("ascii"), hashlib.sha256).digest()
    ).rstrip(b"=").decode("ascii")
    token = f"{signed}.{signature}"
    assert verify_capability_token(token, key)["execution_id"] == "execution-1"
    with pytest.raises(AccessDenied):
        verify_capability_token(token + "x", key)

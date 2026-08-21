from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sqlite3
from pathlib import Path
from time import time

import httpx
import pytest

from hermes_postgres_mcp.adapters import AdapterError, adapter_for
from hermes_postgres_mcp.auth import AccessDenied, verify_capability_token
from hermes_postgres_mcp.server import (
    _require_permission,
    _require_response_size,
    _stored_object,
    _timeouts,
    _validate_analysis,
)
from hermes_postgres_mcp.sql_policy import SQLPolicyError, analyze_read_query, analyze_select


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
    with pytest.raises(AccessDenied, match="PERMISSION_DENIED"):
        _require_permission({"permissions": {"describe": False}}, "describe")
    with pytest.raises(ValueError, match="响应大小"):
        _require_response_size({"rows": ["x" * 200]}, 32)


def test_sql_policy_errors_carry_the_standard_gateway_code() -> None:
    with pytest.raises(SQLPolicyError, match="INVALID_ARGUMENT"):
        analyze_select("DELETE FROM public.items")


@pytest.mark.parametrize(
    ("database_type", "sql", "relation"),
    [
        ("mysql", "SELECT * FROM business.items", ("business", "items")),
        ("sqlserver", "SELECT TOP 10 * FROM dbo.items", ("dbo", "items")),
        ("oracle", "SELECT * FROM REPORTING.ITEMS", ("REPORTING", "ITEMS")),
        ("dm", "SELECT * FROM REPORTING.ITEMS", ("REPORTING", "ITEMS")),
        ("clickhouse", "SELECT * FROM analytics.events", ("analytics", "events")),
        ("elasticsearch", 'SELECT * FROM "news-index"', (None, "news-index")),
        ("sqlite", "SELECT * FROM main.items", ("main", "items")),
    ],
)
def test_generic_sql_policy_extracts_scoped_relations(database_type: str, sql: str, relation: tuple[str | None, str]) -> None:
    assert relation in analyze_read_query(sql, database_type).relations


@pytest.mark.parametrize(
    ("database_type", "sql"),
    [
        ("mysql", "WITH changed AS (DELETE FROM users RETURNING *) SELECT * FROM changed"),
        ("sqlserver", "EXEC xp_cmdshell 'whoami'"),
        ("sqlite", "PRAGMA writable_schema=ON"),
        ("clickhouse", "DROP TABLE analytics.events"),
    ],
)
def test_generic_sql_policy_rejects_non_read_operations(database_type: str, sql: str) -> None:
    with pytest.raises(SQLPolicyError):
        analyze_read_query(sql, database_type)


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, "用户名或密码无效"),
        (403, "cluster monitor"),
        (429, "HTTP 429"),
    ],
)
def test_elasticsearch_http_errors_are_explicit_and_do_not_echo_request_credentials(status: int, expected: str) -> None:
    adapter = adapter_for("elasticsearch")
    request = httpx.Request("GET", "http://elastic.internal:9200", headers={"authorization": "secret-value"})
    error = httpx.HTTPStatusError("provider failure", request=request, response=httpx.Response(status, request=request))
    rendered = str(adapter._http_error(error))
    assert expected in rendered
    assert "secret-value" not in rendered


@pytest.mark.asyncio
async def test_sqlite_adapter_discovers_and_reads_only_from_scoped_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database = tmp_path / "demo.db"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE items(id INTEGER, name TEXT)")
    connection.execute("INSERT INTO items VALUES (1, 'ok')")
    connection.commit()
    connection.close()
    monkeypatch.setenv("DATABASE_MCP_SQLITE_ROOT", str(tmp_path))
    config = {"database_type": "sqlite", "database_file": "demo.db", "maintenance_database": "main"}
    adapter = adapter_for("sqlite")
    discovery = await adapter.test_and_discover(config, {"username": "", "password": ""})
    assert discovery["database_type"] == "sqlite"
    assert discovery["databases"][0]["schemas"][0]["tables"][0]["name"] == "items"
    result = await adapter.select(
        {"config": config, "credential": {"username": "", "password": ""}, "database": "main", "scope": {"limits": {}}},
        "SELECT * FROM items",
        10,
    )
    assert result["rows"] == [{"id": 1, "name": "ok"}]
    outside = tmp_path.parent / "outside.db"
    outside.touch()
    config["database_file"] = str(outside)
    with pytest.raises(AdapterError, match="目录内"):
        await adapter.test_and_discover(config, {"username": "", "password": ""})


def test_stored_json_objects_accept_asyncpg_jsonb_strings_and_reject_non_objects() -> None:
    assert _stored_object({"database": "business_db"}) == {"database": "business_db"}
    assert _stored_object('{"database":"analytics_db"}') == {"database": "analytics_db"}
    with pytest.raises(ValueError, match="存储对象格式无效"):
        _stored_object("[]")
    with pytest.raises(ValueError, match="存储对象格式无效"):
        _stored_object("not-json")


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

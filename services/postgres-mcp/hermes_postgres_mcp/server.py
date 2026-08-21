from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import socket
from contextlib import asynccontextmanager
from datetime import date, datetime, time
from decimal import Decimal
from time import monotonic
from typing import Any, AsyncIterator
from uuid import UUID

import asyncpg
import redis.asyncio as redis
from cryptography.fernet import Fernet, InvalidToken
from mcp.server.fastmcp import Context, FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from hermes_postgres_mcp.auth import AccessDenied, bearer, verify_capability_token
from hermes_postgres_mcp.adapters import AdapterError, adapter_for
from hermes_postgres_mcp.sql_policy import QueryAnalysis, SQLPolicyError, analyze_read_query


logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)
SIGNING_KEY = os.environ["MCP_GATEWAY_SIGNING_KEY"]
FERNET = Fernet(os.environ["MODEL_REGISTRY_ENCRYPTION_KEY"].strip().encode("ascii"))
DISCOVERY_CONCURRENCY = max(1, min(int(os.getenv("POSTGRES_MCP_DISCOVERY_CONCURRENCY", "4")), 16))
DISCOVERY_MAX_DATABASES = max(1, min(int(os.getenv("POSTGRES_MCP_DISCOVERY_MAX_DATABASES", "100")), 1000))
DEFAULT_MAX_RESPONSE_BYTES = int(os.getenv("POSTGRES_MCP_MAX_RESPONSE_BYTES", "2097152"))
REGISTRY_POOL: asyncpg.Pool | None = None
REDIS_CLIENT: redis.Redis | None = None
TARGET_POOLS: dict[tuple[str, str, str], asyncpg.Pool] = {}
RESOURCE_LOCK = asyncio.Lock()


async def _ensure_resources() -> tuple[asyncpg.Pool, redis.Redis]:
    global REGISTRY_POOL, REDIS_CLIENT
    async with RESOURCE_LOCK:
        if REGISTRY_POOL is None:
            REGISTRY_POOL = await asyncpg.create_pool(
                host=os.getenv("POSTGRES_HOST", "postgres"),
                port=int(os.getenv("POSTGRES_PORT", "5432")),
                user=os.environ["POSTGRES_USER"],
                password=os.environ["POSTGRES_PASSWORD"],
                database=os.environ["POSTGRES_DB"],
                min_size=1,
                max_size=5,
                command_timeout=10,
            )
        if REDIS_CLIENT is None:
            REDIS_CLIENT = redis.Redis(
                host=os.getenv("REDIS_HOST", "redis"),
                port=int(os.getenv("REDIS_PORT", "6379")),
                db=int(os.getenv("REDIS_DB", "0")),
                password=os.getenv("REDIS_PASSWORD") or None,
                decode_responses=True,
            )
        return REGISTRY_POOL, REDIS_CLIENT


async def _close_resources() -> None:
    global REGISTRY_POOL, REDIS_CLIENT
    async with RESOURCE_LOCK:
        pools = list(TARGET_POOLS.values())
        TARGET_POOLS.clear()
        registry, redis_client = REGISTRY_POOL, REDIS_CLIENT
        REGISTRY_POOL = None
        REDIS_CLIENT = None
    await asyncio.gather(*(pool.close() for pool in pools), return_exceptions=True)
    if registry is not None:
        await registry.close()
    if redis_client is not None:
        await redis_client.aclose()


@asynccontextmanager
async def lifespan(_: Any) -> AsyncIterator[dict[str, Any]]:
    pool, redis_client = await _ensure_resources()
    yield {"pool": pool, "redis": redis_client}


mcp = FastMCP(
    "Agent Database MCP",
    instructions="Platform-scoped, read-only multi-database tools.",
    host="0.0.0.0",
    port=8091,
    streamable_http_path="/mcp",
    json_response=True,
    stateless_http=True,
    lifespan=lifespan,
)


@mcp.tool()
async def db_list_schemas(ctx: Context) -> dict[str, Any]:
    runtime = await _authorize(ctx, "db_list_schemas")
    return {"database": runtime["database"], "schemas": sorted(runtime["scope"]["schemas"])}


@mcp.tool()
async def db_list_tables(ctx: Context, schema: str | None = None) -> dict[str, Any]:
    runtime = await _authorize(ctx, "db_list_tables")
    scopes = runtime["scope"]["schemas"]
    if schema is not None:
        selected = _schema_scope(scopes, schema)
        return {"database": runtime["database"], "schemas": [{"name": schema, **selected}]}
    return {
        "database": runtime["database"],
        "schemas": [{"name": name, **value} for name, value in sorted(scopes.items())],
    }


@mcp.tool()
async def db_describe_table(schema: str, table: str, ctx: Context) -> dict[str, Any]:
    runtime = await _authorize(ctx, "db_describe_table")
    _require_permission(runtime["scope"], "describe")
    _require_object(runtime["scope"], schema, table)
    if runtime["database_type"] != "postgresql":
        result = await adapter_for(runtime["database_type"]).describe(runtime, schema, table)
        _require_response_size(result, int(runtime["scope"]["limits"].get("max_response_bytes") or DEFAULT_MAX_RESPONSE_BYTES))
        return result
    pool = await _target_pool(runtime)
    rows = await pool.fetch(
        """
        SELECT column_name, data_type, udt_name, is_nullable, ordinal_position,
               character_maximum_length, numeric_precision, numeric_scale
        FROM information_schema.columns
        WHERE table_schema = $1 AND table_name = $2
        ORDER BY ordinal_position
        """,
        schema,
        table,
    )
    return {"database": runtime["database"], "schema": schema, "table": table, "columns": [_record(row) for row in rows]}


@mcp.tool()
async def db_preview_table(schema: str, table: str, ctx: Context, limit: int = 20) -> dict[str, Any]:
    runtime = await _authorize(ctx, "db_preview_table")
    _require_permission(runtime["scope"], "preview")
    _require_object(runtime["scope"], schema, table)
    maximum = min(max(1, int(limit)), int(runtime["scope"]["limits"]["max_rows"]))
    if runtime["database_type"] != "postgresql":
        result = await adapter_for(runtime["database_type"]).preview(runtime, schema, table, maximum)
        _require_response_size(result, int(runtime["scope"]["limits"].get("max_response_bytes") or DEFAULT_MAX_RESPONSE_BYTES))
        return result
    sql = f'SELECT * FROM {_identifier(schema)}.{_identifier(table)} LIMIT {maximum + 1}'
    return await _execute(runtime, sql, maximum=maximum)


@mcp.tool()
async def db_select(sql: str, ctx: Context) -> dict[str, Any]:
    runtime = await _authorize(ctx, "db_select")
    _require_permission(runtime["scope"], "query")
    analysis = analyze_read_query(sql, runtime["database_type"])
    await _validate_analysis(runtime, analysis)
    return await _execute(runtime, analysis.sql, maximum=int(runtime["scope"]["limits"]["max_rows"]))


@mcp.tool()
async def db_explain(sql: str, ctx: Context) -> dict[str, Any]:
    runtime = await _authorize(ctx, "db_explain")
    _require_permission(runtime["scope"], "query")
    analysis = analyze_read_query(sql, runtime["database_type"])
    await _validate_analysis(runtime, analysis)
    if runtime["database_type"] != "postgresql":
        result = await adapter_for(runtime["database_type"]).explain(runtime, analysis.sql)
        _require_response_size(result, int(runtime["scope"]["limits"].get("max_response_bytes") or DEFAULT_MAX_RESPONSE_BYTES))
        return result
    pool = await _target_pool(runtime)
    limits = runtime["scope"]["limits"]
    async with pool.acquire() as connection:
        async with connection.transaction(readonly=True):
            await _timeouts(connection, limits, runtime["scope"])
            plan = await connection.fetchval(f"EXPLAIN (FORMAT JSON, ANALYZE FALSE, VERBOSE FALSE) {analysis.sql}")
    result = {"database": runtime["database"], "plan": plan}
    _require_response_size(result, int(limits.get("max_response_bytes") or DEFAULT_MAX_RESPONSE_BYTES))
    return result


@mcp.custom_route("/internal/admin/test", methods=["POST"])
async def test_temporary(request: Request) -> JSONResponse:
    try:
        payload = await request.json()
        endpoint = _object(payload.get("endpoint"))
        credential = _object(payload.get("credential"))
        return JSONResponse(await _test_and_discover(endpoint, credential))
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=422)
    except Exception:
        logger.exception("temporary database test failed")
        return JSONResponse({"detail": "数据库连接测试失败"}, status_code=502)


@mcp.custom_route("/internal/admin/revisions/{revision_id}/test", methods=["POST"])
async def test_revision(request: Request) -> JSONResponse:
    return await _revision_discovery(request)


@mcp.custom_route("/internal/admin/revisions/{revision_id}/discover", methods=["POST"])
async def discover_revision(request: Request) -> JSONResponse:
    return await _revision_discovery(request)


@mcp.custom_route("/internal/admin/revisions/{revision_id}/invalidate", methods=["POST"])
async def invalidate_revision(request: Request) -> JSONResponse:
    revision_id = str(request.path_params["revision_id"])
    await _invalidate(revision_id)
    return JSONResponse({"status": "invalidated", "revision_id": revision_id})


@mcp.custom_route("/health", methods=["GET"])
async def health(_: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "registry": REGISTRY_POOL is not None})


async def _revision_discovery(request: Request) -> JSONResponse:
    try:
        revision_id = UUID(str(request.path_params["revision_id"]))
        runtime = await _load_revision(revision_id)
        if not runtime["enabled"]:
            return JSONResponse({"detail": "数据库连接已停用"}, status_code=409)
        return JSONResponse(await _test_and_discover(runtime["config"], runtime["credential"]))
    except (ValueError, AccessDenied) as exc:
        return JSONResponse({"detail": str(exc)}, status_code=422)
    except Exception:
        logger.exception("saved database test failed")
        return JSONResponse({"detail": "数据库连接测试失败"}, status_code=502)


async def _load_revision(revision_id: UUID) -> dict[str, Any]:
    pool, _ = await _ensure_resources()
    row = await pool.fetchrow(
        """
        SELECT r.connection_config, r.credential_ref, i.enabled,
               c.encrypted_payload, c.last_rotated_at
        FROM connector_instance_revisions r
        JOIN connector_instances i ON i.id = r.connector_instance_id
        LEFT JOIN connector_credentials c ON c.id = r.credential_ref
        WHERE r.id = $1
        """,
        revision_id,
    )
    if row is None or row["encrypted_payload"] is None:
        raise ValueError("数据库连接 Revision 或凭据不存在")
    return {
        "config": _stored_object(row["connection_config"]),
        "credential": _decrypt(str(row["encrypted_payload"])),
        "enabled": bool(row["enabled"]),
        "credential_epoch": row["last_rotated_at"].isoformat(),
    }


async def _test_and_discover(config: dict[str, Any], credential: dict[str, Any]) -> dict[str, Any]:
    database_type = str(config.get("database_type") or "postgresql")
    if database_type != "postgresql":
        return await adapter_for(database_type).test_and_discover(config, credential)
    started = monotonic()
    checks: list[dict[str, Any]] = []
    warnings: list[str] = []
    host = _required_text(config, "host")
    port = int(config.get("port") or 5432)
    maintenance = str(config.get("maintenance_database") or "postgres")
    username = _required_text(credential, "username")
    password = _required_text(credential, "password")
    timeout = float(config.get("connect_timeout_seconds") or 5)
    try:
        addresses = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
        address = str(addresses[0][4][0]) if addresses else host
        checks.append({"name": "dns", "status": "passed", "detail": f"{host} -> {address}"})
    except socket.gaierror as exc:
        raise ValueError(f"主机解析失败：找不到 {host}") from exc
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)
        writer.close()
        await writer.wait_closed()
        del reader
        checks.append({"name": "tcp", "status": "passed", "detail": f"{host}:{port}"})
    except (OSError, TimeoutError) as exc:
        raise ValueError(f"端口不可访问：{host}:{port}") from exc
    try:
        connection = await _connect(config, credential, maintenance)
    except asyncpg.InvalidPasswordError as exc:
        raise ValueError(f"认证失败：用户 {username} 的密码无效") from exc
    except asyncpg.InvalidCatalogNameError as exc:
        raise ValueError(f"数据库不存在：{maintenance}") from exc
    except (asyncpg.PostgresError, OSError, TimeoutError) as exc:
        raise ValueError(f"PostgreSQL 连接失败：{type(exc).__name__}") from exc
    try:
        server_version = str(await connection.fetchval("SHOW server_version"))
        await connection.fetchval("SELECT 1")
        checks.append({"name": "authentication", "status": "passed", "detail": username})
        checks.append({"name": "select", "status": "passed", "detail": "SELECT 1"})
        async with connection.transaction(readonly=True):
            await connection.fetchval("SELECT 1")
        checks.append({"name": "read_only", "status": "passed"})
        database_names = list(
            await connection.fetch(
                """
                SELECT datname
                FROM pg_database
                WHERE datallowconn AND NOT datistemplate
                  AND has_database_privilege(current_user, datname, 'CONNECT')
                ORDER BY datname
                LIMIT $1
                """,
                DISCOVERY_MAX_DATABASES + 1,
            )
        )
    finally:
        await connection.close()
    truncated = len(database_names) > DISCOVERY_MAX_DATABASES
    names = [str(row["datname"]) for row in database_names[:DISCOVERY_MAX_DATABASES]]
    if truncated:
        warnings.append(f"数据库数量超过 {DISCOVERY_MAX_DATABASES}，已截断")
    semaphore = asyncio.Semaphore(DISCOVERY_CONCURRENCY)

    async def discover(name: str) -> dict[str, Any]:
        async with semaphore:
            try:
                return {"name": name, "status": "READY", "schemas": await _discover_database(config, credential, name)}
            except Exception as exc:
                logger.warning("database discovery degraded database=%s error=%s", name, type(exc).__name__)
                return {"name": name, "status": "UNAVAILABLE", "schemas": [], "error": type(exc).__name__}

    databases = await asyncio.gather(*(discover(name) for name in names))
    warnings.extend(
        f"数据库 {item['name']} 资源发现失败：{item.get('error') or 'unknown'}"
        for item in databases
        if item["status"] != "READY"
    )
    if not any(item["status"] == "READY" for item in databases):
        raise ValueError("没有可发现的数据库")
    checks.append({"name": "discovery", "status": "passed", "detail": f"发现 {len(databases)} 个数据库"})
    return {
        "status": "READY",
        "database_type": "postgresql",
        "latency_ms": max(0, round((monotonic() - started) * 1000)),
        "checks": checks,
        "server": {"version": f"PostgreSQL {server_version}"},
        "databases": databases,
        "warnings": warnings,
    }


async def _discover_database(config: dict[str, Any], credential: dict[str, Any], database: str) -> list[dict[str, Any]]:
    connection = await _connect(config, credential, database)
    try:
        rows = await connection.fetch(
            """
            SELECT n.nspname AS schema_name, c.relname AS object_name,
                   CASE c.relkind WHEN 'r' THEN 'table' WHEN 'p' THEN 'table' ELSE 'view' END AS object_type
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relkind IN ('r', 'p', 'v', 'm')
              AND n.nspname NOT IN ('pg_catalog', 'information_schema')
              AND n.nspname NOT LIKE 'pg_toast%'
              AND has_schema_privilege(current_user, n.oid, 'USAGE')
              AND has_table_privilege(current_user, c.oid, 'SELECT')
            ORDER BY n.nspname, c.relname
            """
        )
        columns = await connection.fetch(
            """
            SELECT table_schema, table_name, column_name, data_type, udt_name,
                   is_nullable, ordinal_position
            FROM information_schema.columns
            WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
              AND table_schema NOT LIKE 'pg_toast%'
            ORDER BY table_schema, table_name, ordinal_position
            """
        )
    finally:
        await connection.close()
    column_map: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in columns:
        column_map.setdefault((row["table_schema"], row["table_name"]), []).append(
            {"name": row["column_name"], "type": row["data_type"], "udt": row["udt_name"], "nullable": row["is_nullable"] == "YES"}
        )
    schemas: dict[str, dict[str, Any]] = {}
    for row in rows:
        value = schemas.setdefault(row["schema_name"], {"name": row["schema_name"], "tables": [], "views": []})
        value[f"{row['object_type']}s"].append(
            {"name": row["object_name"], "columns": column_map.get((row["schema_name"], row["object_name"]), [])}
        )
    return [schemas[name] for name in sorted(schemas)]


async def _connect(config: dict[str, Any], credential: dict[str, Any], database: str) -> asyncpg.Connection:
    ssl_mode = str(config.get("ssl_mode") or "disable")
    ssl_value: Any = False if ssl_mode == "disable" else ssl_mode
    return await asyncpg.connect(
        host=_required_text(config, "host"),
        port=int(config.get("port") or 5432),
        database=database,
        user=_required_text(credential, "username"),
        password=_required_text(credential, "password"),
        timeout=float(config.get("connect_timeout_seconds") or 5),
        ssl=ssl_value,
        server_settings={"application_name": "hermes-postgres-mcp"},
    )


async def _authorize(ctx: Context, tool: str) -> dict[str, Any]:
    request = ctx.request_context.request
    if not isinstance(request, Request):
        raise AccessDenied("缺少内部请求上下文")
    claims = verify_capability_token(bearer(request.headers.get("authorization")), SIGNING_KEY)
    execution_id = _header(request, "x-hermes-execution-id")
    binding_id = _header(request, "x-hermes-binding-id")
    revision_id = _header(request, "x-hermes-connector-revision-id")
    scope_id = _header(request, "x-hermes-scope-revision-id")
    if execution_id != claims["execution_id"] or binding_id not in claims["allowed_bindings"]:
        raise AccessDenied("Execution 或 Binding 与 Token 不匹配")
    pool, redis_client = await _ensure_resources()
    if await redis_client.exists(f"hermes:capability-token:revoked:{claims['jti']}"):
        raise AccessDenied("Execution Token 已撤销")
    row = await pool.fetchrow(
        """
        SELECT e.status AS execution_status, e.agent_id, e.agent_version_id,
               av.resolution_digest, b.resource_scope_revision_id,
               ci.connector_instance_revision_id, o.path_or_tool,
               i.enabled, r.connection_config, r.credential_ref,
               cred.encrypted_payload, cred.last_rotated_at,
               scope.scope_definition
        FROM execution_logs e
        JOIN agent_versions av ON av.id = e.agent_version_id
        JOIN agent_capability_bindings b ON b.id = $2::uuid AND b.agent_version_id = av.id AND b.enabled
        JOIN capability_implementations ci ON ci.id = b.implementation_id AND ci.status = 'active'
        JOIN connector_operations o ON o.id = ci.connector_operation_id
        JOIN connectors connector ON connector.id = o.connector_id AND connector.type IN ('postgresql_mcp', 'database_mcp')
        JOIN connector_instance_revisions r ON r.id = ci.connector_instance_revision_id
        JOIN connector_instances i ON i.id = r.connector_instance_id
        JOIN connector_credentials cred ON cred.id = r.credential_ref AND cred.rotation_status = 'active'
        JOIN resource_scope_revisions scope ON scope.id = b.resource_scope_revision_id
        WHERE e.id = $1::uuid
        """,
        execution_id,
        binding_id,
    )
    if row is None:
        raise AccessDenied("数据库能力 Binding 不存在")
    if (
        row["execution_status"] != "running"
        or row["agent_id"] != claims["agent_id"]
        or str(row["agent_version_id"]) != claims["agent_version_id"]
        or row["resolution_digest"] != claims["resolution_digest"]
        or str(row["connector_instance_revision_id"]) != revision_id
        or str(row["resource_scope_revision_id"]) != scope_id
        or row["path_or_tool"] != tool
        or not row["enabled"]
    ):
        raise AccessDenied("数据库能力运行上下文不匹配或连接已停用")
    scope = _stored_object(row["scope_definition"])
    if scope.get("connector_revision_id") != revision_id:
        raise AccessDenied("Scope 未绑定当前 Connector Revision")
    return {
        "revision_id": revision_id,
        "database": _required_text(scope, "database"),
        "database_type": str(_stored_object(row["connection_config"]).get("database_type") or "postgresql"),
        "config": _stored_object(row["connection_config"]),
        "credential": _decrypt(str(row["encrypted_payload"])),
        "credential_epoch": row["last_rotated_at"].isoformat(),
        "scope": scope,
    }


async def _target_pool(runtime: dict[str, Any]) -> asyncpg.Pool:
    key = (runtime["revision_id"], runtime["database"], runtime["credential_epoch"])
    async with RESOURCE_LOCK:
        existing = TARGET_POOLS.get(key)
        if existing is not None:
            return existing
        config, credential = runtime["config"], runtime["credential"]
        ssl_mode = str(config.get("ssl_mode") or "disable")
        ssl_value: Any = False if ssl_mode == "disable" else ssl_mode
        value = await asyncpg.create_pool(
            host=_required_text(config, "host"),
            port=int(config.get("port") or 5432),
            database=runtime["database"],
            user=_required_text(credential, "username"),
            password=_required_text(credential, "password"),
            timeout=float(config.get("connect_timeout_seconds") or 5),
            ssl=ssl_value,
            min_size=0,
            max_size=5,
            max_inactive_connection_lifetime=60,
            server_settings={"application_name": "hermes-postgres-mcp"},
        )
        TARGET_POOLS[key] = value
        stale = [pool_key for pool_key in TARGET_POOLS if pool_key[:2] == key[:2] and pool_key != key]
        stale_pools = [TARGET_POOLS.pop(pool_key) for pool_key in stale]
    await asyncio.gather(*(pool.close() for pool in stale_pools), return_exceptions=True)
    return value


async def _invalidate(revision_id: str) -> None:
    async with RESOURCE_LOCK:
        keys = [key for key in TARGET_POOLS if key[0] == revision_id]
        pools = [TARGET_POOLS.pop(key) for key in keys]
    await asyncio.gather(*(pool.close() for pool in pools), return_exceptions=True)


async def _validate_analysis(runtime: dict[str, Any], analysis: QueryAnalysis) -> None:
    scope = runtime["scope"]
    schemas = _object(scope.get("schemas"))
    case_insensitive = str(runtime.get("database_type") or "postgresql") in {"oracle", "dm", "sqlserver"}
    normalized_schemas = {str(key).lower() if case_insensitive else str(key): value for key, value in schemas.items()}
    relation_index: dict[str, list[str]] = {}
    for schema_name, definition in normalized_schemas.items():
        definition = _object(definition)
        for relation in [*definition.get("tables", []), *definition.get("views", [])]:
            normalized_relation = str(relation).lower() if case_insensitive else str(relation)
            relation_index.setdefault(normalized_relation, []).append(str(schema_name))
    for schema, relation in analysis.relations:
        normalized_relation = relation.lower() if case_insensitive else relation
        normalized_schema = schema.lower() if case_insensitive and schema is not None else schema
        if schema is None:
            matches = relation_index.get(normalized_relation, [])
            if len(matches) != 1:
                raise AccessDenied(f"未限定 Schema 的对象 {relation} 不唯一或不在 Scope")
        elif normalized_schema not in normalized_schemas or normalized_relation not in [
            str(item).lower() if case_insensitive else str(item)
            for item in [
                *normalized_schemas.get(normalized_schema, {}).get("tables", []),
                *normalized_schemas.get(normalized_schema, {}).get("views", []),
            ]
        ]:
            raise AccessDenied(f"对象 {schema}.{relation} 不在 Scope")
    if analysis.uses_aggregate and not bool(_object(scope.get("permissions")).get("aggregate", True)):
        raise AccessDenied("当前 Scope 禁止聚合查询")
    if str(runtime.get("database_type") or "postgresql") != "postgresql":
        return
    if analysis.functions:
        custom = [
            function
            for function in analysis.functions
            if len(function) > 1 and function[-2].lower() != "pg_catalog"
        ]
        if custom:
            raise AccessDenied(f"禁止调用自定义函数 {'.'.join(custom[0])}")
        pool = await _target_pool(runtime)
        async with pool.acquire() as connection:
            for function in analysis.functions:
                safe = await connection.fetchval(
                    """
                    SELECT bool_and(p.provolatile <> 'v' AND NOT p.prosecdef)
                    FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
                    WHERE n.nspname = 'pg_catalog' AND p.proname = $1
                    """,
                    function[-1],
                )
                if safe is not True:
                    raise AccessDenied(f"函数 {'.'.join(function)} 不在只读允许范围")


async def _execute(runtime: dict[str, Any], sql: str, *, maximum: int) -> dict[str, Any]:
    if runtime["database_type"] != "postgresql":
        result = await adapter_for(runtime["database_type"]).select(runtime, sql, maximum)
        _require_response_size(result, int(_object(runtime["scope"].get("limits")).get("max_response_bytes") or DEFAULT_MAX_RESPONSE_BYTES))
        return result
    pool = await _target_pool(runtime)
    limits = _object(runtime["scope"].get("limits"))
    wrapped = f"SELECT * FROM ({sql}) AS hermes_scoped_query LIMIT {maximum + 1}"
    async with pool.acquire() as connection:
        async with connection.transaction(readonly=True):
            await _timeouts(connection, limits, runtime["scope"])
            rows = await connection.fetch(wrapped)
    truncated = len(rows) > maximum
    values = [_record(row) for row in rows[:maximum]]
    result = {"database": runtime["database"], "rows": values, "row_count": len(values), "truncated": truncated}
    maximum_bytes = int(limits.get("max_response_bytes") or DEFAULT_MAX_RESPONSE_BYTES)
    _require_response_size(result, maximum_bytes)
    return result


async def _timeouts(
    connection: asyncpg.Connection,
    limits: dict[str, Any],
    scope: dict[str, Any],
) -> None:
    statement = int(limits.get("statement_timeout_ms") or 5000)
    lock = int(limits.get("lock_timeout_ms") or 1000)
    await connection.execute("SELECT set_config('statement_timeout', $1, true)", f"{statement}ms")
    await connection.execute("SELECT set_config('lock_timeout', $1, true)", f"{lock}ms")
    # Unqualified relations are accepted only when they are unique inside the
    # frozen Scope. Pin search_path to pg_catalog plus those exact schemas so
    # PostgreSQL cannot resolve a same-named object from an out-of-scope schema.
    schemas = sorted(_object(scope.get("schemas")))
    search_path = ", ".join([_identifier("pg_catalog"), *(_identifier(item) for item in schemas)])
    await connection.execute("SELECT set_config('search_path', $1, true)", search_path)


def _require_response_size(value: dict[str, Any], maximum_bytes: int) -> None:
    if len(json.dumps(value, ensure_ascii=False, default=str).encode()) > maximum_bytes:
        raise ValueError("查询结果超过响应大小限制")


def _require_object(scope: dict[str, Any], schema: str, table: str) -> None:
    schemas = _object(scope.get("schemas"))
    definition = _schema_scope(schemas, schema)
    if table not in [*definition.get("tables", []), *definition.get("views", [])]:
        raise AccessDenied(f"对象 {schema}.{table} 不在 Scope")


def _schema_scope(schemas: dict[str, Any], schema: str) -> dict[str, Any]:
    value = schemas.get(schema)
    if not isinstance(value, dict):
        raise AccessDenied(f"Schema {schema} 不在 Scope")
    return value


def _require_permission(scope: dict[str, Any], permission: str) -> None:
    if not bool(_object(scope.get("permissions")).get(permission, False)):
        raise AccessDenied(f"当前 Scope 禁止 {permission}")


def _decrypt(value: str) -> dict[str, Any]:
    try:
        payload = json.loads(FERNET.decrypt(value.encode("ascii")).decode())
    except (InvalidToken, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("数据库凭据无法解密") from exc
    result = _object(payload)
    if not isinstance(result.get("username", ""), str) or not isinstance(result.get("password", ""), str):
        raise ValueError("数据库凭据格式无效")
    return result


def _object(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("请求对象格式无效")
    return value


def _stored_object(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("存储对象格式无效") from exc
    try:
        return _object(value)
    except ValueError as exc:
        raise ValueError("存储对象格式无效") from exc


def _required_text(value: dict[str, Any], field: str) -> str:
    item = value.get(field)
    if not isinstance(item, str) or not item:
        raise ValueError(f"缺少字段 {field}")
    return item


def _header(request: Request, name: str) -> str:
    value = request.headers.get(name)
    if not value:
        raise AccessDenied(f"缺少内部 Header {name}")
    return value


def _identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _record(row: asyncpg.Record) -> dict[str, Any]:
    return {key: _json_value(value) for key, value in row.items()}


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, bytes):
        return {"base64": base64.b64encode(value).decode("ascii")}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    return str(value)


def create_application():
    application = mcp.streamable_http_app()
    session_lifespan = application.router.lifespan_context

    @asynccontextmanager
    async def application_lifespan(app):
        await _ensure_resources()
        try:
            async with session_lifespan(app):
                yield
        finally:
            await _close_resources()

    application.router.lifespan_context = application_lifespan
    return application


app = create_application()


if __name__ == "__main__":
    mcp.run(transport="streamable-http")

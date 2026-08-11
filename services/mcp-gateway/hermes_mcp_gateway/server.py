from __future__ import annotations

import json
import logging
import os
import re
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, AsyncIterator

import asyncpg
from mcp.server.fastmcp import Context, FastMCP

from hermes_mcp_gateway.auth import MCPAccessClaims, MCPAccessDenied, verify_mcp_access_token

logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

FILES_ROOT = Path(os.environ.get("MCP_FILES_ROOT", "/data/files")).resolve()
SIGNING_KEY = os.environ["MCP_GATEWAY_SIGNING_KEY"]
if len(SIGNING_KEY) < 32:
    raise RuntimeError("MCP_GATEWAY_SIGNING_KEY must contain at least 32 characters")
MAX_FILE_BYTES = int(os.environ.get("MCP_MAX_FILE_BYTES", "262144"))
MAX_DATABASE_ROWS = int(os.environ.get("MCP_MAX_DATABASE_ROWS", "100"))
DATABASE_STATEMENT_TIMEOUT_MS = int(os.environ.get("MCP_DATABASE_STATEMENT_TIMEOUT_MS", "5000"))
ACCESS_TOKEN_TTL_SECONDS = int(os.environ.get("MCP_ACCESS_TOKEN_TTL_SECONDS", "300"))
if not 60 <= ACCESS_TOKEN_TTL_SECONDS <= 3600:
    raise RuntimeError("MCP_ACCESS_TOKEN_TTL_SECONDS must be between 60 and 3600")
READ_QUERY = re.compile(r"^(select|with)\b", re.IGNORECASE)


@asynccontextmanager
async def lifespan(_) -> AsyncIterator[dict[str, Any]]:
    FILES_ROOT.mkdir(parents=True, exist_ok=True)
    pool = await asyncpg.create_pool(
        host=os.environ.get("POSTGRES_HOST", "postgres"),
        port=int(os.environ.get("POSTGRES_PORT", "5432")),
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        database=os.environ["POSTGRES_DB"],
        min_size=1,
        max_size=5,
        command_timeout=10,
    )
    try:
        yield {"pool": pool}
    finally:
        await pool.close()


mcp = FastMCP(
    "Hermes Agent Platform MCP Gateway",
    instructions="Read-only filesystem and PostgreSQL tools with per-execution authorization.",
    host="0.0.0.0",
    port=8090,
    streamable_http_path="/mcp",
    json_response=True,
    stateless_http=True,
    lifespan=lifespan,
)


@mcp.tool()
async def filesystem_read(access_token: str, path: str, ctx: Context) -> str:
    """Read one UTF-8 text file below the configured root. Pass the exact access_token supplied in the task."""
    claims = await _authorize(access_token, ctx)
    started_at = _timestamp()
    mcp_id = await _require_capability(
        ctx,
        claims,
        "filesystem",
        "filesystem_read",
        {"path": path},
        started_at,
    )
    try:
        resolved = _resolve_file(path)
        size = resolved.stat().st_size
        if size > MAX_FILE_BYTES:
            raise ValueError(f"file exceeds {MAX_FILE_BYTES} bytes")
        content = resolved.read_text(encoding="utf-8")
        result = json.dumps({"path": path, "bytes": size, "content": content}, ensure_ascii=False)
        await _record_call(
            ctx,
            claims,
            mcp_id,
            "filesystem_read",
            "succeeded",
            {"path": path},
            {"bytes": size},
            started_at,
        )
        logger.info("MCP tool called: filesystem_read agent=%s execution=%s", claims.agent_id, claims.execution_id)
        return result
    except Exception as exc:
        await _record_call(
            ctx,
            claims,
            mcp_id,
            "filesystem_read",
            "failed",
            {"path": path},
            {"error": type(exc).__name__},
            started_at,
        )
        raise


@mcp.tool()
async def database_query(access_token: str, sql: str, ctx: Context) -> str:
    """Run one read-only PostgreSQL SELECT/WITH query. Pass the exact access_token supplied in the task."""
    claims = await _authorize(access_token, ctx)
    started_at = _timestamp()
    normalized = sql.strip().rstrip(";").strip()
    mcp_id = await _require_capability(
        ctx,
        claims,
        "database",
        "database_query",
        {"sql": normalized[:500]},
        started_at,
    )
    if not READ_QUERY.match(normalized) or ";" in normalized:
        raise ValueError("only one read-only SELECT or WITH statement is allowed")

    pool: asyncpg.Pool = ctx.request_context.lifespan_context["pool"]
    try:
        wrapped = f"SELECT * FROM ({normalized}) AS hermes_read_query LIMIT {MAX_DATABASE_ROWS + 1}"
        async with pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute("SET TRANSACTION READ ONLY")
                await connection.execute(f"SET LOCAL statement_timeout = {DATABASE_STATEMENT_TIMEOUT_MS}")
                records = await connection.fetch(wrapped)
        truncated = len(records) > MAX_DATABASE_ROWS
        records = records[:MAX_DATABASE_ROWS]
        rows = [{key: _json_value(value) for key, value in record.items()} for record in records]
        result = json.dumps(
            {"rows": rows, "row_count": len(rows), "truncated": truncated},
            ensure_ascii=False,
        )
        await _record_call(
            ctx,
            claims,
            mcp_id,
            "database_query",
            "succeeded",
            {"sql": normalized[:500]},
            {"row_count": len(rows), "truncated": truncated},
            started_at,
        )
        logger.info("MCP tool called: database_query agent=%s execution=%s", claims.agent_id, claims.execution_id)
        return result
    except Exception as exc:
        await _record_call(
            ctx,
            claims,
            mcp_id,
            "database_query",
            "failed",
            {"sql": normalized[:500]},
            {"error": type(exc).__name__},
            started_at,
        )
        raise


async def _authorize(access_token: str, ctx: Context) -> MCPAccessClaims:
    execution_id = verify_mcp_access_token(access_token, SIGNING_KEY)
    pool: asyncpg.Pool = ctx.request_context.lifespan_context["pool"]
    record = await pool.fetchrow(
        """
        SELECT agent_id, status, started_at, details->>'mcp_permissions' AS permissions
        FROM execution_logs
        WHERE id = $1::uuid
        """,
        execution_id,
    )
    if record is None or record["status"] != "running":
        raise MCPAccessDenied("access denied: MCP execution is not active")
    if record["started_at"] < datetime.now(timezone.utc) - timedelta(seconds=ACCESS_TOKEN_TTL_SECONDS):
        raise MCPAccessDenied("access denied: MCP access token expired")
    try:
        permissions = json.loads(record["permissions"] or "{}")
    except json.JSONDecodeError as exc:
        raise MCPAccessDenied("access denied: invalid MCP permission snapshot") from exc
    if not isinstance(permissions, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in permissions.items()
    ):
        raise MCPAccessDenied("access denied: invalid MCP permission snapshot")
    return MCPAccessClaims(
        agent_id=record["agent_id"],
        execution_id=execution_id,
        mcp=permissions,
    )


async def _require_capability(
    ctx: Context,
    claims: MCPAccessClaims,
    capability: str,
    tool: str,
    input_summary: dict[str, Any],
    started_at: str,
) -> str:
    try:
        return claims.require(capability)
    except MCPAccessDenied:
        await _record_call(
            ctx,
            claims,
            None,
            tool,
            "denied",
            input_summary,
            {"error": "MCPAccessDenied", "capability": capability},
            started_at,
        )
        logger.warning(
            "MCP tool denied: %s agent=%s execution=%s capability=%s",
            tool,
            claims.agent_id,
            claims.execution_id,
            capability,
        )
        raise


def _resolve_file(relative_path: str) -> Path:
    candidate = Path(relative_path)
    if candidate.is_absolute():
        raise ValueError("absolute paths are not allowed")
    resolved = (FILES_ROOT / candidate).resolve()
    try:
        resolved.relative_to(FILES_ROOT)
    except ValueError as exc:
        raise ValueError("path escapes the configured filesystem root") from exc
    if not resolved.is_file():
        raise FileNotFoundError(f"file does not exist: {relative_path}")
    return resolved


async def _record_call(
    ctx: Context,
    claims: MCPAccessClaims,
    mcp_id: str | None,
    tool: str,
    status: str,
    input_summary: dict[str, Any],
    result_summary: dict[str, Any],
    started_at: str,
) -> None:
    event = {
        "mcp_id": mcp_id,
        "tool": tool,
        "status": status,
        "input": input_summary,
        "result": result_summary,
        "started_at": started_at,
        "finished_at": _timestamp(),
    }
    pool: asyncpg.Pool = ctx.request_context.lifespan_context["pool"]
    await pool.execute(
        """
        UPDATE execution_logs
        SET details = jsonb_set(
            COALESCE(details, '{}'::jsonb),
            '{mcp_calls}',
            COALESCE(details->'mcp_calls', '[]'::jsonb) || $1::jsonb,
            true
        )
        WHERE id = $2::uuid AND agent_id = $3
        """,
        json.dumps([event], ensure_ascii=False),
        claims.execution_id,
        claims.agent_id,
    )


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    mcp.run(transport="streamable-http")

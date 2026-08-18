from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import os
import re
import socket
import uuid
from datetime import datetime, timezone
from time import monotonic
from typing import Any
from urllib.parse import urljoin, urlparse

import asyncpg
import httpx
from cryptography.fernet import Fernet, InvalidToken
from jsonschema import ValidationError, validate
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from starlette.requests import Request
from starlette.responses import JSONResponse

from hermes_mcp_gateway.auth import MCPAccessDenied, renew_capability_token, verify_capability_token


logger = logging.getLogger(__name__)

STANDARD_ERRORS = {
    "INVALID_ARGUMENT": 422,
    "NOT_FOUND": 404,
    "PERMISSION_DENIED": 403,
    "CONFLICT": 409,
    "RATE_LIMITED": 429,
    "PROVIDER_UNAVAILABLE": 502,
    "TIMEOUT": 504,
    "OUTPUT_INVALID": 502,
    "INTERNAL_ERROR": 500,
}
PROTECTED_FIELDS = {
    "endpoint",
    "credential_ref",
    "connector_instance_id",
    "implementation_id",
    "resource_scope",
    "access_token",
    "api_key",
}
SAFE_HEADER = re.compile(r"^[A-Za-z][A-Za-z0-9-]{0,63}$")
MAX_RESPONSE_BYTES = int(os.getenv("CAPABILITY_MAX_RESPONSE_BYTES", "2097152"))


class GatewayError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


async def resolve_capabilities(
    request: Request,
    *,
    pool: asyncpg.Pool,
    redis_client: Any,
    signing_key: str,
) -> JSONResponse:
    try:
        token = _bearer(request.headers.get("authorization"))
        claims = verify_capability_token(token, signing_key)
        await _ensure_not_revoked(redis_client, claims)
        try:
            payload = await request.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise GatewayError("INVALID_ARGUMENT", "请求必须是 JSON 对象") from exc
        if not isinstance(payload, dict):
            raise GatewayError("INVALID_ARGUMENT", "请求必须是 JSON 对象")
        execution_id = str(payload.get("execution_id") or "")
        if execution_id != claims["execution_id"]:
            raise GatewayError("INVALID_ARGUMENT", "execution_id 与 Execution Token 不匹配")
        await _authorized_execution(pool, execution_id, claims)
        rows = await pool.fetch(
            """
            SELECT b.id::text AS binding_id, b.tool_alias, c.key AS capability_key,
                   c.display_name, c.description, cv.version, cv.input_schema,
                   cv.output_schema, cv.side_effect, cv.idempotency
            FROM agent_capability_bindings b
            JOIN capability_versions cv ON cv.id = b.capability_version_id
            JOIN capabilities c ON c.id = cv.capability_id
            WHERE b.agent_version_id = $1::uuid
              AND b.enabled
              AND b.id::text = ANY($2::text[])
            ORDER BY b.tool_alias
            """,
            claims["agent_version_id"],
            claims["allowed_bindings"],
        )
        return JSONResponse(
            {
                "status": "SUCCEEDED",
                "execution_id": execution_id,
                "resolution_digest": claims["resolution_digest"],
                "tools": [
                    {
                        "binding_id": row["binding_id"],
                        "tool_name": row["tool_alias"],
                        "capability": row["capability_key"],
                        "version": row["version"],
                        "description": row["description"] or row["display_name"],
                        "input_schema": _json_object(row["input_schema"]),
                        "output_schema": _json_object(row["output_schema"]),
                        "side_effect": row["side_effect"],
                        "idempotency": row["idempotency"],
                    }
                    for row in rows
                ],
            }
        )
    except MCPAccessDenied as exc:
        return _error("PERMISSION_DENIED", str(exc), None)
    except GatewayError as exc:
        return _error(exc.code, exc.message, None)
    except Exception:
        return _error("INTERNAL_ERROR", "Capability Gateway 内部错误", None)


async def invoke_capability(
    request: Request,
    *,
    pool: asyncpg.Pool,
    redis_client: Any,
    signing_key: str,
) -> JSONResponse:
    invocation_id: uuid.UUID | None = None
    started = monotonic()
    try:
        token = _bearer(request.headers.get("authorization"))
        claims = verify_capability_token(token, signing_key)
        await _ensure_not_revoked(redis_client, claims)
        try:
            payload = await request.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise GatewayError("INVALID_ARGUMENT", "请求必须是 JSON 对象") from exc
        if not isinstance(payload, dict):
            raise GatewayError("INVALID_ARGUMENT", "请求必须是 JSON 对象")
        execution_id = str(payload.get("execution_id") or "")
        tool_name = str(payload.get("tool_name") or "")
        arguments = payload.get("arguments")
        if execution_id != claims["execution_id"] or not tool_name or not isinstance(arguments, dict):
            raise GatewayError("INVALID_ARGUMENT", "execution_id、tool_name 或 arguments 无效")
        execution = await _authorized_execution(pool, execution_id, claims)

        binding = await pool.fetchrow(
            """
            SELECT b.*, cv.version AS capability_version, cv.input_schema, cv.output_schema,
                   cv.side_effect, cv.idempotency, cv.default_timeout_ms,
                   c.key AS capability_key
            FROM agent_capability_bindings b
            JOIN capability_versions cv ON cv.id = b.capability_version_id
            JOIN capabilities c ON c.id = cv.capability_id
            WHERE b.agent_version_id = $1::uuid AND b.tool_alias = $2 AND b.enabled
            """,
            claims["agent_version_id"],
            tool_name,
        )
        if binding is None or str(binding["id"]) not in claims["allowed_bindings"]:
            raise GatewayError("PERMISSION_DENIED", "当前 Agent Version 未绑定该能力")
        implementation = await _implementation(pool, binding)
        if implementation is None:
            raise GatewayError("PROVIDER_UNAVAILABLE", "能力没有可用实现")
        provider = await pool.fetchrow(
            """
            SELECT o.protocol, o.method, o.path_or_tool, o.request_mapping, o.response_mapping,
                   o.error_mapping, o.side_effect AS operation_side_effect,
                   r.id AS revision_id, r.endpoint, r.auth_type, r.credential_ref,
                   r.network_zone, r.connection_config, r.timeout_policy, r.retry_policy,
                   i.enabled, i.health_status, cred.encrypted_payload,
                   scope.scope_definition
            FROM connector_operations o
            JOIN connector_instance_revisions r ON r.id = $2::uuid
            JOIN connector_instances i ON i.id = r.connector_instance_id
            LEFT JOIN connector_credentials cred ON cred.id = r.credential_ref
            LEFT JOIN resource_scope_revisions scope ON scope.id = $3::uuid
            WHERE o.id = $1::uuid
            """,
            implementation["connector_operation_id"],
            implementation["connector_instance_revision_id"],
            binding["resource_scope_revision_id"],
        )
        if provider is None or not provider["enabled"] or provider["health_status"] == "offline":
            raise GatewayError("PROVIDER_UNAVAILABLE", "Connector 当前不可用")
        await _enforce_approval(binding, execution)
        await _enforce_quota(pool, binding, provider, execution_id)
        try:
            validate(arguments, _json_object(binding["input_schema"]))
        except ValidationError as exc:
            raise GatewayError("INVALID_ARGUMENT", f"Capability 输入不符合契约：{exc.message}") from exc
        scoped_arguments = _apply_policy(
            arguments,
            _json_object(binding["parameter_policy"]),
            _json_object(provider["scope_definition"]) if provider["scope_definition"] else None,
        )
        invocation_id = uuid.uuid4()
        await pool.execute(
            """
            INSERT INTO capability_invocations
                (id, execution_id, agent_id, agent_version_id, binding_id,
                 capability_key, capability_version, tool_alias,
                 connector_instance_revision_id, resource_scope_revision_id,
                 status, input_summary)
            VALUES ($1, $2::uuid, $3, $4::uuid, $5::uuid, $6, $7, $8,
                    $9::uuid, $10::uuid, 'PENDING', $11::jsonb)
            """,
            invocation_id,
            execution_id,
            claims["agent_id"],
            claims["agent_version_id"],
            binding["id"],
            binding["capability_key"],
            binding["capability_version"],
            tool_name,
            implementation["connector_instance_revision_id"],
            binding["resource_scope_revision_id"],
            json.dumps(_summary(scoped_arguments)),
        )
        secret = _decrypt(provider["encrypted_payload"]) if provider["encrypted_payload"] else None
        result = await _invoke_provider(
            provider,
            scoped_arguments,
            secret,
            token,
            idempotency=str(binding["idempotency"]),
        )
        mapped = _map_response(result, _json_object(provider["response_mapping"]))
        try:
            validate(mapped, _json_object(binding["output_schema"]))
        except ValidationError as exc:
            raise GatewayError("OUTPUT_INVALID", f"Connector 输出不符合契约：{exc.message}") from exc
        latency = max(0, round((monotonic() - started) * 1000))
        await _finish(pool, invocation_id, "SUCCEEDED", latency, output=_summary(mapped))
        await _trace(pool, execution_id, invocation_id, binding, "succeeded", latency)
        token_renewal = None
        if int(claims["exp"]) - int(datetime.now(timezone.utc).timestamp()) < int(
            os.getenv("CAPABILITY_TOKEN_RENEW_BEFORE_SECONDS", "120")
        ):
            token_renewal = renew_capability_token(
                claims,
                signing_key,
                ttl_seconds=int(os.getenv("CAPABILITY_TOKEN_TTL_SECONDS", "600")),
            )
        return JSONResponse(
            {
                "invocation_id": str(invocation_id),
                "status": "SUCCEEDED",
                "data": mapped,
                "metadata": {
                    "capability": binding["capability_key"],
                    "version": binding["capability_version"],
                    "latency_ms": latency,
                    "provider_revision": str(implementation["connector_instance_revision_id"]),
                    "cache_hit": False,
                    "token_renewal": token_renewal,
                },
            }
        )
    except MCPAccessDenied as exc:
        return _error("PERMISSION_DENIED", str(exc), None)
    except GatewayError as exc:
        if invocation_id is not None:
            latency = max(0, round((monotonic() - started) * 1000))
            await _finish(pool, invocation_id, "DENIED" if exc.code == "PERMISSION_DENIED" else "FAILED", latency, error=exc.code)
        return _error(exc.code, exc.message, invocation_id)
    except httpx.TimeoutException:
        if invocation_id is not None:
            await _finish(pool, invocation_id, "FAILED", max(0, round((monotonic() - started) * 1000)), error="TIMEOUT")
        return _error("TIMEOUT", "Connector 调用超时", invocation_id)
    except httpx.HTTPError:
        if invocation_id is not None:
            await _finish(pool, invocation_id, "FAILED", max(0, round((monotonic() - started) * 1000)), error="PROVIDER_UNAVAILABLE")
        return _error("PROVIDER_UNAVAILABLE", "Connector 调用失败", invocation_id)
    except Exception:
        logger.exception("Capability invocation failed unexpectedly invocation=%s", invocation_id)
        if invocation_id is not None:
            await _finish(pool, invocation_id, "FAILED", max(0, round((monotonic() - started) * 1000)), error="INTERNAL_ERROR")
        return _error("INTERNAL_ERROR", "Capability Gateway 内部错误", invocation_id)


async def _implementation(pool: asyncpg.Pool, binding: asyncpg.Record) -> asyncpg.Record | None:
    if binding["implementation_id"]:
        return await pool.fetchrow(
            "SELECT * FROM capability_implementations WHERE id = $1::uuid AND status = 'active'",
            binding["implementation_id"],
        )
    return await pool.fetchrow(
        """
        SELECT * FROM capability_implementations
        WHERE capability_version_id = $1::uuid AND status = 'active'
        ORDER BY priority, created_at LIMIT 1
        """,
        binding["capability_version_id"],
    )


async def _ensure_not_revoked(redis_client: Any, claims: dict[str, Any]) -> None:
    if redis_client is not None and await redis_client.exists(
        f"hermes:capability-token:revoked:{claims['jti']}"
    ):
        raise GatewayError("PERMISSION_DENIED", "Execution Token 已撤销")


async def _authorized_execution(
    pool: asyncpg.Pool,
    execution_id: str,
    claims: dict[str, Any],
) -> asyncpg.Record:
    execution = await pool.fetchrow(
        """
        SELECT e.agent_id, e.agent_version_id, e.status, e.details, av.resolution_digest
        FROM execution_logs e
        LEFT JOIN agent_versions av ON av.id = e.agent_version_id
        WHERE e.id = $1::uuid
        """,
        execution_id,
    )
    if execution is None or execution["status"] != "running":
        raise GatewayError("PERMISSION_DENIED", "Execution 当前不可调用能力")
    if (
        execution["agent_id"] != claims["agent_id"]
        or str(execution["agent_version_id"]) != claims["agent_version_id"]
        or execution["resolution_digest"] != claims["resolution_digest"]
    ):
        raise GatewayError("PERMISSION_DENIED", "Execution Token 与执行快照不匹配")
    return execution


async def _enforce_approval(binding: asyncpg.Record, execution: asyncpg.Record) -> None:
    policy = _json_object(binding["approval_policy"])
    mode = str(policy.get("mode") or policy.get("type") or "NONE").upper()
    required = bool(policy.get("required")) or mode not in {"", "NONE", "DISABLED"}
    if not required:
        return
    details = _json_object(execution["details"])
    approvals = details.get("capability_approvals")
    approved_ids: set[str] = set()
    if isinstance(approvals, list):
        for item in approvals:
            if isinstance(item, str):
                approved_ids.add(item)
            elif isinstance(item, dict) and str(item.get("status") or "").lower() == "approved":
                approved_ids.add(str(item.get("binding_id") or ""))
    if str(binding["id"]) not in approved_ids:
        raise GatewayError("PERMISSION_DENIED", "Capability 调用需要先完成审批")


async def _enforce_quota(
    pool: asyncpg.Pool,
    binding: asyncpg.Record,
    provider: asyncpg.Record,
    execution_id: str,
) -> None:
    quota = _json_object(binding["quota_policy"])
    calls_per_execution = int(quota.get("calls_per_execution") or 20)
    calls_per_minute = int(quota.get("calls_per_minute") or 60)
    max_concurrency = int(quota.get("max_concurrency") or 2)
    execution_count, minute_count, active_count = await pool.fetchrow(
        """
        SELECT
          count(*) FILTER (WHERE execution_id = $2::uuid),
          count(*) FILTER (WHERE created_at >= now() - interval '1 minute'),
          count(*) FILTER (WHERE status = 'PENDING')
        FROM capability_invocations WHERE binding_id = $1::uuid
        """,
        binding["id"],
        execution_id,
    )
    if execution_count >= calls_per_execution or minute_count >= calls_per_minute or active_count >= max_concurrency:
        raise GatewayError("RATE_LIMITED", "Capability 调用达到配额或并发上限")
    instance_quota = _json_object(_json_object(provider["connection_config"]).get("quota_policy"))
    instance_calls_per_minute = int(instance_quota.get("calls_per_minute") or 600)
    instance_max_concurrency = int(instance_quota.get("max_concurrency") or 20)
    instance_minute_count, instance_active_count = await pool.fetchrow(
        """
        SELECT
          count(*) FILTER (WHERE created_at >= now() - interval '1 minute'),
          count(*) FILTER (WHERE status = 'PENDING')
        FROM capability_invocations
        WHERE connector_instance_revision_id = $1::uuid
        """,
        provider["revision_id"],
    )
    if (
        instance_minute_count >= instance_calls_per_minute
        or instance_active_count >= instance_max_concurrency
    ):
        raise GatewayError("RATE_LIMITED", "Connector Instance 达到全局配额或并发上限")


def _apply_policy(arguments: dict[str, Any], policy: dict[str, Any], scope: dict[str, Any] | None) -> dict[str, Any]:
    value = json.loads(json.dumps(arguments))
    forbidden = PROTECTED_FIELDS | {str(item) for item in policy.get("forbidden_fields", [])}
    present = sorted(_protected_paths(value, forbidden))
    if present:
        raise GatewayError("PERMISSION_DENIED", f"禁止传入参数：{', '.join(present)}")
    for field in policy.get("required_fields", []):
        if str(field) not in value:
            raise GatewayError("INVALID_ARGUMENT", f"缺少必填参数 {field}")
    for field, choices in (policy.get("allowed_values") or {}).items():
        if field in value and value[field] not in choices:
            raise GatewayError("PERMISSION_DENIED", f"参数 {field} 不在允许范围")
    for field, limit in (policy.get("maximum") or {}).items():
        if field in value and value[field] > limit:
            raise GatewayError("PERMISSION_DENIED", f"参数 {field} 超过上限")
    for field, limit in (policy.get("minimum") or {}).items():
        if field in value and value[field] < limit:
            raise GatewayError("PERMISSION_DENIED", f"参数 {field} 低于下限")
    value.update(policy.get("fixed") or {})
    value.update(policy.get("injected_fields") or {})
    if scope:
        value["resource_scope"] = scope
    return value


def _protected_paths(value: Any, forbidden: set[str], prefix: str = "") -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if str(key).lower() in {name.lower() for name in forbidden}:
                found.add(path)
            found.update(_protected_paths(item, forbidden, path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.update(_protected_paths(item, forbidden, f"{prefix}[{index}]"))
    return found


async def _invoke_provider(
    provider: asyncpg.Record,
    arguments: dict[str, Any],
    secret: str | None,
    execution_token: str,
    *,
    idempotency: str,
) -> Any:
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    auth_type = provider["auth_type"]
    config = _json_object(provider["connection_config"])
    if secret and auth_type == "bearer":
        headers["Authorization"] = f"Bearer {secret}"
    elif secret and auth_type == "header":
        name = str(config.get("auth_header") or "X-API-Key")
        if not SAFE_HEADER.fullmatch(name) or name.lower() in {"host", "connection", "content-length"}:
            raise GatewayError("INVALID_ARGUMENT", "Connector 鉴权 Header 不安全")
        headers[name] = secret
    endpoint = str(provider["endpoint"])
    await _validate_network(endpoint, str(provider["network_zone"]), config)
    request_data = _map_request(arguments, _json_object(provider["request_mapping"]))
    timeout_policy = _json_object(provider["timeout_policy"])
    timeout = httpx.Timeout(
        float(timeout_policy.get("read_seconds") or 15),
        connect=float(timeout_policy.get("connect_seconds") or 5),
    )
    if provider["protocol"] == "mcp":
        if auth_type == "execution_capability":
            request_data["access_token"] = execution_token
        async with httpx.AsyncClient(headers=headers, timeout=timeout, trust_env=False) as mcp_http:
            async with streamable_http_client(endpoint, http_client=mcp_http) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(str(provider["path_or_tool"]), request_data)
        if result.isError:
            raise GatewayError("PROVIDER_UNAVAILABLE", "MCP Tool 返回错误")
        texts = [item.text for item in result.content if getattr(item, "type", None) == "text"]
        if len(texts) == 1:
            try:
                return json.loads(texts[0])
            except (ValueError, json.JSONDecodeError):
                return {"content": texts[0]}
        return {"content": texts}
    operation_path = str(provider["path_or_tool"])
    parsed_operation = urlparse(operation_path)
    if parsed_operation.scheme or parsed_operation.netloc:
        raise GatewayError("PERMISSION_DENIED", "Connector Operation 不允许覆盖 Endpoint Host")
    url = urljoin(endpoint.rstrip("/") + "/", operation_path.lstrip("/"))
    base_url = urlparse(endpoint)
    target_url = urlparse(url)
    if (target_url.scheme, target_url.hostname, target_url.port) != (
        base_url.scheme,
        base_url.hostname,
        base_url.port,
    ):
        raise GatewayError("PERMISSION_DENIED", "Connector Operation 不允许跨 Host")
    await _validate_network(url, str(provider["network_zone"]), config)
    method = str(provider["method"] or "POST").upper()
    retries = int(_json_object(provider["retry_policy"]).get("max_retries") or 0)
    if (
        provider["operation_side_effect"] != "READ_ONLY"
        and idempotency not in {"SAFE_RETRY", "IDEMPOTENT"}
    ):
        retries = 0
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False) as client:
        response_status: int | None = None
        response_headers: dict[str, str] = {}
        content = b""
        for attempt in range(min(retries, 2) + 1):
            try:
                should_retry = False
                async with client.stream(
                    method,
                    url,
                    headers=headers,
                    params=request_data if method == "GET" else None,
                    json=request_data if method != "GET" else None,
                ) as response:
                    response_status = response.status_code
                    response_headers = dict(response.headers)
                    if response.status_code in {429} or response.status_code >= 500:
                        should_retry = attempt < retries
                    if not should_retry:
                        content = await _read_limited_response(response)
                if not should_retry:
                    break
            except httpx.TimeoutException:
                if attempt >= retries:
                    raise
            await asyncio.sleep(0.2 * (attempt + 1))
    assert response_status is not None
    if response_status == 429:
        raise GatewayError("RATE_LIMITED", "Connector 返回限流")
    if response_status >= 500:
        raise GatewayError("PROVIDER_UNAVAILABLE", f"Connector 返回 HTTP {response_status}")
    if response_status >= 400:
        raise GatewayError("INVALID_ARGUMENT", f"Connector 拒绝请求，HTTP {response_status}")
    content_type = response_headers.get("content-type", "")
    if "json" not in content_type.lower():
        raise GatewayError("OUTPUT_INVALID", "首版 REST Adapter 只接受 JSON 响应")
    try:
        return json.loads(content)
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise GatewayError("OUTPUT_INVALID", "Connector 返回的 JSON 无效") from exc


async def _read_limited_response(response: httpx.Response) -> bytes:
    chunks: list[bytes] = []
    size = 0
    async for chunk in response.aiter_bytes():
        size += len(chunk)
        if size > MAX_RESPONSE_BYTES:
            raise GatewayError("OUTPUT_INVALID", "Connector 响应超过大小限制")
        chunks.append(chunk)
    return b"".join(chunks)


async def _validate_network(endpoint: str, zone: str, config: dict[str, Any]) -> None:
    parsed = urlparse(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise GatewayError("INVALID_ARGUMENT", "Connector Endpoint 无效")
    allowed_hosts = config.get("allowed_hosts")
    if isinstance(allowed_hosts, list) and allowed_hosts and parsed.hostname not in allowed_hosts:
        raise GatewayError("PERMISSION_DENIED", "Connector Host 不在白名单")
    try:
        addresses = await asyncio.to_thread(socket.getaddrinfo, parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
    except OSError as exc:
        raise GatewayError("PROVIDER_UNAVAILABLE", "Connector DNS 解析失败") from exc
    for entry in addresses:
        address = ipaddress.ip_address(entry[4][0])
        if address.is_link_local or address.is_multicast or address.is_unspecified or str(address) == "169.254.169.254":
            raise GatewayError("PERMISSION_DENIED", "Connector 地址被 SSRF 策略拒绝")
        if zone == "dmz" and (address.is_private or address.is_loopback):
            raise GatewayError("PERMISSION_DENIED", "DMZ Connector 不允许访问内网地址")


def _map_request(arguments: dict[str, Any], mapping: dict[str, Any]) -> dict[str, Any]:
    fields = mapping.get("fields") if isinstance(mapping.get("fields"), dict) else {}
    dropped = {str(item) for item in mapping.get("drop", [])}
    value = {str(fields.get(key) or key): item for key, item in arguments.items() if key != "resource_scope" and key not in dropped}
    value.update(mapping.get("fixed") if isinstance(mapping.get("fixed"), dict) else {})
    scope_target = mapping.get("scope_target")
    if scope_target and arguments.get("resource_scope") is not None:
        value[str(scope_target)] = arguments["resource_scope"]
    return value


def _json_object(value: Any) -> dict[str, Any]:
    """Normalize JSONB returned by asyncpg, which is text without a custom codec."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except (ValueError, json.JSONDecodeError):
            return {}
        return decoded if isinstance(decoded, dict) else {}
    try:
        return dict(value) if value is not None else {}
    except (TypeError, ValueError):
        return {}


def _map_response(result: Any, mapping: dict[str, Any]) -> Any:
    if not mapping:
        return result
    source = result
    root = mapping.get("root")
    if isinstance(root, str):
        source = _read_path(result, root)
    fields = mapping.get("fields") if isinstance(mapping.get("fields"), dict) else {}
    if not fields:
        return source
    return {target: _read_path(source, str(path)) for target, path in fields.items()}


def _read_path(value: Any, path: str) -> Any:
    current = value
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def _decrypt(ciphertext: str) -> str:
    key = os.getenv("MODEL_REGISTRY_ENCRYPTION_KEY") or os.getenv("CONNECTOR_REGISTRY_ENCRYPTION_KEY")
    if not key:
        raise GatewayError("PROVIDER_UNAVAILABLE", "Connector 凭据加密主密钥未配置")
    try:
        return Fernet(key.strip().encode("ascii")).decrypt(ciphertext.encode("ascii")).decode()
    except (ValueError, InvalidToken, UnicodeError) as exc:
        raise GatewayError("PROVIDER_UNAVAILABLE", "Connector 凭据无法解密") from exc


async def _finish(
    pool: asyncpg.Pool,
    invocation_id: uuid.UUID,
    status: str,
    latency: int,
    *,
    output: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    await pool.execute(
        """
        UPDATE capability_invocations SET status=$2, latency_ms=$3,
            output_summary=$4::jsonb, error_code=$5, finished_at=now()
        WHERE id=$1
        """,
        invocation_id,
        status,
        latency,
        json.dumps(output or {}),
        error,
    )


async def _trace(
    pool: asyncpg.Pool,
    execution_id: str,
    invocation_id: uuid.UUID,
    binding: asyncpg.Record,
    status: str,
    latency: int,
) -> None:
    event = {
        "event": "connector_invoked",
        "invocation_id": str(invocation_id),
        "capability": binding["capability_key"],
        "tool_name": binding["tool_alias"],
        "status": status,
        "latency_ms": latency,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    await pool.execute(
        """
        UPDATE execution_logs SET details = jsonb_set(
          COALESCE(details, '{}'::jsonb), '{capability_events}',
          COALESCE(details->'capability_events', '[]'::jsonb) || $1::jsonb, true
        ) WHERE id=$2::uuid
        """,
        json.dumps([event]),
        execution_id,
    )


def _summary(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return {
            key: ("[REDACTED]" if any(part in key.lower() for part in ("token", "secret", "password", "api_key")) else _bounded(item))
            for key, item in list(value.items())[:50]
            if key != "resource_scope"
        }
    return {"value": _bounded(value)}


def _bounded(value: Any) -> Any:
    if isinstance(value, str):
        return value[:500]
    if isinstance(value, list):
        return [_bounded(item) for item in value[:20]]
    if isinstance(value, dict):
        return {str(key): _bounded(item) for key, item in list(value.items())[:20]}
    return value if value is None or isinstance(value, (bool, int, float)) else str(value)[:500]


def _bearer(value: str | None) -> str:
    if not value or not value.startswith("Bearer "):
        raise MCPAccessDenied("access denied: missing bearer token")
    return value[7:].strip()


def _error(code: str, message: str, invocation_id: uuid.UUID | None) -> JSONResponse:
    return JSONResponse(
        {
            "invocation_id": str(invocation_id) if invocation_id else None,
            "status": "FAILED",
            "error": {"code": code, "message": message},
        },
        status_code=STANDARD_ERRORS.get(code, 500),
    )

from __future__ import annotations

import base64
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any


TOOL_ALIAS = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,127}$")
MAX_TOOLS = 100
MAX_RESPONSE_BYTES = int(os.getenv("HERMES_CAPABILITY_MAX_RESPONSE_BYTES", "2097152"))
CAPABILITY_ENDPOINT = os.getenv(
    "CAPABILITY_GATEWAY_ENDPOINT",
    "http://mcp-gateway:8090/internal/capabilities/invoke",
).rstrip("/")
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_LOCK = threading.RLock()
_BINDINGS: dict[str, "RunBinding"] = {}
_ALIASES: dict[str, int] = {}
_RENEWER_STARTED = False


class PlatformCapabilityError(RuntimeError):
    pass


@dataclass
class RunBinding:
    run_id: str
    session_id: str
    execution_id: str
    token: str
    tools: dict[str, dict[str, Any]]
    active: bool = True
    lock: threading.Lock = field(default_factory=threading.Lock)


def pop_platform_context(body: dict[str, Any]) -> dict[str, Any] | None:
    """Remove the internal context from a /v1/runs request and validate it."""
    if not isinstance(body, dict):
        raise PlatformCapabilityError("request body must be an object")
    metadata = body.get("metadata")
    if not isinstance(metadata, dict):
        return None
    runtime_options = metadata.get("runtime_options")
    if not isinstance(runtime_options, dict):
        return None
    raw = runtime_options.pop("platform_context", None)
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise PlatformCapabilityError("platform_context must be an object")
    raw_metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
    raw_tools = raw.get("capability_tools")
    if not isinstance(raw_tools, list):
        raw_tools = raw_metadata.get("capability_tools")
    tools = [item for item in (raw_tools or []) if isinstance(item, dict)]
    if len(tools) > MAX_TOOLS:
        raise PlatformCapabilityError("too many platform Capability tools")
    sanitized: list[dict[str, Any]] = []
    for tool in tools:
        name = tool.get("tool_name")
        schema = tool.get("input_schema")
        if not isinstance(name, str) or not TOOL_ALIAS.fullmatch(name):
            raise PlatformCapabilityError("invalid platform Capability alias")
        if not isinstance(schema, dict) or schema.get("type") != "object":
            raise PlatformCapabilityError("invalid platform Capability input schema")
        sanitized.append(
            {
                "tool_name": name,
                "description": str(tool.get("description") or name),
                "input_schema": schema,
            }
        )
    raw_token = raw.get("capability_token") or raw_metadata.get("capability_token") or ""
    token = raw_token if isinstance(raw_token, str) else ""
    execution_id = raw_metadata.get("execution_id")
    if not isinstance(execution_id, str) or not execution_id:
        raise PlatformCapabilityError("platform Capability execution_id is missing")
    if sanitized and not token:
        raise PlatformCapabilityError("platform Capability Token is missing")
    return {"execution_id": execution_id, "token": token, "tools": sanitized}


def register_run(
    run_id: str,
    session_id: str,
    context: dict[str, Any] | None,
) -> None:
    if context is None or not context.get("tools"):
        return
    tools = {str(item["tool_name"]): item for item in context["tools"]}
    binding = RunBinding(
        run_id=run_id,
        session_id=session_id,
        execution_id=str(context["execution_id"]),
        token=str(context["token"]),
        tools=tools,
    )
    registered: list[str] = []
    from tools.registry import registry

    with _LOCK:
        if run_id in _BINDINGS or (session_id != run_id and session_id in _BINDINGS):
            raise PlatformCapabilityError("Hermes Capability run identity is already active")
        try:
            for alias in tools:
                existing = registry.get_entry(alias)
                if existing is not None and existing.toolset != "mcp-hermes-platform":
                    raise PlatformCapabilityError(f"Capability alias conflicts with Hermes tool: {alias}")
                if alias not in _ALIASES:
                    registry.register(
                        name=alias,
                        toolset="mcp-hermes-platform",
                        schema={
                            "name": alias,
                            "description": "Platform-scoped Capability",
                            "parameters": {"type": "object", "properties": {}, "additionalProperties": True},
                        },
                        handler=_handler(alias),
                    )
                    _ALIASES[alias] = 0
                    registered.append(alias)
                _ALIASES[alias] += 1
            _BINDINGS[run_id] = binding
            if session_id != run_id:
                _BINDINGS[session_id] = binding
            _start_renewer()
        except Exception:
            for alias in tools:
                if alias in _ALIASES and _ALIASES[alias] > 0:
                    _ALIASES[alias] -= 1
                if alias in registered and _ALIASES.get(alias) == 0:
                    _ALIASES.pop(alias, None)
                    registry.deregister(alias)
            raise


def attach_run_tools(agent: Any, run_id: str) -> None:
    with _LOCK:
        binding = _BINDINGS.get(run_id)
        if binding is None:
            return
        definitions = [
            {
                "type": "function",
                "function": {
                    "name": tool["tool_name"],
                    "description": tool["description"],
                    "parameters": tool["input_schema"],
                },
            }
            for tool in binding.tools.values()
        ]
    existing = {
        item.get("function", {}).get("name")
        for item in (getattr(agent, "tools", None) or [])
        if isinstance(item, dict)
    }
    collisions = sorted(item["function"]["name"] for item in definitions if item["function"]["name"] in existing)
    if collisions:
        raise PlatformCapabilityError(f"Capability alias already exists in Hermes Agent: {', '.join(collisions)}")
    agent.tools = [*(getattr(agent, "tools", None) or []), *definitions]
    valid = set(getattr(agent, "valid_tool_names", None) or ())
    valid.update(item["function"]["name"] for item in definitions)
    agent.valid_tool_names = valid
    enabled = getattr(agent, "enabled_toolsets", None)
    if enabled is not None and "mcp-hermes-platform" not in enabled:
        agent.enabled_toolsets = [*enabled, "mcp-hermes-platform"]
    disabled = getattr(agent, "disabled_toolsets", None)
    if disabled is not None and "mcp-hermes-platform" in disabled:
        agent.disabled_toolsets = [item for item in disabled if item != "mcp-hermes-platform"]
    # Hermes caches the deferrable catalog by the effective toolset scope.
    # The dynamic platform toolset is attached after Agent construction, so
    # discard any catalog computed from the pre-attachment scope.
    agent._tool_search_scope_cache = None


def unregister_run(run_id: str) -> None:
    from tools.registry import registry

    with _LOCK:
        binding = _BINDINGS.pop(run_id, None)
        if binding is None:
            return
        if binding.session_id != run_id and _BINDINGS.get(binding.session_id) is binding:
            _BINDINGS.pop(binding.session_id, None)
        binding.active = False
        binding.token = ""
        for alias in binding.tools:
            remaining = _ALIASES.get(alias, 0) - 1
            if remaining <= 0:
                _ALIASES.pop(alias, None)
                registry.deregister(alias)
            else:
                _ALIASES[alias] = remaining
        binding.tools.clear()


def _handler(alias: str):
    def invoke(arguments: dict[str, Any], task_id: str | None = None, session_id: str | None = None, **_: Any) -> str:
        with _LOCK:
            binding = _BINDINGS.get(str(task_id or "")) or _BINDINGS.get(str(session_id or ""))
        if binding is None or not binding.active or alias not in binding.tools:
            raise PlatformCapabilityError("Capability is not authorized for this Hermes run")
        if not isinstance(arguments, dict):
            raise PlatformCapabilityError("Capability arguments must be an object")
        payload = _invoke(binding, alias, arguments)
        return json.dumps(payload.get("data"), ensure_ascii=False, separators=(",", ":"), default=str)

    return invoke


def _invoke(binding: RunBinding, alias: str, arguments: dict[str, Any]) -> dict[str, Any]:
    with binding.lock:
        if not binding.active:
            raise PlatformCapabilityError("Capability run is no longer active")
        if _token_expiry(binding.token) <= int(time.time()) + 120:
            _renew(binding)
        payload = _post(
            CAPABILITY_ENDPOINT,
            binding.token,
            {"execution_id": binding.execution_id, "tool_name": alias, "arguments": arguments},
        )
        if payload.get("status") != "SUCCEEDED":
            error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
            raise PlatformCapabilityError(str(error.get("message") or "Capability invocation failed")[:500])
        renewal = _metadata(payload).get("token_renewal")
        if isinstance(renewal, str) and renewal:
            binding.token = renewal
        return payload


def _renew(binding: RunBinding) -> None:
    endpoint = CAPABILITY_ENDPOINT.removesuffix("/invoke") + "/resolve"
    payload = _post(endpoint, binding.token, {"execution_id": binding.execution_id})
    if payload.get("status") != "SUCCEEDED":
        raise PlatformCapabilityError("Capability Token renewal failed")
    renewal = _metadata(payload).get("token_renewal")
    if isinstance(renewal, str) and renewal:
        binding.token = renewal


def _post(endpoint: str, token: str, payload: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload, separators=(",", ":")).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with _OPENER.open(request, timeout=30) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except (urllib.error.URLError, TimeoutError) as exc:
        raise PlatformCapabilityError("Capability Gateway is unavailable") from exc
    if len(raw) > MAX_RESPONSE_BYTES:
        raise PlatformCapabilityError("Capability Gateway response is too large")
    try:
        value = json.loads(raw)
    except (UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise PlatformCapabilityError("Capability Gateway returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise PlatformCapabilityError("Capability Gateway returned an invalid response")
    return value


def _metadata(payload: dict[str, Any]) -> dict[str, Any]:
    value = payload.get("metadata")
    return value if isinstance(value, dict) else {}


def _token_expiry(token: str) -> int:
    try:
        encoded = token.split(".", 2)[1]
        padded = encoded + "=" * (-len(encoded) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
        value = payload.get("exp") if isinstance(payload, dict) else None
        return int(value) if isinstance(value, int) else 0
    except (ValueError, IndexError, UnicodeError, json.JSONDecodeError):
        return 0


def _start_renewer() -> None:
    global _RENEWER_STARTED
    if _RENEWER_STARTED:
        return
    _RENEWER_STARTED = True
    threading.Thread(target=_renew_loop, name="hermes-capability-renewer", daemon=True).start()


def _renew_loop() -> None:
    while True:
        time.sleep(30)
        with _LOCK:
            bindings = {id(value): value for value in _BINDINGS.values()}.values()
        for binding in bindings:
            if not binding.active or _token_expiry(binding.token) > int(time.time()) + 120:
                continue
            try:
                with binding.lock:
                    if binding.active:
                        _renew(binding)
            except Exception:
                # Invocation will surface a bounded error if renewal remains
                # unavailable. Never log the Token or request context here.
                continue

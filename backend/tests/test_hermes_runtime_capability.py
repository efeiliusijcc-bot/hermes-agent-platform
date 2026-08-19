from __future__ import annotations

import base64
import importlib.util
import json
import sys
import time
from pathlib import Path
from types import ModuleType, SimpleNamespace


MODULE_PATH = Path("services/hermes-runtime/platform_capabilities.py")


def load_module():
    spec = importlib.util.spec_from_file_location("hermes_platform_capabilities_test", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def token(marker: str) -> str:
    encoded = base64.urlsafe_b64encode(
        json.dumps({"exp": int(time.time()) + 600, "marker": marker}).encode()
    ).rstrip(b"=").decode("ascii")
    return f"cap1.{encoded}.signature"


class Registry:
    def __init__(self) -> None:
        self.entries: dict[str, SimpleNamespace] = {}

    def get_entry(self, name: str):
        return self.entries.get(name)

    def register(self, *, name: str, toolset: str, schema: dict, handler, **_kwargs) -> None:
        self.entries[name] = SimpleNamespace(toolset=toolset, schema=schema, handler=handler)

    def deregister(self, name: str) -> None:
        self.entries.pop(name, None)


def install_registry(registry: Registry) -> tuple[ModuleType | None, ModuleType | None]:
    old_tools = sys.modules.get("tools")
    old_registry = sys.modules.get("tools.registry")
    tools = ModuleType("tools")
    registry_module = ModuleType("tools.registry")
    registry_module.registry = registry  # type: ignore[attr-defined]
    sys.modules["tools"] = tools
    sys.modules["tools.registry"] = registry_module
    return old_tools, old_registry


def restore_registry(previous: tuple[ModuleType | None, ModuleType | None]) -> None:
    for name, value in zip(("tools", "tools.registry"), previous):
        if value is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = value


def context(execution_id: str, execution_token: str) -> dict[str, object]:
    return {
        "execution_id": execution_id,
        "token": execution_token,
        "tools": [{
            "tool_name": "business_db_select",
            "description": "query",
            "input_schema": {
                "type": "object", "properties": {"sql": {"type": "string"}}, "required": ["sql"],
            },
        }],
    }


def test_platform_context_is_removed_before_hermes_sees_the_request() -> None:
    module = load_module()
    execution_token = token("one")
    body = {
        "input": "query",
        "metadata": {
            "runtime_options": {
                "temperature": 0,
                "platform_context": {
                    "capability_token": execution_token,
                    "capability_tools": context("execution-1", execution_token)["tools"],
                    "metadata": {"execution_id": "execution-1"},
                },
            }
        },
    }
    value = module.pop_platform_context(body)
    assert value["execution_id"] == "execution-1"
    assert "platform_context" not in body["metadata"]["runtime_options"]
    assert execution_token not in json.dumps(body)


def test_two_concurrent_runs_share_alias_schema_but_dispatch_by_run_identity() -> None:
    module = load_module()
    registry = Registry()
    previous = install_registry(registry)
    calls: list[tuple[str, str, dict[str, object]]] = []

    def post(_endpoint: str, execution_token: str, payload: dict[str, object]):
        calls.append((execution_token, str(payload["execution_id"]), payload))
        return {"status": "SUCCEEDED", "data": {"execution": payload["execution_id"]}, "metadata": {}}

    module._post = post
    module._start_renewer = lambda: None
    try:
        module.register_run("run-1", "run-1", context("execution-1", token("one")))
        module.register_run("run-2", "run-2", context("execution-2", token("two")))
        agent = SimpleNamespace(
            tools=[],
            valid_tool_names=set(),
            enabled_toolsets=["hermes-cli"],
            disabled_toolsets=["mcp-hermes-platform", "browser"],
            _tool_search_scope_cache=("stale", frozenset()),
        )
        module.attach_run_tools(agent, "run-1")
        assert agent.tools[0]["function"]["name"] == "business_db_select"
        assert agent.enabled_toolsets == ["hermes-cli", "mcp-hermes-platform"]
        assert agent.disabled_toolsets == ["browser"]
        assert agent._tool_search_scope_cache is None
        handler = registry.entries["business_db_select"].handler
        assert json.loads(handler({"sql": "SELECT 1"}, task_id="run-1")) == {"execution": "execution-1"}
        assert json.loads(handler({"sql": "SELECT 2"}, task_id="run-2")) == {"execution": "execution-2"}
        assert [item[1] for item in calls] == ["execution-1", "execution-2"]
        module.unregister_run("run-1")
        assert "business_db_select" in registry.entries
        module.unregister_run("run-2")
        assert "business_db_select" not in registry.entries
    finally:
        restore_registry(previous)


def test_derived_image_is_pinned_and_patch_is_digest_guarded() -> None:
    dockerfile = Path("services/hermes-runtime/Dockerfile").read_text()
    patcher = Path("services/hermes-runtime/patch_api_server.py").read_text()
    compose = Path("docker-compose.yml").read_text()
    assert "nousresearch/hermes-agent:v2026.8.3@sha256:" in dockerfile
    assert "EXPECTED_SHA256" in patcher and "digest mismatch" in patcher
    assert "hermes-agent-platform/hermes-runtime:capability-v1" in compose

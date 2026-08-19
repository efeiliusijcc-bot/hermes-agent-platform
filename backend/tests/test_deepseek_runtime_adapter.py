from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from app.api.agents import _requires_fresh_runtime_session
from app.runtime.base import RuntimeAdapterError, RuntimeContext
from app.runtime.deepseek import DeepSeekRuntimeAdapter


def repository_context() -> RuntimeContext:
    return RuntimeContext(
        agent_id="coding-agent",
        session_id="platform-session",
        workspace="/data/workspaces/coding-agent/sessions/platform-session/repository",
        workspace_type="repository",
        memory_namespace="agent:coding-agent:session:test",
        capability_profile={
            "workspace_type": "repository",
            "artifact_types": ["code_patch", "git_diff", "test_report"],
        },
    )


def test_deepseek_service_uses_official_jsonrpc_runtime_on_an_internal_network() -> None:
    requirements = Path("services/deepseek-runtime/requirements.txt").read_text()
    package = json.loads(Path("services/deepseek-runtime/package.json").read_text())
    package_lock = json.loads(Path("services/deepseek-runtime/package-lock.json").read_text())
    compose = Path("docker-compose.yml").read_text()
    dockerfile = Path("services/deepseek-runtime/Dockerfile").read_text()
    cordis = Path("services/deepseek-runtime/cordis.yml").read_text()
    gateway = compose.split("\n  deepseek-runtime:\n", 1)[1].split(
        "\n  deepseek-harness-core:\n", 1
    )[0]
    core = compose.split("\n  deepseek-harness-core:\n", 1)[1].split(
        "\n  mcp-gateway:\n", 1
    )[0]

    assert "deepseek-harness-runtime-bin" not in requirements
    assert "deepseek-harness-sdk" not in requirements
    assert "httpx==0.28.1" in requirements
    assert package["version"] == "0.1.0-rc.6"
    assert package_lock["packages"][""]["version"] == "0.1.0-rc.6"
    assert all(version == "0.1.0-rc.6" for version in package["dependencies"].values())
    assert package["dependencies"]["@deepseek-ai/dsh-sdk-jsonrpc-demo"] == "0.1.0-rc.6"
    assert package["dependencies"]["@deepseek-ai/dsh-subprocess-local"] == "0.1.0-rc.6"
    assert "services/deepseek-runtime/Dockerfile" in compose
    assert "MODEL_GATEWAY_ENDPOINT: http://deepseek-runtime:8770/model/v1" in core
    assert "MODEL_GATEWAY_API_KEY" not in core
    assert "DEEPSEEK_RUNTIME_API_KEY" not in core
    assert 'user: "0:0"' in core
    assert all(
        capability in core
        for capability in ("- SETUID", "- SETGID", "- CHOWN", "- FOWNER", "- KILL")
    )
    assert "- deepseek-harness-internal" in core
    assert "- deepseek-runtime-internal" not in core
    assert "- deepseek-runtime-internal" in gateway
    assert "- deepseek-harness-internal" in gateway
    assert "MODEL_GATEWAY_API_KEY" in gateway
    assert "ports:" not in gateway and "ports:" not in core
    assert "read_only: true" in gateway and "read_only: true" in core
    assert "node:22.19.0-bookworm-slim AS harness-runtime" in dockerfile
    assert "npm ci --omit=dev" in dockerfile
    assert "COPY --from=harness-runtime /usr/local/bin/node" in dockerfile
    assert "python:3.12.10-slim-bookworm" in dockerfile
    assert "COPY services/deepseek-runtime/cordis.yml" in dockerfile
    assert "COPY services/deepseek-runtime/platform-capabilities.mjs ./platform-capabilities.mjs" in dockerfile
    assert "@deepseek-ai/dsh-sdk-jsonrpc-server" in cordis
    assert "/opt/deepseek-harness/platform-capabilities.mjs" in cordis
    assert "thinking: disabled" in cordis
    plugin = Path("services/deepseek-runtime/platform-capabilities.mjs").read_text()
    assert "ctx.tools.register(defineTool" in plugin
    assert "HERMES_CAPABILITY_FD" in plugin
    assert "capability_token" not in plugin.lower()


def test_runtime_migration_keeps_existing_platform_artifact_provenance() -> None:
    migration = Path("backend/alembic/versions/0014_runtime_integration_layer.py").read_text()
    assert "SET runtime_source = session.runtime_type" not in migration
    assert 'server_default="platform"' in migration


@pytest.mark.asyncio
async def test_deepseek_adapter_requires_repository_workspace() -> None:
    adapter = DeepSeekRuntimeAdapter(endpoint="http://deepseek-runtime:8770")
    with pytest.raises(RuntimeAdapterError, match="repository workspace"):
        await adapter.create_session(
            agent_id="coding-agent",
            execution_id="execution-1",
            context=RuntimeContext(
                agent_id="coding-agent",
                session_id="platform-session",
                workspace="/data/workspaces/coding-agent/platform-session",
                workspace_type="document",
                memory_namespace="agent:coding-agent:session:test",
            ),
        )


@pytest.mark.asyncio
async def test_deepseek_health_reports_the_pinned_harness_version() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/health"
        return httpx.Response(
            200,
            json={"status": "ready", "version": "1.0.0", "harness_version": "0.1.0-rc.6"},
        )

    adapter = DeepSeekRuntimeAdapter(
        endpoint="http://deepseek-runtime:8770",
        version="0.1.0-rc.6",
        transport=httpx.MockTransport(handler),
    )
    health = await adapter.health_check()
    assert health.status == "online"
    assert health.version == "0.1.0-rc.6"


@pytest.mark.asyncio
async def test_deepseek_adapter_maps_bridge_result_and_coding_artifacts() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/sessions":
            return httpx.Response(201, json={"id": "dsh-session"})
        if request.url.path.endswith("/execute"):
            return httpx.Response(
                200,
                json={
                    "run_id": "execution-1",
                    "status": "completed",
                    "output": "code updated",
                    "usage": {"total_tokens": 75},
                    "trace": [{"event": "code_edit", "status": "succeeded"}],
                    "artifacts": [
                        {
                            "filename": "changes.patch",
                            "artifact_type": "code_patch",
                            "content_type": "text/x-diff; charset=utf-8",
                            "content": "diff --git a/a.py b/a.py",
                        }
                    ],
                },
            )
        return httpx.Response(404)

    adapter = DeepSeekRuntimeAdapter(
        endpoint="http://deepseek-runtime:8770",
        transport=httpx.MockTransport(handler),
    )
    adapter.api_key = "runtime-key"
    context = repository_context()
    runtime_session = await adapter.create_session(
        agent_id="coding-agent", execution_id="execution-1", context=context
    )
    result = await adapter.execute(
        [{"role": "user", "content": "fix the code"}],
        session_id=runtime_session.id,
        model="managed-coding-model",
        model_adapter="openai",
        agent_id="coding-agent",
        execution_id="execution-1",
        context=context,
    )

    assert result.output == "code updated" and result.token_usage == 75
    assert result.artifacts[0].artifact_type == "code_patch"
    assert result.artifacts[0].content.startswith(b"diff --git")
    execute_request = next(value for value in requests if value.url.path.endswith("/execute"))
    assert execute_request.headers["authorization"] == "Bearer runtime-key"
    body = json.loads(execute_request.content)
    assert body["context"]["workspace_type"] == "repository"


def test_deepseek_adapter_rejects_unsafe_or_unknown_artifacts() -> None:
    adapter = DeepSeekRuntimeAdapter(endpoint="http://deepseek-runtime:8770")
    with pytest.raises(RuntimeAdapterError, match="unsafe artifact filename"):
        adapter.result_artifacts(
            {
                "artifacts": [
                    {"filename": "../escape.patch", "artifact_type": "code_patch", "content": "x"}
                ]
            }
        )
    with pytest.raises(RuntimeAdapterError, match="unsupported artifact type"):
        adapter.result_artifacts(
            {
                "artifacts": [
                    {"filename": "result.bin", "artifact_type": "binary", "content": "x"}
                ]
            }
        )


def test_deepseek_retry_uses_a_fresh_durable_harness_session() -> None:
    assert not _requires_fresh_runtime_session("deepseek", 0)
    assert _requires_fresh_runtime_session("deepseek", 1)
    assert not _requires_fresh_runtime_session("pi", 1)

from __future__ import annotations

import asyncio
import os
import subprocess
import textwrap
import base64
import json
import socket
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from deepseek_runtime_service.gateway import RUNTIME_API_KEY, _authorize, _relay
from deepseek_runtime_service.capability_dispatcher import CapabilityDispatcher
from deepseek_runtime_service.harness import (
    HarnessProcess,
    _runtime_launch,
    _subprocess_identity,
    _turn_error_detail,
)
from deepseek_runtime_service.server import (
    EventCollector,
    RuntimeManager,
    SessionCreate,
    _capability_context,
    _assign_workspace_owner,
    _collect_artifacts,
    _git_output,
    _tool_event_type,
    _session_context,
    settings,
)


def test_security_gateway_keeps_runtime_key_out_of_harness_core() -> None:
    _authorize(f"Bearer {RUNTIME_API_KEY}")
    with pytest.raises(HTTPException) as exc_info:
        _authorize("Bearer wrong")
    assert exc_info.value.status_code == 401


def test_default_runtime_launch_uses_the_pinned_official_npm_carrier() -> None:
    args, config = _runtime_launch(None)

    assert args == (
        "node",
        "/opt/deepseek-harness/node_modules/@deepseek-ai/dsh-sdk-jsonrpc-demo/lib/packaged-bin.js",
    )
    assert config == "/app/cordis.yml"


def _capability_token(expires_in: int = 600) -> str:
    encoded = base64.urlsafe_b64encode(
        json.dumps({"exp": int(time.time()) + expires_in}).encode()
    ).rstrip(b"=").decode("ascii")
    return f"cap1.{encoded}.signature"


def test_runtime_session_drops_per_execution_token_but_keeps_identity() -> None:
    token = _capability_token()
    context = {
        "agent_id": "agent-1",
        "workspace": "/data/workspaces/agent-1/repository",
        "capability_token": token,
        "capability_tools": [{"tool_name": "business_db_select", "input_schema": {"type": "object"}}],
        "metadata": {"capability_token": token, "capability_tools": []},
    }
    sanitized = _session_context(context)
    assert sanitized["agent_id"] == "agent-1"
    assert "capability_token" not in sanitized and "capability_tools" not in sanitized
    assert "capability_token" not in sanitized["metadata"]
    extracted_token, tools = _capability_context(context)
    assert extracted_token == token and tools[0]["tool_name"] == "business_db_select"


@pytest.mark.asyncio
async def test_private_unix_dispatcher_hides_token_and_invokes_only_authorized_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = _capability_token()
    calls: list[dict[str, object]] = []

    class Response:
        is_success = True

        @staticmethod
        def json() -> dict[str, object]:
            return {"status": "SUCCEEDED", "data": {"rows": [{"id": 1}]}, "invocation_id": "inv-1", "metadata": {}}

    class Client:
        def __init__(self, **_kwargs: object) -> None: pass
        async def __aenter__(self): return self
        async def __aexit__(self, *_args: object) -> None: return None
        async def post(self, endpoint: str, **kwargs: object) -> Response:
            calls.append({"endpoint": endpoint, **kwargs})
            return Response()

    monkeypatch.setattr(
        "deepseek_runtime_service.capability_dispatcher.httpx.AsyncClient",
        Client,
    )
    dispatcher = CapabilityDispatcher(
        endpoint="http://deepseek-runtime:8770/capability/invoke",
        execution_id="execution-1",
        token=token,
        tools=[{
            "tool_name": "business_db_select",
            "description": "query",
            "input_schema": {"type": "object", "properties": {"sql": {"type": "string"}}},
            "binding_id": "must-not-reach-node",
        }],
        timeout_seconds=5,
    )
    await dispatcher.start()
    child = socket.socket(fileno=os.dup(dispatcher.child_fd))
    child.setblocking(False)
    dispatcher.child_spawned()
    reader, writer = await asyncio.open_connection(sock=child)
    try:
        writer.write(b'{"id":"1","type":"list"}\n')
        await writer.drain()
        listed = json.loads(await reader.readline())
        serialized = json.dumps(listed)
        assert listed["tools"][0]["tool_name"] == "business_db_select"
        assert "binding_id" not in serialized and token not in serialized

        writer.write(b'{"id":"2","type":"invoke","tool_name":"business_db_select","arguments":{"sql":"SELECT 1"}}\n')
        await writer.drain()
        invoked = json.loads(await reader.readline())
        assert invoked["ok"] is True and invoked["invocation_id"] == "inv-1"
        assert calls[0]["headers"]["Authorization"] == f"Bearer {token}"
        assert calls[0]["json"] == {
            "execution_id": "execution-1", "tool_name": "business_db_select", "arguments": {"sql": "SELECT 1"},
        }
    finally:
        writer.close()
        await writer.wait_closed()
        await dispatcher.close()


def test_builtin_python_unittest_is_normalized_as_a_test_run() -> None:
    assert _tool_event_type("bash", "python -m unittest -v") == "test_run"


def test_execution_identity_can_open_only_the_shared_session_parent(tmp_path: Path) -> None:
    session_root = tmp_path / "session-1"
    session_root.mkdir()

    identity = _subprocess_identity(session_root, 20001)

    assert identity == {
        "user": 20001,
        "group": 20001,
        "extra_groups": (tmp_path.stat().st_gid,),
        "umask": 0o077,
    }


@pytest.mark.asyncio
async def test_security_gateway_replaces_client_authorization_before_model_gateway() -> None:
    captured: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            stream=httpx.ByteStream(b'{"ok":true}'),
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/model/v1/chat/completions",
        "raw_path": b"/model/v1/chat/completions",
        "query_string": b"",
        "headers": [(b"authorization", b"Bearer model-visible-value")],
        "client": ("127.0.0.1", 1234),
        "server": ("gateway", 8770),
        "app": SimpleNamespace(state=SimpleNamespace(client=client)),
    }
    delivered = False

    async def receive() -> dict[str, object]:
        nonlocal delivered
        if delivered:
            return {"type": "http.disconnect"}
        delivered = True
        return {"type": "http.request", "body": b"{}", "more_body": False}

    try:
        response = await _relay(
            Request(scope, receive),
            "http://model-gateway:8080/v1/chat/completions",
            authorization="Bearer gateway-owned-secret",
        )
        body = b"".join([chunk async for chunk in response.body_iterator])
    finally:
        await client.aclose()

    assert body == b'{"ok":true}'
    assert captured[0].headers["authorization"] == "Bearer gateway-owned-secret"


@pytest.mark.asyncio
async def test_runtime_session_rejects_workspace_identity_change(tmp_path: Path) -> None:
    manager = RuntimeManager(settings)
    first = await manager.create_session(
        SessionCreate(
            agent_id="coding-agent",
            execution_id="execution-1",
            context={
                "agent_id": "coding-agent",
                "session_id": "platform-session",
                "workspace": str(tmp_path / "one"),
                "workspace_type": "repository",
                "memory_namespace": "agent:coding-agent:session:test",
            },
        )
    )
    with pytest.raises(HTTPException) as exc_info:
        await manager._session(
            first.id,
            {
                **first.context,
                "workspace": str(tmp_path / "two"),
            },
        )
    assert exc_info.value.status_code == 409


def test_workspace_execution_identity_makes_repository_private(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = tmp_path / "coding-agent" / "sessions" / "session-1" / "repository"
    repository.mkdir(parents=True)
    source = repository / "app.py"
    source.write_text("print('ok')\n")
    current_uid = os.getuid()
    monkeypatch.setattr(os, "chown", lambda *args, **kwargs: None)

    selected = _assign_workspace_owner(repository, tmp_path, current_uid, current_uid)

    assert selected == current_uid
    assert repository.stat().st_mode & 0o777 == 0o700
    assert source.stat().st_mode & 0o777 == 0o600
    assert repository.parent.stat().st_mode & 0o001


@pytest.mark.asyncio
async def test_jsonrpc_client_drives_the_official_wire_contract(tmp_path: Path) -> None:
    runtime = tmp_path / "fake-runtime"
    runtime.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import json
            import sys

            for line in sys.stdin:
                frame = json.loads(line)
                method = frame.get("method")
                if method == "initialize":
                    print(json.dumps({"jsonrpc":"2.0","id":frame["id"],"result":{"serverInfo":{"name":"deepseek-harness-sdk-runtime","version":"0.0.1"}}}), flush=True)
                elif method == "session/prompt":
                    sid = frame["params"]["sessionId"]
                    print(json.dumps({"jsonrpc":"2.0","id":frame["id"],"result":{"messageId":"message-1"}}), flush=True)
                    print(json.dumps({"jsonrpc":"2.0","method":"session.status","params":{"sessionId":sid,"status":"running"}}), flush=True)
                    print(json.dumps({"jsonrpc":"2.0","method":"session.event","params":{"sessionId":sid,"event":{"type":"assistant/message","data":{"message":{"content":[{"type":"text","text":"bridge ok"}]},"usage":{"inputTokens":2,"outputTokens":3,"cacheReadTokens":4}}}}}), flush=True)
                    print(json.dumps({"jsonrpc":"2.0","method":"session.event","params":{"sessionId":sid,"event":{"type":"turn/end","data":{"reason":{"kind":"completed"}}}}}), flush=True)
                    print(json.dumps({"jsonrpc":"2.0","method":"session.status","params":{"sessionId":sid,"status":"idle"}}), flush=True)
                elif method == "shutdown":
                    print(json.dumps({"jsonrpc":"2.0","id":frame["id"],"result":{}}), flush=True)
                    break
            """
        )
    )
    runtime.chmod(0o755)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    process = HarnessProcess(
        cwd=workspace,
        session_root=tmp_path / "sessions",
        provider="deepseek-official",
        model="test-model",
        max_tokens=1024,
        system_prompt="You are a coding agent.",
        base_url="http://model-gateway:8080/v1",
        api_key="test-model-key",
        request_timeout_seconds=5,
        runtime_bin=str(runtime),
    )
    try:
        result = await process.run(session_id="session-1", prompt="fix it")
    finally:
        await process.close()

    assert result.output == "bridge ok"
    assert result.finish_reason == "completed"
    assert result.error_detail is None
    assert result.token_usage == 9


def test_turn_error_detail_is_bounded_and_redacts_credentials() -> None:
    detail = _turn_error_detail(
        [
            {
                "type": "turn/end",
                "data": {
                    "reason": {
                        "kind": "error",
                        "error": {
                            "message": "provider rejected token=do-not-log-this credential"
                        },
                    }
                },
            }
        ]
    )

    assert detail == "provider rejected token=[REDACTED] credential"


@pytest.mark.asyncio
async def test_event_adapter_maps_repository_test_and_text_events() -> None:
    emitted: list[dict[str, object]] = []

    async def emit(event: dict[str, object]) -> None:
        emitted.append(event)

    collector = EventCollector("run-1", emit)
    await collector.consume(
        {
            "type": "tool/call",
            "data": {
                "callId": "call-1",
                "name": "bash",
                "arguments": '{"command":"python -m pytest -q"}',
            },
        }
    )
    await collector.consume(
        {
            "type": "tool/result",
            "data": {
                "message": {
                    "source": {"callId": "call-1"},
                    "content": [
                        {
                            "type": "tool-result",
                            "isError": False,
                            "content": [{"type": "text", "text": "3 passed"}],
                        }
                    ],
                }
            },
        }
    )
    await collector.consume(
        {
            "type": "assistant/chunk",
            "data": {"chunk": {"type": "text-delta", "text": "done"}},
        }
    )

    assert [event["event"] for event in emitted] == ["test_run", "test_run", "message.delta"]
    assert collector.test_report == ["$ python -m pytest -q", "3 passed", "status: succeeded"]


@pytest.mark.asyncio
async def test_artifact_adapter_collects_git_diff_and_observed_test_output(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Test"], check=True)
    source = tmp_path / "app.py"
    source.write_text("print('before')\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "app.py"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "base"], check=True)
    source.write_text("print('after')\n")
    (tmp_path / "new module.py").write_text("NEW_VALUE = 1\n")

    artifacts = await _collect_artifacts(
        tmp_path,
        test_report=["$ pytest -q", "1 passed", "status: succeeded"],
        maximum_bytes=100_000,
    )

    assert [artifact["artifact_type"] for artifact in artifacts] == [
        "code_patch",
        "git_diff",
        "test_report",
    ]
    assert "print('after')" in artifacts[0]["content"]
    assert "new module.py" in artifacts[0]["content"]
    assert "NEW_VALUE = 1" in artifacts[0]["content"]
    assert "1 passed" in artifacts[-1]["content"]


@pytest.mark.asyncio
async def test_git_artifact_reader_trusts_only_the_exact_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: list[tuple[str, ...]] = []

    class Process:
        returncode = 0

        async def communicate(self) -> tuple[bytes, bytes]:
            return b"", b""

    async def create_subprocess_exec(*args: str, **_kwargs: object) -> Process:
        captured.append(args)
        return Process()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_subprocess_exec)

    await _git_output(
        tmp_path,
        1024,
        "git",
        "status",
        "--short",
        accepted_return_codes={0},
    )

    assert captured == [
        (
            "git",
            "-c",
            f"safe.directory={tmp_path.resolve()}",
            "status",
            "--short",
        )
    ]

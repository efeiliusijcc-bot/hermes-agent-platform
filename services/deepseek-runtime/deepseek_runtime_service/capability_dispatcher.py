from __future__ import annotations

import asyncio
import base64
import json
import socket
import time
from contextlib import suppress
from typing import Any

import httpx


MAX_FRAME_BYTES = 2_097_152


class CapabilityDispatcherError(RuntimeError):
    pass


class CapabilityDispatcher:
    """Per-execution Unix socket dispatcher owned by the Python parent.

    The child receives only one inherited socket descriptor. Execution Tokens
    stay in this object and are never placed in the child environment, config,
    prompt, workspace, or ordinary logs.
    """

    def __init__(
        self,
        *,
        endpoint: str,
        execution_id: str,
        token: str,
        tools: list[dict[str, Any]],
        timeout_seconds: float,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.execution_id = execution_id
        self._token = token
        self._tools = {
            str(tool["tool_name"]): {
                "tool_name": str(tool["tool_name"]),
                "description": str(tool.get("description") or tool["tool_name"]),
                "input_schema": _object(tool.get("input_schema")),
            }
            for tool in tools
            if isinstance(tool, dict) and isinstance(tool.get("tool_name"), str)
        }
        self.timeout_seconds = timeout_seconds
        self._parent_socket: socket.socket | None = None
        self._child_socket: socket.socket | None = None
        self._serve_task: asyncio.Task[None] | None = None
        self._renew_task: asyncio.Task[None] | None = None
        self._renew_lock = asyncio.Lock()
        self._closed = False

    @property
    def child_fd(self) -> int:
        if self._child_socket is None:
            raise CapabilityDispatcherError("Capability dispatcher is not started")
        return self._child_socket.fileno()

    async def start(self) -> None:
        if self._parent_socket is not None:
            return
        parent, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        parent.setblocking(False)
        child.set_inheritable(True)
        self._parent_socket = parent
        self._child_socket = child
        self._serve_task = asyncio.create_task(self._serve())
        self._renew_task = asyncio.create_task(self._renew_loop())

    def child_spawned(self) -> None:
        if self._child_socket is not None:
            self._child_socket.close()
            self._child_socket = None

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._token = ""
        if self._child_socket is not None:
            self._child_socket.close()
            self._child_socket = None
        if self._parent_socket is not None:
            self._parent_socket.close()
            self._parent_socket = None
        tasks = [task for task in (self._serve_task, self._renew_task) if task is not None]
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tools.clear()

    async def _serve(self) -> None:
        parent = self._parent_socket
        if parent is None:
            return
        reader, writer = await asyncio.open_connection(sock=parent, limit=MAX_FRAME_BYTES + 1)
        try:
            while not self._closed:
                try:
                    raw = await reader.readline()
                except (ValueError, asyncio.LimitOverrunError):
                    break
                if not raw:
                    break
                response: dict[str, Any]
                request_id: Any = None
                try:
                    if len(raw) > MAX_FRAME_BYTES:
                        raise CapabilityDispatcherError("Capability dispatcher request is too large")
                    request = json.loads(raw)
                    if not isinstance(request, dict):
                        raise CapabilityDispatcherError("Capability dispatcher request must be an object")
                    request_id = request.get("id")
                    response = {"id": request_id, "ok": True, **await self._dispatch(request)}
                except Exception as exc:
                    response = {
                        "id": request_id,
                        "ok": False,
                        "error": {"message": _safe_error(exc)},
                    }
                payload = (json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
                if len(payload) > MAX_FRAME_BYTES:
                    payload = json.dumps(
                        {"id": request_id, "ok": False, "error": {"message": "Capability response is too large"}},
                        separators=(",", ":"),
                    ).encode() + b"\n"
                writer.write(payload)
                await writer.drain()
        except (BrokenPipeError, ConnectionError, asyncio.CancelledError):
            pass
        finally:
            writer.close()
            with suppress(Exception):
                await writer.wait_closed()

    async def _dispatch(self, request: dict[str, Any]) -> dict[str, Any]:
        kind = request.get("type")
        if kind == "list":
            return {"tools": list(self._tools.values())}
        if kind != "invoke":
            raise CapabilityDispatcherError("Unsupported Capability dispatcher request")
        tool_name = request.get("tool_name")
        arguments = request.get("arguments")
        if not isinstance(tool_name, str) or tool_name not in self._tools:
            raise CapabilityDispatcherError("Capability tool is not authorized for this execution")
        if not isinstance(arguments, dict):
            raise CapabilityDispatcherError("Capability arguments must be an object")
        await self._renew_if_needed()
        headers = {"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=self.timeout_seconds, trust_env=False) as client:
            response = await client.post(
                self.endpoint,
                headers=headers,
                json={
                    "execution_id": self.execution_id,
                    "tool_name": tool_name,
                    "arguments": arguments,
                },
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise CapabilityDispatcherError("Capability Gateway returned invalid JSON") from exc
        if not response.is_success or not isinstance(payload, dict) or payload.get("status") != "SUCCEEDED":
            error = payload.get("error") if isinstance(payload, dict) else None
            message = error.get("message") if isinstance(error, dict) else None
            raise CapabilityDispatcherError(str(message or "Capability invocation failed"))
        renewal = _object(payload.get("metadata")).get("token_renewal")
        if isinstance(renewal, str) and renewal:
            self._token = renewal
        return {"data": payload.get("data"), "invocation_id": payload.get("invocation_id")}

    async def _renew_loop(self) -> None:
        try:
            while not self._closed:
                await asyncio.sleep(30)
                with suppress(Exception):
                    await self._renew_if_needed()
        except asyncio.CancelledError:
            return

    async def _renew_if_needed(self) -> None:
        if _token_expiry(self._token) > int(time.time()) + 120:
            return
        async with self._renew_lock:
            if _token_expiry(self._token) > int(time.time()) + 120:
                return
            endpoint = self.endpoint.removesuffix("/invoke") + "/resolve"
            async with httpx.AsyncClient(timeout=self.timeout_seconds, trust_env=False) as client:
                response = await client.post(
                    endpoint,
                    headers={"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"},
                    json={"execution_id": self.execution_id},
                )
            payload = response.json()
            if not response.is_success or not isinstance(payload, dict) or payload.get("status") != "SUCCEEDED":
                raise CapabilityDispatcherError("Capability Token renewal failed")
            renewal = _object(payload.get("metadata")).get("token_renewal")
            if isinstance(renewal, str) and renewal:
                self._token = renewal


def _token_expiry(token: str) -> int:
    try:
        encoded = token.split(".", 2)[1]
        padded = encoded + "=" * (-len(encoded) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
        value = payload.get("exp") if isinstance(payload, dict) else None
        return int(value) if isinstance(value, int) else 0
    except (ValueError, IndexError, UnicodeError, json.JSONDecodeError):
        return 0


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_error(exc: Exception) -> str:
    if isinstance(exc, CapabilityDispatcherError):
        return str(exc)[:500]
    if isinstance(exc, (httpx.TimeoutException, httpx.HTTPError)):
        return "Capability Gateway is unavailable"
    return "Capability dispatcher failed"

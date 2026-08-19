from __future__ import annotations

import asyncio
import json
import os
import re
import signal
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from .capability_dispatcher import CapabilityDispatcher


JsonObject = dict[str, Any]
EventCallback = Callable[[JsonObject], Awaitable[None]]


class HarnessProtocolError(RuntimeError):
    """The official Harness process violated its documented JSON-RPC contract."""


class HarnessTransportError(RuntimeError):
    """The official Harness process could not be started or disappeared."""


class HarnessCancelledError(RuntimeError):
    """The owner deliberately stopped the Harness process."""


@dataclass(frozen=True)
class HarnessResult:
    output: str
    finish_reason: str | None
    error_detail: str | None
    token_usage: int | None
    events: tuple[JsonObject, ...]


class HarnessProcess:
    """Minimal async client for the official newline-delimited JSON-RPC wire."""

    def __init__(
        self,
        *,
        cwd: Path,
        session_root: Path,
        provider: str,
        model: str,
        max_tokens: int | None,
        system_prompt: str,
        base_url: str,
        api_key: str,
        request_timeout_seconds: float,
        runtime_bin: str | None = None,
        cordis_config: str | None = None,
        execution_uid: int | None = None,
        capability_gateway_endpoint: str | None = None,
        capability_token: str = "",
        capability_tools: list[dict[str, Any]] | None = None,
        execution_id: str = "",
    ) -> None:
        self.cwd = cwd
        self.session_root = session_root
        self.provider = provider
        self.model = model
        self.max_tokens = max_tokens
        self.system_prompt = system_prompt
        self.base_url = base_url
        self.api_key = api_key
        self.request_timeout_seconds = request_timeout_seconds
        self.runtime_bin = runtime_bin
        self.cordis_config = cordis_config
        self.execution_uid = execution_uid
        self.capability_gateway_endpoint = capability_gateway_endpoint
        self.capability_token = capability_token
        self.capability_tools = list(capability_tools or [])
        self.execution_id = execution_id
        self.capability_dispatcher: CapabilityDispatcher | None = None
        self.process: asyncio.subprocess.Process | None = None
        self._reader: asyncio.Task[None] | None = None
        self._stderr_reader: asyncio.Task[None] | None = None
        self._responses: dict[str, asyncio.Future[Any]] = {}
        self._notifications: asyncio.Queue[JsonObject | BaseException] = asyncio.Queue()
        self._write_lock = asyncio.Lock()
        self._stderr: deque[str] = deque(maxlen=200)
        self._cancelled = False

    async def start(self) -> None:
        if self.process is not None:
            return
        args, default_config = _runtime_launch(self.runtime_bin)
        env = os.environ.copy()
        private_home = self.session_root / "home"
        env.update(
            {
                "DEEPSEEK_API_KEY": self.api_key,
                "DEEPSEEK_BASE_URL": self.base_url,
                "DSH_CWD": str(self.cwd),
                "DSH_SESSION_ROOT": str(self.session_root),
                "DSH_SYSTEM_PROMPT": self.system_prompt,
                "HOME": str(private_home),
            }
        )
        config = self.cordis_config or default_config
        if config:
            env["DSH_CORDIS_CONFIG"] = config
        self.session_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        private_home.mkdir(parents=True, exist_ok=True, mode=0o700)
        subprocess_identity: dict[str, Any] = {}
        if self.execution_uid is not None:
            self.session_root.parent.chmod(self.session_root.parent.stat().st_mode | 0o001)
            _own_private_path(self.session_root, self.execution_uid)
            subprocess_identity = _subprocess_identity(self.session_root, self.execution_uid)
        pass_fds: tuple[int, ...] = ()
        if self.capability_tools:
            if not self.capability_gateway_endpoint or not self.capability_token or not self.execution_id:
                raise HarnessProtocolError("Capability Gateway context is incomplete")
            self.capability_dispatcher = CapabilityDispatcher(
                endpoint=self.capability_gateway_endpoint,
                execution_id=self.execution_id,
                token=self.capability_token,
                tools=self.capability_tools,
                timeout_seconds=self.request_timeout_seconds,
            )
            await self.capability_dispatcher.start()
            capability_fd = self.capability_dispatcher.child_fd
            env["HERMES_CAPABILITY_FD"] = str(capability_fd)
            pass_fds = (capability_fd,)
        try:
            self.process = await asyncio.create_subprocess_exec(
                *args,
                cwd=str(self.cwd),
                env=env,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
                pass_fds=pass_fds,
                **subprocess_identity,
            )
        except (OSError, FileNotFoundError) as exc:
            if self.capability_dispatcher is not None:
                self.capability_dispatcher.child_spawned()
                await self.capability_dispatcher.close()
            raise HarnessTransportError(f"failed to start DeepSeek Harness: {exc}") from exc
        if self.capability_dispatcher is not None:
            self.capability_dispatcher.child_spawned()
        self._reader = asyncio.create_task(self._read_stdout())
        self._stderr_reader = asyncio.create_task(self._read_stderr())
        params: JsonObject = {
            "cwd": str(self.cwd),
            "provider": self.provider,
            "model": self.model,
        }
        if self.max_tokens is not None:
            params["maxTokens"] = self.max_tokens
        result = await self._request("initialize", params)
        server = result.get("serverInfo") if isinstance(result, dict) else None
        if not isinstance(server, dict) or server.get("name") != "deepseek-harness-sdk-runtime":
            raise HarnessProtocolError("DeepSeek Harness initialize returned an invalid server identity")

    async def run(
        self,
        *,
        session_id: str,
        prompt: str,
        on_event: EventCallback | None = None,
    ) -> HarnessResult:
        await self.start()
        receipt = await self._request(
            "session/prompt",
            {
                "sessionId": session_id,
                "contentBlocks": [{"type": "text", "text": prompt}],
            },
        )
        if not isinstance(receipt, dict) or not isinstance(receipt.get("messageId"), str):
            raise HarnessProtocolError("DeepSeek Harness session/prompt returned no messageId")
        events: list[JsonObject] = []
        while True:
            item = await self._notifications.get()
            if isinstance(item, BaseException):
                raise item
            method = item.get("method")
            params = item.get("params")
            if not isinstance(params, dict):
                continue
            if method == "session.event" and params.get("sessionId") == session_id:
                event = params.get("event")
                if isinstance(event, dict):
                    events.append(event)
                    if on_event is not None:
                        await on_event(event)
            if (
                method == "session.status"
                and params.get("sessionId") == session_id
                and params.get("status") == "idle"
            ):
                break
        return HarnessResult(
            output=_final_response(events),
            finish_reason=_finish_reason(events),
            error_detail=_turn_error_detail(events),
            token_usage=_token_usage(events),
            events=tuple(events),
        )

    async def close(self) -> None:
        process = self.process
        if process is None:
            if self.capability_dispatcher is not None:
                await self.capability_dispatcher.close()
                self.capability_dispatcher = None
            return
        if process.returncode is None and not self._cancelled:
            try:
                await self._request("shutdown", None, timeout=2.0)
            except Exception:
                pass
        if process.returncode is None:
            await self._terminate_process_group(signal.SIGTERM)
            try:
                await asyncio.wait_for(process.wait(), timeout=2.0)
            except TimeoutError:
                await self._terminate_process_group(signal.SIGKILL)
                await process.wait()
        await self._finish_readers()
        self.process = None
        if self.capability_dispatcher is not None:
            await self.capability_dispatcher.close()
            self.capability_dispatcher = None

    async def cancel(self) -> None:
        self._cancelled = True
        process = self.process
        if process is not None and process.returncode is None:
            await self._terminate_process_group(signal.SIGTERM)

    async def _request(
        self,
        method: str,
        params: JsonObject | None,
        *,
        timeout: float | None = None,
    ) -> Any:
        process = self.process
        if process is None or process.stdin is None:
            raise HarnessTransportError("DeepSeek Harness is not running")
        request_id = str(uuid4())
        future = asyncio.get_running_loop().create_future()
        self._responses[request_id] = future
        frame: JsonObject = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            frame["params"] = params
        try:
            payload = (json.dumps(frame, separators=(",", ":")) + "\n").encode()
            async with self._write_lock:
                process.stdin.write(payload)
                await process.stdin.drain()
            return await asyncio.wait_for(
                future,
                timeout=self.request_timeout_seconds if timeout is None else timeout,
            )
        except TimeoutError as exc:
            raise HarnessTransportError(
                f"DeepSeek Harness {method} timed out{self._diagnostics()}"
            ) from exc
        except (BrokenPipeError, ConnectionError) as exc:
            raise HarnessTransportError(
                f"DeepSeek Harness transport closed{self._diagnostics()}"
            ) from exc
        finally:
            self._responses.pop(request_id, None)

    async def _read_stdout(self) -> None:
        process = self.process
        if process is None or process.stdout is None:
            return
        error: BaseException | None = None
        try:
            while line := await process.stdout.readline():
                try:
                    message = json.loads(line)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if not isinstance(message, dict):
                    continue
                request_id = message.get("id")
                method = message.get("method")
                if isinstance(request_id, (str, int)) and not isinstance(method, str):
                    future = self._responses.get(str(request_id))
                    if future is None or future.done():
                        continue
                    raw_error = message.get("error")
                    if isinstance(raw_error, dict):
                        future.set_exception(
                            HarnessProtocolError(str(raw_error.get("message") or "JSON-RPC error"))
                        )
                    else:
                        future.set_result(message.get("result"))
                elif isinstance(method, str) and request_id is None:
                    await self._notifications.put(
                        {"method": method, "params": message.get("params") or {}}
                    )
        except asyncio.CancelledError:
            return
        except BaseException as exc:
            error = exc
        if self._cancelled:
            error = HarnessCancelledError("DeepSeek Harness execution was cancelled")
        elif error is None:
            error = HarnessTransportError(f"DeepSeek Harness exited{self._diagnostics()}")
        self._fail_waiters(error)
        await self._notifications.put(error)

    async def _read_stderr(self) -> None:
        process = self.process
        if process is None or process.stderr is None:
            return
        try:
            while line := await process.stderr.readline():
                self._stderr.append(line.decode(errors="replace").rstrip())
        except asyncio.CancelledError:
            return

    def _fail_waiters(self, error: BaseException) -> None:
        for future in self._responses.values():
            if not future.done():
                future.set_exception(error)

    async def _terminate_process_group(self, sig: signal.Signals) -> None:
        process = self.process
        if process is None or process.returncode is not None:
            return
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            return

    async def _finish_readers(self) -> None:
        readers = [task for task in (self._reader, self._stderr_reader) if task is not None]
        for task in readers:
            if not task.done():
                task.cancel()
        if readers:
            await asyncio.gather(*readers, return_exceptions=True)

    def _diagnostics(self) -> str:
        process = self.process
        details = []
        if process is not None and process.returncode is not None:
            details.append(f"exit_code={process.returncode}")
        if self._stderr:
            details.append("stderr_tail=" + " | ".join(self._stderr))
        return f" ({'; '.join(details)})" if details else ""


def _runtime_launch(runtime_bin: str | None) -> tuple[tuple[str, ...], str | None]:
    if runtime_bin:
        return (runtime_bin,), None
    return (
        (
            "node",
            "/opt/deepseek-harness/node_modules/@deepseek-ai/dsh-sdk-jsonrpc-demo/lib/packaged-bin.js",
        ),
        "/app/cordis.yml",
    )


def _own_private_path(root: Path, uid: int) -> None:
    for current, directory_names, filenames in os.walk(root, followlinks=False):
        current_path = Path(current)
        os.chown(current_path, uid, uid)
        current_path.chmod(0o700)
        for name in directory_names:
            path = current_path / name
            if path.is_symlink():
                os.chown(path, uid, uid, follow_symlinks=False)
        for name in filenames:
            path = current_path / name
            if path.is_symlink():
                os.chown(path, uid, uid, follow_symlinks=False)
                continue
            executable = bool(path.stat().st_mode & 0o111)
            os.chown(path, uid, uid)
            path.chmod(0o700 if executable else 0o600)


def _subprocess_identity(session_root: Path, execution_uid: int) -> dict[str, Any]:
    # The official persistence plugin opens the shared session parent while
    # initializing. Give the child only that parent's group; sibling session
    # directories remain private because each one is owned by a distinct UID
    # and kept at mode 0700.
    return {
        "user": execution_uid,
        "group": execution_uid,
        "extra_groups": (session_root.parent.stat().st_gid,),
        "umask": 0o077,
    }


def _final_response(events: list[JsonObject]) -> str:
    for event in reversed(events):
        if event.get("type") != "assistant/message":
            continue
        data = event.get("data")
        message = data.get("message") if isinstance(data, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            continue
        return "".join(
            str(block.get("text") or "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""


def _finish_reason(events: list[JsonObject]) -> str | None:
    for event in reversed(events):
        if event.get("type") != "turn/end":
            continue
        data = event.get("data")
        reason = data.get("reason") if isinstance(data, dict) else None
        kind = reason.get("kind") if isinstance(reason, dict) else None
        if not isinstance(kind, str):
            raise HarnessProtocolError("turn/end is missing data.reason.kind")
        return kind
    return None


def _turn_error_detail(events: list[JsonObject]) -> str | None:
    """Extract a bounded, redacted diagnostic from an official turn/end event."""
    for event in reversed(events):
        if event.get("type") != "turn/end":
            continue
        data = event.get("data")
        if not isinstance(data, dict):
            return None
        reason = data.get("reason")
        if not isinstance(reason, dict) or reason.get("kind") != "error":
            return None
        for value in (
            reason.get("message"),
            reason.get("error"),
            data.get("message"),
            data.get("error"),
        ):
            detail = _error_message(value)
            if detail:
                return detail
        return None
    return None


def _error_message(value: Any) -> str | None:
    if isinstance(value, str):
        normalized = " ".join(value.split())
    elif isinstance(value, dict):
        normalized = ""
        for key in ("message", "detail", "error", "code", "type"):
            nested = _error_message(value.get(key))
            if nested:
                normalized = nested
                break
    else:
        return None
    if not normalized:
        return None
    redacted = re.sub(
        r"(?i)\b(authorization|api[-_ ]?key|token)\b\s*[:=]\s*\S+",
        r"\1=[REDACTED]",
        normalized,
    )
    return redacted[:500]


def _token_usage(events: list[JsonObject]) -> int | None:
    total = 0
    found = False
    for event in events:
        if event.get("type") != "assistant/message":
            continue
        data = event.get("data")
        usage = data.get("usage") if isinstance(data, dict) else None
        if not isinstance(usage, dict):
            continue
        for field in ("inputTokens", "outputTokens", "cacheReadTokens"):
            value = usage.get(field)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                total += value
                found = True
    return total if found else None

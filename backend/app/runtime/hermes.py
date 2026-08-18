from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import get_settings


class HermesRuntimeError(RuntimeError):
    pass


@dataclass(frozen=True)
class RuntimeArtifact:
    filename: str
    content: bytes
    content_type: str
    artifact_type: str


@dataclass(frozen=True)
class HermesRunResult:
    output: str
    run_id: str | None
    status: str
    token_usage: int | None = None
    trace: tuple[dict[str, Any], ...] = ()
    artifacts: tuple[RuntimeArtifact, ...] = ()


class HermesClient:
    terminal_statuses = {"completed", "succeeded", "failed", "cancelled", "canceled", "expired"}
    successful_statuses = {"completed", "succeeded"}

    def __init__(self, *, endpoint: str | None = None) -> None:
        settings = get_settings()
        self.runs_url = f"{(endpoint or settings.hermes_endpoint).rstrip('/')}/runs"
        self.api_key = settings.hermes_api_key.get_secret_value()
        self.model = settings.hermes_model
        self.timeout = settings.hermes_timeout_seconds
        self.poll_interval = settings.hermes_poll_interval_seconds

    async def run(
        self,
        *,
        prompt: str,
        agent_id: str,
        execution_id: str,
        requested_model: str | None = None,
        model_adapter: str = "hermes",
        runtime_options: dict[str, Any] | None = None,
    ) -> HermesRunResult:
        headers = self._headers()
        payload = self._payload(
            prompt=prompt,
            agent_id=agent_id,
            execution_id=execution_id,
            requested_model=requested_model,
            model_adapter=model_adapter,
            runtime_options=runtime_options,
        )
        timeout = httpx.Timeout(self.timeout + 10, connect=10)
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            created = await self._request_json(client, "POST", self.runs_url, headers=headers, json=payload)
            immediate_output = self._extract_output(created)
            status = self._extract_status(created)
            run_id = self._extract_id(created)
            if immediate_output and (not run_id or status in self.successful_statuses):
                return HermesRunResult(
                    output=immediate_output,
                    run_id=run_id,
                    status=status or "completed",
                    token_usage=self._extract_token_usage(created),
                )
            if not run_id:
                raise HermesRuntimeError("Hermes did not return a run id or final output")

            elapsed = 0.0
            while elapsed < self.timeout:
                await asyncio.sleep(self.poll_interval)
                elapsed += self.poll_interval
                run = await self._request_json(
                    client,
                    "GET",
                    f"{self.runs_url}/{run_id}",
                    headers=headers,
                )
                status = self._extract_status(run)
                output = self._extract_output(run)
                if status in self.successful_statuses and output:
                    return HermesRunResult(
                        output=output,
                        run_id=run_id,
                        status=status,
                        token_usage=self._extract_token_usage(run),
                    )
                if status in self.terminal_statuses and status not in self.successful_statuses:
                    error = self._extract_error(run)
                    raise HermesRuntimeError(f"Hermes run ended with status {status}: {error}")
            raise HermesRuntimeError(f"Hermes run timed out after {self.timeout} seconds")

    async def stream(
        self,
        *,
        prompt: str,
        agent_id: str,
        execution_id: str,
        requested_model: str | None = None,
        model_adapter: str = "hermes",
        runtime_options: dict[str, Any] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield Hermes' native structured run events, including real message deltas."""
        headers = self._headers()
        payload = self._payload(
            prompt=prompt,
            agent_id=agent_id,
            execution_id=execution_id,
            requested_model=requested_model,
            model_adapter=model_adapter,
            runtime_options=runtime_options,
        )
        timeout = httpx.Timeout(self.timeout + 10, connect=10)
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            created = await self._request_json(client, "POST", self.runs_url, headers=headers, json=payload)
            run_id = self._extract_id(created)
            immediate_output = self._extract_output(created)
            created_status = self._extract_status(created)
            if immediate_output and (not run_id or created_status in self.successful_statuses):
                event: dict[str, Any] = {
                    "event": "run.completed",
                    "run_id": run_id,
                    "output": immediate_output,
                    "status": created_status or "completed",
                }
                if isinstance(created.get("usage"), dict):
                    event["usage"] = created["usage"]
                yield event
                return
            if not run_id:
                raise HermesRuntimeError("Hermes did not return a run id or final output")

            yield {"event": "run.created", "run_id": run_id, "status": created_status or "started"}
            terminal_seen = False
            try:
                async with client.stream(
                    "GET",
                    f"{self.runs_url}/{run_id}/events",
                    headers=headers,
                ) as response:
                    if response.is_error:
                        body = (await response.aread()).decode(errors="replace")[:500]
                        raise HermesRuntimeError(
                            f"Hermes event stream returned HTTP {response.status_code}: {body}"
                        )
                    async for line in response.aiter_lines():
                        if line.startswith(":"):
                            yield {"event": "_keepalive", "run_id": run_id}
                            continue
                        if not line.startswith("data:"):
                            continue
                        raw = line[5:].strip()
                        if not raw:
                            continue
                        try:
                            event = json.loads(raw)
                        except ValueError as exc:
                            raise HermesRuntimeError("Hermes returned an invalid SSE event") from exc
                        if not isinstance(event, dict):
                            raise HermesRuntimeError("Hermes returned a non-object SSE event")
                        event.setdefault("run_id", run_id)
                        yield event
                        if str(event.get("event", "")) in {
                            "run.completed",
                            "run.failed",
                            "run.cancelled",
                            "run.canceled",
                        }:
                            terminal_seen = True
            except asyncio.CancelledError:
                try:
                    await client.post(f"{self.runs_url}/{run_id}/stop", headers=headers)
                except httpx.HTTPError:
                    pass
                raise
            except httpx.TimeoutException as exc:
                raise HermesRuntimeError("Hermes event stream timed out") from exc
            except httpx.HTTPError as exc:
                raise HermesRuntimeError(f"Hermes event stream failed: {exc}") from exc

            if terminal_seen:
                return
            final = await self._request_json(client, "GET", f"{self.runs_url}/{run_id}", headers=headers)
            final_status = self._extract_status(final)
            if final_status in self.successful_statuses:
                event = {
                    "event": "run.completed",
                    "run_id": run_id,
                    "output": self._extract_output(final),
                    "status": final_status,
                }
                if isinstance(final.get("usage"), dict):
                    event["usage"] = final["usage"]
                yield event
                return
            raise HermesRuntimeError(
                f"Hermes event stream ended with status {final_status or 'unknown'}: {self._extract_error(final)}"
            )

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def _payload(
        self,
        *,
        prompt: str,
        agent_id: str,
        execution_id: str,
        requested_model: str | None = None,
        model_adapter: str = "hermes",
        runtime_options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "model": requested_model or self.model,
            "input": prompt,
            "metadata": {
                "agent_id": agent_id,
                "execution_id": execution_id,
                "source": "hermes-agent-platform",
                "requested_model": requested_model or self.model,
                "model_adapter": model_adapter,
                "runtime_options": runtime_options or {},
            },
        }

    @staticmethod
    async def _request_json(client: httpx.AsyncClient, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = await client.request(method, url, **kwargs)
            response.raise_for_status()
            payload = response.json()
        except httpx.TimeoutException as exc:
            raise HermesRuntimeError("Hermes request timed out") from exc
        except httpx.HTTPStatusError as exc:
            body = exc.response.text[:500]
            raise HermesRuntimeError(f"Hermes returned HTTP {exc.response.status_code}: {body}") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise HermesRuntimeError(f"Hermes request failed: {exc}") from exc
        if not isinstance(payload, dict):
            raise HermesRuntimeError("Hermes returned a non-object response")
        return payload

    @staticmethod
    def _extract_id(payload: dict[str, Any]) -> str | None:
        value = payload.get("id") or payload.get("run_id")
        return str(value) if value else None

    @staticmethod
    def _extract_status(payload: dict[str, Any]) -> str:
        value = payload.get("status") or payload.get("state") or ""
        return str(value).lower()

    @staticmethod
    def _extract_token_usage(payload: dict[str, Any]) -> int | None:
        """Read only the Runtime's explicit aggregate token observation."""
        usage = payload.get("usage")
        if not isinstance(usage, dict):
            return None
        value = usage.get("total_tokens")
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return None
        return value

    @classmethod
    def _extract_output(cls, payload: dict[str, Any]) -> str:
        for key in ("output_text", "text", "response", "result"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, dict):
                nested = cls._extract_output(value)
                if nested:
                    return nested

        output = payload.get("output")
        if isinstance(output, str):
            return output.strip()
        if isinstance(output, list):
            parts: list[str] = []
            for item in output:
                if isinstance(item, str):
                    parts.append(item)
                    continue
                if not isinstance(item, dict):
                    continue
                content = item.get("content")
                if isinstance(content, str):
                    parts.append(content)
                elif isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and isinstance(block.get("text"), str):
                            parts.append(block["text"])
            return "\n".join(part.strip() for part in parts if part.strip())
        return ""

    @staticmethod
    def _extract_error(payload: dict[str, Any]) -> str:
        value = payload.get("error") or payload.get("last_error") or "no error details"
        if isinstance(value, dict):
            value = value.get("message") or value.get("detail") or str(value)
        return str(value)[:500]

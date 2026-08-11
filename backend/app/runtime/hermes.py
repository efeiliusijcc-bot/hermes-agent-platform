from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import get_settings


class HermesRuntimeError(RuntimeError):
    pass


@dataclass(frozen=True)
class HermesRunResult:
    output: str
    run_id: str | None
    status: str


class HermesClient:
    terminal_statuses = {"completed", "succeeded", "failed", "cancelled", "canceled", "expired"}
    successful_statuses = {"completed", "succeeded"}

    def __init__(self) -> None:
        settings = get_settings()
        self.runs_url = f"{settings.hermes_endpoint.rstrip('/')}/runs"
        self.api_key = settings.hermes_api_key.get_secret_value()
        self.model = settings.hermes_model
        self.timeout = settings.hermes_timeout_seconds
        self.poll_interval = settings.hermes_poll_interval_seconds

    async def run(self, *, prompt: str, agent_id: str, execution_id: str) -> HermesRunResult:
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {
            "model": self.model,
            "input": prompt,
            "metadata": {"agent_id": agent_id, "execution_id": execution_id, "source": "hermes-agent-platform"},
        }
        timeout = httpx.Timeout(self.timeout + 10, connect=10)
        async with httpx.AsyncClient(timeout=timeout) as client:
            created = await self._request_json(client, "POST", self.runs_url, headers=headers, json=payload)
            immediate_output = self._extract_output(created)
            status = self._extract_status(created)
            run_id = self._extract_id(created)
            if immediate_output and (not run_id or status in self.successful_statuses):
                return HermesRunResult(output=immediate_output, run_id=run_id, status=status or "completed")
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
                    return HermesRunResult(output=output, run_id=run_id, status=status)
                if status in self.terminal_statuses and status not in self.successful_statuses:
                    error = self._extract_error(run)
                    raise HermesRuntimeError(f"Hermes run ended with status {status}: {error}")
            raise HermesRuntimeError(f"Hermes run timed out after {self.timeout} seconds")

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

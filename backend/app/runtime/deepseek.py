from __future__ import annotations

import re
from collections.abc import AsyncIterator
from typing import Any

from app.runtime.base import RuntimeAdapterError, RuntimeContext, RuntimeSession
from app.runtime.hermes import HermesRunResult, RuntimeArtifact
from app.runtime.pi import PiRuntimeAdapter


SAFE_FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$")
CODING_ARTIFACT_TYPES = {"code_patch", "git_diff", "test_report"}


class DeepSeekRuntimeAdapter(PiRuntimeAdapter):
    """Adapter for the Hermes-owned DeepSeek Harness bridge.

    DeepSeek Harness itself exposes newline-delimited JSON-RPC over a child
    process' stdio. The internal bridge owns those processes and presents the
    platform's HTTP Runtime contract so API and Worker containers can share
    lifecycle, cancellation, streaming, and health semantics.
    """

    runtime_type = "deepseek"
    runtime_label = "DeepSeek"

    @staticmethod
    def _default_endpoint(settings: Any) -> str | None:
        return settings.deepseek_runtime_endpoint

    @staticmethod
    def _default_timeout(settings: Any) -> float:
        return settings.deepseek_runtime_timeout_seconds

    @staticmethod
    def _default_api_key(settings: Any) -> str | None:
        return (
            settings.deepseek_runtime_api_key.get_secret_value()
            if settings.deepseek_runtime_api_key is not None
            else None
        )

    async def create_session(
        self,
        *,
        agent_id: str,
        execution_id: str,
        metadata: dict[str, Any] | None = None,
        context: RuntimeContext | None = None,
    ) -> RuntimeSession:
        self._require_repository(context)
        return await super().create_session(
            agent_id=agent_id,
            execution_id=execution_id,
            metadata=metadata,
            context=context,
        )

    async def execute(
        self,
        messages: list[dict[str, str]],
        *,
        session_id: str,
        model: str,
        model_adapter: str,
        agent_id: str,
        execution_id: str,
        runtime_options: dict[str, Any] | None = None,
        context: RuntimeContext | None = None,
    ) -> HermesRunResult:
        self._require_repository(context)
        return await super().execute(
            messages,
            session_id=session_id,
            model=model,
            model_adapter=model_adapter,
            agent_id=agent_id,
            execution_id=execution_id,
            runtime_options=runtime_options,
            context=context,
        )

    async def stream(
        self,
        messages: list[dict[str, str]],
        *,
        session_id: str,
        model: str,
        model_adapter: str,
        agent_id: str,
        execution_id: str,
        runtime_options: dict[str, Any] | None = None,
        context: RuntimeContext | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        self._require_repository(context)
        async for event in super().stream(
            messages,
            session_id=session_id,
            model=model,
            model_adapter=model_adapter,
            agent_id=agent_id,
            execution_id=execution_id,
            runtime_options=runtime_options,
            context=context,
        ):
            yield event

    def result_artifacts(self, payload: dict[str, Any]) -> tuple[RuntimeArtifact, ...]:
        raw_artifacts = payload.get("artifacts") or []
        if not isinstance(raw_artifacts, list):
            raise RuntimeAdapterError("DeepSeek Runtime artifacts must be an array")
        values: list[RuntimeArtifact] = []
        filenames: set[str] = set()
        for raw in raw_artifacts:
            if not isinstance(raw, dict):
                raise RuntimeAdapterError("DeepSeek Runtime returned an invalid artifact")
            filename = str(raw.get("filename") or "")
            artifact_type = str(raw.get("artifact_type") or "")
            content = raw.get("content")
            if (
                not SAFE_FILENAME.fullmatch(filename)
                or filename in {"result.json", "result.txt", "report.md"}
                or filename in filenames
            ):
                raise RuntimeAdapterError("DeepSeek Runtime returned an unsafe artifact filename")
            if artifact_type not in CODING_ARTIFACT_TYPES:
                raise RuntimeAdapterError("DeepSeek Runtime returned an unsupported artifact type")
            if not isinstance(content, str):
                raise RuntimeAdapterError("DeepSeek Runtime artifact content must be text")
            content_type = str(raw.get("content_type") or "text/plain; charset=utf-8")
            filenames.add(filename)
            values.append(
                RuntimeArtifact(
                    filename=filename,
                    content=content.encode("utf-8"),
                    content_type=content_type,
                    artifact_type=artifact_type,
                )
            )
        return tuple(values)

    @staticmethod
    def _require_repository(context: RuntimeContext | None) -> None:
        if context is None or context.workspace_type != "repository":
            raise RuntimeAdapterError("DeepSeek Runtime requires a repository workspace")

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from app.runtime.hermes import HermesClient, HermesRunResult


SUPPORTED_ADAPTERS = ("hermes", "qwen", "deepseek", "gpt", "claude")


@dataclass(frozen=True)
class ModelAdapter:
    """Uniform chat interface over the Hermes runtime and its model gateway.

    Hermes remains responsible for the agent loop and tool execution. Provider
    adapters identify the requested provider/model in run metadata while the
    runtime's model gateway handles the target network protocol.
    """

    name: str

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str,
        agent_id: str,
        execution_id: str,
        runtime_options: dict[str, Any] | None = None,
    ) -> HermesRunResult:
        return await HermesClient().run(
            prompt=self.render_messages(messages),
            agent_id=agent_id,
            execution_id=execution_id,
            requested_model=model,
            model_adapter=self.name,
            runtime_options=runtime_options,
        )

    async def stream_chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str,
        agent_id: str,
        execution_id: str,
        runtime_options: dict[str, Any] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        async for event in HermesClient().stream(
            prompt=self.render_messages(messages),
            agent_id=agent_id,
            execution_id=execution_id,
            requested_model=model,
            model_adapter=self.name,
            runtime_options=runtime_options,
        ):
            yield event

    @staticmethod
    def render_messages(messages: list[dict[str, str]]) -> str:
        return "\n\n".join(
            f"{message['role'].upper()}:\n{message['content']}"
            for message in messages
        )


def get_model_adapter(name: str) -> ModelAdapter:
    normalized = name.strip().lower()
    if normalized not in SUPPORTED_ADAPTERS:
        raise ValueError(f"unsupported model adapter: {name}")
    return ModelAdapter(name=normalized)


def supported_model_adapters() -> tuple[str, ...]:
    return SUPPORTED_ADAPTERS

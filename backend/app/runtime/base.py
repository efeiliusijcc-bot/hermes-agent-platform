from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from app.runtime.hermes import HermesRunResult


class RuntimeAdapterError(RuntimeError):
    """A runtime failed before or during an Agent loop."""


class RuntimeCancelledError(RuntimeAdapterError):
    """A runtime run was cancelled by an explicit stop request."""


@dataclass(frozen=True)
class RuntimeSession:
    id: str
    runtime_type: str


@dataclass(frozen=True)
class RuntimeHealth:
    status: str
    version: str | None = None
    detail: str = "ok"


@dataclass(frozen=True)
class RuntimeFeatureProfile:
    runtime_type: str
    features: dict[str, bool]


@dataclass(frozen=True)
class RuntimeContext:
    agent_id: str
    session_id: str
    workspace: str
    memory_namespace: str
    workspace_type: str = "document"
    capability_profile: dict[str, Any] | None = None
    tools: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()
    metadata: dict[str, Any] | None = None
    capability_tools: tuple[dict[str, Any], ...] = ()
    capability_token: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "session_id": self.session_id,
            "workspace": self.workspace,
            "workspace_type": self.workspace_type,
            "memory_namespace": self.memory_namespace,
            "capability_profile": self.capability_profile or {},
            "tools": list(self.tools),
            "skills": list(self.skills),
            "metadata": self.metadata or {},
            "capability_tools": list(self.capability_tools),
            "capability_token": self.capability_token,
        }


class RuntimeAdapter(ABC):
    runtime_type: str

    def describe_features(self) -> RuntimeFeatureProfile:
        return RuntimeFeatureProfile(
            runtime_type=self.runtime_type,
            features={
                "tool_call": True,
                "structured_output": True,
                "streaming": True,
                "stop": True,
            },
        )

    @abstractmethod
    async def create_session(
        self,
        *,
        agent_id: str,
        execution_id: str,
        metadata: dict[str, Any] | None = None,
        context: RuntimeContext | None = None,
    ) -> RuntimeSession:
        raise NotImplementedError

    @abstractmethod
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
        raise NotImplementedError

    @abstractmethod
    def stream(
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
        raise NotImplementedError

    @abstractmethod
    async def stop(self, run_id: str) -> None:
        raise NotImplementedError

    @abstractmethod
    async def health_check(self) -> RuntimeHealth:
        raise NotImplementedError

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import Agent, AgentTask, ExecutionLog, Workflow, WorkflowRun
from app.message_bus import AgentMessageBus, AgentMessageBusError
from app.repositories import multi_agent as multi_repository
from app.repositories import orchestration as task_repository
from app.schemas.multi_agent import MultiAgentRunRequest, WorkflowNodeSpec
from app.task_queue import TaskQueue
from app.workspace import WorkspaceManager
from app.workspace import WorkspaceBoundaryError
from app.runtime.capabilities import normalize_capability_profile


class OrchestratorError(RuntimeError):
    pass


def _orchestration_memory_session_id(
    client_session_id: str,
    run_id: UUID,
    node_key: str,
) -> str:
    """Build a stable runtime-safe memory namespace for one orchestration node."""

    digest = sha256(f"{client_session_id}:{run_id}:{node_key}".encode("utf-8")).hexdigest()
    return f"ma-{run_id.hex}-{digest[:24]}"


class AgentOrchestrator:
    def __init__(self, queue: TaskQueue, message_bus: AgentMessageBus) -> None:
        self.queue = queue
        self.message_bus = message_bus
        self.settings = get_settings()

    async def submit_team_run(
        self,
        session: AsyncSession,
        *,
        team: Any,
        payload: MultiAgentRunRequest,
    ) -> WorkflowRun:
        run = await multi_repository.create_run(
            session, team_id=team.id, workflow_id=None, input_text=payload.input
        )
        root = await self._create_task(
            session,
            agent=team.owner_agent,
            run=run,
            payload=payload,
            node_key="__manager__",
            node_type="agent",
            parent_task_id=None,
            role="manager",
            initial_status="waiting_child",
        )
        children: list[AgentTask] = []
        for member in sorted(team.members, key=lambda item: (-item.priority, item.agent_id)):
            if member.agent_id == team.owner_agent_id or member.agent.status != "active":
                continue
            child = await self._create_task(
                session,
                agent=member.agent,
                run=run,
                payload=payload,
                node_key=f"member-{member.agent_id}",
                node_type="agent",
                parent_task_id=root.id,
                role=member.role,
                initial_status="pending",
            )
            children.append(child)
        run.status = "running"
        run.started_at = datetime.now(timezone.utc)
        if not children:
            root.status = "pending"
            await session.commit()
            await self.queue.enqueue(root.id, root.priority)
        else:
            await session.commit()
            for child in children:
                await self.queue.enqueue(child.id, child.priority)
                await self._publish_task(root, child, payload.input)
        return run

    async def submit_workflow_run(
        self,
        session: AsyncSession,
        *,
        team: Any,
        workflow: Workflow,
        payload: MultiAgentRunRequest,
    ) -> WorkflowRun:
        nodes = [WorkflowNodeSpec.model_validate(item) for item in workflow.definition.get("nodes", [])]
        if not nodes:
            raise OrchestratorError("workflow has no executable nodes")
        members = {member.agent_id: member.agent for member in team.members}
        resolved_agents: dict[str, Agent] = {}
        for node in nodes:
            agent_id = node.agent_id or team.owner_agent_id
            agent = members.get(agent_id)
            if agent is None or agent.status != "active":
                raise OrchestratorError(
                    f"workflow node {node.key} references an unavailable team Agent"
                )
            resolved_agents[node.key] = agent
        run = await multi_repository.create_run(
            session, team_id=team.id, workflow_id=workflow.id, input_text=payload.input
        )
        root = await self._create_task(
            session,
            agent=team.owner_agent,
            run=run,
            payload=payload,
            node_key="__manager__",
            node_type="agent",
            parent_task_id=None,
            role="manager",
            initial_status="waiting_child",
            workflow_id=workflow.id,
        )
        ready: list[AgentTask] = []
        for node in nodes:
            agent = resolved_agents[node.key]
            if node.node_type == "human_approval" and not node.depends_on:
                initial_status = "human_review"
            elif node.depends_on:
                initial_status = "waiting_child"
            else:
                initial_status = "pending"
            child = await self._create_task(
                session,
                agent=agent,
                run=run,
                payload=payload,
                node_key=node.key,
                node_type=node.node_type,
                parent_task_id=root.id,
                role=node.name,
                initial_status=initial_status,
                workflow_id=workflow.id,
                depends_on=node.depends_on,
                config=node.config,
            )
            if initial_status == "pending":
                ready.append(child)
        run.status = "human_review" if any(
            node.node_type == "human_approval" and not node.depends_on for node in nodes
        ) else "running"
        run.started_at = datetime.now(timezone.utc)
        await session.commit()
        for task in ready:
            await self.queue.enqueue(task.id, task.priority)
            await self._publish_task(root, task, payload.input)
        return run

    async def reconcile_run(self, session: AsyncSession, run: WorkflowRun) -> None:
        tasks = await task_repository.list_run_tasks(session, run.id)
        root = next((task for task in tasks if task.parent_task_id is None), None)
        if root is None:
            run.status = "failed"
            run.error = "orchestration root task is missing"
            run.finished_at = datetime.now(timezone.utc)
            await session.commit()
            return
        children = [task for task in tasks if task.parent_task_id == root.id]
        by_key = {task.node_key: task for task in children if task.node_key}

        failed = next((task for task in children if task.status == "failed"), None)
        if failed is not None:
            await self._fail_run(session, run, root, failed.error or f"task {failed.node_key} failed")
            return

        changed: list[AgentTask] = []
        for task in children:
            if task.status != "waiting_child":
                continue
            dependencies = [by_key.get(key) for key in task.depends_on]
            if any(item is None for item in dependencies):
                await self._fail_run(session, run, root, f"task {task.node_key} dependency is missing")
                return
            if any(item.status in {"failed", "cancelled"} for item in dependencies if item):
                task.status = "cancelled"
                task.error = "dependency failed or was cancelled"
                task.finished_at = datetime.now(timezone.utc)
                continue
            if dependencies and all(item.status == "succeeded" for item in dependencies if item):
                if task.node_type == "human_approval":
                    task.status = "human_review"
                else:
                    task.status = "pending"
                    changed.append(task)
        await session.commit()
        for task in changed:
            await self.queue.enqueue(task.id, task.priority)
            await self._publish_task(root, task, run.input)

        await session.refresh(run)
        tasks = await task_repository.list_run_tasks(session, run.id)
        root = next(task for task in tasks if task.parent_task_id is None)
        children = [task for task in tasks if task.parent_task_id == root.id]
        if any(task.status == "human_review" for task in children):
            run.status = "human_review"
            await session.commit()
            return
        run.status = "running"
        if children and all(task.status == "succeeded" for task in children):
            if root.status == "waiting_child":
                root.session.input = self._manager_prompt(run.input, children)
                root.input_data = {
                    **(root.input_data or {}),
                    "child_results": self._child_results(children),
                }
                if root.execution_id:
                    execution = await session.get(ExecutionLog, root.execution_id)
                    if execution is not None:
                        execution.input = root.session.input
                        execution.input_json = {
                            "task": root.session.input,
                            "parameters": {},
                            "orchestration_run_id": str(run.id),
                        }
                root.status = "pending"
                await session.commit()
                await self.queue.enqueue(root.id, root.priority)
                return
        if root.status == "succeeded":
            run.status = "succeeded"
            run.output = root.session.output
            run.error = None
            run.finished_at = root.finished_at or datetime.now(timezone.utc)
        elif root.status == "failed":
            await self._fail_run(session, run, root, root.error or "manager Agent failed")
            return
        await session.commit()

    async def _create_task(
        self,
        session: AsyncSession,
        *,
        agent: Agent,
        run: WorkflowRun,
        payload: MultiAgentRunRequest,
        node_key: str,
        node_type: str,
        parent_task_id: UUID | None,
        role: str,
        initial_status: str,
        workflow_id: UUID | None = None,
        depends_on: list[str] | None = None,
        config: dict[str, Any] | None = None,
    ) -> AgentTask:
        internal_session_id = uuid4()
        manager = WorkspaceManager(self.settings.workspace_root)
        capability_profile = normalize_capability_profile(
            agent.capability_profile,
            runtime_type=agent.runtime_type,
        )
        workspace_type = str(capability_profile["workspace_type"])
        try:
            workspace = manager.create_session(
                agent.id,
                internal_session_id,
                workspace_type=workspace_type,
            )
        except (OSError, WorkspaceBoundaryError) as exc:
            raise OrchestratorError("task workspace creation failed") from exc
        task_input = self._node_prompt(payload.input, role, node_type, config or {})
        return await task_repository.create_task(
            session,
            agent_id=agent.id,
            input_text=task_input,
            memory_session_id=_orchestration_memory_session_id(
                payload.session_id,
                run.id,
                node_key,
            ),
            user_id=payload.user_id,
            priority=payload.priority,
            max_attempts=self.settings.task_max_attempts,
            workspace_path=manager.relative(workspace.root),
            internal_session_id=internal_session_id,
            input_json={
                "task": task_input,
                "parameters": payload.parameters,
                "orchestration_run_id": str(run.id),
                "node_key": node_key,
                "node_type": node_type,
            },
            agent_version_id=agent.current_version_id,
            runtime_type=agent.runtime_type,
            workspace_type=workspace_type,
            parent_task_id=parent_task_id,
            workflow_id=workflow_id,
            workflow_run_id=run.id,
            node_key=node_key,
            node_type=node_type,
            depends_on=depends_on or [],
            task_input_data={"role": role, "config": config or {}, "original_input": payload.input},
            initial_status=initial_status,
        )

    async def _publish_task(self, root: AgentTask, task: AgentTask, input_text: str) -> None:
        try:
            await self.message_bus.publish(
                from_agent=root.agent_id,
                to_agent=task.agent_id,
                message_type="task",
                payload={"input": input_text, "node_key": task.node_key},
                task_id=str(task.id),
            )
        except AgentMessageBusError:
            # Redis task state remains authoritative. Reconciliation must not
            # fail after a task was already accepted by the queue.
            return

    async def _fail_run(
        self, session: AsyncSession, run: WorkflowRun, root: AgentTask, error: str
    ) -> None:
        now = datetime.now(timezone.utc)
        run.status = "failed"
        run.error = error[:2000]
        run.finished_at = now
        if root.status in {"waiting_child", "pending"}:
            root.status = "failed"
            root.error = error[:2000]
            root.finished_at = now
            root.session.status = "failed"
            root.session.finished_at = now
        await session.commit()

    @staticmethod
    def _node_prompt(original: str, role: str, node_type: str, config: dict[str, Any]) -> str:
        instruction = str(config.get("instruction") or "").strip()
        suffix = f"\n节点要求：{instruction}" if instruction else ""
        return f"团队总任务：{original}\n你的职责：{role}\n节点类型：{node_type}{suffix}"

    @staticmethod
    def _child_results(children: list[AgentTask]) -> list[dict[str, Any]]:
        return [
            {
                "node_key": task.node_key,
                "agent_id": task.agent_id,
                "output": task.session.output,
            }
            for task in children
        ]

    @classmethod
    def _manager_prompt(cls, original: str, children: list[AgentTask]) -> str:
        sections = ["请作为 Manager Agent 汇总并校验团队结果。", f"原始任务：{original}"]
        for result in cls._child_results(children):
            sections.append(
                f"\n[{result['node_key']} / {result['agent_id']}]\n{result['output'] or '(无输出)'}"
            )
        return "\n".join(sections)

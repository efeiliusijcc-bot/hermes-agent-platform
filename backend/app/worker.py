from __future__ import annotations

import asyncio
import logging
import signal
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException

from app.api.agents import execute_agent_sync
from app.config import get_settings
from app.db.session import SessionFactory, engine
from app.memory import AgentMemoryError, get_memory_store
from app.message_bus import AgentMessageBusError, get_agent_message_bus
from app.repositories import agents as agent_repository
from app.repositories import orchestration as repository
from app.repositories import production as production_repository
from app.runtime.hermes import HermesRuntimeError
from app.schemas.agent import AgentRunRequest
from app.task_queue import TaskQueueError, get_task_queue
from app.db.models import AgentTask, ExecutionLog
from sqlalchemy.ext.asyncio import AsyncSession


settings = get_settings()
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


class AgentWorker:
    def __init__(self) -> None:
        self.queue = get_task_queue()
        self.memory = get_memory_store()
        self.message_bus = get_agent_message_bus()
        self.stop = asyncio.Event()

    async def run(self) -> None:
        await self.queue.ping()
        await self.memory.ping()
        await self.message_bus.ping()
        await self._recover()
        loops = [asyncio.create_task(self._consume(index)) for index in range(settings.worker_concurrency)]
        recovery = asyncio.create_task(self._recovery_loop())
        await self.stop.wait()
        for item in [*loops, recovery]:
            item.cancel()
        await asyncio.gather(*loops, recovery, return_exceptions=True)

    async def close(self) -> None:
        await self.queue.close()
        await self.memory.close()
        await self.message_bus.close()
        await engine.dispose()

    async def _consume(self, index: int) -> None:
        worker_id = f"{settings.worker_id}-{index}"
        while not self.stop.is_set():
            try:
                task_id = await self.queue.dequeue()
            except TaskQueueError:
                logger.exception("task dequeue failed")
                await asyncio.sleep(settings.task_queue_poll_seconds)
                continue
            if task_id is None:
                await asyncio.sleep(settings.task_queue_poll_seconds)
                continue
            try:
                await self._execute(task_id, worker_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("unexpected task execution failure task=%s", task_id)

    async def _execute(self, task_id: UUID, worker_id: str) -> None:
        async with SessionFactory() as session:
            task = await repository.get_task(session, task_id, lock=True)
            if task is None or task.status not in {"pending", "retrying"}:
                return
            if task.session.status == "succeeded":
                task.status = "succeeded"
                task.error = None
                task.finished_at = task.session.finished_at or datetime.now(timezone.utc)
                task.worker_id = worker_id
                await session.commit()
                return
            agent = await agent_repository.get_agent(session, task.agent_id)
            if agent is None or agent.status != "active":
                await self._terminal_failure(task, session, "Agent is unavailable")
                return
            task.status = "running"
            task.attempt += 1
            task.worker_id = worker_id
            task.started_at = datetime.now(timezone.utc)
            task.error = None
            task.session.status = "running"
            task.session.started_at = task.started_at
            execution = await session.get(ExecutionLog, task.execution_id) if task.execution_id else None
            if execution is not None:
                execution.status = "running"
                execution.started_at = task.started_at
                execution.error = None
                execution.details = {**(execution.details or {}), "phase": "worker_running", "worker_id": worker_id}
            await session.commit()
            parameters = None
            temperature = None
            if execution is not None and isinstance(execution.input_json, dict):
                raw_parameters = execution.input_json.get("parameters")
                if isinstance(raw_parameters, dict):
                    parameters = raw_parameters
                runtime_options = execution.input_json.get("runtime_options")
                if isinstance(runtime_options, dict) and isinstance(
                    runtime_options.get("temperature"), (int, float)
                ):
                    temperature = float(runtime_options["temperature"])
            request = AgentRunRequest(
                input=task.session.input,
                session_id=task.session.memory_session_id,
                parameters=parameters,
                temperature=temperature,
            )
            runtime_agent = agent
            schema_runtime = None
            if execution is not None and execution.agent_version_id is not None:
                version = await production_repository.get_agent_version_by_id(
                    session, agent.id, execution.agent_version_id
                )
                if version is None:
                    await self._terminal_failure(task, session, "Agent Version is unavailable")
                    return
                try:
                    runtime_agent, schema_runtime = await production_repository.build_version_runtime_agent(
                        session, agent, version
                    )
                except ValueError as exc:
                    await self._terminal_failure(task, session, str(exc))
                    return
            try:
                await execute_agent_sync(
                    runtime_agent,
                    request,
                    session,
                    self.memory,
                    orchestration_session=task.session,
                    existing_execution=execution,
                    schema_version=schema_runtime,
                    response_mode="async",
                    retry_attempt=max(0, task.attempt - 1),
                    agent_version_id=(execution.agent_version_id if execution is not None else None),
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await session.rollback()
                task = await repository.get_task(session, task_id, lock=True)
                if task is None:
                    return
                message = _error_message(exc)
                if task.attempt < task.max_attempts:
                    task.status = "retrying"
                    task.error = message
                    task.worker_id = None
                    task.session.status = "queued"
                    task.session.finished_at = None
                    if task.execution_id:
                        execution = await session.get(ExecutionLog, task.execution_id)
                        if execution is not None:
                            execution.status = "queued"
                            execution.error = message
                            execution.finished_at = None
                    await session.commit()
                    if settings.task_retry_delay_seconds:
                        await asyncio.sleep(settings.task_retry_delay_seconds)
                    await self.queue.enqueue(task.id, task.priority)
                    return
                await self._terminal_failure(task, session, message)
                return
            await session.refresh(task, attribute_names=["session"])
            task.status = "succeeded"
            task.error = None
            task.finished_at = datetime.now(timezone.utc)
            task.worker_id = worker_id
            await session.commit()
            await self._publish_result(session, task)

    async def _terminal_failure(self, task: AgentTask, session: AsyncSession, message: str) -> None:
        now = datetime.now(timezone.utc)
        task.status = "failed"
        task.error = message[:2000]
        task.finished_at = now
        task.session.status = "failed"
        task.session.finished_at = now
        if task.execution_id:
            execution = await session.get(ExecutionLog, task.execution_id)
            if execution is not None:
                execution.status = "failed"
                execution.error = message[:2000]
                execution.finished_at = now
                execution.duration_ms = max(
                    0, int((now - execution.started_at).total_seconds() * 1000)
                )
        await session.commit()
        await self._publish_result(session, task)

    async def _publish_result(self, session: AsyncSession, task: AgentTask) -> None:
        if task.parent_task_id is None:
            return
        parent = await repository.get_task(session, task.parent_task_id)
        if parent is None:
            return
        try:
            await self.message_bus.publish(
                from_agent=task.agent_id,
                to_agent=parent.agent_id,
                message_type="result",
                payload={
                    "status": task.status,
                    "node_key": task.node_key,
                    "output": task.session.output,
                    "error": task.error,
                },
                task_id=str(task.id),
            )
        except AgentMessageBusError:
            logger.warning("could not publish Agent result task=%s", task.id)

    async def _recover(self) -> None:
        async with SessionFactory() as session:
            stale = await repository.stale_running_tasks(session, settings.task_stale_seconds)
            for task in stale:
                if task.session.status == "succeeded":
                    task.status = "succeeded"
                    task.error = None
                    task.worker_id = settings.worker_id
                    task.finished_at = task.session.finished_at or datetime.now(timezone.utc)
                    continue
                task.status = "retrying" if task.attempt < task.max_attempts else "failed"
                task.worker_id = None
                task.error = "worker lease expired"
                task.session.status = "queued" if task.status == "retrying" else "failed"
                if task.execution_id:
                    execution = await session.get(ExecutionLog, task.execution_id)
                    if execution is not None:
                        execution.status = "queued" if task.status == "retrying" else "failed"
                        execution.error = "worker lease expired"
                        if task.status == "failed":
                            execution.finished_at = datetime.now(timezone.utc)
                            execution.duration_ms = max(
                                0,
                                int(
                                    (execution.finished_at - execution.started_at).total_seconds()
                                    * 1000
                                ),
                            )
                if task.status == "failed":
                    task.finished_at = datetime.now(timezone.utc)
                    task.session.finished_at = task.finished_at
            await session.commit()
            pending = await repository.pending_tasks(session)
            for task in pending:
                await self.queue.enqueue(task.id, task.priority)

    async def _recovery_loop(self) -> None:
        while not self.stop.is_set():
            await asyncio.sleep(min(settings.task_stale_seconds / 2, 30))
            try:
                await self._recover()
            except Exception:
                logger.exception("task recovery failed")


def _error_message(exc: Exception) -> str:
    if isinstance(exc, HTTPException):
        return str(exc.detail)
    return str(exc)


async def main() -> None:
    worker = AgentWorker()
    loop = asyncio.get_running_loop()
    for name in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(name, worker.stop.set)
    try:
        await worker.run()
    finally:
        await worker.close()


if __name__ == "__main__":
    asyncio.run(main())

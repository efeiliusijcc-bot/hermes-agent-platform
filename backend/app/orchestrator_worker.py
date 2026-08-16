from __future__ import annotations

import asyncio
import logging
import signal

from app.config import get_settings
from app.db.session import SessionFactory, engine
from app.message_bus import get_agent_message_bus
from app.orchestrator import AgentOrchestrator
from app.repositories import multi_agent as repository
from app.task_queue import get_task_queue


settings = get_settings()
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


class OrchestratorWorker:
    def __init__(self) -> None:
        self.queue = get_task_queue()
        self.message_bus = get_agent_message_bus()
        self.orchestrator = AgentOrchestrator(self.queue, self.message_bus)
        self.stop = asyncio.Event()

    async def run(self) -> None:
        await self.queue.ping()
        await self.message_bus.ping()
        while not self.stop.is_set():
            try:
                async with SessionFactory() as session:
                    runs = await repository.list_runs(session, active_only=True)
                    for run in runs:
                        await self.orchestrator.reconcile_run(session, run)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("orchestration reconciliation failed")
            try:
                await asyncio.wait_for(
                    self.stop.wait(), timeout=settings.orchestrator_poll_seconds
                )
            except asyncio.TimeoutError:
                pass

    async def close(self) -> None:
        await self.queue.close()
        await self.message_bus.close()
        await engine.dispose()


async def main() -> None:
    worker = OrchestratorWorker()
    loop = asyncio.get_running_loop()
    for name in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(name, worker.stop.set)
    try:
        await worker.run()
    finally:
        await worker.close()


if __name__ == "__main__":
    asyncio.run(main())

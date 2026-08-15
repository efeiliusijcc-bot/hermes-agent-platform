from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator


class LocalConcurrencyGate:
    def __init__(self, limit: int) -> None:
        if limit < 1:
            raise ValueError("concurrency limit must be positive")
        self.limit = limit
        self._semaphore = asyncio.Semaphore(limit)

    @asynccontextmanager
    async def slot(self, timeout_seconds: float) -> AsyncIterator[None]:
        try:
            await asyncio.wait_for(self._semaphore.acquire(), timeout=timeout_seconds)
        except asyncio.TimeoutError as exc:
            raise TimeoutError("model concurrency capacity wait timed out") from exc
        try:
            yield
        finally:
            self._semaphore.release()

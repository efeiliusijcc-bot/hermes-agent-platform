from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class MemoryValueWrite(BaseModel):
    value: Any


class MemoryValueRead(BaseModel):
    namespace: str
    key: str
    value: Any

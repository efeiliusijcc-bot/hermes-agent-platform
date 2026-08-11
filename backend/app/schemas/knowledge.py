from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class KnowledgeSourceCreate(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$")
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    status: Literal["active", "disabled"] = "active"


class KnowledgeSourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str | None
    config: dict[str, Any]
    status: Literal["active", "disabled"]
    created_at: datetime
    updated_at: datetime


class KnowledgeDocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_id: str
    filename: str
    content_type: str
    sha256: str
    size_bytes: int
    chunk_count: int
    parser: str
    created_at: datetime


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=20_000)
    top_k: int = Field(default=5, ge=1, le=20)


class KnowledgeSearchHit(BaseModel):
    source_id: str
    document_id: UUID
    filename: str
    chunk_id: UUID
    chunk_index: int
    content: str
    score: float


class KnowledgeSearchResponse(BaseModel):
    hits: list[KnowledgeSearchHit]
    embedding_model: str
    dimensions: int


class AgentKnowledgeBindingRead(BaseModel):
    agent_id: str
    source_ids: list[str]

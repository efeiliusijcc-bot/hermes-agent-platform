from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import uuid
from contextlib import asynccontextmanager
from io import BytesIO
from pathlib import Path
from typing import Any, AsyncIterator

import asyncpg
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, status
from minio import Minio
from minio.error import S3Error
from pydantic import BaseModel, Field

from hermes_knowledge_service.embedding import EMBEDDING_DIMENSIONS, EMBEDDING_MODEL, embed_text, vector_literal
from hermes_knowledge_service.parsers import DocumentParseError, chunk_text, parse_document

logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

SOURCE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$")
MAX_UPLOAD_BYTES = int(os.environ.get("KNOWLEDGE_MAX_UPLOAD_BYTES", "10485760"))
CHUNK_MAX_CHARS = int(os.environ.get("KNOWLEDGE_CHUNK_MAX_CHARS", "1200"))
CHUNK_OVERLAP_CHARS = int(os.environ.get("KNOWLEDGE_CHUNK_OVERLAP_CHARS", "150"))
MINIO_BUCKET = os.environ.get("KNOWLEDGE_MINIO_BUCKET", "knowledge")
if not 1024 <= MAX_UPLOAD_BYTES <= 104_857_600:
    raise RuntimeError("KNOWLEDGE_MAX_UPLOAD_BYTES must be between 1024 and 104857600")
if not 256 <= CHUNK_MAX_CHARS <= 10_000:
    raise RuntimeError("KNOWLEDGE_CHUNK_MAX_CHARS must be between 256 and 10000")
if not 0 <= CHUNK_OVERLAP_CHARS < CHUNK_MAX_CHARS:
    raise RuntimeError("KNOWLEDGE_CHUNK_OVERLAP_CHARS must be smaller than KNOWLEDGE_CHUNK_MAX_CHARS")


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=20_000)
    source_ids: list[str] = Field(min_length=1, max_length=20)
    top_k: int = Field(default=5, ge=1, le=20)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    pool = await asyncpg.create_pool(
        host=os.environ.get("POSTGRES_HOST", "postgres"),
        port=int(os.environ.get("POSTGRES_PORT", "5432")),
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        database=os.environ["POSTGRES_DB"],
        min_size=1,
        max_size=5,
        command_timeout=30,
    )
    minio = Minio(
        os.environ.get("MINIO_ENDPOINT", "minio:9000"),
        access_key=os.environ["MINIO_ROOT_USER"],
        secret_key=os.environ["MINIO_ROOT_PASSWORD"],
        secure=False,
    )
    try:
        if not await asyncio.to_thread(minio.bucket_exists, MINIO_BUCKET):
            await asyncio.to_thread(minio.make_bucket, MINIO_BUCKET)
        app.state.pool = pool
        app.state.minio = minio
        yield
    finally:
        await pool.close()


app = FastAPI(title="Hermes Knowledge Service", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health(request: Request) -> dict[str, Any]:
    await request.app.state.pool.fetchval("SELECT 1")
    bucket_ready = await asyncio.to_thread(request.app.state.minio.bucket_exists, MINIO_BUCKET)
    if not bucket_ready:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Knowledge bucket is unavailable")
    return {
        "status": "ok",
        "database": "ok",
        "object_store": "ok",
        "embedding_model": EMBEDDING_MODEL,
        "dimensions": EMBEDDING_DIMENSIONS,
    }


@app.post("/v1/documents", status_code=status.HTTP_201_CREATED)
async def upload_document(
    request: Request,
    source_id: str = Form(...),
    file: UploadFile = File(...),
) -> dict[str, Any]:
    if not SOURCE_ID_PATTERN.fullmatch(source_id):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid Knowledge source id")
    source = await request.app.state.pool.fetchrow(
        "SELECT id, status FROM knowledge_sources WHERE id = $1",
        source_id,
    )
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge source not found")
    if source["status"] != "active":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Knowledge source is not active")

    filename = _safe_filename(file.filename or "document")
    content_type = (file.content_type or "application/octet-stream")[:255]
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if not content:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Uploaded document is empty")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Uploaded document is too large")
    try:
        parsed = await asyncio.to_thread(parse_document, filename, content)
        chunks = chunk_text(parsed.text, max_chars=CHUNK_MAX_CHARS, overlap_chars=CHUNK_OVERLAP_CHARS)
    except DocumentParseError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    if not chunks:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Document produced no chunks")

    document_id = uuid.uuid4()
    checksum = hashlib.sha256(content).hexdigest()
    object_key = f"{source_id}/{document_id}/{filename}"
    minio: Minio = request.app.state.minio
    try:
        await asyncio.to_thread(
            minio.put_object,
            MINIO_BUCKET,
            object_key,
            BytesIO(content),
            len(content),
            content_type=content_type,
        )
    except S3Error as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Document object could not be stored") from exc

    pool: asyncpg.Pool = request.app.state.pool
    try:
        async with pool.acquire() as connection:
            async with connection.transaction():
                created_at = await connection.fetchval(
                    """
                    INSERT INTO knowledge_documents(
                        id, source_id, filename, content_type, object_key, sha256,
                        size_bytes, chunk_count, parser
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    RETURNING created_at
                    """,
                    document_id,
                    source_id,
                    filename,
                    content_type,
                    object_key,
                    checksum,
                    len(content),
                    len(chunks),
                    parsed.parser,
                )
                await connection.executemany(
                    """
                    INSERT INTO knowledge_chunks(
                        id, document_id, source_id, chunk_index, content, char_count, embedding, metadata
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7::vector, $8::jsonb)
                    """,
                    [
                        (
                            uuid.uuid4(),
                            document_id,
                            source_id,
                            index,
                            chunk,
                            len(chunk),
                            vector_literal(embed_text(chunk)),
                            json.dumps({"filename": filename, "parser": parsed.parser}, ensure_ascii=False),
                        )
                        for index, chunk in enumerate(chunks)
                    ],
                )
    except asyncpg.UniqueViolationError as exc:
        await _remove_object(minio, object_key)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This document content already exists in the Knowledge source",
        ) from exc
    except Exception:
        await _remove_object(minio, object_key)
        raise

    logger.info("Knowledge document indexed: source=%s document=%s chunks=%s", source_id, document_id, len(chunks))
    return {
        "id": document_id,
        "source_id": source_id,
        "filename": filename,
        "content_type": content_type,
        "sha256": checksum,
        "size_bytes": len(content),
        "chunk_count": len(chunks),
        "parser": parsed.parser,
        "created_at": created_at,
    }


@app.post("/v1/search")
async def search(request: SearchRequest, http_request: Request) -> dict[str, Any]:
    if any(not SOURCE_ID_PATTERN.fullmatch(source_id) for source_id in request.source_ids):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid Knowledge source id")
    query_vector = vector_literal(embed_text(request.query))
    records = await http_request.app.state.pool.fetch(
        """
        SELECT
            chunk.source_id,
            chunk.document_id,
            document.filename,
            chunk.id AS chunk_id,
            chunk.chunk_index,
            chunk.content,
            1 - (chunk.embedding <=> $1::vector) AS score
        FROM knowledge_chunks AS chunk
        JOIN knowledge_documents AS document ON document.id = chunk.document_id
        JOIN knowledge_sources AS source ON source.id = chunk.source_id
        WHERE chunk.source_id = ANY($2::varchar[]) AND source.status = 'active'
        ORDER BY chunk.embedding <=> $1::vector, chunk.source_id, chunk.document_id, chunk.chunk_index
        LIMIT $3
        """,
        query_vector,
        request.source_ids,
        request.top_k,
    )
    return {
        "hits": [
            {
                "source_id": record["source_id"],
                "document_id": record["document_id"],
                "filename": record["filename"],
                "chunk_id": record["chunk_id"],
                "chunk_index": record["chunk_index"],
                "content": record["content"],
                "score": max(-1.0, min(1.0, float(record["score"]))),
            }
            for record in records
        ],
        "embedding_model": EMBEDDING_MODEL,
        "dimensions": EMBEDDING_DIMENSIONS,
    }


@app.delete("/v1/sources/{source_id}")
async def delete_source(source_id: str, request: Request) -> dict[str, str]:
    if not SOURCE_ID_PATTERN.fullmatch(source_id):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid Knowledge source id")
    pool: asyncpg.Pool = request.app.state.pool
    records = await pool.fetch("SELECT object_key FROM knowledge_documents WHERE source_id = $1", source_id)
    exists = await pool.fetchval("SELECT EXISTS(SELECT 1 FROM knowledge_sources WHERE id = $1)", source_id)
    if not exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge source not found")
    minio: Minio = request.app.state.minio
    for record in records:
        await _remove_object(minio, record["object_key"], strict=True)
    await pool.execute("DELETE FROM knowledge_sources WHERE id = $1", source_id)
    logger.info("Knowledge source deleted: source=%s documents=%s", source_id, len(records))
    return {"status": "deleted"}


def _safe_filename(filename: str) -> str:
    value = Path(filename).name.strip()
    if not value or value in {".", ".."}:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid document filename")
    if len(value) > 255:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Document filename is too long")
    return value


async def _remove_object(minio: Minio, object_key: str, *, strict: bool = False) -> None:
    try:
        await asyncio.to_thread(minio.remove_object, MINIO_BUCKET, object_key)
    except S3Error as exc:
        logger.exception("Knowledge object cleanup failed: key=%s", object_key)
        if strict:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Knowledge object could not be deleted",
            ) from exc

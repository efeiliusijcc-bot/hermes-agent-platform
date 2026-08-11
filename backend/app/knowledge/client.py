from __future__ import annotations

from typing import Any

import httpx

from app.config import get_settings


class KnowledgeServiceError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


class KnowledgeServiceClient:
    def __init__(self) -> None:
        settings = get_settings()
        self.base_url = settings.knowledge_service_endpoint.rstrip("/")
        self.timeout = settings.knowledge_service_timeout_seconds

    async def upload_document(
        self,
        *,
        source_id: str,
        filename: str,
        content_type: str,
        content: bytes,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/v1/documents",
            data={"source_id": source_id},
            files={"file": (filename, content, content_type)},
        )

    async def search(self, *, query: str, source_ids: list[str], top_k: int) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/v1/search",
            json={"query": query, "source_ids": source_ids, "top_k": top_k},
        )

    async def delete_source(self, source_id: str) -> None:
        await self._request("DELETE", f"/v1/sources/{source_id}")

    async def health(self) -> None:
        await self._request("GET", "/health")

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.request(method, f"{self.base_url}{path}", **kwargs)
        except httpx.TimeoutException as exc:
            raise KnowledgeServiceError("Knowledge service request timed out") from exc
        except httpx.HTTPError as exc:
            raise KnowledgeServiceError("Knowledge service request failed") from exc

        if response.is_error:
            try:
                detail = response.json().get("detail", "Knowledge service rejected the request")
            except (ValueError, AttributeError):
                detail = "Knowledge service rejected the request"
            status_code = response.status_code if 400 <= response.status_code < 500 else 502
            raise KnowledgeServiceError(str(detail)[:500], status_code=status_code)
        try:
            payload = response.json()
        except ValueError as exc:
            raise KnowledgeServiceError("Knowledge service returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise KnowledgeServiceError("Knowledge service returned a non-object response")
        return payload

from __future__ import annotations

from time import monotonic

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import ModelRegistration
from app.db.session import get_session
from app.model_secrets import ModelSecretCipher, ModelSecretError
from app.repositories import model_registrations as repository
from app.schemas.model_registration import (
    ModelConnectivityRead,
    ModelRegistrationCreate,
    ModelRegistrationRead,
    ModelRegistrationUpdate,
)


router = APIRouter(prefix="/api/models", tags=["model-registry"])


def get_cipher() -> ModelSecretCipher:
    configured = get_settings().model_registry_encryption_key
    if configured is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="模型密钥加密主密钥未配置",
        )
    try:
        return ModelSecretCipher(configured.get_secret_value())
    except ModelSecretError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="模型密钥加密主密钥无效",
        ) from exc


async def require_model(session: AsyncSession, model_id: str) -> ModelRegistration:
    value = await repository.get_model(session, model_id)
    if value is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="模型配置不存在")
    return value


@router.get("", response_model=list[ModelRegistrationRead])
async def list_models(
    enabled_only: bool = False,
    session: AsyncSession = Depends(get_session),
) -> list[ModelRegistrationRead]:
    return [
        ModelRegistrationRead.model_validate(item)
        for item in await repository.list_models(session, enabled_only=enabled_only)
    ]


@router.get("/{model_id}", response_model=ModelRegistrationRead)
async def get_model(
    model_id: str,
    session: AsyncSession = Depends(get_session),
) -> ModelRegistrationRead:
    return ModelRegistrationRead.model_validate(await require_model(session, model_id))


@router.post("", response_model=ModelRegistrationRead, status_code=status.HTTP_201_CREATED)
async def create_model(
    payload: ModelRegistrationCreate,
    session: AsyncSession = Depends(get_session),
) -> ModelRegistrationRead:
    try:
        value = await repository.create_model(session, payload, get_cipher())
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="模型 ID 已存在") from exc
    return ModelRegistrationRead.model_validate(value)


@router.patch("/{model_id}", response_model=ModelRegistrationRead)
async def update_model(
    model_id: str,
    payload: ModelRegistrationUpdate,
    session: AsyncSession = Depends(get_session),
) -> ModelRegistrationRead:
    value = await require_model(session, model_id)
    if value.is_default and (payload.is_enabled is False or payload.is_default is False):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="默认模型不能停用或取消默认；请先设置另一默认模型",
        )
    try:
        result = await repository.update_model(session, value, payload, get_cipher())
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="模型配置冲突") from exc
    return ModelRegistrationRead.model_validate(result)


@router.post("/{model_id}/default", response_model=ModelRegistrationRead)
async def set_default_model(
    model_id: str,
    session: AsyncSession = Depends(get_session),
) -> ModelRegistrationRead:
    value = await require_model(session, model_id)
    return ModelRegistrationRead.model_validate(await repository.set_default(session, value))


@router.post("/{model_id}/test", response_model=ModelConnectivityRead)
async def test_model(
    model_id: str,
    session: AsyncSession = Depends(get_session),
) -> ModelConnectivityRead:
    value = await require_model(session, model_id)
    if not value.is_enabled:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="模型已停用")
    try:
        api_key = (
            get_cipher().decrypt(value.api_key_ciphertext)
            if value.api_key_ciphertext
            else ""
        )
    except ModelSecretError as exc:
        await repository.record_health(session, value, online=False, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="模型密钥无法解密，请重新录入密钥",
        ) from exc

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    endpoint = _chat_completions_url(value.base_url)
    started = monotonic()
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(value.timeout_seconds, connect=10),
            follow_redirects=False,
        ) as client:
            response = await client.post(
                endpoint,
                headers=headers,
                json={
                    "model": value.upstream_model,
                    "messages": [{"role": "user", "content": "Respond with OK only."}],
                    "temperature": 0,
                    "max_tokens": 8,
                    "stream": False,
                },
            )
        online = response.is_success
        detail = "模型调用成功" if online else f"模型服务返回 HTTP {response.status_code}"
    except httpx.HTTPError as exc:
        online = False
        detail = f"模型连接失败：{type(exc).__name__}"
    latency = max(0, round((monotonic() - started) * 1000))
    await repository.record_health(session, value, online=online, error=None if online else detail)
    return ModelConnectivityRead(
        id=value.id,
        status="online" if online else "offline",
        latency_ms=latency,
        detail=detail,
    )


@router.delete("/{model_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_model(
    model_id: str,
    session: AsyncSession = Depends(get_session),
) -> Response:
    value = await require_model(session, model_id)
    if value.is_default:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="默认模型不能删除；请先设置另一默认模型",
        )
    references = await repository.agent_reference_count(session, value.id)
    if references:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"仍有 {references} 个 Agent 使用此模型，不能删除",
        )
    await repository.delete_model(session, value)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _chat_completions_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    return base if base.endswith("/chat/completions") else f"{base}/chat/completions"

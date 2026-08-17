from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Agent, ModelRegistration
from app.model_secrets import ModelSecretCipher

if TYPE_CHECKING:
    from app.schemas.model_registration import ModelRegistrationCreate, ModelRegistrationUpdate


async def create_model(
    session: AsyncSession,
    payload: ModelRegistrationCreate,
    cipher: ModelSecretCipher,
) -> ModelRegistration:
    if payload.is_default:
        await session.execute(
            update(ModelRegistration).values(is_default=False, updated_at=func.now())
        )
    secret = payload.api_key.get_secret_value() if payload.api_key is not None else ""
    value = ModelRegistration(
        id=payload.id,
        display_name=payload.display_name,
        provider=payload.provider,
        adapter=payload.adapter,
        base_url=payload.base_url,
        upstream_model=payload.upstream_model,
        api_key_ciphertext=cipher.encrypt(secret) if secret else None,
        is_enabled=payload.is_enabled,
        is_default=payload.is_default,
        timeout_seconds=payload.timeout_seconds,
        max_retries=payload.max_retries,
    )
    session.add(value)
    await session.commit()
    await session.refresh(value)
    return value


async def ensure_legacy_models(
    session: AsyncSession,
    *,
    model_id: str,
    base_url: str,
    upstream_model: str,
    api_key: str,
    cipher: ModelSecretCipher,
) -> list[ModelRegistration]:
    existing = await list_models(session)
    existing_ids = {item.id for item in existing}
    has_default = any(item.is_default for item in existing)
    usage_rows = (
        await session.execute(
            select(
                Agent.model,
                Agent.model_adapter,
                func.count(Agent.id).label("usage_count"),
            )
            .group_by(Agent.model, Agent.model_adapter)
            .order_by(Agent.model, func.count(Agent.id).desc(), Agent.model_adapter)
        )
    ).all()
    adapters: dict[str, str] = {}
    for row in usage_rows:
        adapters.setdefault(str(row.model), str(row.model_adapter))
    adapters.setdefault(model_id, adapters.get(model_id, "hermes"))

    created: list[ModelRegistration] = []
    for alias, adapter in adapters.items():
        if alias in existing_ids:
            continue
        provider = {
            "qwen": "qwen",
            "deepseek": "deepseek",
            "gpt": "openai",
            "claude": "claude",
        }.get(adapter, "custom")
        value = ModelRegistration(
            id=alias,
            display_name=alias,
            provider=provider,
            adapter=adapter,
            base_url=base_url,
            upstream_model=upstream_model if alias == model_id else alias,
            api_key_ciphertext=cipher.encrypt(api_key) if api_key else None,
            is_enabled=True,
            is_default=not has_default and alias == model_id,
            timeout_seconds=180,
            max_retries=2,
        )
        if value.is_default:
            has_default = True
        session.add(value)
        created.append(value)
    if not has_default:
        default = next((item for item in existing if item.id == model_id), None)
        if default is not None:
            default.is_enabled = True
            default.is_default = True
    await session.commit()
    for value in created:
        await session.refresh(value)
    return created


async def list_models(
    session: AsyncSession,
    *,
    enabled_only: bool = False,
) -> list[ModelRegistration]:
    statement = select(ModelRegistration)
    if enabled_only:
        statement = statement.where(ModelRegistration.is_enabled.is_(True))
    values = await session.scalars(
        statement.order_by(ModelRegistration.is_default.desc(), ModelRegistration.display_name)
    )
    return list(values)


async def get_model(session: AsyncSession, model_id: str) -> ModelRegistration | None:
    return await session.get(ModelRegistration, model_id)


async def resolve_model(
    session: AsyncSession,
    model_id: str | None,
) -> ModelRegistration | None:
    if model_id:
        return await session.scalar(
            select(ModelRegistration).where(
                ModelRegistration.id == model_id,
                ModelRegistration.is_enabled.is_(True),
            )
        )
    return await session.scalar(
        select(ModelRegistration)
        .where(
            ModelRegistration.is_default.is_(True),
            ModelRegistration.is_enabled.is_(True),
        )
        .limit(1)
    )


async def update_model(
    session: AsyncSession,
    value: ModelRegistration,
    payload: ModelRegistrationUpdate,
    cipher: ModelSecretCipher,
) -> ModelRegistration:
    changes = payload.model_dump(
        exclude_unset=True,
        exclude={"api_key", "clear_api_key"},
    )
    if changes.get("is_default"):
        changes["is_enabled"] = True
        await session.execute(
            update(ModelRegistration)
            .where(ModelRegistration.id != value.id)
            .values(is_default=False, updated_at=func.now())
        )
    if payload.clear_api_key:
        value.api_key_ciphertext = None
    elif payload.api_key is not None:
        secret = payload.api_key.get_secret_value()
        if secret:
            value.api_key_ciphertext = cipher.encrypt(secret)
    for key, item in changes.items():
        setattr(value, key, item)
    value.status = "unknown"
    value.last_health_at = None
    value.last_error = None
    await session.commit()
    await session.refresh(value)
    return value


async def set_default(session: AsyncSession, value: ModelRegistration) -> ModelRegistration:
    await session.execute(
        update(ModelRegistration).values(is_default=False, updated_at=func.now())
    )
    value.is_enabled = True
    value.is_default = True
    await session.commit()
    await session.refresh(value)
    return value


async def record_health(
    session: AsyncSession,
    value: ModelRegistration,
    *,
    online: bool,
    error: str | None = None,
) -> ModelRegistration:
    value.status = "online" if online else "offline"
    value.last_health_at = datetime.now(timezone.utc)
    value.last_error = None if online else (error or "模型连通性测试失败")[:2000]
    await session.commit()
    await session.refresh(value)
    return value


async def agent_reference_count(session: AsyncSession, model_id: str) -> int:
    return int(
        await session.scalar(
            select(func.count()).select_from(Agent).where(Agent.model == model_id)
        )
        or 0
    )


async def delete_model(session: AsyncSession, value: ModelRegistration) -> None:
    await session.delete(value)
    await session.commit()

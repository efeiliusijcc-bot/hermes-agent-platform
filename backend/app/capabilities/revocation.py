from __future__ import annotations

import redis.asyncio as redis

from app.config import get_settings


async def revoke_execution_capability_token(details: dict | None) -> bool:
    jti = details.get("capability_token_jti") if isinstance(details, dict) else None
    if not isinstance(jti, str) or not jti:
        return False
    settings = get_settings()
    client = redis.Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        db=settings.redis_db,
        password=settings.redis_password.get_secret_value(),
        socket_timeout=settings.redis_socket_timeout_seconds,
        decode_responses=True,
    )
    try:
        await client.set(
            f"hermes:capability-token:revoked:{jti}",
            "1",
            ex=settings.execution_capability_token_ttl_seconds,
        )
        return True
    finally:
        await client.aclose()

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from app.api.agents import router as agents_router
from app.api.mcp_servers import router as mcp_servers_router
from app.api.skills import router as skills_router
from app.config import get_settings
from app.db.session import SessionFactory, engine
from app.memory import get_memory_store

settings = get_settings()
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    async with SessionFactory() as session:
        await session.execute(text("SELECT 1"))
    memory_store = get_memory_store()
    await memory_store.ping()
    logger.info("control plane started", extra={"environment": settings.app_env})
    try:
        yield
    finally:
        await memory_store.close()
        await engine.dispose()


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
app.include_router(agents_router)
app.include_router(mcp_servers_router)
app.include_router(skills_router)


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    async with SessionFactory() as session:
        await session.execute(text("SELECT 1"))
    await get_memory_store().ping()
    return {"status": "ok", "database": "ok", "memory": "ok"}

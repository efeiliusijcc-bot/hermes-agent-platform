from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import MCPServer
from app.schemas.mcp_server import MCPServerCreate


async def create_mcp_server(session: AsyncSession, payload: MCPServerCreate) -> MCPServer:
    server = MCPServer(
        id=payload.id,
        name=payload.name,
        endpoint=payload.endpoint,
        config=payload.config,
    )
    session.add(server)
    await session.commit()
    await session.refresh(server)
    return server


async def list_mcp_servers(session: AsyncSession) -> list[MCPServer]:
    result = await session.scalars(select(MCPServer).order_by(MCPServer.created_at, MCPServer.id))
    return list(result)


async def get_mcp_server(session: AsyncSession, mcp_id: str) -> MCPServer | None:
    return await session.get(MCPServer, mcp_id)


async def delete_mcp_server(session: AsyncSession, server: MCPServer) -> None:
    await session.delete(server)
    await session.commit()

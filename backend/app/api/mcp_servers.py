from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.session import get_session
from app.repositories import mcp_servers as repository
from app.schemas.mcp_server import MCPServerCreate, MCPServerRead

router = APIRouter(prefix="/api/mcp-servers", tags=["mcp-servers"])


@router.post("", response_model=MCPServerRead, status_code=status.HTTP_201_CREATED)
async def create_mcp_server(
    payload: MCPServerCreate,
    session: AsyncSession = Depends(get_session),
) -> MCPServerRead:
    if payload.endpoint.rstrip("/") != get_settings().mcp_gateway_endpoint.rstrip("/"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="first-stage MCP servers must use MCP_GATEWAY_ENDPOINT",
        )
    try:
        return MCPServerRead.model_validate(await repository.create_mcp_server(session, payload))
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="MCP server id already exists") from exc


@router.get("", response_model=list[MCPServerRead])
async def list_mcp_servers(session: AsyncSession = Depends(get_session)) -> list[MCPServerRead]:
    return [MCPServerRead.model_validate(item) for item in await repository.list_mcp_servers(session)]


@router.get("/{mcp_id}", response_model=MCPServerRead)
async def get_mcp_server(mcp_id: str, session: AsyncSession = Depends(get_session)) -> MCPServerRead:
    server = await repository.get_mcp_server(session, mcp_id)
    if server is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MCP server not found")
    return MCPServerRead.model_validate(server)


@router.delete("/{mcp_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_mcp_server(mcp_id: str, session: AsyncSession = Depends(get_session)) -> Response:
    server = await repository.get_mcp_server(session, mcp_id)
    if server is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MCP server not found")
    await repository.delete_mcp_server(session, server)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

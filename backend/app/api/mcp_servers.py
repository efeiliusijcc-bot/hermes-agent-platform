from time import monotonic

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.session import get_session
from app.repositories import mcp_servers as repository
from app.schemas.mcp_server import MCPServerCreate, MCPServerRead, MCPServerTestRead, MCPServerUpdate

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


@router.put("/{mcp_id}", response_model=MCPServerRead)
async def update_mcp_server(
    mcp_id: str,
    payload: MCPServerUpdate,
    session: AsyncSession = Depends(get_session),
) -> MCPServerRead:
    server = await repository.get_mcp_server(session, mcp_id)
    if server is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MCP server not found")
    if payload.endpoint.rstrip("/") != get_settings().mcp_gateway_endpoint.rstrip("/"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="first-stage MCP servers must use MCP_GATEWAY_ENDPOINT",
        )
    return MCPServerRead.model_validate(await repository.update_mcp_server(session, server, payload))


@router.post("/{mcp_id}/test", response_model=MCPServerTestRead)
async def test_mcp_server(mcp_id: str, session: AsyncSession = Depends(get_session)) -> MCPServerTestRead:
    server = await repository.get_mcp_server(session, mcp_id)
    if server is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MCP server not found")
    started = monotonic()
    value = "offline"
    detail = "gateway did not accept an MCP initialize request"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                server.endpoint,
                headers={"Accept": "application/json, text/event-stream"},
                json={
                    "jsonrpc": "2.0",
                    "id": "platform-connectivity-test",
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-03-26",
                        "capabilities": {},
                        "clientInfo": {"name": "hermes-agent-platform", "version": "0.2.0"},
                    },
                },
            )
        if response.status_code < 500 and (response.is_success or response.status_code in {400, 401, 403, 406}):
            value = "online"
            detail = f"gateway responded with HTTP {response.status_code}"
        else:
            detail = f"gateway responded with HTTP {response.status_code}"
    except httpx.HTTPError as exc:
        detail = f"gateway connection failed: {type(exc).__name__}"
    await repository.set_status(session, server, value)
    return MCPServerTestRead(
        id=server.id,
        status=value,
        latency_ms=max(0, round((monotonic() - started) * 1000)),
        detail=detail,
    )


@router.delete("/{mcp_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_mcp_server(mcp_id: str, session: AsyncSession = Depends(get_session)) -> Response:
    server = await repository.get_mcp_server(session, mcp_id)
    if server is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MCP server not found")
    await repository.delete_mcp_server(session, server)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

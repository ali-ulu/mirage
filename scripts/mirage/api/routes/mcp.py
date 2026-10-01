"""
MIRAGE API — MCP gateway ucu.

`POST /mcp/evaluate` — bir MCP araç çağrısını politika + sunucu riski + denetim
kapısından geçirir. `MIRAGE_MCP_*` env'inden politika okunur; `scan_hook`
verilmezse yalnızca politika/risk kararı uygulanır. Karar fail-safe üretilir;
`allowed=False` ise 403 döner.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..deps import get_mcp_gateway, require_api_token
from ...mcp_gateway import MCPServerInfo

router = APIRouter(prefix="/mcp", tags=["mcp"])


class MCPServerModel(BaseModel):
    name: str = Field(..., description="Server identifier (e.g. 'filesystem')")
    url: str = Field("", description="Server URL (http/sse transports)")
    transport: str = Field("stdio", pattern="^(stdio|http|sse)$")
    capabilities: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    authenticated: bool = Field(False, description="Whether the call carries credentials")


class MCPEvaluateRequest(BaseModel):
    server: MCPServerModel
    tool: str = Field(..., description="Tool name being invoked")
    arguments: Optional[Any] = Field(None, description="Tool arguments (scanned if hook configured)")
    actor: str = Field("", description="Actor label for the audit log")


@router.post("/evaluate")
def evaluate_mcp_call(req: MCPEvaluateRequest, request: Request) -> dict:
    """
    MCP çağrısı için gateway kararı döner.

    Yanıt: `{"allowed": bool, "reason": str, "server": str, "tool": str,
    "risk": {"score", "level", "reasons"}}`. `allowed=False` ise HTTP 403.
    """
    require_api_token(request)
    gateway = get_mcp_gateway()
    try:
        decision = gateway.evaluate(
            MCPServerInfo(**req.server.model_dump()),
            req.tool,
            arguments=req.arguments,
            actor=req.actor,
        )
    except Exception as exc:  # fail-safe: karar üretilemezse engelle
        raise HTTPException(status_code=500, detail=f"MCP gateway error: {exc}")
    payload = decision.to_dict()
    if not decision.allowed:
        raise HTTPException(status_code=403, detail=payload)
    return payload


@router.get("/audit")
def mcp_audit_summary(request: Request) -> dict:
    """Bu süreçteki MCP gateway denetim günlüğünün özeti (in-memory)."""
    require_api_token(request)
    return get_mcp_gateway().audit_summary()

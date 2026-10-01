"""
MIRAGE API — router kaydı.

Yeni savunma modüllerini (MCP gateway, RAG guard, deception, behavior, Merkle
anchor, DLP) HTTP yüzeyine bağlar. Her router kendi modülünde tanımlanır; burada
yalnızca tek bir `register_routers(app)` ile app'e eklenir. Böylece `server.py`
monolitik büyümez ve her yüzey bağımsız test edilebilir.
"""
from __future__ import annotations

from fastapi import FastAPI

from .behavior import router as behavior_router
from .deception import router as deception_router
from .dlp import router as dlp_router
from .evidence import router as evidence_router
from .mcp import router as mcp_router
from .rag import router as rag_router

ROUTERS = (
    mcp_router,
    rag_router,
    deception_router,
    behavior_router,
    evidence_router,
    dlp_router,
)


def register_routers(app: FastAPI) -> None:
    """Tüm savunma router'larını app'e ekler (idempotent değil; bir kez çağır)."""
    for router in ROUTERS:
        app.include_router(router)


__all__ = ["register_routers", "ROUTERS"]

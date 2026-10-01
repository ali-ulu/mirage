"""
PR — Satır-içi ajan koruması: API/MCP çağrılarını savunma/engelleme/yakalama.

Kapsam:
  - `AgentGuard.guard_api_call`: temiz geçer, ihlalde `GuardBlocked`, rapor modu.
  - `AgentGuard.guard_mcp_message`: tools/call arguments + nested content taraması,
    enforce'ta JSON-RPC `error` üretimi, id'siz bildirim davranışı.
  - Fail-closed: tarama hatası enforce modunda bloklar.
  - `AgentGuardMiddleware`: /agent/proxy gövdesi ihlalde 422, temizde geçer.
  - `POST /agent/proxy`: enforce'ta 422 + bloklama; rapor modunda 200.
  - Triyaj sink: ihlal deftere yazılır (yakalama → kanıt/triyaj zinciri).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mirage import server  # noqa: E402
from mirage.agent import (  # noqa: E402
    AgentGuard,
    CanaryRegistry,
    GuardBlocked,
    OutboundScanner,
)
from mirage.agent.guard import MCP_ERROR_CODE  # noqa: E402
from mirage.agent.prompt_canary import build_marker  # noqa: E402


def _leaky() -> tuple[CanaryRegistry, str]:
    reg = CanaryRegistry()
    canary = reg.issue("system_prompt", label="sys")
    return reg, canary.token


def _guard(*, enforce: bool = True, rules=None, registry=None) -> AgentGuard:
    return AgentGuard(
        scanner=OutboundScanner(registry=registry, rules=rules or [], block=enforce),
        enforce=enforce,
    )


# ---------------------------------------------------------------------------
# guard_api_call
# ---------------------------------------------------------------------------
def test_api_call_clean_passes():
    guard = _guard(rules=[{"name": "aws", "pattern": r"sk-[A-Z0-9]{8,}"}])
    report = guard.guard_api_call({"q": "merhaba"}, surface="api-call")
    assert report["clean"] is True


def test_api_call_blocks_canary_leak():
    registry, token = _leaky()
    guard = _guard(registry=registry)
    with pytest.raises(GuardBlocked) as exc:
        guard.guard_api_call({"prompt": build_marker(token)}, surface="api-call")
    assert exc.value.surface == "api-call"
    assert exc.value.leak["count"] >= 1
    assert exc.value.leak["blocked"] is True


def test_api_call_report_only_when_not_enforced():
    registry, token = _leaky()
    guard = _guard(enforce=False, registry=registry)
    report = guard.guard_api_call({"prompt": build_marker(token)})
    assert report["clean"] is False
    assert report["blocked"] is False


def test_api_call_fail_closed_on_scan_error():
    class BoomScanner(OutboundScanner):
        def scan(self, text):
            raise RuntimeError("boom")

    guard = AgentGuard(scanner=BoomScanner(registry=None, rules=[], block=True), enforce=True)
    with pytest.raises(GuardBlocked):
        guard.guard_api_call("x")


# ---------------------------------------------------------------------------
# guard_mcp_message
# ---------------------------------------------------------------------------
def test_mcp_tools_call_clean_passes():
    guard = _guard()
    out = guard.guard_mcp_message(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": "search", "arguments": {"q": "merhaba"}}}
    )
    assert out["clean"] is True and out["blocked"] is False


def test_mcp_tools_call_blocks_and_emits_jsonrpc_error():
    registry, token = _leaky()
    guard = _guard(registry=registry)
    out = guard.guard_mcp_message(
        {"jsonrpc": "2.0", "id": 42, "method": "tools/call",
         "params": {"name": "send", "arguments": {"body": build_marker(token)}}}
    )
    assert out["blocked"] is True
    assert out["response"]["id"] == 42
    assert out["response"]["error"]["code"] == MCP_ERROR_CODE
    assert "result" not in out["response"]


def test_mcp_nested_content_scanned():
    registry, token = _leaky()
    guard = _guard(registry=registry)
    msg = {"jsonrpc": "2.0", "id": 7, "method": "tools/call",
           "params": {"name": "echo", "arguments": {"nested": {"deep": [build_marker(token)]}}}}
    out = guard.guard_mcp_message(msg)
    assert out["blocked"] is True


def test_mcp_notification_without_id_reports_only():
    registry, token = _leaky()
    guard = _guard(registry=registry)
    out = guard.guard_mcp_message(
        {"jsonrpc": "2.0", "method": "notifications/progress",
         "params": {"content": build_marker(token)}}
    )
    assert out["blocked"] is True
    assert "response" not in out


def test_mcp_regex_rule_hit_blocks():
    guard = _guard(rules=[{"name": "aws", "pattern": r"AKIA[0-9A-Z]{16}", "severity": "high"}])
    out = guard.guard_mcp_message(
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "store", "arguments": {"key": "AKIAIOSFODNN7EXAMPLE"}}}
    )
    assert out["blocked"] is True
    assert out["leak"]["rule_hits"] >= 1


# ---------------------------------------------------------------------------
# Triyaj sink (yakalama → defter)
# ---------------------------------------------------------------------------
def test_guard_calls_triage_sink_on_leak():
    registry, token = _leaky()
    seen = {}

    def sink(text, leak):
        seen["text"] = text
        seen["leak"] = leak

    guard = AgentGuard(
        scanner=OutboundScanner(registry=registry, rules=[], block=False),
        enforce=False,
        triage_sink=sink,
    )
    guard.guard_api_call(build_marker(token))
    assert seen["leak"]["count"] >= 1


# ---------------------------------------------------------------------------
# AgentGuardMiddleware (ASGI, /agent/proxy)
# ---------------------------------------------------------------------------
def _middleware_client(guard: AgentGuard) -> TestClient:
    from fastapi import FastAPI
    from mirage.agent.guard import AgentGuardMiddleware

    app = FastAPI()

    @app.post("/agent/proxy")
    async def _proxy(payload: dict):  # pragma: no cover - reached only when allowed
        return {"reached": True}

    @app.get("/other")
    def _other():
        return {"ok": True}

    app.add_middleware(AgentGuardMiddleware, guard=guard, protect_prefixes=("/agent/proxy",))
    return TestClient(app)


def test_middleware_blocks_leaky_request_before_handler():
    registry, token = _leaky()
    client = _middleware_client(_guard(registry=registry))
    resp = client.post("/agent/proxy", json={"body": build_marker(token)})
    assert resp.status_code == 422
    assert "leak blocked" in resp.json()["detail"]


def test_middleware_passes_clean_request_to_handler():
    client = _middleware_client(_guard())
    resp = client.post("/agent/proxy", json={"body": "merhaba"})
    assert resp.status_code == 200
    assert resp.json() == {"reached": True}


def test_middleware_ignores_unprotected_paths():
    registry, _ = _leaky()
    client = _middleware_client(_guard(registry=registry))
    resp = client.get("/other")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# POST /agent/proxy (server — server'ın kendi registry'si kullanılır)
# ---------------------------------------------------------------------------
def _server_canary_marker() -> str:
    canary = server.get_canary_registry().issue("system_prompt", label="server-sys")
    return build_marker(canary.token)


def test_server_proxy_blocks_when_guard_enabled(monkeypatch):
    monkeypatch.setenv("MIRAGE_AGENT_GUARD", "1")
    client = TestClient(server.app)
    resp = client.post(
        "/agent/proxy",
        json={"url": "https://api.example.com/v1", "body": {"prompt": _server_canary_marker()}},
    )
    assert resp.status_code == 422


def test_server_proxy_reports_when_guard_disabled(monkeypatch):
    monkeypatch.delenv("MIRAGE_AGENT_GUARD", raising=False)
    client = TestClient(server.app)
    resp = client.post(
        "/agent/proxy",
        json={"url": "https://api.example.com/v1", "body": {"q": "merhaba"},
              "rules": [{"name": "aws", "pattern": r"AKIA[0-9A-Z]{16}"}]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["enforced"] is False
    assert body["clean"] is True


def test_server_proxy_regex_rule_blocks(monkeypatch):
    monkeypatch.setenv("MIRAGE_AGENT_GUARD", "1")
    client = TestClient(server.app)
    resp = client.post(
        "/agent/proxy",
        json={"url": "https://api.example.com/v1", "body": {"key": "AKIAIOSFODNN7EXAMPLE"},
              "rules": [{"name": "aws", "pattern": r"AKIA[0-9A-Z]{16}"}]},
    )
    assert resp.status_code == 422

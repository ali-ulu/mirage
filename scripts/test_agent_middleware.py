"""
MIRAGE — Otomatik tarama middleware'i testleri.

Kapsam: yol filtresi, JSON gövde taraması, canary + regex sızıntısı, excluded
uçlar, büyük gövde koruması, fail-safe ve uçtan uca (opt-in env ile) kurulum.
Gerçek ASGI yığını üzerinden test edilir; mock yok.
"""
from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mirage import server  # noqa: E402
from mirage.agent import CanaryRegistry  # noqa: E402
from mirage.agent.middleware import (  # noqa: E402
    AgentScanMiddleware,
    scan_middleware_enabled,
    should_scan_path,
)


def _app_with(body, *, content_type="application/json", status=200):
    app = FastAPI()

    @app.get("/thing")
    def thing():
        if content_type == "application/json":
            return JSONResponse(content=body, status_code=status)
        return Response(content=body, media_type=content_type, status_code=status)

    return app


def _client(app, **kwargs):
    app.add_middleware(AgentScanMiddleware, **kwargs)
    return TestClient(app)


# ---------------------------------------------------------------------------
# Yol filtresi
# ---------------------------------------------------------------------------
def test_should_scan_path_excludes_canary_and_scan():
    assert should_scan_path("/agent/plan") is True
    assert should_scan_path("/agent/canary") is False
    assert should_scan_path("/agent/canary/check") is False
    assert should_scan_path("/agent/scan") is False


def test_scan_middleware_enabled_env(monkeypatch):
    monkeypatch.delenv("MIRAGE_SCAN_MIDDLEWARE", raising=False)
    assert scan_middleware_enabled() is False
    monkeypatch.setenv("MIRAGE_SCAN_MIDDLEWARE", "true")
    assert scan_middleware_enabled() is True


# ---------------------------------------------------------------------------
# Tarama davranışı
# ---------------------------------------------------------------------------
def test_canary_leak_triggers_sink():
    reg = CanaryRegistry()
    canary = reg.issue("system_prompt")
    captured = {}

    def sink(text, leak):
        captured["text"] = text
        captured["leak"] = leak

    app = _app_with({"answer": f"echo: {canary.marker}"})
    client = _client(app, registry=reg, triage_sink=sink)
    resp = client.get("/thing")

    assert resp.status_code == 200  # yanıt bozulmaz
    assert captured["leak"]["count"] == 1
    assert captured["leak"]["canaries"][0]["token"] == canary.token


def test_regex_rule_leak_triggers_sink():
    captured = {}
    app = _app_with({"out": "here is sk-SECRET123"})
    client = _client(
        app,
        registry=None,
        rules=[{"name": "aws", "pattern": r"sk-[A-Z0-9]+", "severity": "high"}],
        triage_sink=lambda t, l: captured.update(l),
    )
    client.get("/thing")
    assert captured["findings"][0]["name"] == "aws"


def test_no_leak_no_sink():
    reg = CanaryRegistry()
    reg.issue("system_prompt")
    called = []
    app = _app_with({"answer": "clean output"})
    client = _client(app, registry=reg, triage_sink=lambda t, l: called.append(l))
    client.get("/thing")
    assert called == []


def test_non_json_body_not_scanned():
    reg = CanaryRegistry()
    canary = reg.issue("system_prompt")
    called = []
    app = _app_with(canary.marker, content_type="text/plain")
    client = _client(app, registry=reg, triage_sink=lambda t, l: called.append(l))
    client.get("/thing")
    assert called == []


def test_large_body_not_scanned():
    reg = CanaryRegistry()
    canary = reg.issue("system_prompt")
    called = []
    app = _app_with({"out": canary.marker + "x" * 1000})
    client = _client(
        app,
        registry=reg,
        triage_sink=lambda t, l: called.append(l),
        max_scan_bytes=64,
    )
    client.get("/thing")
    assert called == []


def test_excluded_path_not_scanned():
    reg = CanaryRegistry()
    canary = reg.issue("system_prompt")
    called = []
    app = FastAPI()

    @app.get("/agent/canary/check")
    def check():
        return JSONResponse({"marker": canary.marker})

    app.add_middleware(AgentScanMiddleware, registry=reg, triage_sink=lambda t, l: called.append(l))
    TestClient(app).get("/agent/canary/check")
    assert called == []


def test_fail_safe_when_registry_raises():
    class Boom:
        def match(self, _text):
            raise RuntimeError("boom")

    app = _app_with({"out": "anything"})
    client = _client(app, registry=Boom())
    resp = client.get("/thing")  # yanıt bozulmamalı
    assert resp.status_code == 200
    assert resp.json() == {"out": "anything"}


# ---------------------------------------------------------------------------
# Uçtan uca: opt-in env ile server'a kurulum
# ---------------------------------------------------------------------------
def test_install_is_noop_when_disabled(monkeypatch):
    monkeypatch.delenv("MIRAGE_SCAN_MIDDLEWARE", raising=False)
    app = FastAPI()
    server.install_agent_scan_middleware(app)
    assert not any(m.cls is AgentScanMiddleware for m in app.user_middleware)


def test_install_adds_middleware_when_enabled(monkeypatch):
    monkeypatch.setenv("MIRAGE_SCAN_MIDDLEWARE", "true")
    monkeypatch.delenv("MIRAGE_API_TOKEN", raising=False)
    server.reset_canary_registry_for_testing()
    app = FastAPI()

    @app.get("/agent/plan")
    def plan():
        return {"ok": True}

    server.install_agent_scan_middleware(app)
    assert any(m.cls is AgentScanMiddleware for m in app.user_middleware)
    # Uç hâlâ çalışır (fail-safe / yanıt bozulmaz).
    assert TestClient(app).get("/agent/plan").json() == {"ok": True}

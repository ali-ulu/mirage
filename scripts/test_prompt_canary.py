"""
MIRAGE — Prompt-layer canary testleri.

Çekirdek tamamen deterministik ve ağsız; LLM gerekmez. Registry JSON
kalıcılığı gerçek dosyayla (tmp_path) test edilir; HTTP uçları FastAPI
TestClient ile (mock yok) doğrulanır.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mirage import server  # noqa: E402
from mirage.agent import (  # noqa: E402
    CanaryRegistry,
    build_marker,
    detect_canaries,
    render_canary,
)


# ---------------------------------------------------------------------------
# Çekirdek fonksiyonlar
# ---------------------------------------------------------------------------
def test_build_marker_format():
    marker = build_marker("11111111-2222-3333-4444-555555555555")
    assert marker == "[[MIRAGE-CANARY:11111111-2222-3333-4444-555555555555]]"


def test_detect_canaries_finds_and_dedupes_in_order():
    a = "11111111-2222-3333-4444-555555555555"
    b = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    text = f"x [[MIRAGE-CANARY:{a}]] mid [[MIRAGE-CANARY:{b}]] again [[MIRAGE-CANARY:{a}]]"
    assert detect_canaries(text) == [a, b]


def test_detect_canaries_empty_text():
    assert detect_canaries("") == []
    assert detect_canaries("no markers here") == []


def test_render_canary_styles():
    reg = CanaryRegistry()
    canary = reg.issue("system_prompt", label="x")
    assert render_canary(canary, "raw") == canary.marker
    assert canary.marker in render_canary(canary, "note")


def test_render_canary_rejects_unknown_style():
    reg = CanaryRegistry()
    canary = reg.issue("rag_document")
    try:
        render_canary(canary, "fancy")
        assert False, "expected ValueError"
    except ValueError:
        pass


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
def test_registry_issue_and_lookup():
    reg = CanaryRegistry()
    canary = reg.issue("agent_memory", label="mem-1")
    assert reg.lookup(canary.token) is canary
    assert reg.lookup("nope") is None
    assert canary.marker == build_marker(canary.token)


def test_registry_rejects_invalid_context():
    reg = CanaryRegistry()
    try:
        reg.issue("nonsense")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_registry_match_only_returns_issued():
    reg = CanaryRegistry()
    mine = reg.issue("system_prompt")
    other = "99999999-8888-7777-6666-555555555555"
    text = f"{mine.marker} and [[MIRAGE-CANARY:{other}]]"
    matches = reg.match(text)
    assert [c.token for c in matches] == [mine.token]


def test_registry_save_load_roundtrip(tmp_path):
    path = tmp_path / "canaries.json"
    reg = CanaryRegistry(path=str(path))
    canary = reg.issue("rag_document", label="kb")
    reg.save()

    raw = json.loads(path.read_text())
    assert raw["version"] == 1

    loaded = CanaryRegistry(path=str(path))
    loaded.load()
    assert loaded.lookup(canary.token) == canary


def test_registry_save_without_path_raises():
    reg = CanaryRegistry()
    reg.issue("system_prompt")
    try:
        reg.save()
        assert False, "expected RuntimeError"
    except RuntimeError:
        pass


# ---------------------------------------------------------------------------
# HTTP uçları
# ---------------------------------------------------------------------------
def test_issue_canary_endpoint(monkeypatch):
    monkeypatch.delenv("MIRAGE_API_TOKEN", raising=False)
    server.reset_canary_registry_for_testing()
    client = TestClient(server.app)
    res = client.post(
        "/agent/canary",
        json={"context": "system_prompt", "label": "agent-1", "style": "note"},
    )
    assert res.status_code == 201
    body = res.json()
    assert body["context"] == "system_prompt"
    assert body["marker"].startswith("[[MIRAGE-CANARY:")
    assert body["marker"] in body["rendered"]


def test_issue_canary_endpoint_rejects_bad_context(monkeypatch):
    monkeypatch.delenv("MIRAGE_API_TOKEN", raising=False)
    client = TestClient(server.app)
    res = client.post("/agent/canary", json={"context": "invalid"})
    assert res.status_code == 422


def test_canary_issue_then_detect_leak(monkeypatch):
    monkeypatch.delenv("MIRAGE_API_TOKEN", raising=False)
    server.reset_canary_registry_for_testing()
    client = TestClient(server.app)

    issued = client.post("/agent/canary", json={"context": "rag_document"}).json()

    # İşaret başka bir sistemin çıktısında görünüyorsa sızıntı tespit edilir.
    leaked = client.post(
        "/agent/canary/check",
        json={"text": f"Agent answer: ... {issued['marker']} ..."},
    ).json()
    assert leaked["leaked"] is True
    assert leaked["count"] == 1
    assert leaked["canaries"][0]["token"] == issued["token"]


def test_canary_check_no_leak(monkeypatch):
    monkeypatch.delenv("MIRAGE_API_TOKEN", raising=False)
    server.reset_canary_registry_for_testing()
    client = TestClient(server.app)
    client.post("/agent/canary", json={"context": "agent_memory"})
    res = client.post("/agent/canary/check", json={"text": "temiz çıktı, işaret yok"})
    assert res.status_code == 200
    assert res.json()["leaked"] is False

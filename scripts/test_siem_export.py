"""
PR — SIEM/SOAR dışa aktarım testleri.

Kapsam:
  - `build_events`: kanıt → beacon olayı, triyaj → triage olayı, severity eşlemesi,
    token'sız kayıtların atlanması, `chain_verified` işlenmesi.
  - `HecSink` / `WebhookSink`: httpx.MockTransport ile ağsız gönderim + payload.
  - `ConsoleSink`: stdout'a yazar.
  - `get_siem_sink`: env'e göre sink seçimi + eksik yapılandırmada `SiemError`.
  - `export_token`: kanıt+triyaj toplama, zincir doğrulama, teslim raporu.
  - `POST /siem/export/{token}`: yapılandırılmamışta 503, başarılıda 200.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mirage import server  # noqa: E402
from mirage.siem import (  # noqa: E402
    ConsoleSink,
    HecSink,
    SiemError,
    WebhookSink,
    build_events,
    export_token,
    get_siem_sink,
)
from mirage.triage_store import TriageRecord  # noqa: E402

TOKEN = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def _evidence():
    return [
        {"token": TOKEN, "ip": "203.0.113.5", "user_agent": "curl/8",
         "received_at": "2026-10-01T00:00:00.000Z", "chain_seq": 1,
         "prev_hash": "0" * 64, "record_hash": "a" * 64, "hmac": "b" * 64},
    ]


def _triage():
    return [
        TriageRecord(token=TOKEN, severity="critical", confidence=0.95,
                     rationale="kanıt zinciri doğrulanamadı", recommended_action="escalate",
                     source="heuristic", chain_seq=1, chain_verified=False,
                     created_at="2026-10-01T00:00:05+00:00"),
    ]


class _EvidenceStore:
    def __init__(self, *, ok=True):
        self._ok = ok

    def list_chain(self, token):
        return _evidence()

    def verify(self, token, key=None):
        return {"token": token, "ok": self._ok, "checked": 1, "broken_at": None}


class _TriageStore:
    def list_for_token(self, token, **kwargs):
        return _triage()


# ---------------------------------------------------------------------------
# build_events
# ---------------------------------------------------------------------------
def test_build_events_maps_beacon_and_triage():
    events = build_events(evidence=_evidence(), triage=_triage(), chain_verified=True)
    assert len(events) == 2
    beacon, triage = events
    assert beacon["mirage"]["record_type"] == "beacon"
    assert beacon["mirage"]["chain_verified"] is True
    assert beacon["source"]["ip"] == "203.0.113.5"
    assert triage["mirage"]["record_type"] == "triage"
    assert triage["event"]["severity"] == 10  # critical
    assert triage["event"]["action"] == "escalate"


def test_build_events_skips_records_without_token():
    events = build_events(evidence=[{"ip": "1.2.3.4"}], triage=[{"severity": "low"}])
    assert events == []


def test_build_events_empty():
    assert build_events() == []


# ---------------------------------------------------------------------------
# HecSink
# ---------------------------------------------------------------------------
def test_hec_sink_posts_envelope():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        captured["body"] = request.content.decode()
        return httpx.Response(200, json={"text": "Success", "code": 0})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    sink = HecSink(url="https://splunk.example.com:8088", token="tok",
                   index="mirage", client=client)
    report = asyncio.run(sink.send(build_events(evidence=_evidence())))
    assert report["ok"] is True and report["sent"] == 1
    assert captured["url"].endswith("/services/collector/event")
    assert captured["auth"] == "Splunk tok"
    envelope = json.loads(captured["body"].splitlines()[0])
    assert envelope["index"] == "mirage"
    assert envelope["sourcetype"] == "mirage:deception"


def test_hec_sink_requires_config():
    with pytest.raises(SiemError):
        HecSink(url="", token="tok")


# ---------------------------------------------------------------------------
# WebhookSink
# ---------------------------------------------------------------------------
def test_webhook_sink_posts_events_array():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        captured["json"] = json.loads(request.content.decode())
        return httpx.Response(202)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    sink = WebhookSink(url="https://soar.example.com/ingest",
                       headers={"Authorization": "Bearer x"}, client=client)
    report = asyncio.run(sink.send(build_events(triage=_triage())))
    assert report["ok"] is True and report["status"] == 202
    assert len(captured["json"]["events"]) == 1
    assert captured["headers"]["authorization"] == "Bearer x"


# ---------------------------------------------------------------------------
# ConsoleSink
# ---------------------------------------------------------------------------
def test_console_sink_prints(capsys):
    report = asyncio.run(ConsoleSink().send(build_events(evidence=_evidence())))
    assert report["ok"] is True and report["sent"] == 1
    assert "honeytoken-opened" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# get_siem_sink (env)
# ---------------------------------------------------------------------------
def test_get_siem_sink_none_by_default(monkeypatch):
    monkeypatch.delenv("MIRAGE_SIEM_SINK", raising=False)
    assert get_siem_sink() is None


def test_get_siem_sink_console(monkeypatch):
    monkeypatch.setenv("MIRAGE_SIEM_SINK", "console")
    assert isinstance(get_siem_sink(), ConsoleSink)


def test_get_siem_sink_hec_requires_token(monkeypatch):
    monkeypatch.setenv("MIRAGE_SIEM_SINK", "hec")
    monkeypatch.setenv("MIRAGE_SIEM_URL", "https://splunk.example.com:8088")
    monkeypatch.delenv("MIRAGE_SIEM_TOKEN", raising=False)
    with pytest.raises(SiemError):
        get_siem_sink()


def test_get_siem_sink_webhook(monkeypatch):
    monkeypatch.setenv("MIRAGE_SIEM_SINK", "webhook")
    monkeypatch.setenv("MIRAGE_SIEM_URL", "https://soar.example.com/ingest")
    monkeypatch.setenv("MIRAGE_SIEM_HEADERS", '{"X-Team":"blue"}')
    sink = get_siem_sink()
    assert isinstance(sink, WebhookSink)
    assert sink.headers == {"X-Team": "blue"}


# ---------------------------------------------------------------------------
# export_token
# ---------------------------------------------------------------------------
def test_export_token_collects_and_reports():
    sink = ConsoleSink()
    report = asyncio.run(
        export_token(token=TOKEN, evidence_store=_EvidenceStore(),
                     triage_store=_TriageStore(), sink=sink)
    )
    assert report["chain_verified"] is True
    assert report["evidence_count"] == 1
    assert report["triage_count"] == 1
    assert report["event_count"] == 2
    assert report["delivery"]["ok"] is True


def test_export_token_no_records():
    class _Empty:
        def list_chain(self, token):
            return []

        def verify(self, token, key=None):
            return {"ok": True}

        def list_for_token(self, token, **kwargs):
            return []

    report = asyncio.run(
        export_token(token=TOKEN, evidence_store=_Empty(), triage_store=_Empty(),
                     sink=ConsoleSink())
    )
    assert report["event_count"] == 0
    assert report["delivery"]["sent"] == 0


# ---------------------------------------------------------------------------
# POST /siem/export/{token}
# ---------------------------------------------------------------------------
def test_server_siem_export_unconfigured_returns_503(monkeypatch):
    monkeypatch.delenv("MIRAGE_SIEM_SINK", raising=False)
    client = TestClient(server.app)
    resp = client.post(f"/siem/export/{TOKEN}")
    assert resp.status_code == 503


def test_server_siem_export_console_success(monkeypatch):
    monkeypatch.setenv("MIRAGE_SIEM_SINK", "console")
    client = TestClient(server.app)
    resp = client.post(f"/siem/export/{TOKEN}")
    # Sink console; kanıt/triyaj store'ları yapılandırılmamışsa boş olay → 200.
    assert resp.status_code == 200
    assert resp.json()["token"] == TOKEN

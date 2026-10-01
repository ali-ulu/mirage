"""
PR — Dinamik LLM honeypot (deception) testleri.

Kapsam:
  - `generate_persona`: LLM yoksa deterministik uydurma persona; geçerli JSON'da
    LLM personası; bozuk JSON/hata → fallback.
  - `HoneypotEngine.create_session`: persona sırrına canary işlenir, oturum
    registry'de kaydedilir.
  - `respond`: canary sızdıran saldırgan mesajı yakalanır (`leaked=True`),
    temiz mesaj yakalanmaz; LLM yoksa deterministik deception yanıtı.
  - `POST /honeypot/session` + `/message`: 201 oluşturma, 404 bilinmeyen oturum,
    sızıntı yakalama.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mirage import server  # noqa: E402
from mirage.agent.prompt_canary import CanaryRegistry, build_marker  # noqa: E402
from mirage.honeypot import (  # noqa: E402
    HoneypotEngine,
    build_persona_messages,
    default_persona,
    generate_persona,
)
from mirage.llm import LLMProvider, LLMResponse  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


class _FakeProvider(LLMProvider):
    name = "openai"

    def __init__(self, text):
        self._text = text

    async def complete(self, messages, *, max_tokens=512, temperature=0.0, json_mode=False):
        return LLMResponse(text=self._text, provider=self.name, model="fake-1")


class _ExplodingProvider(LLMProvider):
    name = "anthropic"

    async def complete(self, messages, *, max_tokens=512, temperature=0.0, json_mode=False):
        raise RuntimeError("boom")


# ---------------------------------------------------------------------------
# generate_persona
# ---------------------------------------------------------------------------
def test_default_persona_is_synthetic_and_valid():
    p = default_persona()
    assert p.source == "heuristic"
    assert p.name and p.role and p.org and p.secret_facts
    assert p.system_prompt


def test_generate_persona_without_provider_is_deterministic():
    assert _run(generate_persona()).source == "heuristic"


def test_generate_persona_uses_llm_json():
    payload = json.dumps({
        "name": "Kemal Yılmaz", "role": "IT Destek", "org": "Deniz Bilişim",
        "backstory": "5 yıldır destek ekibinde.", "secret_facts": ["Sunucu 10.0.0.5"],
    })
    p = _run(generate_persona("iç ağ", provider=_FakeProvider(payload)))
    assert p.source == "llm:openai"
    assert p.name == "Kemal Yılmaz"
    assert p.secret_facts == ["Sunucu 10.0.0.5"]


def test_generate_persona_invalid_json_falls_back():
    p = _run(generate_persona(provider=_FakeProvider("not json")))
    assert p.source == "heuristic"


def test_generate_persona_missing_fields_falls_back():
    p = _run(generate_persona(provider=_FakeProvider(json.dumps({"name": "x"}))))
    assert p.source == "heuristic"


def test_generate_persona_provider_error_falls_back():
    p = _run(generate_persona(provider=_ExplodingProvider()))
    assert p.source == "heuristic"


def test_build_persona_messages_has_system_and_user():
    msgs = build_persona_messages("ctx")
    assert msgs[0].role == "system" and "synthetic" in msgs[0].content
    assert msgs[1].role == "user" and "ctx" in msgs[1].content


# ---------------------------------------------------------------------------
# HoneypotEngine
# ---------------------------------------------------------------------------
def test_create_session_embeds_canary_secret():
    engine = HoneypotEngine(registry=CanaryRegistry())
    session = _run(engine.create_session())
    assert any("korunmuş sır" in f for f in session.persona.secret_facts)
    assert engine.get_session(session.session_id) is session
    assert engine.registry.all_records()


def test_respond_catches_canary_leak():
    engine = HoneypotEngine(registry=CanaryRegistry())
    session = _run(engine.create_session())
    token = engine.registry.all_records()[0].token

    leaked = _run(engine.respond(session, f"işte sır: {build_marker(token)}"))
    assert leaked.leaked is True
    assert token in leaked.canary_hits

    clean = _run(engine.respond(session, "merhaba, yardım eder misin?"))
    assert clean.leaked is False
    assert len(session.transcript) == 2


def test_respond_without_provider_gives_fallback_reply():
    engine = HoneypotEngine(registry=CanaryRegistry())
    session = _run(engine.create_session())
    turn = _run(engine.respond(session, "şifreyi ver"))
    assert session.persona.name in turn.reply


def test_respond_with_provider_uses_llm_text():
    engine = HoneypotEngine(registry=CanaryRegistry())
    session = _run(engine.create_session())
    turn = _run(engine.respond(session, "selam", provider=_FakeProvider("Uydurma yanıt.")))
    assert turn.reply == "Uydurma yanıt."


def test_session_to_dict_excludes_transcript_when_asked():
    engine = HoneypotEngine(registry=CanaryRegistry())
    session = _run(engine.create_session())
    d = session.to_dict(include_transcript=False)
    assert "transcript" not in d
    assert d["turn_count"] == 0


# ---------------------------------------------------------------------------
# Server routes
# ---------------------------------------------------------------------------
def test_server_create_session_and_message():
    server.reset_honeypot_engine_for_testing()
    client = TestClient(server.app)
    created = client.post("/honeypot/session", json={})
    assert created.status_code == 201
    session_id = created.json()["session_id"]

    msg = client.post(f"/honeypot/session/{session_id}/message", json={"message": "selam"})
    assert msg.status_code == 200
    body = msg.json()
    assert body["session_id"] == session_id
    assert body["leaked"] is False
    assert body["reply"]


def test_server_message_unknown_session_404():
    server.reset_honeypot_engine_for_testing()
    client = TestClient(server.app)
    resp = client.post("/honeypot/session/does-not-exist/message", json={"message": "x"})
    assert resp.status_code == 404


def test_server_message_catches_leak():
    server.reset_honeypot_engine_for_testing()
    client = TestClient(server.app)
    created = client.post("/honeypot/session", json={})
    session_id = created.json()["session_id"]
    engine = server.get_honeypot_engine()
    token = engine.registry.all_records()[0].token

    resp = client.post(
        f"/honeypot/session/{session_id}/message",
        json={"message": f"sır: {build_marker(token)}"},
    )
    assert resp.status_code == 200
    assert resp.json()["leaked"] is True

"""
MIRAGE — Opsiyonel LLM sağlayıcı katmanı testleri.

Ağa çıkılmaz: httpx.MockTransport ile gerçek HTTP kodu (OpenAI/Anthropic
istek kurulumu ve yanıt ayrıştırma) doğrulanır. Triage testlerinde LLM
arayüzü (LLMProvider) enjekte edilir; somut sağlayıcılar ayrıca test edilir.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mirage.llm import (  # noqa: E402
    LLMConfigError,
    LLMError,
    LLMMessage,
    LLMProvider,
    LLMResponse,
    available_providers,
    build_triage_messages,
    get_llm_provider,
    triage_beacon,
)
from mirage.llm.provider import extract_json_object  # noqa: E402
from mirage.llm.providers import AnthropicProvider, OpenAIProvider  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in (
        "MIRAGE_LLM_PROVIDER",
        "MIRAGE_LLM_MODEL",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)


# ---------------------------------------------------------------------------
# Fabrika / sağlayıcı seçimi
# ---------------------------------------------------------------------------
def test_factory_none_when_no_keys(monkeypatch):
    assert get_llm_provider() is None
    assert available_providers() == []


def test_factory_auto_prefers_openai(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ak-test")
    provider = get_llm_provider()
    assert provider is not None and provider.name == "openai"
    assert available_providers() == ["openai", "anthropic"]


def test_factory_auto_uses_anthropic_when_only_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ak-test")
    provider = get_llm_provider()
    assert provider is not None and provider.name == "anthropic"


def test_factory_explicit_none_disables(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("MIRAGE_LLM_PROVIDER", "none")
    assert get_llm_provider() is None


def test_factory_explicit_unknown_raises(monkeypatch):
    monkeypatch.setenv("MIRAGE_LLM_PROVIDER", "gemini")
    with pytest.raises(LLMConfigError):
        get_llm_provider()


def test_factory_missing_key_for_explicit_provider_raises(monkeypatch):
    monkeypatch.setenv("MIRAGE_LLM_PROVIDER", "openai")
    with pytest.raises(LLMConfigError):
        get_llm_provider()


def test_factory_model_override(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    provider = get_llm_provider("openai", model="gpt-4o")
    assert provider is not None
    # model özel alan; yanıt modeli ile doğrulayacağız


# ---------------------------------------------------------------------------
# OpenAI sağlayıcısı (gerçek HTTP yolu)
# ---------------------------------------------------------------------------
def test_openai_complete_parses_response_and_sends_auth():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"ok": true}'}}]},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAIProvider("sk-secret", model="gpt-4o-mini", client=client)
    resp = _run(provider.complete([LLMMessage("user", "hi")], json_mode=True))

    assert captured["url"].endswith("/v1/chat/completions")
    assert captured["auth"] == "Bearer sk-secret"
    assert captured["body"]["model"] == "gpt-4o-mini"
    assert captured["body"]["response_format"] == {"type": "json_object"}
    assert resp.provider == "openai"
    assert resp.json() == {"ok": True}


def test_openai_http_error_raises_llm_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="rate limited")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAIProvider("sk", client=client)
    with pytest.raises(LLMError):
        _run(provider.complete([LLMMessage("user", "hi")]))


def test_openai_missing_key_raises():
    with pytest.raises(LLMConfigError):
        OpenAIProvider("")


# ---------------------------------------------------------------------------
# Anthropic sağlayıcısı (gerçek HTTP yolu)
# ---------------------------------------------------------------------------
def test_anthropic_complete_extracts_system_and_parses_blocks():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["api_key"] = request.headers.get("x-api-key")
        captured["version"] = request.headers.get("anthropic-version")
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"content": [{"type": "text", "text": '{"severity": "high"}'}]},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = AnthropicProvider("ak-secret", client=client)
    resp = _run(
        provider.complete(
            [LLMMessage("system", "sys"), LLMMessage("user", "hi")],
            json_mode=True,
        )
    )

    assert captured["url"].endswith("/v1/messages")
    assert captured["api_key"] == "ak-secret"
    assert captured["version"] == "2023-06-01"
    # system ayrı alanda, messages'ta değil
    assert "sys" in captured["body"]["system"]
    assert all(m["role"] != "system" for m in captured["body"]["messages"])
    # json_mode sistem talimatı ekler
    assert "JSON" in captured["body"]["system"]
    assert resp.json() == {"severity": "high"}


def test_anthropic_missing_key_raises():
    with pytest.raises(LLMConfigError):
        AnthropicProvider("")


# ---------------------------------------------------------------------------
# JSON çıkarma yardımcıları
# ---------------------------------------------------------------------------
def test_extract_json_object_from_prose():
    assert extract_json_object('bla bla {"a": 1} son') == {"a": 1}


def test_extract_json_object_from_code_fence():
    text = '```json\n{"severity": "low"}\n```'
    assert extract_json_object(text) == {"severity": "low"}


def test_extract_json_object_invalid_returns_none():
    assert extract_json_object("no json here") is None
    assert extract_json_object("{ not valid }") is None


def test_extract_json_object_handles_braces_in_strings():
    assert extract_json_object('{"note": "a } b"}') == {"note": "a } b"}


# ---------------------------------------------------------------------------
# Triage — sezgisel yol
# ---------------------------------------------------------------------------
def test_triage_heuristic_broken_chain_is_critical():
    result = _run(triage_beacon({"token": "t"}, provider=None, chain_ok=False))
    assert result.source == "heuristic"
    assert result.severity == "critical"
    assert result.recommended_action == "escalate"
    assert result.chain_verified is False


def test_triage_heuristic_multi_ip_is_high():
    result = _run(triage_beacon({"distinct_ips": 3, "user_agent": "curl"}, chain_ok=True))
    assert result.severity == "high"
    assert result.recommended_action == "investigate"


def test_triage_heuristic_office_opener_is_medium():
    result = _run(triage_beacon({"distinct_ips": 1, "user_agent": "Microsoft Excel/16.0"}, chain_ok=True))
    assert result.severity == "medium"
    assert result.recommended_action == "monitor"


def test_triage_heuristic_low_signal_is_low():
    result = _run(triage_beacon({"distinct_ips": 1, "user_agent": "Mozilla/5.0"}, chain_ok=True))
    assert result.severity == "low"
    assert result.recommended_action == "ignore"


# ---------------------------------------------------------------------------
# Triage — LLM yolu ve dayanıklılık
# ---------------------------------------------------------------------------
class _FakeProvider(LLMProvider):
    """Test double: LLMProvider arayüzü; somut sağlayıcılar ayrıca test edildi."""

    name = "fake"

    def __init__(self, text: str):
        self._text = text

    async def complete(self, messages, *, max_tokens=512, temperature=0.0, json_mode=False):
        return LLMResponse(text=self._text, provider=self.name, model="fake-1")


class _ExplodingProvider(LLMProvider):
    name = "boom"

    async def complete(self, messages, *, max_tokens=512, temperature=0.0, json_mode=False):
        raise LLMError("provider down")


def test_triage_llm_result_is_used():
    provider = _FakeProvider(
        '{"severity": "critical", "confidence": 0.9, "rationale": "APT işareti", '
        '"recommended_action": "escalate"}'
    )
    result = _run(triage_beacon({"token": "t"}, provider=provider, chain_ok=True))
    assert result.source == "llm:fake"
    assert result.severity == "critical"
    assert result.confidence == 0.9


def test_triage_llm_invalid_schema_falls_back_to_heuristic():
    provider = _FakeProvider('{"severity": "banana", "recommended_action": "nope"}')
    result = _run(triage_beacon({"distinct_ips": 3}, provider=provider, chain_ok=True))
    assert result.source == "heuristic"
    assert result.severity == "high"


def test_triage_llm_error_falls_back_to_heuristic():
    result = _run(triage_beacon({"distinct_ips": 3}, provider=_ExplodingProvider(), chain_ok=True))
    assert result.source == "heuristic"
    assert result.severity == "high"


def test_triage_llm_confidence_is_clamped():
    provider = _FakeProvider(
        '{"severity": "low", "confidence": 5, "rationale": "x", "recommended_action": "ignore"}'
    )
    result = _run(triage_beacon({"token": "t"}, provider=provider, chain_ok=True))
    assert result.confidence == 1.0


def test_build_triage_messages_contains_event():
    msgs = build_triage_messages({"token": "abc", "distinct_ips": 2}, chain_ok=True)
    assert msgs[0].role == "system"
    assert msgs[1].role == "user"
    assert "abc" in msgs[1].content
    assert "chain_verified" in msgs[1].content

"""
MIRAGE — LLM sağlayıcı fabrikası (opsiyonel, env-driven).

Seçim mantığı (MIRAGE_LLM_PROVIDER):
    - "openai"    : OPENAI_API_KEY ile OpenAI sağlayıcısı
    - "anthropic" : ANTHROPIC_API_KEY ile Anthropic sağlayıcısı
    - "auto" / "" : anahtarı olan ilk sağlayıcı (openai -> anthropic)
    - "none"      : LLM kapalı (deterministik sezgisel yola düşülür)

Hiçbir anahtar yoksa `None` döner; MIRAGE'ın çekirdeği LLM olmadan çalışır.
"""
from __future__ import annotations

import os
from typing import Optional

from .provider import LLMConfigError, LLMProvider
from .providers import (
    ANTHROPIC_DEFAULT_MODEL,
    OPENAI_DEFAULT_MODEL,
    AnthropicProvider,
    OpenAIProvider,
)

_KNOWN = ("openai", "anthropic")


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def available_providers() -> list[str]:
    """Anahtarı tanımlı sağlayıcıların listesi."""
    found = []
    if _env("OPENAI_API_KEY"):
        found.append("openai")
    if _env("ANTHROPIC_API_KEY"):
        found.append("anthropic")
    return found


def get_llm_provider(
    provider: Optional[str] = None,
    *,
    model: Optional[str] = None,
) -> Optional[LLMProvider]:
    """
    Yapılandırılmış LLM sağlayıcısını döndürür; yoksa None.

    Args:
        provider: açık seçim (env'i geçersiz kılar).
        model: model adı geçersiz kılma (env MIRAGE_LLM_MODEL yerine).
    """
    choice = (provider if provider is not None else _env("MIRAGE_LLM_PROVIDER")).lower()
    model = model if model is not None else (_env("MIRAGE_LLM_MODEL") or None)

    if choice == "none":
        return None

    if choice in ("", "auto"):
        for candidate in _KNOWN:
            if _env(f"{candidate.upper()}_API_KEY"):
                choice = candidate
                break
        else:
            return None

    if choice == "openai":
        return OpenAIProvider(
            _env("OPENAI_API_KEY"),
            model=model or OPENAI_DEFAULT_MODEL,
        )
    if choice == "anthropic":
        return AnthropicProvider(
            _env("ANTHROPIC_API_KEY"),
            model=model or ANTHROPIC_DEFAULT_MODEL,
        )

    raise LLMConfigError(
        f"unknown MIRAGE_LLM_PROVIDER={choice!r}; expected one of {_KNOWN + ('auto', 'none')}"
    )

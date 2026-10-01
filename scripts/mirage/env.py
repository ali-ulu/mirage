"""
MIRAGE Production — Environment validation.

Bu modül, FastAPI startup'ında çalışır ve gerekli env var'ların
set edildiğini doğrular. Eksikse uygulama başlamaz (fail-fast).
"""
from __future__ import annotations

import os
import sys
from typing import Optional


REQUIRED_FOR_PRODUCTION = [
    "SUPABASE_URL",
    "SUPABASE_SERVICE_ROLE_KEY",
]

# Kanıt zinciri imzası için zorunlu (fail-closed: yoksa kanıt üretilemez).
REQUIRED_FOR_EVIDENCE = [
    "MIRAGE_EVIDENCE_HMAC_KEY",
]

REQUIRED_FOR_NEXTJS_PUBLIC = [
    "NEXT_PUBLIC_SUPABASE_URL",
    "NEXT_PUBLIC_SUPABASE_ANON_KEY",
]

# Opsiyonel LLM katmanı için geçerli seçimler.
_VALID_LLM_PROVIDERS = ("openai", "anthropic", "auto", "none")


def is_production() -> bool:
    """MIRAGE_ENV=production ise true."""
    return os.environ.get("MIRAGE_ENV", "").lower() == "production"


def validate_production_env() -> list[str]:
    """
    Production için gerekli env var'ları kontrol et.
    Eksik olanların listesini döndür (boş liste = OK).
    """
    missing: list[str] = []
    for var in REQUIRED_FOR_PRODUCTION + REQUIRED_FOR_EVIDENCE:
        if not os.environ.get(var):
            missing.append(var)
    return missing


def validate_llm_env() -> list[str]:
    """
    LLM sağlayıcı yapılandırmasının tutarlılığını doğrular.

    Döndürür: insan-okur hata mesajları listesi (boş = OK). LLM opsiyoneldir;
    yalnızca *seçilen* sağlayıcı için tutarlılık aranır:
      - MIRAGE_LLM_PROVIDER geçerli bir değer mi?
      - seçilen sağlayıcının anahtarı set mi?
    """
    errors: list[str] = []
    choice = (os.environ.get("MIRAGE_LLM_PROVIDER") or "").strip().lower()
    if choice and choice not in _VALID_LLM_PROVIDERS:
        errors.append(
            f"MIRAGE_LLM_PROVIDER={choice!r} is invalid "
            f"(expected one of {', '.join(_VALID_LLM_PROVIDERS)})"
        )
        return errors
    if choice == "openai" and not (os.environ.get("OPENAI_API_KEY") or "").strip():
        errors.append("MIRAGE_LLM_PROVIDER=openai requires OPENAI_API_KEY")
    if choice == "anthropic" and not (os.environ.get("ANTHROPIC_API_KEY") or "").strip():
        errors.append("MIRAGE_LLM_PROVIDER=anthropic requires ANTHROPIC_API_KEY")
    return errors


def _emit(msg: str) -> None:
    """Production'da çök, development'ta uyarı ver."""
    if is_production():
        print(msg, file=sys.stderr)
        sys.exit(1)
    import warnings
    warnings.warn(msg, RuntimeWarning, stacklevel=3)


def fail_fast_on_missing_env() -> None:
    """
    Production modunda eksik/geçersiz env var varsa sys.exit ile çök.
    Development'ta warning yaz, devam et.

    Kontroller:
      - Zorunlu Supabase + kanıt imza anahtarı (production'da fail-closed).
      - LLM sağlayıcı tutarlılığı (opsiyonel; ama yanlış yapılandırma fail-fast).
    """
    missing = validate_production_env()
    if missing:
        _emit(
            f"[MIRAGE] Missing required environment variables: {', '.join(missing)}. "
            f"Set them in .env or your hosting platform's env configuration. "
            f"See DEPLOYMENT.md for details."
        )

    llm_errors = validate_llm_env()
    if llm_errors:
        _emit(
            f"[MIRAGE] Invalid LLM configuration: {'; '.join(llm_errors)}. "
            f"See DEPLOYMENT.md for the optional LLM section."
        )

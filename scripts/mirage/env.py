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

REQUIRED_FOR_NEXTJS_PUBLIC = [
    "NEXT_PUBLIC_SUPABASE_URL",
    "NEXT_PUBLIC_SUPABASE_ANON_KEY",
]


def is_production() -> bool:
    """MIRAGE_ENV=production ise true."""
    return os.environ.get("MIRAGE_ENV", "").lower() == "production"


def validate_production_env() -> list[str]:
    """
    Production için gerekli env var'ları kontrol et.
    Eksik olanların listesini döndür (boş liste = OK).
    """
    missing: list[str] = []
    for var in REQUIRED_FOR_PRODUCTION:
        if not os.environ.get(var):
            missing.append(var)
    return missing


def fail_fast_on_missing_env() -> None:
    """
    Production modunda eksik env var varsa sys.exit ile çök.
    Development'ta warning yaz, devam et.
    """
    missing = validate_production_env()
    if not missing:
        return

    msg = (
        f"[MIRAGE] Missing required environment variables: {', '.join(missing)}. "
        f"Set them in .env or your hosting platform's env configuration. "
        f"See DEPLOYMENT.md for details."
    )

    if is_production():
        print(msg, file=sys.stderr)
        sys.exit(1)
    else:
        # Development'ta sadece warning
        import warnings
        warnings.warn(msg, RuntimeWarning, stacklevel=2)

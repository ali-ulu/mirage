"""MIRAGE — Opsiyonel LLM sağlayıcı katmanı.

MIRAGE'ın çekirdek savunması LLM'siz çalışır. Bu katman, kanıt zinciri
üzerine oturan **opsiyonel** bir zenginleştirme (ör. beacon triyajı) sağlar.
Sağlayıcı seçimi env ile yapılır; hiçbir sağlayıcı yapılandırılmamışsa
deterministik sezgisel (heuristic) yola düşülür.
"""
from .provider import (
    LLMError,
    LLMMessage,
    LLMProvider,
    LLMResponse,
    LLMConfigError,
)
from .factory import get_llm_provider, available_providers
from .triage import triage_beacon, build_triage_messages

__all__ = [
    "LLMError",
    "LLMConfigError",
    "LLMMessage",
    "LLMProvider",
    "LLMResponse",
    "get_llm_provider",
    "available_providers",
    "triage_beacon",
    "build_triage_messages",
]

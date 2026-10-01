"""
MIRAGE — LLM sağlayıcı arayüzü (SOLID: Dependency Inversion).

Üst katmanlar somut sağlayıcılara (OpenAI/Anthropic) değil, bu arayüze
bağımlıdır. Yeni bir sağlayıcı eklemek mevcut kodu değiştirmez (Open/Closed).
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


class LLMError(RuntimeError):
    """Sağlayıcı çağrısı başarısız olduğunda yükseltilir."""


class LLMConfigError(LLMError):
    """Sağlayıcı yapılandırması eksik/geçersiz."""


@dataclass(frozen=True)
class LLMMessage:
    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass(frozen=True)
class LLMResponse:
    text: str
    provider: str
    model: str
    # Opsiyonel: sağlayıcı JSON döndürdüyse çözümlenmiş nesne.
    data: Optional[dict[str, Any]] = None
    raw: Optional[dict[str, Any]] = field(default=None, repr=False)

    def json(self) -> Optional[dict[str, Any]]:
        """Yanıt gövdesinden JSON nesnesi çıkarır (yoksa None)."""
        if self.data is not None:
            return self.data
        return extract_json_object(self.text)


class LLMProvider(ABC):
    """Tüm LLM sağlayıcılarının uyduğu sözleşme."""

    name: str = "abstract"

    @abstractmethod
    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        max_tokens: int = 512,
        temperature: float = 0.0,
        json_mode: bool = False,
    ) -> LLMResponse:
        """Mesajları sağlayıcıya gönderir ve yanıtı döndürür."""

    def __repr__(self) -> str:  # pragma: no cover - teşhis kolaylığı
        return f"<{type(self).__name__} name={self.name!r}>"


def extract_json_object(text: str) -> Optional[dict[str, Any]]:
    """
    Model metninden ilk JSON nesnesini çıkarır.

    Modeller bazen JSON'u kod bloğu içinde veya açıklama ile döndürür;
    bu yardımcı, ilk `{` ile dengeli `}` arasını bulup ayrıştırmayı dener.
    """
    if not text:
        return None
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                candidate = text[start : i + 1]
                try:
                    parsed = json.loads(candidate)
                except json.JSONDecodeError:
                    return None
                return parsed if isinstance(parsed, dict) else None
    return None

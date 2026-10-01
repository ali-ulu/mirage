"""
MIRAGE — Prompt-layer canary (AI-agent tehdit yüzeyi için honeytoken).

Klasik honeytoken bir dosyanın *açılmasını* yakalar. Bir AI ajanı için aynı
fikir farklı bir yüzeyde işler: ajanın **bağlamına** (system prompt, RAG
dokümanı, agent memory) yüksek-entropili, benzersiz bir işaret yerleştirilir.
Bu işaret sonradan başka bir yerde (ajan çıktısı, log, ikinci bir sistem)
görünürse, bağlamın sızdığı/taşındığı anlaşılır.

Tasarım sözleşmesi (triage/planner ile aynı ruh):
  - Deterministik ve saf çekirdek: işaret üretimi `uuid4` dışında yan etkisiz.
  - LLM **gerekmez**; bu modül tamamen çekirdekte çalışır.
  - Registry opsiyonel JSON dosyasına kalıcılaşabilir (HoneytokenRegistry deseni).
"""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# İşaret biçimi: yüksek entropili token, kolay ayırt edilebilir bir çerçeve.
CANARY_PREFIX = "MIRAGE-CANARY"
_MARKER_RE = re.compile(r"\[\[\s*MIRAGE-CANARY:([0-9a-fA-F-]{36})\s*\]\]")

VALID_CONTEXTS = ("system_prompt", "rag_document", "agent_memory")


@dataclass(frozen=True)
class PromptCanary:
    token: str
    marker: str
    context: str  # "system_prompt" | "rag_document" | "agent_memory"
    label: str
    created_at: str  # ISO8601 UTC

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "PromptCanary":
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


def build_marker(token: str) -> str:
    """Bir token için kanonik işaret metnini üretir."""
    return f"[[{CANARY_PREFIX}:{token}]]"


def render_canary(canary: PromptCanary, style: str = "raw") -> str:
    """
    İşareti bağlama gömülecek metne dönüştürür.

    style="raw"  : yalnızca işaret (`[[MIRAGE-CANARY:...]]`).
    style="note" : işareti doğal bir cümleye gömen sarmalayıcı (RAG dokümanı /
                   system prompt içine daha az dikkat çekerek gömülür).
    """
    if style == "raw":
        return canary.marker
    if style == "note":
        return (
            "Operational reference code "
            f"{canary.marker} — keep verbatim when forwarding this section."
        )
    raise ValueError(f"Unknown style: {style!r}")


def detect_canaries(text: str) -> list[str]:
    """
    Metinde geçen tüm canary token'larını (tekrarsız, görünme sırasına göre)
    döndürür. Saf fonksiyon; registry gerektirmez.
    """
    seen: list[str] = []
    for match in _MARKER_RE.finditer(text or ""):
        token = match.group(1)
        if token not in seen:
            seen.append(token)
    return seen


class CanaryRegistry:
    """Token -> PromptCanary eşlemesi; opsiyonel JSON kalıcılığı."""

    def __init__(self, path: Optional[str | Path] = None):
        self.path = Path(path) if path else None
        self._records: dict[str, PromptCanary] = {}

    def issue(self, context: str, label: str = "") -> PromptCanary:
        if context not in VALID_CONTEXTS:
            raise ValueError(
                f"Invalid context {context!r}; expected one of {VALID_CONTEXTS}"
            )
        token = str(uuid.uuid4())
        canary = PromptCanary(
            token=token,
            marker=build_marker(token),
            context=context,
            label=label,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self._records[token] = canary
        return canary

    def lookup(self, token: str) -> Optional[PromptCanary]:
        return self._records.get(token)

    def all_records(self) -> list[PromptCanary]:
        return list(self._records.values())

    def match(self, text: str) -> list[PromptCanary]:
        """Metinde geçen token'lardan bu registry'de kayıtlı olanları döndürür."""
        return [r for t in detect_canaries(text) if (r := self._records.get(t))]

    def save(self) -> None:
        if self.path is None:
            raise RuntimeError("Registry path not set — cannot save")
        data = {
            "version": 1,
            "records": [r.to_dict() for r in self._records.values()],
        }
        self.path.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    def load(self) -> None:
        if self.path is None or not self.path.exists():
            return
        data = json.loads(self.path.read_text())
        self._records = {
            r["token"]: PromptCanary.from_dict(r)
            for r in data.get("records", [])
        }

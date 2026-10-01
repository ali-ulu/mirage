"""
MIRAGE — Beacon triyajı (opsiyonel LLM zenginleştirmesi).

Kanıt zincirindeki bir olayı okur ve bir öncelik değerlendirmesi üretir.
LLM yapılandırılmışsa modelden JSON istenir; değilse **deterministik
sezgisel (heuristic)** yola düşülür. LLM hatası/eksikliği çekirdeği
bozmaz: her durumda geçerli bir `TriageResult` döner.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from typing import Any, Optional

from .provider import LLMError, LLMMessage, LLMProvider

VALID_SEVERITIES = ("low", "medium", "high", "critical")
VALID_ACTIONS = ("ignore", "monitor", "investigate", "escalate")

# Office uygulamaları honeytoken (XLSX vb.) açıldığında tipik User-Agent'lar.
_OFFICE_UA_HINTS = ("excel", "word", "libreoffice", "openoffice", "powerpoint")


@dataclass(frozen=True)
class TriageResult:
    severity: str
    confidence: float
    rationale: str
    recommended_action: str
    source: str  # "llm:openai" | "llm:anthropic" | "heuristic"
    chain_verified: Optional[bool] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _heuristic(event: dict[str, Any], chain_ok: Optional[bool]) -> TriageResult:
    """LLM olmadan, olay sinyallerine göre deterministik değerlendirme."""
    score = 0
    reasons: list[str] = []

    if chain_ok is False:
        score += 100
        reasons.append("kanıt zinciri doğrulanamadı (kurcalama şüphesi)")

    distinct_ips = int(event.get("distinct_ips") or 1)
    if distinct_ips >= 3:
        score += 60
        reasons.append(f"{distinct_ips} farklı kaynak IP (dağıtık yoklama)")
    elif distinct_ips == 2:
        score += 20
        reasons.append("2 farklı kaynak IP")

    ua = str(event.get("user_agent") or "")
    opener = str(event.get("opener_app") or "")
    haystack = f"{ua} {opener}".lower()
    if any(hint in haystack for hint in _OFFICE_UA_HINTS):
        score += 25
        reasons.append("office uygulaması honeytoken'ı açtı")

    if not ua:
        score += 10
        reasons.append("User-Agent yok (otomasyon olabilir)")

    if score >= 100:
        severity, action, confidence = "critical", "escalate", 0.95
    elif score >= 50:
        severity, action, confidence = "high", "investigate", 0.8
    elif score >= 20:
        severity, action, confidence = "medium", "monitor", 0.6
    else:
        severity, action, confidence = "low", "ignore", 0.4

    rationale = "; ".join(reasons) if reasons else "belirgin yükseltici sinyal yok"
    return TriageResult(
        severity=severity,
        confidence=confidence,
        rationale=rationale,
        recommended_action=action,
        source="heuristic",
        chain_verified=chain_ok,
    )


def build_triage_messages(event: dict[str, Any], chain_ok: Optional[bool]) -> list[LLMMessage]:
    """LLM için sistem + kullanıcı mesajlarını kurar (saf fonksiyon, test edilebilir)."""
    system = (
        "Sen bir siber savunma triyaj asistanısın. Sana bir honeytoken (tuzak) "
        "beacon olayı verilir. Olayın aciliyetini değerlendir. "
        "Yanıtını SADECE şu alanları içeren tek bir JSON nesnesi olarak ver: "
        '{"severity": "low|medium|high|critical", '
        '"confidence": 0.0-1.0, '
        '"rationale": "kısa gerekçe", '
        '"recommended_action": "ignore|monitor|investigate|escalate"}. '
        "Yalnızca HTTP isteğinden elde edilen kanıtlara dayan; spekülasyon yapma."
    )
    payload = {
        "event": event,
        "chain_verified": chain_ok,
    }
    user = (
        "Honeytoken beacon olayı (kanıt zincirinden):\n"
        + json.dumps(payload, ensure_ascii=False, sort_keys=True)
    )
    return [LLMMessage(role="system", content=system), LLMMessage(role="user", content=user)]


def _coerce_llm_result(data: dict[str, Any], provider_name: str, chain_ok: Optional[bool]) -> Optional[TriageResult]:
    """Model JSON'unu doğrular; şema uymuyorsa None döner (çağıran heuristic'e düşer)."""
    severity = str(data.get("severity", "")).lower()
    action = str(data.get("recommended_action", "")).lower()
    if severity not in VALID_SEVERITIES or action not in VALID_ACTIONS:
        return None
    try:
        confidence = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        return None
    confidence = min(1.0, max(0.0, confidence))
    rationale = str(data.get("rationale", "")).strip() or "model gerekçe vermedi"
    return TriageResult(
        severity=severity,
        confidence=confidence,
        rationale=rationale,
        recommended_action=action,
        source=f"llm:{provider_name}",
        chain_verified=chain_ok,
    )


async def triage_beacon(
    event: dict[str, Any],
    *,
    provider: Optional[LLMProvider] = None,
    chain_ok: Optional[bool] = None,
) -> TriageResult:
    """
    Bir beacon olayını değerlendirir.

    Args:
        event: olay alanları (token, ip, user_agent, opener_app, distinct_ips...).
        provider: LLM sağlayıcısı; None ise heuristic kullanılır.
        chain_ok: kanıt zinciri doğrulama sonucu (opsiyonel bağlam).

    Returns:
        TriageResult — LLM başarısız olsa bile her zaman geçerli bir sonuç.
    """
    if provider is None:
        return _heuristic(event, chain_ok)

    messages = build_triage_messages(event, chain_ok)
    try:
        response = await provider.complete(messages, max_tokens=400, temperature=0.0, json_mode=True)
        data = response.json()
        if data:
            coerced = _coerce_llm_result(data, provider.name, chain_ok)
            if coerced is not None:
                return coerced
    except LLMError:
        # Opsiyonel zenginleştirme; hata çekirdeği bozmamalı.
        pass
    except Exception:  # pragma: no cover - beklenmeyen sağlayıcı hatalarına karşı dayanıklılık
        pass

    fallback = _heuristic(event, chain_ok)
    return TriageResult(
        severity=fallback.severity,
        confidence=fallback.confidence,
        rationale=f"LLM kullanılamadı, sezgisel değerlendirme: {fallback.rationale}",
        recommended_action=fallback.recommended_action,
        source=fallback.source,
        chain_verified=chain_ok,
    )

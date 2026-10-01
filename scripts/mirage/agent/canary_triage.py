"""
MIRAGE — Prompt-layer canary sızıntısı triyajı.

Bir canary işareti ajan bağlamı dışında (çıktı, log, ikinci sistem) görünürse
bu bir **sızıntı olayıdır**. Bu modül, beacon triyajıyla (`llm/triage.py`) aynı
sözleşmeyi izler: LLM yapılandırılmışsa JSON istenir, değilse **deterministik
sezgisel** yola düşülür; her hata fallback'tir ve çekirdek bozulmaz.

Sonuç tipi olarak beacon triyajının `TriageResult`'ı **yeniden kullanılır**;
böylece sızıntı, append-only triyaj defterine (`beacon_triage`) beacon olayıyla
aynı şekilde yazılabilir.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from ..llm.provider import LLMError, LLMMessage, LLMProvider
from ..llm.triage import TriageResult

# Bağlama göre taban ağırlık — system prompt sızıntısı en kritik.
_CONTEXT_WEIGHTS = {
    "system_prompt": 25,
    "agent_memory": 20,
    "rag_document": 15,
}


def _heuristic(leak: dict[str, Any], chain_ok: Optional[bool]) -> TriageResult:
    """LLM olmadan, sızıntı sinyallerine göre deterministik değerlendirme."""
    score = 0
    reasons: list[str] = []

    if chain_ok is False:
        score += 100
        reasons.append("kanıt zinciri doğrulanamadı (kurcalama şüphesi)")

    # Her sızmış bağlam kendi ağırlığını ekler → çok yüzeyli sızıntı daha ağır.
    contexts = sorted(set(leak.get("contexts") or []))
    for ctx in contexts:
        score += _CONTEXT_WEIGHTS.get(ctx, 0)
    if len(contexts) >= 2:
        reasons.append(f"{len(contexts)} farklı bağlam sızdı (çok yüzeyli)")
    elif len(contexts) == 1 and _CONTEXT_WEIGHTS.get(contexts[0]):
        reasons.append(f"'{contexts[0]}' bağlamı sızdı")

    count = int(leak.get("count") or 0)
    if count >= 3:
        score += 30
        reasons.append(f"{count} canary işareti sızdı (yaygın sızıntı)")
    elif count >= 2:
        score += 10
        reasons.append(f"{count} canary işareti sızdı")

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


def build_canary_triage_messages(
    leak: dict[str, Any], chain_ok: Optional[bool]
) -> list[LLMMessage]:
    """LLM için sistem + kullanıcı mesajlarını kurar (saf fonksiyon)."""
    system = (
        "Sen bir siber savunma triyaj asistanısın. Bir AI ajanı bağlamına "
        "gömülen canary (honeytoken) işareti bağlam dışında görüldü — bu bir "
        "prompt/bağlam sızıntısı olayıdır. Olayın aciliyetini değerlendir. "
        "Yanıtını SADECE şu alanları içeren tek bir JSON nesnesi olarak ver: "
        '{"severity": "low|medium|high|critical", '
        '"confidence": 0.0-1.0, '
        '"rationale": "kısa gerekçe", '
        '"recommended_action": "ignore|monitor|investigate|escalate"}. '
        "Yalnızca verilen kanıtlara dayan; spekülasyon yapma."
    )
    payload = {"leak": leak, "chain_verified": chain_ok}
    user = (
        "Canary sızıntı olayı:\n"
        + json.dumps(payload, ensure_ascii=False, sort_keys=True)
    )
    return [LLMMessage(role="system", content=system), LLMMessage(role="user", content=user)]


def _coerce_llm_result(
    data: dict[str, Any], provider_name: str, chain_ok: Optional[bool]
) -> Optional[TriageResult]:
    """Model JSON'unu doğrular; şema uymuyorsa None döner (çağıran heuristic'e düşer)."""
    from ..llm.triage import VALID_ACTIONS, VALID_SEVERITIES

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


async def triage_canary(
    leak: dict[str, Any],
    *,
    provider: Optional[LLMProvider] = None,
    chain_ok: Optional[bool] = None,
) -> TriageResult:
    """
    Bir canary sızıntı olayını değerlendirir.

    Args:
        leak: sızıntı alanları (count, contexts, canaries...).
        provider: LLM sağlayıcısı; None ise heuristic kullanılır.
        chain_ok: kanıt zinciri doğrulama sonucu (opsiyonel bağlam).

    Returns:
        TriageResult — LLM başarısız olsa bile her zaman geçerli bir sonuç.
    """
    if provider is None:
        return _heuristic(leak, chain_ok)

    messages = build_canary_triage_messages(leak, chain_ok)
    try:
        response = await provider.complete(
            messages, max_tokens=400, temperature=0.0, json_mode=True
        )
        data = response.json()
        if data:
            coerced = _coerce_llm_result(data, provider.name, chain_ok)
            if coerced is not None:
                return coerced
    except LLMError:
        pass
    except Exception:  # pragma: no cover - beklenmeyen sağlayıcı hatalarına karşı dayanıklılık
        pass

    fallback = _heuristic(leak, chain_ok)
    return TriageResult(
        severity=fallback.severity,
        confidence=fallback.confidence,
        rationale=f"LLM kullanılamadı, sezgisel değerlendirme: {fallback.rationale}",
        recommended_action=fallback.recommended_action,
        source=fallback.source,
        chain_verified=chain_ok,
    )

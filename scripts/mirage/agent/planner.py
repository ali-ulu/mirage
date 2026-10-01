"""
MIRAGE — Planner Agent (opsiyonel LLM zenginleştirmesi).

Bir DataFrame şemasını analiz eder ve hangi kolonların **decoy** (sentetik
tuzak verisiyle değiştirilecek) hangilerinin **korunacağını** planlar. Mevcut
motor uçları ajanın tool'larıdır: `profile_column` (şema keşfi),
`MirageSynthesizer` (decoy üretimi), `HoneytokenRegistry` (tuzak kaydı).

LLM yapılandırılmışsa modelden JSON istenir; değilse **deterministik sezgisel**
yola düşülür. LLM hatası/eksikliği çekirdeği bozmaz: her durumda geçerli bir
`DecoyPlan` döner. Bu, `llm/triage.py` ile aynı sözleşmedir.

Güvenlik notu: heuristic, tanımlayıcı/anahtar kolonları (id, foreign key, uuid)
asla decoy yapmaz; aksi halde ilişkisel bütünlük bozulur. Bu, "önce zarar verme"
ilkesidir.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from typing import Any, Optional

import pandas as pd

from ..analyzer import ColumnProfile, profile_column
from ..llm.provider import LLMError, LLMMessage, LLMProvider

VALID_DISPOSITIONS = ("decoy", "keep")

# İlişkisel bütünlüğü bozacağı için asla decoy yapılmayacak kolon adları.
_IDENTIFIER_NAMES = frozenset(
    {"id", "uuid", "guid", "pk", "foreign_key", "fk"}
)

# Decoy için yüksek değerli, kişisel/hassas kolon adı ipuçları.
_SENSITIVE_HINTS = (
    "name", "email", "mail", "phone", "tel", "mobile", "address", "addr",
    "iban", "account", "card", "ssn", "national", "passport", "license",
    "dob", "birth", "salary", "wage", "customer", "client", "user",
)

# Şema özetine dahil edilecek kolon tipi -> ajan-okur etiket.
_DECOY_TYPES = ("categorical", "empirical_text", "free_text", "formatted", "timestamp")


@dataclass(frozen=True)
class ColumnDecision:
    name: str
    col_type: str
    disposition: str  # "decoy" | "keep"
    sensitivity: str  # "high" | "medium" | "low"
    rationale: str


@dataclass(frozen=True)
class DecoyPlan:
    decisions: list[ColumnDecision]
    strategy: str
    source: str  # "llm:openai" | "llm:anthropic" | "heuristic"

    @property
    def decoy_columns(self) -> list[str]:
        return [d.name for d in self.decisions if d.disposition == "decoy"]

    @property
    def kept_columns(self) -> list[str]:
        return [d.name for d in self.decisions if d.disposition == "keep"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "source": self.source,
            "decoy_columns": self.decoy_columns,
            "kept_columns": self.kept_columns,
            "decisions": [asdict(d) for d in self.decisions],
        }


def _is_identifier(profile: ColumnProfile) -> bool:
    """Kolon bir tanımlayıcı/anahtar mı (decoy yapılmamalı)?"""
    name = profile.name.lower()
    if name in _IDENTIFIER_NAMES or name.endswith("_id") or name.endswith("_key"):
        return True
    return profile.col_type == "formatted" and profile.format_kind == "uuid"


def _sensitivity(profile: ColumnProfile) -> str:
    name = profile.name.lower()
    if any(hint in name for hint in _SENSITIVE_HINTS):
        return "high"
    if profile.col_type in ("formatted", "free_text"):
        return "high"
    if profile.col_type in ("categorical", "empirical_text", "timestamp"):
        return "medium"
    return "low"


def schema_summary(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Ajan için kompakt, JSON-serileştirilebilir şema özeti."""
    summary: list[dict[str, Any]] = []
    for name in df.columns:
        profile = profile_column(name, df[name])
        entry: dict[str, Any] = {
            "name": str(name),
            "col_type": profile.col_type,
            "null_prob": round(profile.null_prob, 4),
        }
        if profile.col_type == "categorical" and profile.categories is not None:
            entry["cardinality"] = int(len(profile.categories))
        if profile.col_type == "formatted":
            entry["format_kind"] = profile.format_kind
        summary.append(entry)
    return summary


def _heuristic(df: pd.DataFrame) -> DecoyPlan:
    """LLM olmadan, kolon adı + tipine göre deterministik plan."""
    decisions: list[ColumnDecision] = []
    for name in df.columns:
        profile = profile_column(name, df[name])
        sensitive = _sensitivity(profile)

        if _is_identifier(profile):
            disposition = "keep"
            rationale = "tanımlayıcı/anahtar kolon; ilişkisel bütünlük için korunur"
        elif profile.col_type in _DECOY_TYPES:
            disposition = "decoy"
            rationale = f"{profile.col_type} kolon; sentetik tuzak verisiyle değiştirilir"
        elif profile.col_type in ("numeric_int", "numeric_float"):
            disposition = "decoy"
            rationale = "sayısal kolon; istatistiksel dağılım korunarak üretilir"
        else:
            disposition = "keep"
            rationale = "desteklenmeyen tip; güvenli tarafta kalınır"

        decisions.append(
            ColumnDecision(
                name=str(name),
                col_type=profile.col_type,
                disposition=disposition,
                sensitivity=sensitive,
                rationale=rationale,
            )
        )

    strategy = "kimlik kolonları korunur, hassas alanlar sentetik decoy ile değiştirilir"
    return DecoyPlan(decisions=decisions, strategy=strategy, source="heuristic")


def build_planner_messages(summary: list[dict[str, Any]]) -> list[LLMMessage]:
    """LLM için sistem + kullanıcı mesajlarını kurar (saf fonksiyon)."""
    system = (
        "Sen bir veri güvenliği planlama asistanısın. Sana bir tablonun kolon "
        "özeti verilir. Hangi kolonların sentetik 'decoy' verisiyle değiştirilip "
        "hangilerinin korunacağını planla. Kimlik/anahtar kolonları (id, uuid, "
        "foreign key) ASLA decoy yapılmaz. Yanıtını SADECE şu JSON nesnesi olarak "
        'ver: {"strategy": "kısa açıklama", "columns": [{"name": "...", '
        '"disposition": "decoy|keep", "rationale": "kısa gerekçe"}]}. '
        "Yalnızca verilen kolonları kullan; spekülasyon yapma."
    )
    user = "Tablo kolon özeti:\n" + json.dumps(summary, ensure_ascii=False, sort_keys=True)
    return [LLMMessage(role="system", content=system), LLMMessage(role="user", content=user)]


def _coerce_llm_plan(
    data: dict[str, Any], provider_name: str, df: pd.DataFrame
) -> Optional[DecoyPlan]:
    """
    Model JSON'unu doğrular. Şema uymuyorsa None döner (çağıran heuristic'e düşer).

    Güvenlik kısıtı: model bir tanımlayıcı kolonu decoy yapmaya çalışırsa bu karar
    zorla `keep`'e çevrilir (modele güvenilmez).
    """
    raw_columns = data.get("columns")
    if not isinstance(raw_columns, list) or not raw_columns:
        return None

    profiles = {str(name): profile_column(name, df[name]) for name in df.columns}
    by_name = {str(name): name for name in df.columns}

    decisions: list[ColumnDecision] = []
    seen: set[str] = set()
    for item in raw_columns:
        if not isinstance(item, dict):
            return None
        name = str(item.get("name", ""))
        if name not in by_name or name in seen:
            return None
        disposition = str(item.get("disposition", "")).lower()
        if disposition not in VALID_DISPOSITIONS:
            return None
        profile = profiles[name]
        rationale = str(item.get("rationale", "")).strip() or "model gerekçe vermedi"
        if disposition == "decoy" and _is_identifier(profile):
            disposition = "keep"
            rationale = "tanımlayıcı kolon; model kararı güvenlik gereği korundu"
        seen.add(name)
        decisions.append(
            ColumnDecision(
                name=name,
                col_type=profile.col_type,
                disposition=disposition,
                sensitivity=_sensitivity(profile),
                rationale=rationale,
            )
        )

    # Model bazı kolonları atladıysa, eksikleri heuristic ile tamamla (güvenli varsayılan).
    if len(decisions) != len(df.columns):
        return None

    strategy = str(data.get("strategy", "")).strip() or "model planı"
    return DecoyPlan(decisions=decisions, strategy=strategy, source=f"llm:{provider_name}")


async def plan_decoy_schema(
    df: pd.DataFrame,
    *,
    provider: Optional[LLMProvider] = None,
) -> DecoyPlan:
    """
    Bir DataFrame şeması için decoy planı üretir.

    Args:
        df: profillenecek tablo (decoy planı üretir, veriyi değiştirmez).
        provider: LLM sağlayıcısı; None ise heuristic kullanılır.

    Returns:
        DecoyPlan — LLM başarısız olsa bile her zaman geçerli bir plan.
    """
    if provider is None:
        return _heuristic(df)

    summary = schema_summary(df)
    messages = build_planner_messages(summary)
    try:
        response = await provider.complete(messages, max_tokens=600, temperature=0.0, json_mode=True)
        data = response.json()
        if data:
            coerced = _coerce_llm_plan(data, provider.name, df)
            if coerced is not None:
                return coerced
    except LLMError:
        # Opsiyonel zenginleştirme; hata çekirdeği bozmamalı.
        pass
    except Exception:  # pragma: no cover - beklenmeyen sağlayıcı hatalarına karşı dayanıklılık
        pass

    fallback = _heuristic(df)
    return DecoyPlan(
        decisions=fallback.decisions,
        strategy=f"LLM kullanılamadı, sezgisel plan: {fallback.strategy}",
        source=fallback.source,
    )

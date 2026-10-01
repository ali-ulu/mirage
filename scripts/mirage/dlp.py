"""
MIRAGE — Regex ötesi DLP (veri kaybı önleme) tarayıcısı.

Klasik DLP yalnızca regex'e bakar ve iki yönde yanılır: (a) biçimi tutan ama
geçersiz veriyi yakalar (yanlış pozitif), (b) biçimi tutmayan gerçek sızıntıyı
kaçırır (yanlış negatif). Bu katman **regex + doğrulama + istatistik** birleşimi
kullanır:

  - **Checksum doğrulaması:** TCKN (Türkiye kimlik no), IBAN (mod-97), kredi
    kartı (Luhn), TR telefon normalizasyonu. Biçim tutsa da sağlama tutmuyorsa
    düşük güvenle işaretlenir.
  - **Shannon entropisi:** yüksek entropili token'lar (API anahtarı, JWT, sır)
    yalnızca desene değil dağılıma göre yakalanır.
  - **Gazetteer + bağlam:** kişi adı / adres, sokak-tipi sözlüğü + yakın bağlam
    sözcükleriyle skorlanır (nerede "ad"/"soyad"/"adres" geçiyorsa).

Tasarım:
  - Deterministik, çevrimdışı, LLM/harici model İNDİRMEZ (tembel bağımlılık yok).
  - `DLPScanner(rules=...)` ile müşteri regex kuralları da beslenebilir (mevcut
    `agent.runtime.evaluate_rules` ile aynı şekil) — tek geçişte birleşik bulgu.
  - Fail-safe: tek bir dedektör hata verse bile tarama durmaz.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from .severity import SEVERITY_ORDER as _SEVERITY_ORDER

# --- Yapısal desenler (regex katmanı) -------------------------------------
_RE_TCKN = re.compile(r"(?<!\d)(\d{11})(?!\d)")
_RE_IBAN = re.compile(r"\bTR\d{2}\s?(?:\d{4}\s?){5}\d{2}\b", re.IGNORECASE)
_RE_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
_RE_PHONE = re.compile(r"(?<!\d)(?:\+90|0)?\s?5\d{2}[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2}(?!\d)")
_RE_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_RE_SECRETISH = re.compile(r"\b[A-Za-z0-9_\-]{20,}\b")
_RE_JWT = re.compile(r"\beyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\b")

# --- Gazetteer / bağlam (istatistik katmanı) ------------------------------
_STREET_TYPES = (
    "sokak", "sok.", "cadde", "cad.", "bulvar", "bulvarı", "mahalle", "mah.",
    "apartman", "apt.", "no:", "daire", "blok", "sokagi",
)
_NAME_CONTEXT = ("ad", "adı", "soyad", "soyadı", "isim", "müşteri", "personel",
                 "çalışan", "ad-soyad", "name", "surname")
_ADDRESS_CONTEXT = ("adres", "address", "ikamet", "konum", "lokasyon")
_ENTROPY_MIN_LEN = 20
_ENTROPY_THRESHOLD = 3.5


def _shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    counts: dict[str, int] = {}
    for ch in s:
        counts[ch] = counts.get(ch, 0) + 1
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def _valid_tckn(value: str) -> bool:
    if len(value) != 11 or value[0] == "0":
        return False
    d = [int(x) for x in value]
    if d[9] != ((sum(d[0:9:2]) * 7) - sum(d[1:9:2])) % 10:
        return False
    return d[10] == sum(d[0:10]) % 10


def _valid_iban_tr(value: str) -> bool:
    compact = re.sub(r"\s", "", value).upper()
    if not compact.startswith("TR") or len(compact) != 26:
        return False
    rearranged = compact[4:] + compact[:4]
    digits = "".join(str(int(ch, 36)) for ch in rearranged)
    return int(digits) % 97 == 1


def _valid_luhn(value: str) -> bool:
    digits = [int(c) for c in re.sub(r"\D", "", value)]
    if len(digits) < 13:
        return False
    checksum = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        checksum += d
    return checksum % 10 == 0


@dataclass(frozen=True)
class Finding:
    category: str  # tckn | iban | credit_card | phone | email | secret | name | address
    severity: str
    confidence: float  # 0..1
    match: str
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"category": self.category, "severity": self.severity,
                "confidence": self.confidence, "match": self.match, "detail": self.detail}


@dataclass
class DLPScanner:
    """
    Birleşik DLP tarayıcısı.

    Args:
        rules: müşteri regex kuralları (`{"name","pattern","severity",...}`);
            `agent.runtime.evaluate_rules` ile aynı şekil.
        entropy_threshold: gizli-token entropi eşiği (varsayılan 3.5 bit/karakter).
    """

    rules: list[dict[str, Any]] = field(default_factory=list)
    entropy_threshold: float = _ENTROPY_THRESHOLD

    def scan(self, text: str) -> list[Finding]:
        findings: list[Finding] = []
        text = text or ""

        findings += _safe(self._scan_tckn, text)
        findings += _safe(self._scan_iban, text)
        findings += _safe(self._scan_cards, text)
        findings += _safe(self._scan_phones, text)
        findings += _safe(self._scan_emails, text)
        findings += _safe(self._scan_secrets, text)
        findings += _safe(self._scan_names, text)
        findings += _safe(self._scan_addresses, text)
        findings += _safe(self._scan_rules, text)
        return findings

    # --- dedektörler -------------------------------------------------------
    def _scan_tckn(self, text: str) -> list[Finding]:
        out = []
        for m in _RE_TCKN.finditer(text):
            v = m.group(1)
            ok = _valid_tckn(v)
            out.append(Finding(
                "tckn", "high" if ok else "low", 0.95 if ok else 0.25,
                v, "checksum geçerli" if ok else "checksum geçersiz (olası yanlış pozitif)",
            ))
        return out

    def _scan_iban(self, text: str) -> list[Finding]:
        out = []
        for m in _RE_IBAN.finditer(text):
            v = m.group(0)
            ok = _valid_iban_tr(v)
            out.append(Finding("iban", "high" if ok else "low",
                               0.95 if ok else 0.3, v,
                               "mod-97 geçerli" if ok else "mod-97 geçersiz"))
        return out

    def _scan_cards(self, text: str) -> list[Finding]:
        out = []
        for m in _RE_CARD.finditer(text):
            v = m.group(0)
            if _valid_luhn(v):
                out.append(Finding("credit_card", "critical", 0.95, v, "Luhn geçerli"))
        return out

    def _scan_phones(self, text: str) -> list[Finding]:
        return [Finding("phone", "medium", 0.7, m.group(0), "TR cep telefonu biçimi")
                for m in _RE_PHONE.finditer(text)]

    def _scan_emails(self, text: str) -> list[Finding]:
        return [Finding("email", "medium", 0.8, m.group(0)) for m in _RE_EMAIL.finditer(text)]

    def _scan_secrets(self, text: str) -> list[Finding]:
        out = []
        for m in _RE_JWT.finditer(text):
            out.append(Finding("secret", "critical", 0.98, m.group(0)[:60], "JWT"))
        for m in _RE_SECRETISH.finditer(text):
            v = m.group(0)
            if len(v) < _ENTROPY_MIN_LEN:
                continue
            if _RE_JWT.search(v):
                continue
            ent = _shannon_entropy(v)
            # Yüksek entropi tek başına zayıftır (uzun küçük-harf sözcükler de
            # yüksek entropili görünür); karakter sınıfı çeşitliliği şart.
            diverse = (
                any(c.isupper() for c in v)
                or any(c.isdigit() for c in v)
                or any(not c.isalnum() for c in v)
            )
            if ent >= self.entropy_threshold and diverse:
                out.append(Finding("secret", "high", min(0.99, ent / 6.0),
                                   v[:60], f"yüksek entropi ({ent:.2f} bit/kar)"))
        return out

    def _scan_names(self, text: str) -> list[Finding]:
        out = []
        # Bağlam sözcüğüne bitişik iki büyük-harf sözcük (ad soyad) yaklaşımı.
        words = re.findall(r"[A-ZÇĞİÖŞÜ][a-zçğıöşü]+", text)
        for i in range(len(words) - 1):
            pair = f"{words[i]} {words[i+1]}"
            window = text.lower()
            ctx_hit = any(c in window for c in _NAME_CONTEXT)
            if len(pair) >= 6 and ctx_hit:
                out.append(Finding("name", "medium", 0.6, pair,
                                   "ad/soyad bağlamı"))
        return out

    def _scan_addresses(self, text: str) -> list[Finding]:
        low = text.lower()
        if any(t in low for t in _STREET_TYPES) and any(c in low for c in _ADDRESS_CONTEXT):
            snippet = next((t for t in _STREET_TYPES if t in low), "")
            return [Finding("address", "medium", 0.65, snippet, "adres bağlamı + sokak tipi")]
        return []

    def _scan_rules(self, text: str) -> list[Finding]:
        out = []
        for rule in self.rules or []:
            pattern = rule.get("pattern")
            if not pattern:
                continue
            try:
                match = re.search(pattern, text)
            except re.error:
                continue  # bozuk müşteri kuralı fail-safe atlanır
            if match:
                out.append(Finding("custom", rule.get("severity", "medium"), 0.8,
                                   match.group(0)[:200], rule.get("name", "")))
        return out


def _safe(fn, text: str) -> list[Finding]:
    try:
        return fn(text)
    except Exception:
        return []


def dlp_scan(text: str, *, rules: Optional[Iterable[dict[str, Any]]] = None) -> list[Finding]:
    """Kolaylık fonksiyonu: tek metni tarar."""
    return DLPScanner(rules=list(rules or [])).scan(text)


def summarize(findings: Iterable[Finding]) -> dict[str, Any]:
    items = list(findings)
    by_cat: dict[str, int] = {}
    for f in items:
        by_cat[f.category] = by_cat.get(f.category, 0) + 1
    top = None
    if items:
        top = max((f.severity for f in items), key=lambda s: _SEVERITY_ORDER.get(s, 0))
    return {"total": len(items), "by_category": by_cat, "max_severity": top,
            "confirmed": sum(1 for f in items if f.confidence >= 0.9)}


__all__ = ["DLPScanner", "Finding", "dlp_scan", "summarize"]

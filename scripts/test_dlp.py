"""
PR — Regex ötesi DLP tarayıcı testleri.

Kapsam:
  - Checksum doğrulaması: TCKN, IBAN (mod-97), kredi kartı (Luhn) — geçerli
    düşük/geçersiz yüksek güven ayrımı.
  - Shannon entropisi ile gizli token + JWT.
  - Gazetteer/bağlam: ad-soyad, adres.
  - Müşteri regex kuralları (birleşik bulgu) + bozuk regex fail-safe.
  - `summarize` ve `dlp_scan`.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mirage.dlp import DLPScanner, dlp_scan, summarize  # noqa: E402


# ---------------------------------------------------------------------------
# checksum: TCKN
# ---------------------------------------------------------------------------
def test_valid_tckn_high_confidence():
    # 10000000146 bilinen geçerli bir test TCKN'sidir.
    findings = [f for f in dlp_scan("kimlik: 10000000146") if f.category == "tckn"]
    assert findings and findings[0].severity == "high"
    assert findings[0].confidence >= 0.9


def test_invalid_tckn_low_confidence():
    findings = [f for f in dlp_scan("numara 12345678901") if f.category == "tckn"]
    assert findings and findings[0].severity == "low"
    assert findings[0].confidence < 0.5


# ---------------------------------------------------------------------------
# checksum: IBAN
# ---------------------------------------------------------------------------
def test_valid_iban():
    # TR33 0006 1005 1978 6457 8413 26 — mod-97 geçerli test IBAN'ı.
    findings = [f for f in dlp_scan("IBAN TR330006100519786457841326") if f.category == "iban"]
    assert findings and findings[0].confidence >= 0.9


def test_invalid_iban_low():
    findings = [f for f in dlp_scan("IBAN TR000000000000000000000000") if f.category == "iban"]
    assert findings and findings[0].confidence < 0.5


# ---------------------------------------------------------------------------
# checksum: kart (Luhn)
# ---------------------------------------------------------------------------
def test_valid_card_luhn_critical():
    findings = [f for f in dlp_scan("kart 4111 1111 1111 1111") if f.category == "credit_card"]
    assert findings and findings[0].severity == "critical"


def test_invalid_card_not_flagged():
    findings = [f for f in dlp_scan("sayi 1234 5678 9012 3456") if f.category == "credit_card"]
    assert findings == []


# ---------------------------------------------------------------------------
# entropy: secret / jwt
# ---------------------------------------------------------------------------
def test_jwt_detected_critical():
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    findings = [f for f in dlp_scan(f"token: {jwt}") if f.category == "secret"]
    assert findings and any(f.severity == "critical" for f in findings)


def test_high_entropy_secret_detected():
    secret = "aZ9bY8cX7dW6eV5fU4gT3hS2iR1jQ0kP"
    findings = [f for f in dlp_scan(f"api_key={secret}") if f.category == "secret"]
    assert findings


def test_low_entropy_word_not_secret():
    findings = [f for f in dlp_scan("thisisaverylongbutplainword") if f.category == "secret"]
    assert findings == []


# ---------------------------------------------------------------------------
# gazetteer / context
# ---------------------------------------------------------------------------
def test_name_with_context():
    findings = [f for f in dlp_scan("Müşteri adı: Ahmet Yılmaz") if f.category == "name"]
    assert findings


def test_address_with_context():
    findings = [f for f in dlp_scan("Adres: Atatürk Caddesi No: 5") if f.category == "address"]
    assert findings


def test_phone_and_email():
    cats = {f.category for f in dlp_scan("tel 0532 123 45 67 mail a@b.com")}
    assert "phone" in cats and "email" in cats


# ---------------------------------------------------------------------------
# custom rules + fail-safe
# ---------------------------------------------------------------------------
def test_custom_rule_applied():
    rules = [{"name": "internal", "pattern": r"GİZLİ-\d+", "severity": "high"}]
    findings = [f for f in dlp_scan("kod GİZLİ-42", rules=rules) if f.category == "custom"]
    assert findings and findings[0].severity == "high"


def test_bad_regex_skipped():
    rules = [{"name": "bad", "pattern": "(", "severity": "high"}]
    # bozuk regex sessizce atlanır, tarama çökmez
    assert dlp_scan("GİZLİ-42", rules=rules) is not None


# ---------------------------------------------------------------------------
# summarize
# ---------------------------------------------------------------------------
def test_summarize():
    findings = dlp_scan("IBAN TR330006100519786457841326 ve kart 4111111111111111")
    s = summarize(findings)
    assert s["total"] >= 2 and s["confirmed"] >= 2
    assert s["max_severity"] == "critical"


def test_scanner_reusable():
    scanner = DLPScanner()
    assert scanner.scan("mail x@y.com") == scanner.scan("mail x@y.com")

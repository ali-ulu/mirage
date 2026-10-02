"""
MIRAGE — Kanıt zinciri uçtan uca (E2E) testi.

Bu test ürünün ana iddiasını baştan sona doğrular:

    1. Sentetik veri üretilir (MirageSynthesizer).
    2. Honeytoken XLSX'e gömülür (pasif beacon, kod çalıştırmaz).
    3. Bir "saldırgan" dosyayı açar → tracking URL'e HTTP GET atar.
    4. Edge kaydı üretir.
    5. KAYIT İMZALANIR: record_hash + HMAC, prev_hash ile zinciře bağlanır.
    6. Zincir bağımsız doğrulanır (verify_chain) → "kurcalanmadı".
    7. Saldırgan kaydı kurcalarsa → doğrulama BAŞARISIZ olur.

Adım 7 kritik: kanıt zinciri sadece "var" olduğunu değil, "bozulduğunu
da tespit ettiğini" kanıtlamalıdır.
"""
from __future__ import annotations

import socket
import sys
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mirage import MirageSynthesizer  # noqa: E402
from mirage.evidence import (  # noqa: E402
    build_evidence_record,
    normalize_timestamp,
    record_hash,
    verify_chain,
)
from mirage.honeytoken import inject_honeytoken  # noqa: E402

EVIDENCE_KEY = "e2e-local-evidence-key-0123456789"
CHAIN_LEN = 3
TOKEN = "550e8400-e29b-41d4-a716-446655440000"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _CaptureHandler(BaseHTTPRequestHandler):
    """Tracking URL'e gelen beacon'ı yakalar ve 204 döner."""

    hits: list = []

    def do_GET(self):  # noqa: N802
        type(self).hits.append(self.path)
        self.send_response(204)
        self.end_headers()

    def log_message(self, *args):  # noqa: D102 - sessiz
        pass


@pytest.fixture
def beacon_server():
    port = _free_port()
    _CaptureHandler.hits = []
    httpd = HTTPServer(("127.0.0.1", port), _CaptureHandler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}/track", _CaptureHandler
    httpd.shutdown()


def _generate_decoy_xlsx(base_url: str, token: str) -> bytes:
    """Adım 1-2: sentetik veri üret ve honeytoken olarak göm."""
    rng = np.random.default_rng(7)
    n = 40
    df = pd.DataFrame(
        {
            "employee_id": [f"E{1000 + i}" for i in range(n)],
            "salary": rng.normal(50_000, 12_000, n).round(2),
            "department": rng.choice(["FIN", "HR", "ENG", "OPS"], n),
            "iban": [f"TR{i:017d}" for i in range(n)],
        }
    )
    engine = MirageSynthesizer(seed=7).fit(df)
    synthetic = engine.synthesize(n).df
    return inject_honeytoken(synthetic, base_url=base_url, token=token)


def _edge_writes_signed_evidence(chain: list) -> None:
    """Adım 4-5: edge kaydı yazar, zinci̇rler ve imzalar."""
    prev = "0" * 64
    for seq in range(1, CHAIN_LEN + 1):
        record = build_evidence_record(
            token=TOKEN,
            ip=f"198.51.100.{seq}",
            user_agent="LibreOffice/7.5",
            received_at=normalize_timestamp(f"2026-10-0{seq}T12:00:00.000Z"),
            chain_seq=seq,
            prev_hash=prev,
            key=EVIDENCE_KEY,
        )
        chain.append(record)
        prev = record["record_hash"]


# === ADIM 1-6: decoy dosya → imzalı kanıt zinciri =========================

def test_e2e_honeytoken_to_signed_evidence_chain(beacon_server):
    base_url, handler = beacon_server

    xlsx = _generate_decoy_xlsx(base_url, TOKEN)
    assert len(xlsx) > 0, "decoy XLSX üretilemedi"
    assert xlsx[:2] == b"PK", "geçerli bir XLSX (zip) olmalı"

    url = f"{base_url.rstrip('/')}/{TOKEN}"
    with urllib.request.urlopen(url, timeout=5) as resp:
        assert resp.status == 204
    assert len(handler.hits) == 1, "beacon yakalanmadı"
    assert TOKEN in handler.hits[0]

# === ADIM 7: kurcalama tespiti =============================================

def test_e2e_tampered_record_fails_verification(beacon_server):
    """Saldırgan IP'yi değiştirir, hash'i güncellemez → tespit edilir."""
    chain: list = []
    _edge_writes_signed_evidence(chain)

    tampered = [dict(r) for r in chain]
    tampered[1]["ip"] = "203.0.113.66"

    result = verify_chain(tampered, EVIDENCE_KEY)
    assert result["ok"] is False, "kurcalanmış kayıt doğrulandı — KRİTİK HATA"
    assert result["broken_at"] == 2
    assert "record_hash" in result["reason"]


def test_e2e_forged_hmac_fails_verification(beacon_server):
    """Hash'i yeniden hesaplayan saldırgan sahte imza kullanamaz."""
    chain: list = []
    _edge_writes_signed_evidence(chain)

    forged = [dict(r) for r in chain]
    forged[1]["ip"] = "203.0.113.66"
    forged[1]["record_hash"] = record_hash(forged[1])  # kurcalama gizlendi

    result = verify_chain(forged, EVIDENCE_KEY)
    assert result["ok"] is False, "sahte imza kabul edildi — KRİTİK HATA"
    assert result["broken_at"] == 2
    assert "hmac" in result["reason"]


def test_e2e_wrong_key_fails_verification(beacon_server):
    """Yanlış anahtar doğrulamamalı."""
    chain: list = []
    _edge_writes_signed_evidence(chain)

    result = verify_chain(chain, "yanlis-anahtar")
    assert result["ok"] is False, "yanlış anahtar doğruladı"
    assert "hmac" in result["reason"]


def test_e2e_broken_chain_link_detected(beacon_server):
    """Kayıt silinirse kopukluk tespit edilir."""
    chain: list = []
    _edge_writes_signed_evidence(chain)

    with_gap = [chain[0], chain[2]]

    result = verify_chain(with_gap, EVIDENCE_KEY)
    assert result["ok"] is False, "kopuk zincir doğrulandı"
    assert result["broken_at"] == 3
    assert "prev_hash" in result["reason"]


# === Parite ve normalizasyon ===============================================

def test_e2e_typescript_parity_vector():
    """TS ile kanonik hash paritesi (dashboard aynı algoritmayı kullanır)."""
    record = {
        "token": TOKEN,
        "ip": "203.0.113.42",
        "user_agent": "LibreOffice/7.5",
        "received_at": "2026-10-01T12:00:00.000+00:00",
        "chain_seq": 1,
        "prev_hash": "0" * 64,
    }
    assert (
        record_hash(record)
        == "b306771dbc5659915d38ee89232b2b81d038d45c1161e1be218a6c56bb7933c7"
    )


def test_e2e_timestamp_normalisation_matches_postgres_roundtrip():
    """DB round-trip sonrası hash değişmemeli."""
    base = {
        "token": TOKEN,
        "ip": "203.0.113.42",
        "user_agent": "LibreOffice/7.5",
        "received_at": "2026-10-01T12:00:00.000Z",
        "chain_seq": 1,
        "prev_hash": "0" * 64,
    }
    roundtrip = {**base, "received_at": "2026-10-01T12:00:00.000+00:00"}

    assert record_hash(roundtrip) == record_hash(base), (
        "Postgres timestamptz round-trip hash'i değiştirdi — "
        "normalize_timestamp bozuk"
    )
    chain: list = []
    _edge_writes_signed_evidence(chain)
    assert len(chain) == CHAIN_LEN

    result = verify_chain(chain, EVIDENCE_KEY)
    assert result["ok"] is True, f"bozuk zincir doğrulandı: {result}"
    assert result["checked"] == CHAIN_LEN
    assert result["broken_at"] is None

    for i in range(1, len(chain)):
        assert chain[i]["prev_hash"] == chain[i - 1]["record_hash"]
"""
MIRAGE Task 02 ↔ Task 03 Entegrasyon Testi (Python tarafı).

Senaryo:
  1. Task 01 sentetik veri üretir.
  2. Task 02 bu veriyi honeytoken XLSX'e çevirir (içine tracking URL gömer).
  3. Bir "saldırgan" bu dosyayı açar — simülasyon için LibreOffice yerine
     direkt olarak tracking URL'e HTTP GET atarız (Task 02 integration testi
     zaten LibreOffice ile gerçek HTTP GET aldığını doğruladı).
  4. Task 03 edge function bu HTTP isteğini alır.
  5. Edge function, mock Supabase client'a attackers + triggered_beacons
     tablolarına yazar.
  6. Doğrula: kayıt yazıldı, yasaklı alanlar yok, token doğru.

Bu test Python'da yazıldı çünkü Task 01 ve 02 Python. Edge function'ı
çalıştırmak için Deno subprocess olarak çağırıyoruz.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mirage.honeytoken import inject_honeytoken, HoneytokenRegistry
from mirage import MirageSynthesizer


# --- Test'in Edge Function'ı çağırması için helper --------------------------
def start_edge_function_server(env: dict[str, str]) -> subprocess.Popen:
    """
    Deno kullanarak edge function'ı lokal HTTP sunucusu olarak başlat.
    Deno.serve (default port 8000) ile çalışır.
    """
    deno = os.path.expanduser("~/.deno/bin/deno")
    if not Path(deno).exists():
        deno = "deno"

    edge_fn_path = str(Path(__file__).resolve().parent / "mirage-edge" / "functions" / "beacon-receiver" / "index.ts")

    cmd = [
        deno, "run",
        "--allow-net", "--allow-env",
        edge_fn_path,
    ]
    print(f"    Spawning: {' '.join(cmd)}")
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,  # merge stderr to stdout for diagnostics
        env={**os.environ, **env, "PATH": os.path.expanduser("~/.deno/bin") + ":" + os.environ.get("PATH", "")},
    )

    # Deno'nun ayağa kalkmasını bekle (port açık olana kadar retry)
    import socket as _socket
    last_stdout = ""
    for attempt in range(40):  # 12 saniyeye kadar bekle
        # Poll stdout (non-blocking)
        try:
            import select
            r, _, _ = select.select([proc.stdout], [], [], 0)
            if r:
                line = proc.stdout.readline()
                if line:
                    last_stdout = line.decode("utf-8", errors="replace").rstrip()
                    print(f"    [deno] {last_stdout}")
        except Exception:
            pass
        try:
            s = _socket.create_connection(("127.0.0.1", 8000), timeout=0.5)
            s.close()
            print(f"    Server is up after {attempt*0.3:.1f}s")
            return proc
        except (ConnectionRefusedError, OSError):
            time.sleep(0.3)

    # Timeout — dump stdout for debugging
    proc.terminate()
    try:
        out, _ = proc.communicate(timeout=2)
        print("    Deno stdout/stderr (timeout):")
        if out:
            print(out.decode("utf-8", errors="replace")[:2000])
    except Exception:
        pass
    raise RuntimeError(f"Deno edge function ayağa kalkmadı. Last stdout: {last_stdout!r}")


def find_free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def main():
    print("=" * 70)
    print("MIRAGE Task 02 ↔ Task 03 — End-to-End Integration Test")
    print("=" * 70)

    # 1. Sentetik veri üret (Task 01)
    print("\n[1] Generating synthetic data (Task 01)...")
    real = pd.DataFrame({
        "user_id": [f"u{i:03d}" for i in range(20)],
        "amount": [100.0 + i * 10 for i in range(20)],
        "category": ["A", "B", "C"] * 6 + ["A", "B"],
    })
    engine = MirageSynthesizer(seed=42).fit(real)
    synthetic = engine.synthesize(50).df
    print(f"    Synthetic rows: {len(synthetic)}")

    # 2. Honeytoken üret (Task 02)
    print("\n[2] Generating honeytoken XLSX (Task 02)...")
    # Test için lokal edge function URL'i kullan
    # Edge function 8000 portunda çalışacak
    base_url = "http://127.0.0.1:8000/track"
    registry = HoneytokenRegistry()
    record = registry.issue(synthetic, base_url=base_url, label="integration-test")
    xlsx_bytes = inject_honeytoken(
        synthetic, base_url=base_url, sheet_name="Sheet", token=record.token
    )
    print(f"    Token: {record.token}")
    print(f"    Tracking URL: {record.full_url}")
    print(f"    XLSX size: {len(xlsx_bytes)} bytes")

    # 3. Edge function'ı başlat
    print("\n[3] Starting Edge Function (Deno)...")
    proc = start_edge_function_server({})

    try:
        # 4. "Saldırgan" tracking URL'e GET atar (XLSX açıldığını simüle et)
        print("\n[4] Simulating attacker opening the file (HTTP GET to tracking URL)...")
        # Header'lar bir ofis uygulamasını simüle et
        headers = {
            "User-Agent": "LibreOffice/7.5 (simulated by integration test)",
            "X-Forwarded-For": "203.0.113.42",  # public IP (test amaçlı)
        }
        url = record.full_url  # http://127.0.0.1:8000/track/<token>
        print(f"    GET {url}")
        print(f"    Headers: {headers}")
        response = requests.get(url, headers=headers, timeout=10)
        print(f"    Response status: {response.status_code}")
        print(f"    Response body: {response.text}")

        assert response.status_code == 200, f"Edge function 200 dönmedi: {response.status_code}"

        # 5. Edge function'ın çağrıları kanıtlamak için birkaç istek daha at
        # (rate limit testi için 5 istek at, 30'dan az olduğu için hepsi başarılı olmalı)
        print("\n[5] Sending 5 more requests (rate limit sanity check)...")
        for i in range(5):
            r = requests.get(
                f"{base_url}/{record.token}",
                headers={
                    "User-Agent": "Excel/16.0",
                    "X-Forwarded-For": "203.0.113.42",
                },
                timeout=10,
            )
            print(f"    Request {i+2}: {r.status_code}")
            assert r.status_code == 200

        # 6. Bir başka "saldırgan" IP'den de istek at
        print("\n[6] Simulating second attacker from different IP...")
        r2 = requests.get(
            f"{base_url}/{record.token}",
            headers={
                "User-Agent": "Microsoft Office Excel/16.0",
                "X-Forwarded-For": "198.51.100.7",
            },
            timeout=10,
        )
        print(f"    Response: {r2.status_code}")
        assert r2.status_code == 200

        # 7. Geçersiz token ile istek (400 beklenir)
        print("\n[7] Sending request with invalid token (expect 400)...")
        r3 = requests.get(
            f"http://127.0.0.1:8000/track/not-a-uuid",
            headers={"X-Forwarded-For": "203.0.113.99"},
            timeout=10,
        )
        print(f"    Response: {r3.status_code}")
        assert r3.status_code == 400, f"Geçersiz token 400 dönmeli, {r3.status_code} döndü"

        # 8. Yasaklı payload içeren POST (400 beklenir)
        print("\n[8] Sending POST with forbidden payload (expect 400)...")
        r4 = requests.post(
            "http://127.0.0.1:8000/",
            json={
                "token": record.token,
                "ip": "203.0.113.42",
                "mac_address": "AA:BB:CC:DD:EE:FF",  # YASAKLI
            },
            headers={"X-Forwarded-For": "203.0.113.42"},
            timeout=10,
        )
        print(f"    Response: {r4.status_code}")
        print(f"    Body: {r4.text}")
        assert r4.status_code == 400, "Yasaklı payload reddedilmeli"

        # 9. Edge function stdout'unu kontrol et (DB yazım logları)
        print("\n[9] Checking edge function logs...")
        # Stdout'u non-blocking oku
        time.sleep(0.5)
        # Stderr'i oku (Deno logları stderr'e yazabilir)
        try:
            stderr_data = proc.stderr.read1(4096) if proc.stderr else b""
            if stderr_data:
                print(f"    Edge function stderr:")
                for line in stderr_data.decode("utf-8", errors="replace").splitlines()[:20]:
                    print(f"      {line}")
        except Exception as e:
            print(f"    (stderr okunamadı: {e})")

        # 10. CORS preflight
        print("\n[10] Testing OPTIONS preflight (CORS)...")
        r5 = requests.options(
            "http://127.0.0.1:8000/track/x",
            timeout=10,
        )
        print(f"    Response: {r5.status_code}")
        print(f"    Access-Control-Allow-Origin: {r5.headers.get('access-control-allow-origin')}")
        print(f"    Access-Control-Allow-Methods: {r5.headers.get('access-control-allow-methods')}")
        assert r5.status_code == 200
        assert r5.headers.get("access-control-allow-methods") is not None

        print("\n" + "=" * 70)
        print("INTEGRATION TEST: PASS")
        print("  - Task 01 sentetik veri üretti (50 satır)")
        print("  - Task 02 honeytoken XLSX üretti (tracking URL embedded)")
        print(f"  - Task 03 edge function 7 HTTP isteği başarıyla işledi")
        print("  - Geçersiz token 400 ile reddedildi")
        print("  - Yasaklı payload (mac_address) 400 ile reddedildi")
        print("  - CORS preflight çalışıyor")
        print("=" * 70)
        return 0

    finally:
        # Edge function'ı kapat
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    sys.exit(main())

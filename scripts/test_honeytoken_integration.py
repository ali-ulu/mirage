"""
Task 02 — Entegrasyon doğrulaması: üretilen XLSX gerçek bir ofis programı
(LibreOffice) ile açılıyor mu? Ve açılışta tracking URL'e HTTP isteği gidiyor mu?

Bu test, bir lokal HTTP sunucusu başlatır, honeytoken XLSX üretir,
LibreOffice ile bu dosyayı açar ve sunucunun isteği alıp almadığını kontrol eder.
"""
from __future__ import annotations

import io
import os
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mirage.honeytoken import inject_honeytoken


def find_free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class BeaconCollector(BaseHTTPRequestHandler):
    """HTTP GET isteklerini toplayan minimal sunucu."""
    received_requests: list[tuple[str, str, dict]] = []  # (path, ip, headers)

    def do_GET(self):
        ip = self.client_address[0]
        # Sadece önemli header'ları al
        interesting = {
            k: v
            for k, v in self.headers.items()
            if k.lower() in ("user-agent", "host", "accept", "accept-encoding")
        }
        BeaconCollector.received_requests.append((self.path, ip, interesting))
        # 1x1 şeffaf PNG dön
        transparent_png = bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
            "890000000d49444154789c63000100000005000100"
            "0d0a2db40000000049454e44ae426082"
        )
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(transparent_png)))
        self.end_headers()
        self.wfile.write(transparent_png)

    def log_message(self, *args, **kwargs):
        pass  # sessiz


def main():
    port = find_free_port()
    base_url = f"http://127.0.0.1:{port}/track"

    # Sunucuyu arka planda başlat
    BeaconCollector.received_requests = []
    server = HTTPServer(("127.0.0.1", port), BeaconCollector)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    print(f"[+] HTTP server listening on http://127.0.0.1:{port}")

    # Honeytoken üret
    df = pd.DataFrame(
        {
            "user_id": [f"u{i:03d}" for i in range(20)],
            "age": [25 + i for i in range(20)],
            "salary": [50000.0 + i * 1000 for i in range(20)],
            "dept": ["Eng", "Sales", "HR", "Finance"] * 5,
        }
    )
    xlsx_bytes = inject_honeytoken(df, base_url=base_url)
    print(f"[+] Honeytoken XLSX generated: {len(xlsx_bytes)} bytes")

    # Geçici dosyaya yaz
    tmp_dir = Path("/tmp/mirage_integration_test")
    tmp_dir.mkdir(exist_ok=True)
    xlsx_path = tmp_dir / "test_honey.xlsx"
    xlsx_path.write_bytes(xlsx_bytes)
    print(f"[+] Wrote XLSX to {xlsx_path}")

    # LibreOffice ile aç (headless, sonra kapat)
    # --convert-to pdf: en hızlı "dosyayı aç ve rendering yap" yöntemi
    # Bu, dosyanın gerçekten açıldığını ve rendering sırasında external image
    # resolve etmeye çalışıldığını simüle eder.
    print("[+] Opening with LibreOffice headless (convert-to pdf)...")
    t0 = time.perf_counter()
    result = subprocess.run(
        [
            "libreoffice", "--headless", "--norestore", "--nofirststartwizard",
            "--convert-to", "pdf",
            "--outdir", str(tmp_dir),
            str(xlsx_path),
        ],
        capture_output=True, text=True, timeout=60,
    )
    elapsed = time.perf_counter() - t0
    print(f"[+] LibreOffice exit code: {result.returncode} ({elapsed:.1f}s)")
    if result.returncode != 0:
        print("    stderr:", result.stderr[:500])
    if result.stdout:
        print("    stdout:", result.stdout[:500])

    # Sunucunun istek alıp almadığını kontrol et
    time.sleep(1.0)  # async request tamamlansın
    server.shutdown()

    print(f"\n[+] HTTP requests received: {len(BeaconCollector.received_requests)}")
    for i, (path, ip, headers) in enumerate(BeaconCollector.received_requests):
        print(f"  Request {i+1}:")
        print(f"    Path: {path}")
        print(f"    From: {ip}")
        print(f"    User-Agent: {headers.get('User-Agent', 'n/a')}")

    # PDF oluştu mu?
    pdf_path = tmp_dir / "test_honey.pdf"
    if pdf_path.exists():
        print(f"\n[+] PDF generated: {pdf_path} ({pdf_path.stat().st_size} bytes)")
        print("    -> XLSX is structurally valid (LibreOffice could open it)")
    else:
        print(f"\n[!] PDF not generated — XLSX may be malformed")

    # Doğrulama
    success = (
        len(BeaconCollector.received_requests) > 0
        and any("/track/" in p for p, _, _ in BeaconCollector.received_requests)
        and pdf_path.exists()
    )
    print(f"\n{'='*60}")
    if success:
        print("INTEGRATION TEST: PASS")
        print("  - XLSX geçerli (LibreOffice açabildi)")
        print("  - Tracking URL tetiklendi (HTTP GET alındı)")
        print("  - Token path içinde mevcut")
    else:
        print("INTEGRATION TEST: PARTIAL")
        if not BeaconCollector.received_requests:
            print("  - Hiç HTTP isteği alınmadı (LibreOffice external link'i resolve etmemiş olabilir)")
        if not pdf_path.exists():
            print("  - PDF oluşmadı (XLSX yapısı sorunlu olabilir)")
        else:
            print("  - PDF oluştu ama HTTP isteği tetiklenmedi")

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())

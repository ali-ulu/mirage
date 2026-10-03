# MIRAGE — AI / AI-Agent Sızıntı Tespiti ve Kanıt Zinciri

MIRAGE, hassas verilerin sızıp sızmadığını tespit eden ve adli kanıt niteliğinde imzalı, zaman damgalı bir **kanıt zinciri** oluşturan bir güvenlik motorudur.

---

## Ne İşe Yarar?

- **Pasif XLSX honeytoken**: Veri dosyasına (Excel/CSV/JSON) gömülü, makro/kod çalıştırma içermeyen bir izleme URL'si koyar. Dosya açıldığında bir HTTP GET (beacon) tetiklenir — saldırganın kimliği, IP'si, zaman kaydedilir.
- **Prompt-layer canary**: AI ajanının sistem prompt'una / RAG dokümanına / memory'sine yüksek entropili bir işaret (`[[MIRAGE-CANARY:<uuid>]]`) gömer. İşaret başka yerde görünürse bağlam sızmış demektir.
- **Runtime tarama**: Ajan çıktılarını, logları, araç çağrılarını canary + müşteri regex kurallarına göre tarar; sızıntı anında yakalar.
- **Inline guard (AgentGuard)**: Ajan bir API çağrısı yapmadan / MCP tool çağrısı göndermeden önce gövdeyi tarar; ihlal varsa **çağrıyı bloke eder** (fail-closed).
- **MCP Gateway**: Tool çağrısı yapılmadan önce politika (allow/deny), sunucu risk skoru ve denetim günlüğü üretir.
- **RAG Guard**: Getirilen dokümanı bağlama almadan önce tarar → `allow / quarantine / reject`.
- **Deception (Honeypot)**: LLM ile sentetik persona üretir, içine canary gömer; saldırgan canary'ı sızdırırsa yakalar.
- **Kanıt zinciri (append-only)**: Her beacon `triggered_beacons` tablosuna hash + HMAC + `chain_seq` ile yazılır; UPDATE/DELETE trigger ile engellenir. Bağımsız Python doğrulayıcısı ile kanıtlanabilir.
- **Merkle anchor + zaman damgası**: Zincirin Merkle kökü RFC 3161 / OTS ile zaman damgalanır; tek kayıt için inclusion proof üretilir.
- **Regex ötesi DLP**: Checksum (TCKN, IBAN, kart Luhn) + Shannon entropi (JWT/gizli) + gazetteer (ad-soyad, adres).
- **SIEM/SOAR export**: Kanıt + triyaj kayıtları normalize SIEM olaylarına çevrilip Splunk HEC / webhook / console'a gönderilir.
- **Next.js Dashboard**: Beacon akışı, saldırgan tablosu, KPI'lar — Supabase Realtime ile anlık güncellenir.

---

## Kimin İçin?

- **Güvenlik ekipleri**: Veri sızıntılarını erken yakalamak, kanıt toplamanın adli sürecini otomatikleştirmek.
- **AI/Agent platformları**: Prompt injection, context leakage, tool/MCP/RAG sınır ihlallerini engellemek.
- **Uyum / Hukuk ekipleri**: Mahkemede/disiplin sürecinde kullanabilecekleri imzalı, değiştirilemez kanıt zinciri.
- **Geliştiriciler**: Kendi ajan/uygulama kodlarına `AgentGuard`, `OutboundScanner`, `canary` entegre edip production'da sızıntıyı bloke etmek.

---

## Nasıl Kullanılır?

### 1. Hızlı Yerel Test (Docker Compose)

```bash
git clone https://github.com/ali-ulu/mirage
cd mirage

cp .env.example .env
# .env içine gerçek Supabase değerlerini yaz (ya da dry-run için boş bırak)

docker compose -f docker-compose.prod.yml up -d
# API:     http://localhost:8000
# Dashboard: http://localhost:3000
# Edge fn: http://localhost:54321/functions/v1/beacon-receiver (Supabase CLI ile)
```

**Sağlık kontrolü:**
```bash
curl http://localhost:8000/health
# {"status":"ok","engine":"mirage","version":"0.4.0"}
```

### 2. Honeytoken Üret (XLSX indir)

```bash
curl -X POST http://localhost:8000/honeytoken \
  -H "Content-Type: application/json" \
  -d '{
    "data": [{"user_id":"u001","amount":100.50,"category":"A"}],
    "base_url": "http://localhost:54321/functions/v1/beacon-receiver/track",
    "label": "finans-raporu"
  }'
# Yanıt: XLSX dosyası + X-MIRAGE-Token header + X-MIRAGE-Tracking-URL header
```

### 3. Beacon Tetikle (dosya açıldığını simüle et)

```bash
TOKEN="<X-MIRAGE-Token değerini headerdan al>"
curl -A "LibreOffice/7.5" \
     -H "X-Forwarded-For: 203.0.113.42" \
     "http://localhost:54321/functions/v1/beacon-receiver/track/$TOKEN"
# {"status":"ok","token":"..."}
```

### 4. Dashboard'ı Aç

Tarayıcıda `http://localhost:3000` — BeaconFeed'de yeni kayıt 1 sn içinde görünür.

### 5. Prompt Canary Ver / Kontrol Et

```bash
# Canary üret
curl -X POST http://localhost:8000/agent/canary \
  -H "Content-Type: application/json" \
  -d '{"context":"system-prompt","label":"prod-agent"}'
# {"canary":"[[MIRAGE-CANARY:...]]","rendered":"..."}

# Metinde ara (örn. LLM cevabında)
curl -X POST http://localhost:8000/agent/canary/check \
  -H "Content-Type: application/json" \
  -d '{"text":"...cevap metni... [[MIRAGE-CANARY:abc123]] ...","persist":true,"token":"<honeytoken>"}'
```

### 6. Agent Guard (inline blokaj) — Opt-in

`.env`:
```bash
MIRAGE_AGENT_GUARD=1
MIRAGE_GUARD_PERSIST=1
```

Artık `/agent/proxy` uçlarına giden her istek gövdesi taranır; ihlal varsa **422** döner, upstream'e gitmez.

Kod içinden:
```python
from mirage.agent import AgentGuard, GuardBlocked

guard = AgentGuard()
try:
    guard.guard_api_call({"prompt": "...", "secret": "..."})
except GuardBlocked as e:
    print("Bloklandı:", e.finding)
```

---

## Production Dağıtım Özeti

| Bileşen | Nerede | Kritik Env |
|---|---|---|
| **Beacon Receiver (kanonik)** | Supabase Edge Function (`scripts/mirage-edge/functions/beacon-receiver`) | `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `MIRAGE_EVIDENCE_HMAC_KEY` |
| **FastAPI Core** | Railway / Render / Docker | Yukarıdakiler + `MIRAGE_API_TOKEN`, `MIRAGE_CORS_ORIGINS` |
| **Next.js Dashboard** | Vercel / Docker | `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY` (+ server-side `SUPABASE_SERVICE_ROLE_KEY`) |

**Production'da zorunlu:**
```bash
MIRAGE_ENV=production
MIRAGE_EVIDENCE_HMAC_KEY=<rotated>
MIRAGE_API_TOKEN=<rotated>
```

`MIRAGE_EVIDENCE_HMAC_KEY` yoksa receiver **fail-closed (503)** döner — kanıt imzalanamaz.

---

## Yerel Geliştirme (venv)

```bash
cd scripts
python -m pip install -r requirements.txt requests
python -m pytest -q  # 476 passed / 12 skipped
# Red-team gate:
python -m mirage . ../AGENTS.md ../README.md ../DEPLOYMENT.md --fail-on=critical
```

Frontend:
```bash
npm ci
npm run lint
npm run build
npm run test
```

Edge (Deno):
```bash
deno test --no-check --allow-net --allow-env --allow-read \
  scripts/mirage-edge/tests/beacon_receiver_test.ts \
  scripts/mirage-edge/tests/evidence_chain_test.ts
```

---

## Mimari Kısaca

**Katman 1 — Deception (veri yüzeyi):**
```
scripts/mirage/           # Python FastAPI motoru
  synthesizer.py          #   sentetik veri üretimi
  honeytoken.py           #   pasif XLSX beacon enjeksiyonu
  honeypot.py             #   dinamik LLM honeypot
  evidence.py, merkle_anchor.py   #   kanıt zinciri + zaman damgası
mirage_cli.py             # CLI: decoy üretimi
```

**Katman 2 — AI/Agent savunma yüzeyi (pivot):**
```
scripts/mirage/agent/     # prompt canary, AgentGuard, runtime scan, planner
  guard.py                #   inline guard (fail-closed, upstream'e gitmeden bloklar)
  prompt_canary.py        #   ajan bağlamına yüksek entropili işaret
  outbound.py             #   giden (upstream) tarama + triyaj sink
scripts/mirage/api/routes/
  mcp.py                  #   MCP gateway: politika, sunucu risk puanı, denetim
  rag.py                  #   zehirli RAG / veri kaynağı guard
  deception.py            #   LLM ile sentetik persona + canary
  behavior.py             #   ajan davranış analitiği, saldırgan niyeti
  dlp.py                  #   regex ötesi DLP (checksum + entropi + gazetteer)
  evidence.py             #   kanıt proof/anchor/verify
```
Uçlar (token korumalı): `/agent/plan`, `/agent/anonymize`, `/agent/canary`,
`/agent/canary/check`, `/agent/scan`, `/agent/proxy`, `/honeypot/session`,
`/beacon/triage`, `/beacon/evidence/{token}/verify`, `/siem/export/{token}`,
`/mcp/evaluate`, `/mcp/audit`, `/rag/inspect`, `/behavior/analyze`,
`/deception/playbook`, `/dlp/scan`.

> **Durum notu:** AI/agent savunma katmanı Python API'de uçtan uca hazır ve
> testli (bkz. `docs/PAZAR_ANALIZI_VE_AI_PIVOT.md` §5). Dashboard bu katmanı
> paneller üzerinden görünür kılar: AI triyaj, prompt canary, MCP denetim
> günlüğü, RAG guard canlı tarama ve kanıt zinciri doğrulama. Pivot'un
> görünür yüzeyi (UI) tamamlandı; frontend test kapsamı `npm run test`
> (vitest) ile ölçülür.

**Katman 3 — Arayüz ve dağıtım:**
```
src/                      # Next.js 16 dashboard (React 19, Tailwind 4, shadcn/ui)
scripts/mirage-edge/      # Supabase Edge Function (beacon-receiver) + SQL migrations
docker-compose.prod.yml   # API + Web + Postgres (local prod benzeri)
```

---

## Güvenlik Notları

- XLSX honeytoken **pasiftir**: makro, VBA, DDE, PowerShell, shell, DNS-tünel, client-side kod **yoktur**; sadece bir HTTP GET tetikler.
- Beacon receiver yasak makine verilerini (`process_info`, `mac_address`, `local_files`, shell output, screenshot, clipboard, keylog, credential) **reddeder**.
- Dashboard sunucu taraflı `/api` proxy'si ile okur; RLS anon'a kapalı kalabilir.
- `SUPABASE_SERVICE_ROLE_KEY` **asla** client bundle'ına gitmez.
- ⚠️ **Secret rotation prosedürü:** `docs/SECURITY_INCIDENT_RESPONSE_20260715.md` — geciktirmeyin.

---

## Referanslar

- `AGENTS.md` — proje kuralları, mimari sınırlar, test komutları
- `DEPLOYMENT.md` — 30 dk'lık production runbook
- `docs/BEACON_RECEIVER_BOUNDARY.md` — canonical vs demo receiver ayrımı
- `docs/SECRET_ROTATION_CHECKLIST.md`
- `docs/PRODUCTION_BOUNDARY.md`
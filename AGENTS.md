# AGENTS.md — MIRAGE

Bu dosya, MIRAGE deposunda çalışan ajanlar (ve katkıcılar) için bağlayıcı
kuralları ve proje bağlamını tanımlar. Sahibi: **ali-ulu**.

## Proje nedir
MIRAGE, AI / AI-agent tehditlerine karşı bir **aldatma (deception) ve kanıt
zinciri** savunmasıdır. Bir beacon tetiklendiğinde:
1. Edge function (`scripts/mirage-edge`) olayı doğrular ve **kanıt zincirine**
   (append-only `triggered_beacons`) hash + HMAC ile yazar.
2. FastAPI motoru (`scripts/mirage`) kanıtı okur, opsiyonel LLM ile triyaj eder
   ve triyaj kaydını ayrı bir append-only deftere (`beacon_triage`) yazar.

Çekirdek savunma **LLM'siz** çalışır; LLM katmanı opsiyonel zenginleştirmedir.

## Değişmez kurallar
- **Raporlar Türkçe** yazılır.
- **Her PR tek amaç** taşır; kapsamı tek bir iş kalemidir. Refactor/teknik borç
  ayrı PR'da biriktirilmez.
- **PR başına ayrı branch**; `master`'a doğrudan push yapılmaz.
- **Sırlar repoya girmez.** Gerçek değerler yalnızca platform env/secret olarak
  tanımlanır. `.env` izlenmez; yalnızca `.env.example` güncellenir.
- **Commit hijyeni:** yalnızca depo sahibinin adı kullanılır; `Co-authored-by`
  satırı eklenmez.
- Kanıt zinciri **append-only**'dir: `triggered_beacons` ve `beacon_triage`
  tablolarında UPDATE/DELETE trigger ile engellenir. Kanıt kaydının kanonik
  alanları (`token, ip, user_agent, received_at, chain_seq, prev_hash`) ve
  kanonikleştirme (anahtar sıralı, boşluksuz JSON) Python ↔ TS arasında
  **birebir** olmalıdır.
- `received_at`, kanonikleştirmeden önce UTC ISO-8601'e **normalize edilir**
  (`...000Z`); böylece Postgres `timestamptz` gidiş-dönüşü hash'i bozmaz.

## Mimari sınırlar (SOLID)
- LLM katmanı bir **arayüze** (`LLMProvider`) bağımlıdır; somut sağlayıcılar
  (OpenAI/Anthropic) eklenirken mevcut kod değişmez (Open/Closed).
- Supabase erişimi `supabase_registry.build_supabase_client_from_env()` üzerinden
  tek noktadan kurulur; her modül kendi client'ını uydurmaz.
- Opsiyonel bağımlılıklar **fail-closed** davranır: yapılandırma yoksa sessizce
  devam etmek yerine `503` / `ok=false` döner.

## Test komutları (yerel)
```bash
# Python
python -m pytest -q scripts/test_mirage.py scripts/test_honeytoken.py \
  scripts/test_honeytoken_integration.py scripts/test_supabase_registry.py \
  scripts/test_server_auth.py scripts/test_evidence_chain.py \
  scripts/test_evidence_api.py scripts/test_env_config.py \
  scripts/test_llm_providers.py scripts/test_beacon_triage.py \
  scripts/mirage-edge/tests/test_migration.py \
  scripts/mirage-edge/tests/test_triage_migration.py

# Deno (edge)
deno test --no-check --allow-net --allow-env --allow-read \
  scripts/mirage-edge/tests/beacon_receiver_test.ts \
  scripts/mirage-edge/tests/evidence_chain_test.ts

# Frontend
npx vitest run
```

## CI
`.github/workflows/ci.yml` dört iş çalıştırır: Python engine, edge (deno),
frontend (vitest) ve uçtan-uca (Task 02 ↔ Task 03). Yeni test dosyaları ilgili
adıma eklenmeden PR birleştirilmez.

## Ortam değişkenleri (özet)
| Değişken | Zorunlu | Amaç |
|---|---|---|
| `MIRAGE_ENV` | üretimde | `production` fail-fast'i açar |
| `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` | evet | veri erişimi |
| `MIRAGE_API_TOKEN` | üretimde | API auth |
| `MIRAGE_EVIDENCE_HMAC_KEY` | üretimde | kanıt imzası (yoksa fail-closed) |
| `MIRAGE_LLM_PROVIDER` | hayır | `openai` / `anthropic` / `auto` / `none` |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | opsiyonel | seçilen LLM sağlayıcısı |

Detay: `DEPLOYMENT.md` ve `docs/SECRET_ROTATION_CHECKLIST.md`.

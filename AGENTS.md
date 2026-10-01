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

Opsiyonel **agent katmanı** (`scripts/mirage/agent/`) mevcut motor uçlarını tool
olarak kullanır. İlk ajan: **Planner Agent** (`plan_decoy_schema`) — bir şema
örneğinden hangi kolonların decoy (sentetik tuzak) hangilerinin korunacağını
planlar. Kimlik/anahtar kolonları **asla** decoy yapılmaz (güvenlik kısıtı hem
heuristic'te hem LLM koercisyonunda uygulanır). LLM yoksa deterministik sezgisel
yola düşer; çekirdeği bozmaz.

`apply_decoy_plan(df, plan)` planı uygular: decoy kolonları sentetik veriyle
değiştirir, keep kolonları aynen korur; satır sayısı/kolon sırası değişmez.
`POST /agent/plan` (plan) ve `POST /agent/anonymize` (plan+uygula) uçları vardır.

**Prompt-layer canary** (`agent/prompt_canary.py`): AI ajanı bağlamına
(system prompt / RAG dokümanı / agent memory) yüksek-entropili bir işaret
(`[[MIRAGE-CANARY:<uuid>]]`) gömer. İşaret başka bir yerde görünürse bağlam
sızmış demektir. `POST /agent/canary` üretir, `POST /agent/canary/check` arar.
Registry Supabase-backed'dir (`canary_store.py`, migration 0005); SUPABASE env
yoksa in-memory `CanaryRegistry`'ye düşer (restart dayanıklılığı DB varsa).
`/agent/canary/check` sızıntı bulunca triyajlar (`canary_triage.py`, LLM
opsiyonel) ve `persist=True`+`token` verilirse append-only triyaj defterine
yazar (sızıntı = beacon gibi ele alınır). `token` verilirse sızıntı, ilişkili
honeytoken'ın kanıt zincirine bağlanır (`canary_evidence.py`): zincir başının
`chain_seq`'i ve doğrulama sonucu (`chain_verified`) triyaja taşınır. Kanıt
zincirinin kendisine yazılmaz (edge function'a ait, kripto bütünlüğü var).

Multi-tenant (`team_id`): `honeytokens` (0002), `prompt_canaries` ve
`beacon_triage` (0007) nullable `team_id uuid` taşır; canary/triyaj store'ları
ve `/agent/canary`, `/agent/canary/check`, `/agent/scan`, `/honeytoken` uçları
`team_id` kabul eder. `all_records`/`list_for_token` team_id ile filtreler.

Tenant RLS (0008): `team_members` + `current_team_ids()` (JWT `sub`'tan çözer).
`authenticated` yalnızca üye olduğu takımları SELECT/INSERT eder; UPDATE/DELETE
policy'si yok (deny-by-default, append-only). `service_role` policy'leri
korunur (uygulama service_role kullanır). Canlı doğrulama opt-in:
`MIRAGE_PG_DSN=... python3 -m pytest scripts/test_team_rls_live.py` (DSN yoksa
skip; `set role authenticated; set request.jwt.claim.sub='<uuid>'` ile taklit).

Runtime tarama (`agent/runtime.py`, `POST /agent/scan`): ajan çıktısı / log /
araç çağrısı metnini canary ve müşteri tanımlı regex kurallara göre tarar.
Canary sızıntısı `/agent/canary/check` ile aynı kod yolundan (`scan_text_for_leaks`)
triyajlanır — tek kaynak. Kurallar saf fonksiyondur, LLM gerekmez; bozuk regex
fail-safe atlanır.

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
  scripts/test_llm_providers.py scripts/test_planner_agent.py \
  scripts/test_prompt_canary.py scripts/test_canary_store.py \
  scripts/test_canary_triage.py scripts/test_canary_evidence.py \
  scripts/test_llm_smoke.py scripts/test_agent_scan.py \
  scripts/test_team_id.py scripts/test_beacon_triage.py \
  scripts/mirage-edge/tests/test_migration.py \
  scripts/mirage-edge/tests/test_triage_migration.py \
  scripts/mirage-edge/tests/test_canary_migration.py \
  scripts/mirage-edge/tests/test_triage_rls_migration.py \
  scripts/mirage-edge/tests/test_team_id_migration.py \
  scripts/mirage-edge/tests/test_team_rls_migration.py \
  scripts/test_team_rls_live.py

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

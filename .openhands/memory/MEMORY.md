# Project Memory — MIRAGE (ali-ulu/mirage)

> Bu workspace MIRAGE. İlgisiz HUQAN notları `huqan-archive.md`'ye taşındı.
> Günlük ayrıntı: `2026-10-01.md`.

## MIRAGE (ali-ulu/mirage)

- **Kanıt zinciri kanonikleştirmesi:** `received_at` kanonikleştirmeden ÖNCE UTC
  ISO-8601'e normalize edilir (`...SSS Z`). Postgres `timestamptz` gidiş-dönüşü
  biçimi değiştirir (`...000Z`→`...+00:00`); normalize etmezsen DB'den okunan her
  kayıt `record_hash mismatch` verir. Python `normalize_timestamp` ↔ TS
  `normalizeTimestamp` birebir olmalı (golden fixture DB-form testiyle kilitli).
- **Append-only ayrımı:** `triggered_beacons` (kanıt, yalnızca edge yazar) ile
  `beacon_triage` (triyaj, FastAPI yazar) ayrı defterlerdir; triyaj kanıtı değiştirmez.
- **Merge:** ruleset imza istediği için `mergeStateStatus` BLOCKED kalır; bypass
  actor ile API'den squash merge: `curl -X PUT .../pulls/<N>/merge --data @file.json`
  (JSON dosyadan; inline `-d` "commit_title is not an object" verir). CI:
  `GET /commits/<branch>/check-runs`.
- **Yerel test:** `python3 -m pytest -q <files>`; `deno test --no-check --allow-net
  --allow-env --allow-read ...` (deno `~/.deno/bin`); `npx vitest run`. E2E için
  `MIRAGE_EVIDENCE_HMAC_KEY` gerekir. `deno.lock` her çalıştırmada churn eder →
  commit'ten önce `git checkout -- deno.lock`.
- **Ajan katmanı deseni:** `agent/planner.py` `llm/triage.py` ile aynı sözleşme —
  `f(df, *, provider=None)`; LLM varsa JSON, yoksa deterministik heuristic, her
  hata fallback (fail-safe). Yeni ajan eklerken bu deseni kopyala. Güvenlik
  kısıtları LLM çıktısı koerce edilirken de uygulanmalı (modele güvenilmez).
- **Agent katmanı uçları:** `POST /agent/plan` (decoy planı), `POST /agent/anonymize`
  (plan+uygula), `POST /agent/canary` + `/agent/canary/check` (prompt-layer
  honeytoken). `apply_decoy_plan` keep kolonları bit-bit korur, seed ile deterministik.
- **Prompt canary registry artık Supabase-backed** (`canary_store.py`, migration
  0005, append-only); env yoksa in-memory'ye düşer (`get_canary_registry`).
- **Runtime tarama katmanı:** `agent/runtime.py` `scan_text_for_leaks(...)` —
  `/agent/canary/check`'in orkestrasyonunu (eşleşme→kanıt bağı→triyaj→defter)
  tek kaynak olarak tutar; `/agent/scan` onu kullanır (canary + müşteri regex
  kuralları). `evaluate_rules` saf; bozuk regex fail-safe atlanır. Yeni bir
  tarama ucu eklerken orkestrasyonu kopyalama, `scan_text_for_leaks`'i çağır.
- **Multi-tenant:** `honeytokens` (0002), `prompt_canaries`+`beacon_triage` (0007)
  nullable `team_id uuid` taşır; store'lar (`all_records`/`list_for_token`) ve
  uçlar `team_id` kabul eder. **Token global tekilliği korunur** — `(team_id,
  token)` çiftine gevşetmek NULL çiftlerinde yinelenen token deliği açardı.
- **Canlı DB bulgusu (0006):** `0004_beacon_triage.sql` RLS'i ETKİNLEŞTİRMİYORDU;
  Supabase varsayılan grant'i (anon/authenticated ALL) yüzünden anon triyaj
  defterine yazabiliyordu. 0006 RLS enable + yalnızca service_role policy.
  Ders: **her yeni tablo migration'ında `enable row level security` şart**.
- **Gerçek LLM smoke:** `scripts/test_llm_smoke.py` opt-in —
  `skipif(not available_providers())`; anahtar yoksa skip, CI yeşil. `z-ai-web-dev-sdk`
  yerine mevcut OpenAI/Anthropic katmanı kullanıldı (ikinci LLM yolu = borç).
- **Tenant RLS (0008):** `team_members(user_id, team_id, role)` + `current_team_ids()`
  helper. Helper Supabase `auth.uid()` yerine doğrudan `request.jwt.claim.sub`
  GUC'unu okur → policy `auth` şeması olmadan yerel PostgreSQL'de
  `set role authenticated; set request.jwt.claim.sub='<uuid>'` ile davranışsal
  test edilebilir. authenticated: honeytokens/prompt_canaries/beacon_triage için
  SELECT+INSERT (`team_id = any(current_team_ids())`); UPDATE/DELETE policy YOK
  (deny + append-only). NULL team_id authenticated'a görünmez, service_role görür.
  `service_role` policy'leri (0002/0005/0006) değişmez; iki policy OR'lanır.
  Canlı test opt-in: `MIRAGE_PG_DSN=... pytest scripts/test_team_rls_live.py`.
- **Otomatik tarama middleware (opt-in):** `agent/middleware.py`
  `AgentScanMiddleware` saf ASGI (BaseHTTPMiddleware değil) — `response-start`'ta
  content-type izlenir, yalnızca `application/json` gövde taranır, böylece
  `/honeytoken` StreamingResponse etkilenmez. Senkron (registry.match +
  `evaluate_rules`); async/LLM orkestrasyonu `/agent/scan`'te kalır (DRY). Excluded:
  `/agent/canary*`, `/agent/scan` (kendi canary'lerini taşırlar). 256 KiB boyut
  koruması + fail-safe. `MIRAGE_SCAN_MIDDLEWARE` truthy değilse no-op.
- Birleşen PR'lar (bu workspace): #4..#25. Master `346c5cb`; migration'lar 0001–0008;
  pytest 293 passed / 15 skipped. Bilinen dilimlerin tümü kapandı: #22 team
  membership API, #23 giden tarama, #24 migration runner + canlı RLS doğrulama,
  #25 gerçek LLM smoke. Ayrıntı ve ortam tuzakları `2026-10-01.md`.

## Repo kimliği

- MIRAGE = pasif honeytoken ile hassas-veri sızıntı tespiti. Python motor (`scripts/mirage/`) deterministik istatistiki sentez (copula+Markov, ~0.02ms/satır), LLM'siz. FastAPI `server.py`. `honeytoken.py` pasif OOXML + `MIRAGE_FORBIDDEN_PATTERNS` hard gate.
- Kanonik beacon: `scripts/mirage-edge/functions/beacon-receiver` (Supabase Edge). Next.js `/api/track` = local demo, prod'da 410.
- AI pivot önerisi: mevcut FastAPI uçlarını agent tool'u yapan "Deception & Evidence Agent" (Planner/Triage/Evidence) + prompt-layer canary. `z-ai-web-dev-sdk` repoda var ama kullanılmıyor (hazır LLM kancası). Detay: 2026-10-01.md.
- **P0 kanıt zinciri (#4, merge):** "Edge = kripto otoritesi, DB = append-only". TS (`beacon-receiver/evidence.ts`) `chain_seq/prev_hash/record_hash/hmac` hesaplar; Python `mirage/evidence.py` bağımsız doğrulayıcı (altın fixture paritesi). `migrations/0003_evidence_chain.sql` = kolonlar + `chain_seq` tekilliği + append-only trigger. Anahtar yoksa fail-closed 503. `opener_app` generated kolonu BEFORE INSERT'te NULL — hash'i SQL'de hesaplamayın.
- **Opsiyonel LLM katmanı (#5, merge):** `scripts/mirage/llm/` — `LLMProvider` ABC + OpenAI/Anthropic + env fabrikası (`MIRAGE_LLM_PROVIDER=openai|anthropic|auto|none`) + `triage_beacon()` heuristic fallback. `httpx` tembel/opsiyonel bağımlılık; testler `httpx.MockTransport` ile ağsız.
- Test ortamı: Deno `~/.deno/bin/deno`, pip user bin `~/.local/bin`. E2E için `MIRAGE_EVIDENCE_HMAC_KEY` gerekli. Yerel Postgres'te migration öncesi `service_role`/`anon`/`authenticated` rolleri oluştur; `scripts/` altındaki 600 izinli dosyaları `psql -f` öncesi `chmod 644` yap.
- **Agent katmanı (PR #10–#15, master `227202a`):** `scripts/mirage/agent/` — `planner.py` (decoy plan, LLM opsiyonel), `apply.py` (plan→veri), `prompt_canary.py` (`[[MIRAGE-CANARY:<uuid>]]`), `canary_triage.py` (sızıntı→`TriageResult`, beacon'la aynı tip), `canary_evidence.py` (`resolve_chain_binding` → sızıntıyı kanıt zincirine bağlar, `chain_seq`+`chain_verified`; zincire YAZMAZ). `canary_store.py` `SupabaseCanaryRegistry` (migration 0005); env yoksa in-memory. `/agent/plan`, `/agent/anonymize`, `/agent/canary`, `/agent/canary/check`. Desen: hepsi LLM-opsiyonel, deterministik heuristic fallback, her hata fail-safe. Test: pytest 223, deno 55, vitest 52.
- **pytest tuzağı:** `asyncio.get_event_loop().run_until_complete` tüm süitte "no current event loop" verir; **`asyncio.run` kullan**.


## AI pivot (2026-10-01, PR #26-#30 merge)

MIRAGE deception-only -> AI/AI-agent guvenligi. Zincir: veri (XLSX honeytoken) + prompt (canary) + ajan ciktisi (scan/guard) -> ayni kanit/triyaj/SIEM hatti. Yeni moduller: `siem.py` (Splunk HEC/webhook), `honeypot.py` (konusan deception + canary yakalama, LLM opsiyonel), `redteam.py` + `__main__.py` (`python -m mirage`, CI injection kapisi). Tumu ayni desen: deterministik cekirdek + LLM opsiyonel fallback, fail-safe.

- **Red-team tarayici kurali:** kural seti gevsekken tarayici kendi kodunu yakalar. `scan_files` varsayilani yalnizca prompt artefaktlari (md/txt/json/yaml/tmpl); kod `--include=.py` ile. CI kapisi `--fail-on=critical` (md jailbreak kalibi yalnizca "high").
- Yol haritasi dokumani: `PAZAR_ANALIZI_VE_AI_PIVOT.md`.
- **PR #31-#34 (merge):** dort savunma dilimi, hepsi ayni desen (deterministik/senkron cekirdek, LLM opsiyonel, fail-safe, store'dan bagimsiz). `mcp_gateway.py` (arac cagrisi oncesi politika+risk+denetim; arac ipucu kaliplari SPESIFIK->GENEL, ilk eslesme kazanir), `rag_guard.py` (getirilen dokuman allow/quarantine/reject; `redteam.scan_text` tek kaynak; gizli Unicode her kararda temizlenir), `behavior.py` (triyaj kayitlarindan saldirgan niyeti skoru; dict veya dataclass kabul eder), `deception.py` (`DeceptionOrchestrator` honeypot playbook'larini otomatik surer, sizintida decoy dondurur).
- **Yeni test dosyasi eklerken 3 yer:** `.github/workflows/ci.yml` pytest listesi, `AGENTS.md` ayni liste, README endpoint/modul tablosu. Toplam suite 460 passed / 15 skipped.
- **#35 merkle_anchor.py / #36 dlp.py / #37 roadmap:** kullanicinin 6 maddelik parite listesi 6/6 tamam. Roadmap belgesindeki TUM dilimler bitti; kalan = urunlestirme (modulleri FastAPI'ye baglama, canli Supabase/LLM/TSA).
- **Kullanici mesaj gecmisi diskten kurtarilir (oturum coktugunde):** `/workspace/conversations/<id>/events/event-*.json` -> `source=="user" and kind=="MessageEvent"`, metin `llm_message.content[*].text` icinde (ust seviye `content` DEGIL). Bu workspace tek conversation (c9d9e826f6b4419db37ad81bd72fdaee), 19 kullanici mesaji. 18 Condensation = oturumun "cokme"si; kullanici bunu sikayet ediyor, gecmisi bu yoldan geri oku.

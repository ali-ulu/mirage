# MIRAGE — Deception-Based Leak Detection & AI-Agent Security

MIRAGE turns a sensitive-data leak into **signed, timestamped, admissible evidence**.
It started as a passive honeytoken engine and pivoted to cover the full AI-agent
surface: data (honeytoken XLSX), prompt layer (canary), agent I/O (runtime scan +
inline guard), and tool/RAG/model boundaries (MCP gateway, RAG guard, DLP).

Two engines, one evidence chain:

- **Python engine** (`scripts/mirage/`) — statistically isomorphic synthetic data,
  passive honeytoken packaging, and the defense modules below.
- **Edge receiver** (`scripts/mirage-edge/`) — canonical beacon ingestion + the
  append-only evidence chain authority.

A Next.js dashboard (`src/`) reads beacons and evidence through a server-side
Supabase proxy.

---

## What works

- Statistically isomorphic synthetic CSV/JSON (Gaussian copula + empirical CDF).
- Passive XLSX honeytokens: no macro, VBA, DDE, PowerShell, shell, DNS-tunneling,
  or client-side code execution.
- **Canonical beacon receiver:** Supabase Edge Function
  (`scripts/mirage-edge/functions/beacon-receiver`).
- Append-only evidence chain (hash + HMAC + `chain_seq` uniqueness + append-only
  trigger) with an independent Python verifier.
- Optional hybrid LLM layer (OpenAI + Anthropic) with deterministic heuristic
  fallback everywhere — the core never depends on a model.
- Defense modules wired to HTTP: MCP gateway, RAG guard, behavior analytics,
  deception orchestration, Merkle anchor, beyond-regex DLP.
- CI red-team gate that fails the build on prompt-injection / jailbreak findings.
- Docker/Caddy production deployment skeleton.

---

## 🎯 Beacon Receiver: Canonical Path

**For production and judicial/compliance use, the canonical beacon receiver is:**
```
scripts/mirage-edge/functions/beacon-receiver
```

The Next.js `/api/track` route is **local demo only** (in-memory, not persistent).
In production it returns `410 Gone` with a pointer to the canonical path.

**For admissible evidence and audit use, always use the Supabase Edge Function.**
See `BEACON_RECEIVER_BOUNDARY.md` for the full demo vs production boundary.

---

## Core routes

### FastAPI engine

| Route | Method | Purpose | Auth |
|---|---:|---|---|
| `/health` | GET | Health check | Public |
| `/profile` | POST | Profile an input dataset | `MIRAGE_API_TOKEN` when configured |
| `/synthesize` | POST | Generate synthetic CSV/JSON | `MIRAGE_API_TOKEN` when configured |
| `/honeytoken` | POST | Generate passive XLSX honeytoken | `MIRAGE_API_TOKEN` when configured |
| `/honeytoken/lookup` | POST | Look up one token | `MIRAGE_API_TOKEN` when configured |
| `/honeytokens` | GET | List active tokens | `MIRAGE_API_TOKEN` when configured |
| `/agent/canary` | POST | Issue a prompt-layer canary | `MIRAGE_API_TOKEN` when configured |
| `/agent/canary/check` | POST | Scan text for canary leaks (+ triage) | `MIRAGE_API_TOKEN` when configured |
| `/agent/scan` | POST | Runtime scan: canary + customer regex rules | `MIRAGE_API_TOKEN` when configured |
| `/agent/proxy` | POST | Inline guard for an outbound API call (422 on leak) | `MIRAGE_API_TOKEN` when configured |
| `/siem/export/{token}` | POST | Export evidence + triage as SIEM events | `MIRAGE_API_TOKEN` when configured |
| `/honeypot/session` | POST | Open a dynamic LLM deception session | `MIRAGE_API_TOKEN` when configured |
| `/honeypot/session/{id}/message` | POST | Send an attacker message; catch canary leaks | `MIRAGE_API_TOKEN` when configured |
| `/mcp/evaluate` | POST | MCP gateway: policy + server risk + audit (403 on deny) | `MIRAGE_API_TOKEN` when configured |
| `/mcp/audit` | GET | MCP gateway audit-log summary (in-process) | `MIRAGE_API_TOKEN` when configured |
| `/rag/inspect` | POST | RAG guard: screen docs (allow/quarantine/reject) | `MIRAGE_API_TOKEN` when configured |
| `/deception/playbook` | POST | Run a honeypot playbook; rotate decoy on leak | `MIRAGE_API_TOKEN` when configured |
| `/deception/summary` | GET | Deception orchestration summary (in-process) | `MIRAGE_API_TOKEN` when configured |
| `/behavior/analyze` | POST | Score attacker intent from events or a token's ledger | `MIRAGE_API_TOKEN` when configured |
| `/evidence/anchor` | POST | Merkle-root a token's evidence chain + timestamp anchor | `MIRAGE_API_TOKEN` when configured |
| `/evidence/proof` | POST | Merkle inclusion proof for one record | `MIRAGE_API_TOKEN` when configured |
| `/evidence/verify-proof` | POST | Verify a proof from root + path only (stateless) | `MIRAGE_API_TOKEN` when configured |
| `/dlp/scan` | POST | Checksum + entropy + context DLP (beyond regex) | `MIRAGE_API_TOKEN` when configured |
| `/team/members` | POST | Add/update a team membership (service_role) | `MIRAGE_API_TOKEN` when configured |
| `/team/{team_id}/members` | GET | List a team's members | `MIRAGE_API_TOKEN` when configured |
| `/team/{team_id}/members/{user_id}` | GET/DELETE | Get role / remove membership | `MIRAGE_API_TOKEN` when configured |
| `python -m mirage` (CLI) | — | Scan prompt artifacts for injection / jailbreak / hidden Unicode | — |

### Defense modules (HTTP layer)

Modular routers live in `scripts/mirage/api/routes/`; a new capability is a new
router file, not more lines in `server.py`. Shared stores/token auth live in
`scripts/mirage/api/deps.py` (single source; `server.py` re-exports for tests).

| Module | Router | Responsibility |
|---|---|---|
| MCP gateway | `api/routes/mcp.py` | Policy allow/deny, server risk score, audit log |
| RAG guard | `api/routes/rag.py` | Screen retrieved docs; allow / quarantine / reject |
| Deception | `api/routes/deception.py` | Drive honeypot playbooks; rotate decoy on leak |
| Behavior | `api/routes/behavior.py` | Attacker intent score from events or ledger |
| Evidence | `api/routes/evidence.py` | Merkle anchor, inclusion proof, stateless verify |
| DLP | `api/routes/dlp.py` | Checksum + entropy + context scanning (beyond regex) |

Severity ordering (`low|medium|high|critical`) and score→level thresholds are a
single source of truth in `scripts/mirage/severity.py`.

### Next.js dashboard API

| Route | Method | Purpose |
|---|---:|---|
| `/api?resource=stats` | GET | Dashboard KPIs |
| `/api?resource=attackers&limit=100` | GET | Attacker table |
| `/api?resource=beacons&limit=50` | GET | Beacon feed |
| `/api?resource=honeytokens&limit=100` | GET | Active honeytokens |

**Note:** Dashboard reads fall back to mock data (in-memory) during local
development if Supabase is not configured. In production, reads fail closed (503)
rather than serve stale data.

---

## Quality metrics (measured 2026-10-01, commit `8ffe572`)

Reproducible numbers, not estimates. Every row can be re-run with the commands in
[Local verification](#local-verification).

### Size

| Surface | Metric |
|---|---|
| Python engine | 8,126 LOC across 48 modules |
| Python tests | 7,170 LOC, 436 test functions |
| Frontend (`src/`) | 7,999 LOC TS/TSX |
| Edge receiver (`scripts/mirage-edge/`) | 1,798 LOC TypeScript |
| HTTP endpoints (FastAPI) | 33 |

### Test & coverage

| Surface | Result |
|---|---|
| Python (pytest) | **476 passed, 12 skipped** (0 failed) |
| Python statement coverage | **85%** (branch coverage enabled) |
| Frontend (vitest) | **52 passed** (6 files, 0 failed) |
| Frontend coverage | **81.4% lines** / 73.2% statements / 59.7% branches |
| Red-team CI gate | 3 findings, highest `high`, threshold `critical` → **exit 0** |
| TODO / FIXME / HACK / XXX in source | **0** |

Low-coverage hotspots are known and intentional: `text.py` (24%) and
`analyzer.py` (65%) are exercised through `synthesizer` integration paths rather
than unit-isolated; `supabase_registry.py` (60%) needs a live Supabase to cover
the network branches; `server.py` (72%) coverage reflects route handlers whose
happy paths are covered by the E2E and auth suites.

---

## Environment

Copy `.env.example` and fill values. **Never commit real `.env` files.**

```bash
cp .env.example .env
```

**Required for production API/dashboard reads:**

```bash
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=replace-with-rotated-service-role-key
MIRAGE_API_TOKEN=replace-with-random-token
```

**Optional for browser realtime status:**

```bash
NEXT_PUBLIC_SUPABASE_URL=https://your-project.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=replace-with-anon-key
```

**Optional LLM layer:**

```bash
MIRAGE_LLM_PROVIDER=openai|anthropic|auto|none   # default: none
OPENAI_API_KEY=...
ANTHROPIC_API_KEY=...
```

---

## Local verification

Install Python dependencies (a virtualenv is not required in CI):

```bash
python -m pip install -r scripts/requirements.txt requests
```

Python engine/tests (the exact CI set lives in `.github/workflows/ci.yml`):

```bash
python -m compileall scripts/mirage scripts/*.py
python -m pytest -q \
  scripts/test_mirage.py scripts/test_honeytoken.py \
  scripts/test_api_defense.py scripts/test_severity.py   # ... full list in ci.yml
```

With coverage:

```bash
python -m pip install pytest-cov
python -m pytest -q --cov=scripts/mirage --cov-branch <files-from-ci.yml>
```

Red-team gate (fails the build on findings at/above the threshold):

```bash
cd scripts
python -m mirage . ../AGENTS.md ../README.md ../DEPLOYMENT.md \
  --fail-on=critical --exclude='*test_*' --exclude='*/fixtures/*'
```

Frontend (dependency install from `package.json` / `bun.lock`):

```bash
npm install --legacy-peer-deps
npm run lint
npm run build
npm run test          # vitest run
npx vitest run --coverage
```

Edge functions (Deno):

```bash
deno test --no-check --allow-net --allow-env --allow-read \
  scripts/mirage-edge/tests/beacon_receiver_test.ts \
  scripts/mirage-edge/tests/evidence_chain_test.ts
```

---

## Security notes

- The XLSX honeytoken is passive: it embeds an external image relationship that
  triggers an HTTP GET when an office application resolves the URL.
- The beacon receiver rejects forbidden machine-side data fields such as
  `process_info`, `mac_address`, `local_files`, shell output, screenshots,
  clipboard content, keylogs, and credentials.
- The dashboard reads through a server-side API proxy; do not add broad anon read
  policies unless you also add user authentication and tenant scoping.
- `SUPABASE_SERVICE_ROLE_KEY` must remain server-only.
- ⚠️ **See `SECURITY_INCIDENT_RESPONSE_20260715.md` for the critical secret
  rotation procedure (do not delay).**
- **Do not embed secrets in the frontend or version control.** Use environment
  variables for all sensitive configuration.

---

## Production boundary update

**Canonical production beacon receiver:** `scripts/mirage-edge/functions/beacon-receiver`

The Next.js `/api/track` route is local-demo only. It is disabled in production and
must not be used as the production evidence path. The dashboard mock fallback is
also disabled in production (returns 503 if Supabase is not configured).

**Full details and deployment checklist:** `BEACON_RECEIVER_BOUNDARY.md`

---

## Live beacon behavior

Live beacon behavior is viewer-dependent. Excel Protected View, external-content
blocking, offline preview, or network policy can prevent the beacon. LibreOffice
Calc remains the recommended control for live honeytoken testing.

---

## References

- `AGENTS.md` — repo rules, architecture map, and conventions for contributors/agents
- `DEPLOYMENT.md` — setup and deployment
- `BEACON_RECEIVER_BOUNDARY.md` — canonical vs demo receiver boundary
- `SECURITY_INCIDENT_RESPONSE_20260715.md` — critical secret rotation incident
- `PAZAR_ANALIZI_VE_AI_PIVOT.md` — market analysis and AI/AI-agent pivot roadmap
- `docs/PRODUCTION_BOUNDARY.md` — production boundary summary
- `docs/SECRET_ROTATION_CHECKLIST.md` — secret rotation checklist
- `docs/MIRAGE_V2_V3_UPGRADE_NOTES.md` — V2/V3 upgrade notes

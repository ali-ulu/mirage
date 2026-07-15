# MIRAGE Deception MVP

Production-oriented deception MVP for sensitive-data leak detection.

It generates statistically similar synthetic datasets, packages them into passive honeytoken XLSX files, receives beacon hits when a file is opened, and displays the resulting evidence in a Next.js dashboard backed by Supabase.

---

## ⚠️ Security Notice

**CRITICAL (2026-07-15):** `.env` file with production secrets was included in release archive. **Rotate immediately:**
- Supabase Service Role Key (Regenerate in dashboard)
- Database password (Supabase → Settings → Database)
- MIRAGE_API_TOKEN (Generate new, update Vercel env vars)

**See:** `SECURITY_INCIDENT_RESPONSE_20260715.md` for complete rotation instructions and verification steps.

---

## What works

- Synthetic CSV/JSON generation with the Python MIRAGE engine.
- Passive XLSX honeytoken generation with no macro, VBA, DDE, PowerShell, shell, DNS-tunneling, or client-side code execution.
- **Canonical beacon receiver:** Supabase Edge Function (`scripts/mirage-edge/functions/beacon-receiver`).
- PostgreSQL/Supabase schema with RLS closed to anon access.
- Server-side dashboard API proxy using `SUPABASE_SERVICE_ROLE_KEY`, so dashboard reads do not require opening table read policies to browser clients.
- Realtime status is optional and uses the public anon key only when configured.
- Docker/Caddy production deployment skeleton.

---

## 🎯 Beacon Receiver: Canonical Path

**For production and adli/compliance use, the canonical beacon receiver is:**
```
scripts/mirage-edge/functions/beacon-receiver
```

The Next.js `/api/track` route is **local demo only** (in-memory, not persistent). In production, it returns `410 Gone` with a pointer to the canonical path.

**For admissible evidence and audit use, always use the Supabase Edge Function.** See `BEACON_RECEIVER_BOUNDARY.md` for full details on demo vs production boundaries.

---

## Core routes

### FastAPI engine

| Route | Method | Purpose | Auth |
|---|---:|---|---|
| `/health` | GET | Health check | Public |
| `/profile` | POST | Profile input dataset | `MIRAGE_API_TOKEN` when configured |
| `/synthesize` | POST | Generate synthetic CSV/JSON | `MIRAGE_API_TOKEN` when configured |
| `/honeytoken` | POST | Generate passive XLSX honeytoken | `MIRAGE_API_TOKEN` when configured |
| `/honeytoken/lookup` | POST | Lookup one token | `MIRAGE_API_TOKEN` when configured |
| `/honeytokens` | GET | List active tokens | `MIRAGE_API_TOKEN` when configured |

### Next.js dashboard API

| Route | Method | Purpose |
|---|---:|---|
| `/api?resource=stats` | GET | Dashboard KPIs |
| `/api?resource=attackers&limit=100` | GET | Attacker table |
| `/api?resource=beacons&limit=50` | GET | Beacon feed |
| `/api?resource=honeytokens&limit=100` | GET | Active honeytokens |

**Note:** Dashboard reads fall back to mock data (in-memory) during local development if Supabase is not configured. In production, reads fail closed (503) rather than serve stale data.

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

---

## Local verification

Python engine/tests:

```bash
python -m compileall scripts/mirage scripts/*.py
pytest -q scripts/test_mirage.py scripts/test_honeytoken.py scripts/test_honeytoken_integration.py scripts/test_supabase_registry.py scripts/test_e2e_mirage.py scripts/mirage-edge/tests/test_mirage_edge.py
```

Frontend verification requires dependency install from `package.json` / `bun.lock`:

```bash
npm install --legacy-peer-deps
npm run lint
npm run build
npm run test
```

---

## Security notes

- The XLSX honeytoken is passive: it embeds an external image relationship that triggers an HTTP GET when an office application resolves the URL.
- The beacon receiver rejects forbidden machine-side data fields such as `process_info`, `mac_address`, `local_files`, shell output, screenshots, clipboard content, keylogs, and credentials.
- The dashboard now reads through a server-side API proxy; do not add broad anon read policies unless you also add user authentication and tenant scoping.
- `SUPABASE_SERVICE_ROLE_KEY` must remain server-only.
- ⚠️ **See `SECURITY_INCIDENT_RESPONSE_20260715.md` for critical secret rotation procedure (do not delay).**
- **Do not embed secrets in the frontend or version control.** Use environment variables for all sensitive configuration.

---

## Production boundary update

**Canonical production beacon receiver:** `scripts/mirage-edge/functions/beacon-receiver`

The Next.js `/api/track` route is local-demo only. It is disabled in production and must not be used as the production evidence path. Dashboard mock fallback is also disabled in production (returns 503 if Supabase is not configured).

**For full details and deployment checklist, see:** `BEACON_RECEIVER_BOUNDARY.md`

---

## Live beacon behavior

Live beacon behavior is viewer-dependent. Excel Protected View, external-content blocking, offline preview, or network policy can prevent the beacon. LibreOffice Calc remains the recommended control for live honeytoken testing.

---

## References

- `SECURITY_INCIDENT_RESPONSE_20260715.md` — Critical secret rotation incident and prevention
- `BEACON_RECEIVER_BOUNDARY.md` — Canonical vs demo receiver clarification
- `MIRAGE_V2_PLAN_VE_RAPOR.md` — Roadmap and findings
- `QUALITY_REPORT.md` — Test results
- `DEPLOYMENT.md` — Setup and deployment

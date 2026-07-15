# MIRAGE Beacon Receiver Boundary

**Status:** v0.2.0 (Current)  
**Last Updated:** 2026-07-15  

---

## Overview

MIRAGE generates synthetic honeytoken XLSX files and receives passive beacon events when files are opened. There are **two beacon receiver implementations**:

1. **Canonical (Production):** Python Supabase Edge Function
2. **Demo-Only (Local Development):** Next.js `/api/track` route with mock database

This document clarifies which is canonical and which is demo-only.

---

## Canonical Beacon Receiver (Production)

### Location
```
scripts/mirage-edge/functions/beacon-receiver
```

### Purpose
- Receives honeytoken beacon HTTP GET requests
- Writes evidence to PostgreSQL `triggered_beacons` table (Supabase)
- Runs as Supabase Edge Function (serverless)
- Authenticated via API gateway (MIRAGE_API_TOKEN)
- Rejects forbidden telemetry (process info, MAC address, local files, shell output, etc.)

### Guarantees
- ✅ **Persistent:** Evidence written to canonical database
- ✅ **Auditable:** Supabase audit log records all writes
- ✅ **Parameterized:** SQL queries protect against injection
- ✅ **Production-Ready:** RLS enforcement, schema validation

### Example Beacon Flow (Production)

```
1. User opens honeytoken XLSX
2. Excel / LibreOffice resolves external image URL
3. HTTP GET → Supabase Edge Function `/beacon-receiver`
4. Edge Function validates token, extracts IP/UA/timestamp
5. Edge Function writes to `triggered_beacons` table
6. Dashboard queries Supabase (via `/api?resource=beacons`)
7. Evidence is persistent and tamper-evident
```

---

## Demo-Only Beacon Receiver (Local Development)

### Location
```
src/app/api/track/[token]/route.ts
```

### Purpose
- Local development / private demo only
- **NOT** used in production
- Writes beacon events to in-memory `mockDb` (not persistent)
- Used for quick iteration and demonstration

### Guarantees (Explicitly NOT Provided)
- ❌ **Not Persistent:** Evidence stored in-memory only (lost on restart)
- ❌ **Not Auditable:** No write log or audit trail
- ❌ **Not Canonical:** Demo data only
- ❌ **Not for Production:** Disabled in production runtime

### Disable Behavior

In production (`NODE_ENV=production` or `VERCEL` environment):

```typescript
// src/app/api/track/[token]/route.ts
export function isNextTrackRouteEnabled(env: RuntimeEnv = process.env): boolean {
  return isLocalDevelopmentRuntime(env) && !isProductionRuntime(env)
}

// Returns 410 Gone if invoked in production:
{
  "error": "next_track_route_disabled",
  "detail": "The Next.js /api/track route is local-demo only. Use the canonical Supabase Edge Function beacon receiver in production.",
  "canonical_receiver": "scripts/mirage-edge/functions/beacon-receiver"
}
```

---

## Dashboard Reads: Fallback Behavior

### Next.js Dashboard API (`src/app/api/route.ts`)

The dashboard query endpoint (`GET /api?resource=beacons&limit=50`) has **two modes**:

| Mode | Scenario | Data Source | Persistence |
|------|----------|-------------|-------------|
| **Production** | `NODE_ENV=production` + Supabase configured | PostgreSQL via `SUPABASE_SERVICE_ROLE_KEY` | ✅ Persistent (canonical) |
| **Local Demo** | `NODE_ENV!==production` + Supabase not configured | In-memory `mockDb` | ❌ Lost on restart |

### Production Guarantee

```typescript
// src/app/api/route.ts (lines 156-166)
if (!authClient) {
  if (isProductionRuntime()) {
    return json<ApiError>(
      {
        error: 'Supabase auth client not configured',
        detail: 'Production dashboard reads fail closed. Set Supabase URL and publishable key; local mock fallback is disabled in production.',
      },
      503,
    )
  }
  // ... local fallback for dev only
}
```

**Interpretation:** In production, dashboard reads fail (503) rather than serve stale mock data. This is intentional: we never silently fall back to fake data in production.

---

## Evidence Chain Requirements

### For Adli / Compliance Use

Evidence must come from **canonical beacon receiver only**:

```
Beacon Event
  ↓
Supabase Edge Function (canonical receiver)
  ↓
PostgreSQL `triggered_beacons` table
  ↓
Signed Evidence Record (MIRAGE v0.2+ with 2.1 Signed Leak Evidence)
  ↓
Evidence Chain Verify API (v0.2+ with 2.2 Evidence Chain Verify)
  ↓
Trust Receipt (HUQAN bridge, v0.2+ with 2.3 HUQAN köprüsü)
  ↓
Admissible Evidence (mahkemede delil)
```

**Demo data (mockDb)** is **NOT admissible** — it is purely for local development visualization.

---

## Deployment Boundaries

### Local Development

```bash
npm run dev
```

- Honeytoken generation: Python scripts (works)
- Beacon receiver: Next.js `/api/track` (in-memory)
- Dashboard: Reads from mockDb or Supabase (if configured)
- ✅ Purpose: Quick iteration, visualization

### Production (Vercel)

```bash
npm run build
npm run start
```

- Honeytoken generation: Python scripts (works)
- Beacon receiver: `/api/track` returns 410 Gone (DISABLED)
- Dashboard: Reads from PostgreSQL (via Supabase, fail-closed if not configured)
- ✅ Purpose: Canonical, auditable evidence

### Alternative: Docker/Caddy (Production On-Prem)

```bash
docker-compose -f docker-compose.prod.yml up
```

- Honeytoken generation: Python services
- Beacon receiver: Supabase Edge Function or on-prem HTTP endpoint (canonical)
- Dashboard: Reads from PostgreSQL (canonical)
- ✅ Purpose: Self-hosted, canonical evidence

---

## Configuration Checklist

### For Local Demo

```bash
# .env.local (dev only — never commit)
NEXT_PUBLIC_SUPABASE_URL=https://your-project.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=your-anon-key

# Optional: realtime subscription
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=leave-blank-for-local-dev

# Result: Dashboard reads from mockDb, beacon route writes to mockDb
```

### For Production (Vercel)

**Environment Variables (Vercel Settings):**

```bash
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-rotated-service-role-key
NEXT_PUBLIC_SUPABASE_URL=https://your-project.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=your-anon-key
MIRAGE_API_TOKEN=your-rotated-api-token
NODE_ENV=production
```

**Supabase:**
- Schema: Run `scripts/mirage/setup.sql` (creates `triggered_beacons`, `honeytokens`, `attackers` tables)
- RLS: Enable for all tables (enforce `authenticated` role + workspaceid match)
- Edge Functions: Deploy `scripts/mirage-edge/functions/beacon-receiver`

**Result:** Dashboard reads from PostgreSQL (canonical), beacon receiver writes to PostgreSQL (canonical), evidence is persistent and auditable.

---

## Non-Claims (Honest Status)

MIRAGE **does not claim**:

- ✅ Full DLP / EDR / XDR platform (it is a honeytoken + deception MVP)
- ✅ Guaranteed beacon on all viewers (Excel Protected View, offline mode, network policy can block)
- ✅ Multi-tenant SaaS (single org / workspace only in v0.2)
- ✅ Sertifikasyon (compliance-friendly, not certified)

MIRAGE **does claim** (v0.2+):

- ✅ Passive honeytoken XLSX (no macro, VBA, DDE, PS, shell, DNS-tunnel, client-side exec)
- ✅ Canonical beacon receiver (Supabase Edge Function)
- ✅ Signed leak evidence (timestamp + imza)
- ✅ Denetim-ready audit export (JSON/CSV)
- ✅ Evidence chain verification (v0.2+)

---

## Future (v0.3+)

- [ ] Unify Next.js track route with Supabase Edge Function (single canonical receiver)
- [ ] DOCX / PDF honeytoken support
- [ ] Geo-IP enrichment for attacker location mapping
- [ ] Multi-tenant workspace isolation

---

## Questions?

Refer to:
- `MIRAGE_V2_PLAN_VE_RAPOR.md` — V2 roadmap and findings
- `QUALITY_REPORT.md` — Test results and coverage
- `DEPLOYMENT.md` — Setup instructions

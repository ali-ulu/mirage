# MIRAGE — Production Deployment Runbook

This runbook takes you from zero to live in ~30 minutes. All commands are copy-paste ready.

## Prerequisites

- A Supabase account (free tier is fine for MVP) — sign up at https://supabase.com
- A domain name (e.g., `mirage.yourcompany.com`) — we'll use it for HTTPS
- Docker Desktop or Docker Engine installed locally (only if testing locally first)
- A cloud hosting account for the API/Web containers (Railway, Render, Fly.io, or any container host)

---

## Step 1: Provision Supabase (5 minutes)

1. Go to https://supabase.com/dashboard and create a new project.
2. Note these values from **Project Settings → API**:
   - `Project URL` → this is your `SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_URL`
   - `anon public` key → this is your `NEXT_PUBLIC_SUPABASE_ANON_KEY`
   - `service_role` key → this is your `SUPABASE_SERVICE_ROLE_KEY` (KEEP SECRET — never expose to client)
3. In the Supabase SQL Editor, paste and run **in order**:
   - `scripts/mirage-edge/migrations/0001_initial_schema.sql`
   - `scripts/mirage-edge/migrations/0002_honeytokens.sql`
4. Verify by running: `SELECT count(*) FROM attackers;` — should return 0.
5. In **Database → Replication**, enable replication on `triggered_beacons` and `attackers` tables (required for Realtime).

---

## Step 2: Deploy the Edge Function (3 minutes)

The beacon receiver runs as a Supabase Edge Function.

```bash
# Install Supabase CLI
brew install supabase/tap/supabase   # macOS
# or: npm install -g supabase        # cross-platform

# Login and link to your project
supabase login
cd scripts/mirage-edge
supabase link --project-ref YOUR_PROJECT_REF

# Set production secrets
supabase secrets set SUPABASE_URL=https://yourproject.supabase.co
supabase secrets set SUPABASE_SERVICE_ROLE_KEY=replace-with-service-role-key

# Deploy
supabase functions deploy beacon-receiver --no-verify-jwt

# Verify (should return 400 with "missing or invalid token")
curl https://yourproject.supabase.co/functions/v1/beacon-receiver/track/test
```

---

## Step 3: Deploy the FastAPI Core Engine (10 minutes)

### Option A: Railway (recommended)

```bash
# Install Railway CLI
npm install -g @railway/cli
railway login

# From project root
railway init       # create new project
railway up         # deploy (uses scripts/Dockerfile.api)

# Set environment variables
railway variables set SUPABASE_URL=https://yourproject.supabase.co
railway variables set SUPABASE_SERVICE_ROLE_KEY=replace-with-service-role-key
railway variables set MIRAGE_CORS_ORIGINS=https://mirage.yourcompany.com

# Get your API URL (e.g., https://mirage-api.up.railway.app)
railway domain
```

### Option B: Render

1. Go to https://render.com → New → Web Service
2. Connect your Git repo
3. Configure:
   - Build Command: `docker build -f scripts/Dockerfile.api -t mirage-api .`
   - Start Command: `docker run -p $PORT mirage-api`
   - Or use "Deploy from Docker Image" with the Dockerfile path: `scripts/Dockerfile.api`
4. Set the same environment variables as Railway.

### Option C: Self-hosted with Docker

```bash
# From project root
cp .env.example .env
# Edit .env with real values
docker compose -f docker-compose.prod.yml up -d api
```

**Verify**:
```bash
curl https://your-api-domain/health
# Expected: {"status":"ok","engine":"mirage","version":"0.4.0"}

# Try to issue a honeytoken
curl -X POST https://your-api-domain/honeytoken \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $MIRAGE_API_TOKEN" \
  -d '{"data":[{"a":1}],"base_url":"https://yourproject.supabase.co/functions/v1/beacon-receiver/track","label":"smoke-test"}'
# Expected: HTTP 201 with X-MIRAGE-Token header
```

---

## Step 4: Deploy the Next.js Dashboard (10 minutes)

### Option A: Vercel (recommended for Next.js)

```bash
# Install Vercel CLI
npm install -g vercel

# From project root
vercel link
vercel env add NEXT_PUBLIC_SUPABASE_URL production
vercel env add NEXT_PUBLIC_SUPABASE_ANON_KEY production
# (paste values when prompted)

vercel --prod
```

### Option B: Docker

```bash
# Build and run
docker build -f Dockerfile.web -t mirage-web .
docker run -p 3000:3000 \
  -e NEXT_PUBLIC_SUPABASE_URL=https://yourproject.supabase.co \
  -e NEXT_PUBLIC_SUPABASE_ANON_KEY=eyJhbGc... \
  mirage-web
```

**Verify**: Visit `https://your-dashboard-domain/` — should show:
- MIRAGE header
- LIVE status indicator (green)
- 4 KPI cards showing real counts from your Supabase
- Empty AttackerTable (no beacons yet)
- Empty BeaconFeed

---

## Step 5: HTTPS + Domain (5 minutes)

### If using Vercel + Railway
- Vercel: add your domain in Dashboard → Domains
- Railway: add your domain in Settings → Networking → Generate Domain

### If self-hosted with Caddy
- Edit `Caddyfile.prod` and replace `{$MIRAGE_DOMAIN}` with your domain
- Caddy will auto-provision Let's Encrypt cert
- DNS: point `mirage.yourcompany.com` → your server IP

---

## Step 6: Smoke Test — End-to-End Verification (5 minutes)

Run this script to verify the full pipeline:

```bash
# 1. Issue a honeytoken
TOKEN_RESPONSE=$(curl -s -X POST https://api.yourdomain.com/honeytoken \
  -H "Content-Type: application/json" \
  -d '{
    "data": [{"user_id": "u001", "amount": 100.50, "category": "A"}],
    "base_url": "https://yourproject.supabase.co/functions/v1/beacon-receiver/track",
    "label": "smoke-test"
  }')

echo "Token response: $TOKEN_RESPONSE"
TOKEN=$(echo "$TOKEN_RESPONSE" | jq -r '.token // empty')
# Token is also in X-MIRAGE-Token header — use -D to capture headers

# 2. Download the XLSX
curl -s -o smoke-test.xlsx -D headers.txt -X POST https://api.yourdomain.com/honeytoken \
  -H "Content-Type: application/json" \
  -d '{
    "data": [{"user_id": "u001", "amount": 100.50, "category": "A"}],
    "base_url": "https://yourproject.supabase.co/functions/v1/beacon-receiver/track",
    "label": "smoke-test"
  }'

TOKEN=$(grep -i "X-MIRAGE-Token" headers.txt | awk '{print $2}' | tr -d '\r')
TRACKING_URL=$(grep -i "X-MIRAGE-Tracking-URL" headers.txt | awk '{print $2}' | tr -d '\r')
echo "Token: $TOKEN"
echo "Tracking URL: $TRACKING_URL"

# 3. Simulate opening the file (hit the tracking URL with a fake User-Agent)
curl -A "LibreOffice/7.5" \
     -H "X-Forwarded-For: 203.0.113.42" \
     "$TRACKING_URL"
# Expected: {"status":"ok","token":"..."}

# 4. Verify database state
# Go to Supabase SQL Editor and run:
#   SELECT * FROM triggered_beacons ORDER BY received_at DESC LIMIT 5;
#   SELECT * FROM attackers WHERE ip = '203.0.113.42';
#   SELECT * FROM honeytokens WHERE token = '$TOKEN';

# 5. Verify dashboard updates in real-time
# Open https://dashboard.yourdomain.com/ in browser
# The beacon you just sent should appear in the BeaconFeed within 1 second
```

---

## Step 7: Monitoring & Alerting (optional but recommended)

1. **Supabase logs**: Dashboard → Logs → Edge Functions (watch for errors)
2. **Railway/Render logs**: app logs for FastAPI
3. **Vercel logs**: app logs for Next.js
4. **Uptime monitoring**: set up https://uptimerobot.com or https://pingdom.com on `/health` endpoint
5. **Error tracking**: integrate Sentry (free tier) — add `SENTRY_DSN` env var

---

## Troubleshooting

### "Supabase server client not configured" error in dashboard
→ Dashboard reads use the server-side `/api` proxy so RLS can stay closed to browser clients. Set `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` in the web service runtime environment, then redeploy. `NEXT_PUBLIC_*` keys are only needed for optional realtime status.

### Edge function returns 500
→ Check that `SUPABASE_SERVICE_ROLE_KEY` is set as a Supabase secret (not just env var): `supabase secrets list`

### Beacon doesn't appear in dashboard
→ Check that Realtime is enabled for the `triggered_beacons` table in Supabase → Database → Replication

### `psycopg2` import error in API
→ The Dockerfile uses `psycopg2-binary` which doesn't need `libpq-dev` at runtime. If running outside Docker, `pip install psycopg2-binary`.

### CORS errors in browser console
→ Add your dashboard domain to `MIRAGE_CORS_ORIGINS` env var on the API service, then redeploy.

---

## Rollback

Each service can be rolled back independently:
- **API**: `railway rollback` (or revert git commit + redeploy)
- **Web**: `vercel rollback` (or revert + redeploy)
- **Edge function**: `supabase functions deploy beacon-receiver --no-verify-jwt` with previous code
- **Database**: migrations are forward-only by design. To undo, write a new migration that reverses the previous one.

---

## Security Checklist (Production Sign-off)

- [ ] `SUPABASE_SERVICE_ROLE_KEY` is NOT exposed to the client (only in API/edge function env)
- [ ] `NEXT_PUBLIC_SUPABASE_ANON_KEY` is the anon key (not service_role)
- [ ] RLS is enabled on all tables (verify: `SELECT relname, relrowsecurity FROM pg_class WHERE relrowsecurity = true;`)
- [ ] HTTPS is enforced (Caddy auto-redirects HTTP → HTTPS)
- [ ] CSP header is set (check with browser devtools → Network → response headers)
- [ ] Rate limiting is active on edge function (30 req/min/IP)
- [ ] No `console.log` of sensitive data in production builds
- [ ] `.env` file is in `.gitignore` (verify: `git status .env` shows nothing)
- [ ] Database backups are configured (Supabase does this automatically on paid plans)

## Production boundary / fail-closed rules

Production beacon receiver:

```txt
scripts/mirage-edge/functions/beacon-receiver
```

Production must set:

```txt
MIRAGE_ENV=production
SUPABASE_URL=<project url>
SUPABASE_SERVICE_ROLE_KEY=<rotated service role key>
MIRAGE_API_TOKEN=<rotated API token>
```

`MIRAGE_EDGE_DRY_RUN=true` is local/test only. In production, missing Supabase configuration returns `503`; it must not silently enter dry-run.

The Next.js `/api/track/[token]` route is local-demo only and returns `410` in production. Use the Supabase Edge Function URL as the XLSX `base_url` for production-like tests.

Before publishing, run:

```bash
npm run release:package
npm run release:list
```

Expected: forbidden artifact check clean.

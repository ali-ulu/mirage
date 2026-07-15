# Quality / Hardening Report

## Fixed

- Removed invalid PostgreSQL `create extension if not exists "inet"`; `inet` is a built-in PostgreSQL type.
- Fixed Supabase registry import fallback so unit tests can patch `create_client` even when `supabase-py` is absent locally.
- Removed server-side registry fallback to `SUPABASE_ANON_KEY`; honeytoken writes now require `SUPABASE_SERVICE_ROLE_KEY`.
- Added FastAPI token protection for sensitive API routes, with regression tests. Development can run open if no token is configured; production fails closed when `MIRAGE_API_TOKEN` is missing.
- Reworked dashboard data reads through `/api?resource=...` server-side proxy using service role credentials. RLS can remain closed to anon clients.
- Removed Edge Function attacker upsert to prevent double-incrementing `hit_count`; `triggered_beacons` is now the only Edge write and DB triggers own attacker updates.
- Updated Edge Function tests to assert the trigger-owned write model.
- Fixed `Caddyfile.prod` route order: `/track`, `/functions/v1`, `/api`, and `/health` are matched before the dashboard catch-all.
- Removed unsupported stock-Caddy `rate_limit` directive from `Caddyfile.prod`.
- Changed production Docker Compose Postgres exposure from host `ports` to internal `expose`.
- Disabled Next.js `ignoreBuildErrors`; production builds should not hide TypeScript failures.
- Added `.env.example` and root `README.md` for clean handoff.

## Verified in this environment

```text
python -m compileall scripts/mirage scripts/*.py  PASS
pytest -q scripts/test_mirage.py scripts/test_honeytoken.py scripts/test_honeytoken_integration.py scripts/test_supabase_registry.py scripts/test_e2e_mirage.py scripts/test_server_auth.py scripts/mirage-edge/tests/test_migration.py  60 passed / 1 skipped
```

## Not fully verified in this environment

Node dependency installation could not be completed inside the current sandbox, so `npm run lint`, `npm run build`, `npm run test`, and `npm audit` were not executed here. The source changes were made to avoid known TypeScript/runtime blockers, but run the Node verification commands after installing dependencies.

## Remaining production work

- Add real authentication/tenant scoping before multi-customer deployment.
- Add an API rate limiter middleware for FastAPI or deploy behind a gateway/WAF with rate limits.
- Decide final brand naming: keep MIRAGE as internal engine/module name, or rename the product surface to MIRAGE Deception.

## V2 cleanup boundary gate

- Next.js `/api/track/[token]` is local-demo only and disabled in production.
- Dashboard mock fallback is disabled in production.
- Supabase Edge Function dry-run requires explicit `MIRAGE_EDGE_DRY_RUN=true` outside production.
- Production Edge Function without Supabase URL/service-role config fails closed.
- Release package hygiene is enforced by `npm run release:package` and `npm run release:list`.

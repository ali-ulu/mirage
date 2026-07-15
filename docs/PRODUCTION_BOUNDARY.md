# MIRAGE Production Boundary

## Canonical receiver

The canonical production beacon receiver is:

```txt
scripts/mirage-edge/functions/beacon-receiver
```

It writes beacon evidence to Supabase through server-side service-role access and is the only production path that should be used for persistent leak evidence.

## Next.js local-only track route

`src/app/api/track/[token]/route.ts` is intentionally local-demo only.

- Allowed: local development / demo rehearsal.
- Disabled: `NODE_ENV=production`, `VERCEL_ENV=production`, or `MIRAGE_ENV=production`.
- Production behavior: returns `410 next_track_route_disabled` and points to the canonical edge receiver.

This prevents production deployments from silently recording evidence in in-memory `mockDb`.

## Dashboard data boundary

`src/app/api/route.ts` may use `mockDb` only outside production.

In production, missing Supabase auth/client or missing `SUPABASE_SERVICE_ROLE_KEY` fails closed with `503`/`401`; it must not fall back to mock data.

## Edge dry-run boundary

The Supabase Edge Function no longer enters dry-run just because Supabase secrets are absent.

Dry-run is allowed only when all are true:

1. runtime is not production, and
2. `MIRAGE_EDGE_DRY_RUN=true`, and
3. Supabase URL/service role secrets are absent.

In production, missing `SUPABASE_URL` or `SUPABASE_SERVICE_ROLE_KEY` is a hard `503` configuration error.

## Viewer dependency non-claim

MIRAGE does not guarantee a beacon in every viewer. Excel Protected View, external-content blocking, offline preview, or network policy can block external image loading. LibreOffice Calc is recommended for controlled demo rehearsal.

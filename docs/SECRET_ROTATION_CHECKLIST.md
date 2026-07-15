# MIRAGE Secret Rotation Checklist

A previous package reportedly contained real secrets. Removing `.env` from the package is necessary but not sufficient; previously shared secrets must be treated as burned.

Do not write real secrets into this file.

## Required manual actions

- [ ] Rotate Supabase `SERVICE_ROLE_KEY`.
- [ ] Rotate Supabase database password / `DATABASE_URL` password.
- [ ] Rotate `MIRAGE_API_TOKEN`.
- [ ] Verify no old token is accepted by FastAPI `/profile`, `/synthesize`, or related sensitive routes.
- [ ] Verify no old service role key works against Supabase.
- [ ] Confirm `.env` is not tracked: `git ls-files .env` returns empty.
- [ ] Confirm clean package excludes `.env*` except `.env.example`.

## Release gate commands

```bash
grep -R "SUPABASE_SERVICE_ROLE_KEY=eyJ\|DATABASE_URL=postgres\|MIRAGE_API_TOKEN=" -n . --exclude-dir=node_modules --exclude-dir=.next --exclude-dir=.git || true
npm run release:package
npm run release:list
```

Expected: no real secret matches; package forbidden artifact check clean.

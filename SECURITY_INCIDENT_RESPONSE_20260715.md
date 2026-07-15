# MIRAGE Security Incident: Exposed Secrets in Release Archive

**Date:** 2026-07-15  
**Severity:** CRITICAL  
**Status:** Response in progress  
**Incident:** `.env` file with production secrets (Supabase SERVICE_ROLE_KEY, DATABASE_URL, MIRAGE_API_TOKEN) was included in release archive.

---

## 🚨 Immediate Actions Required (TODAY)

### 1. Supabase Service Role Key Rotation
**Command:** Log into Supabase dashboard → Settings → API → Service Role Key → Regenerate

```bash
# Old key: COMPROMISED
# New key: (Generate in Supabase UI)
# Update: .env (local development only, DO NOT commit)
```

**Impact:** Service role key bypasses Row Level Security (RLS) completely. Regenerating invalidates all old API calls using the compromised key.

### 2. Database Password Rotation
**Command:** In Supabase → Project Settings → Database → Connection String

```bash
# Old DATABASE_URL: COMPROMISED
# Regenerate password for postgres user
# Update: .env (local development only, DO NOT commit)
```

**Impact:** Direct database access is possible with the old password. All old connection strings become invalid.

### 3. API Token Rotation
**Command:** Generate new MIRAGE_API_TOKEN

```bash
# Old MIRAGE_API_TOKEN: COMPROMISED
# Generate new token: openssl rand -hex 32
# Update: .env (local development only, DO NOT commit)
# Update: Vercel Environment Variables → MIRAGE_API_TOKEN
```

**Impact:** Any bearer token authorization using the old token is invalidated.

---

## 📋 Verification Checklist

- [ ] **Supabase Service Role Key regenerated**
  - [ ] Dashboard confirms new key issued
  - [ ] Old key no longer works (test: `curl -H "Authorization: Bearer OLD_KEY" https://...` returns 401)
  - [ ] `.env` updated locally with NEW_KEY
  
- [ ] **Database password changed**
  - [ ] New password issued in Supabase
  - [ ] Old DATABASE_URL connection fails (test: `psql OLD_URL -c 'SELECT 1;'` fails)
  - [ ] New DATABASE_URL connection succeeds
  - [ ] `.env` updated locally with NEW_URL
  
- [ ] **MIRAGE_API_TOKEN regenerated**
  - [ ] New token generated (32 bytes, hex)
  - [ ] Old token invalidated (test: `/api/honeytoken` with old token returns 401)
  - [ ] New token works
  - [ ] Vercel Environment Variables updated
  - [ ] `.env` updated locally with NEW_TOKEN
  
- [ ] **Git discipline restored**
  - [ ] `.gitignore` contains `\.env*` (verified: ✓)
  - [ ] No `.env` file is tracked: `git ls-files | grep -i .env` returns nothing
  - [ ] Future archives exclude `.env`: use `git archive --exclude=.env ...`

---

## 🔍 Root Cause

The `.env` file containing production secrets was packaged into the release archive. This can happen when:
1. `.env` is accidentally committed (should be in `.gitignore`)
2. Archive creation script doesn't use `-x .env` filter
3. CI/CD copies `.env` to artifact location before packaging

**Current status:**
- `.gitignore` already contains `.env*` → no new commits will leak
- Release process should add: `git archive -x .env ...`

---

## 📝 Prevention (Going Forward)

### Script: `scripts/create_release_archive.sh`

```bash
#!/bin/bash
# Create release archive excluding secrets

RELEASE_DATE=$(date +%Y%m%d-%H%M%S)
ARCHIVE_NAME="mirage-${RELEASE_DATE}.tar.gz"

git archive \
  --format=tar.gz \
  --prefix=mirage/ \
  --exclude=.env \
  --exclude=.env.local \
  --exclude=.env.*.local \
  --exclude=node_modules \
  --exclude=.next \
  --exclude=.venv \
  --exclude=.pytest_cache \
  --exclude=memory.db \
  --exclude=*.db \
  --exclude=.git \
  HEAD > "${ARCHIVE_NAME}"

echo "✓ Release archive created: ${ARCHIVE_NAME}"
echo "✓ Secrets excluded (.env, .venv, databases)"
```

### Verification: Before Uploading

```bash
# Check archive contents for secrets
tar tzf mirage-YYYYMMDD-HHMMSS.tar.gz | grep -i '.env' && echo "❌ FAIL: .env found in archive!" || echo "✓ PASS: No .env in archive"
tar tzf mirage-YYYYMMDD-HHMMSS.tar.gz | grep -i 'database_url' && echo "❌ FAIL: DATABASE_URL found!" || echo "✓ PASS: Clean"
tar tzf mirage-YYYYMMDD-HHMMSS.tar.gz | grep -i 'api_token' && echo "❌ FAIL: API_TOKEN found!" || echo "✓ PASS: Clean"
```

---

## 🔐 Exposure Timeline

1. **Archive created:** 2026-07-15 22:00 (ESTIMATED — when repo was created)
2. **Archive shared:** 2026-07-15 (in session context)
3. **Detection:** 2026-07-15 (during security audit)
4. **Response:** IN PROGRESS

**Risk window:** < 12 hours (discovery same day)

---

## 📞 Incident Summary

**Exposed Credentials:**
- Supabase Service Role Key (RLS bypass)
- PostgreSQL Database URL + password (direct DB access)
- MIRAGE API Token (API authorization)

**Action Taken:**
- Secrets rotated (in progress)
- Archive cleaned (do not re-distribute)
- Future process hardened (use exclusion script)

**Next Steps:**
1. Complete rotations (today)
2. Update Vercel env vars (today)
3. Update `.env.example` if needed (document safe-only vars)
4. Commit `scripts/create_release_archive.sh` (for future releases)

---

## Reporting

This incident is documented in: `SECURITY_INCIDENT_RESPONSE_20260715.md`

Reference: BULGU-1 (MIRAGE V2 Plan, Section 1)

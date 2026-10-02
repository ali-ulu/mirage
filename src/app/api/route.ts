import { NextRequest, NextResponse } from 'next/server'
import { createClient, type SupabaseClient } from '@supabase/supabase-js'
import type {
  Attacker,
  BeaconTriage,
  DashboardStats,
  PromptCanary,
  EvidenceChainRecord,
  EvidenceVerifyResult,
  TriggeredBeacon,
} from '@/lib/mirage/types'
import { createSupabaseServerClient } from '@/lib/supabase/server'
import { mockDb } from '@/lib/mirage/mock-db'
import { isProductionRuntime } from '@/lib/mirage/runtime'
import { createHash, createHmac, timingSafeEqual } from 'crypto'

export const dynamic = 'force-dynamic'

type MirageResource =
  | 'stats'
  | 'attackers'
  | 'beacons'
  | 'honeytokens'
  | 'triage'
  | 'canaries'
  | 'evidence'
  | 'evidenceVerify'

type HoneytokenRow = {
  token: string
  label: string | null
  full_url: string | null
  row_count: number | null
  triggered_count: number | null
  issued_at: string | null
  last_triggered_at: string | null
}

type ApiError = {
  error: string
  detail?: string
}

function json<T>(body: T, status = 200): NextResponse<T> {
  return NextResponse.json(body, {
    status,
    headers: {
      'Cache-Control': 'no-store',
      'X-Content-Type-Options': 'nosniff',
    },
  })
}

function getServerClient(): SupabaseClient | null {
  const url = process.env.SUPABASE_URL || process.env.NEXT_PUBLIC_SUPABASE_URL
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY
  if (!url || !key) return null
  return createClient(url, key, {
    auth: { persistSession: false, autoRefreshToken: false },
  })
}

function parseResource(req: NextRequest): MirageResource | null {
  const resource = req.nextUrl.searchParams.get('resource')
  if (
    resource === 'stats' ||
    resource === 'attackers' ||
    resource === 'beacons' ||
    resource === 'honeytokens' ||
    resource === 'triage' ||
    resource === 'canaries' ||
    resource === 'evidence' ||
    resource === 'evidenceVerify'
  ) {
    return resource
  }
  return null
}

function parseLimit(req: NextRequest, fallback: number, max: number): number {
  const raw = req.nextUrl.searchParams.get('limit')
  const parsed = raw ? Number.parseInt(raw, 10) : fallback
  if (!Number.isFinite(parsed) || parsed <= 0) return fallback
  return Math.min(parsed, max)
}

async function getStats(client: SupabaseClient): Promise<DashboardStats> {
  const since24h = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString()
  const [attackers, beacons, beacons24h, tokens] = await Promise.all([
    client.from('attackers').select('*', { count: 'exact', head: true }),
    client.from('triggered_beacons').select('*', { count: 'exact', head: true }),
    client
      .from('triggered_beacons')
      .select('*', { count: 'exact', head: true })
      .gt('received_at', since24h),
    client
      .from('honeytokens')
      .select('*', { count: 'exact', head: true })
      .is('revoked_at', null),
  ])

  if (attackers.error) throw attackers.error
  if (beacons.error) throw beacons.error
  if (beacons24h.error) throw beacons24h.error
  if (tokens.error) throw tokens.error

  const [lastBeacon, lastAttacker] = await Promise.all([
    client
      .from('triggered_beacons')
      .select('received_at, ip')
      .order('received_at', { ascending: false })
      .limit(1)
      .maybeSingle(),
    client
      .from('attackers')
      .select('ip, last_seen')
      .order('last_seen', { ascending: false })
      .limit(1)
      .maybeSingle(),
  ])

  if (lastBeacon.error) throw lastBeacon.error
  if (lastAttacker.error) throw lastAttacker.error

  return {
    total_attackers: attackers.count || 0,
    total_beacons: beacons.count || 0,
    last_24h_beacons: beacons24h.count || 0,
    active_tokens: tokens.count || 0,
    last_attacker_ip:
      typeof lastAttacker.data?.ip === 'string' ? lastAttacker.data.ip : null,
    last_beacon_at:
      typeof lastBeacon.data?.received_at === 'string' ? lastBeacon.data.received_at : null,
  }
}

async function getAttackers(client: SupabaseClient, limit: number): Promise<Attacker[]> {
  const { data, error } = await client
    .from('attackers')
    .select('id, ip, first_seen, last_seen, hit_count, last_user_agent, last_token, tags')
    .order('last_seen', { ascending: false })
    .limit(limit)

  if (error) throw error
  return (data || []) as Attacker[]
}

async function getBeacons(client: SupabaseClient, limit: number): Promise<TriggeredBeacon[]> {
  const { data, error } = await client
    .from('triggered_beacons')
    .select('id, token, ip, user_agent, received_at, opener_app')
    .order('received_at', { ascending: false })
    .limit(limit)

  if (error) throw error
  return (data || []) as TriggeredBeacon[]
}

async function getHoneytokens(client: SupabaseClient, limit: number): Promise<HoneytokenRow[]> {
  const { data, error } = await client
    .from('honeytokens')
    .select('token, label, full_url, row_count, triggered_count, issued_at, last_triggered_at')
    .is('revoked_at', null)
    .order('issued_at', { ascending: false })
    .limit(limit)

  if (error) throw error
  return (data || []) as HoneytokenRow[]
}

async function getTriage(client: SupabaseClient, limit: number): Promise<BeaconTriage[]> {
  const { data, error } = await client
    .from('beacon_triage')
    .select(
      'id, token, chain_seq, severity, confidence, rationale, recommended_action, source, chain_verified, model, created_at'
    )
    .order('created_at', { ascending: false })
    .limit(limit)

  if (error) throw error
  return (data || []) as BeaconTriage[]
}

/**
 * Sunucu tarafında okunan tam kanıt kaydı. `hmac` ve `prev_hash` yalnızca
 * doğrulama için kullanılır ve frontend'e asla gönderilmez.
 */
type EvidenceRow = EvidenceChainRecord & {
  prev_hash: string | null
  hmac: string | null
}

/**
 * Kanıt zinciri kayıtlarını `chain_seq` sırasıyla okur.
 *
 * `hmac` ve `prev_hash` frontend'e GÖNDERİLMEZ. İmza ve önceki hash
 * değerleri sızsaydı saldırgan zincirin içeriğini taklit edebilirdi.
 */
/**
 * Prompt canary'lerini okur.
 *
 * `marker` alanı tam olarak frontend'e gider ama panel kısaltarak gösterir.
 * API katmanında maskelemek yerine sunucu tarafında maskeliyoruz: böylece
 * başka bir istemci bu resource'u çağırsa da tam işaret sızmaz.
 */
async function getCanaries(
  client: SupabaseClient,
  limit: number
): Promise<PromptCanary[]> {
  const { data, error } = await client
    .from('prompt_canaries')
    .select('id, token, marker, context, label, created_at')
    .order('created_at', { ascending: false })
    .limit(limit)

  if (error) throw error
  return (data || []) as PromptCanary[]
}

async function getEvidenceChain(
  client: SupabaseClient,
  token: string
): Promise<EvidenceChainRecord[]> {
  const { data, error } = await client
    .from('triggered_beacons')
    .select('token, ip, user_agent, received_at, chain_seq, record_hash')
    .eq('token', token)
    .order('chain_seq', { ascending: true })

  if (error) throw error
  return (data || []) as EvidenceChainRecord[]
}

// ---------------------------------------------------------------------------
// Kanonik hash — Python `mirage/evidence.py` ile BİREBİR aynı olmalı.
// Farklılık, sahte "kurcalama" uyarısı üretir. Parite zorunlu.
// ---------------------------------------------------------------------------

/** Zincirin ilk kaydının `prev_hash` değeri. Python: GENESIS_HASH = "0" * 64 */
const GENESIS_HASH = '0'.repeat(64)

/** İmzalanan alanlar, Python EVIDENCE_FIELDS ile aynı sırada. */
const EVIDENCE_FIELDS = ['token', 'ip', 'user_agent', 'received_at', 'chain_seq', 'prev_hash'] as const

/**
 * Timestamp'i kanonik UTC ISO-8601'e çevirir: milisaniye + `Z` son eki.
 * Python `normalize_timestamp` ile aynı mantık. Gerekçe: Postgres
 * `...000Z` değeri `...+00:00` olarak geri döner; normalize edilmezse
 * hash eşleşmez ve doğrulama yanlışlıkla "kurcalandı" der.
 */
export function normalizeTimestamp(value: string): string {
  const iso = value.endsWith('Z') ? `${value.slice(0, -1)}+00:00` : value
  const dt = new Date(iso)
  if (Number.isNaN(dt.getTime())) return value
  return `${dt.toISOString().slice(0, 23)}Z`
}

/**
 * Kanonik JSON: yalnızca imzalanan alanlar, anahtarlar sıralı, boşluksuz.
 * Python `json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False)`
 * ile aynı bayt dizisini üretmelidir.
 */
function canonicalJson(record: EvidenceRow): string {
  const subset: Record<string, unknown> = {
    token: record.token ?? null,
    ip: record.ip ?? null,
    user_agent: record.user_agent ?? null,
    received_at:
      record.received_at != null ? normalizeTimestamp(String(record.received_at)) : null,
    chain_seq: record.chain_seq ?? null,
    prev_hash: record.prev_hash ?? null,
  }

  return JSON.stringify(subset, Object.keys(subset).sort())
}

function sha256Hex(input: string): string {
  return createHash('sha256').update(input, 'utf8').digest('hex')
}

/**
 * Bir token'ın kanıt zincirini sunucu tarafında doğrular.
 *
 * Python `verify_chain` ile aynı üç kontrolü yapar:
 *   1. record_hash alanlardan yeniden hesaplanabilir mi?  (kurcalama)
 *   2. prev_hash bir önceki kaydın record_hash'ine bağlı mı? (kopukluk)
 *   3. hmac, kayıtlı record_hash için geçerli mi?          (sahte kayıt)
 *
 * Güvenlik: `MIRAGE_EVIDENCE_HMAC_KEY` yalnızca burada okunur ve asla
 * response'a girmez. Anahtar yoksa FAIL-CLOSED: "doğrulandı" denmez,
 * "doğrulanamadı" döner — Python ile aynı semantik.
 */
async function verifyEvidenceChain(
  client: SupabaseClient,
  token: string
): Promise<EvidenceVerifyResult> {
  const key = process.env.MIRAGE_EVIDENCE_HMAC_KEY

  if (!key) {
    return {
      token,
      ok: false,
      checked: 0,
      broken_at: null,
      reason: 'signing key unavailable',
    }
  }

  const { data, error } = await client
    .from('triggered_beacons')
    .select('token, ip, user_agent, received_at, chain_seq, prev_hash, record_hash, hmac')
    .eq('token', token)
    .order('chain_seq', { ascending: true })

  if (error) throw error

  const rows = (data || []) as EvidenceRow[]

  if (rows.length === 0) {
    return {
      token,
      ok: false,
      checked: 0,
      broken_at: null,
      reason: 'no evidence records for token',
    }
  }

  const ordered = [...rows].sort((a, b) => Number(a.chain_seq) - Number(b.chain_seq))

  let prev = GENESIS_HASH
  let checked = 0

  for (const r of ordered) {
    checked += 1

    const expectedHash = sha256Hex(canonicalJson(r))
    if (expectedHash !== r.record_hash) {
      return {
        token,
        ok: false,
        checked,
        broken_at: Number(r.chain_seq),
        reason: 'record_hash mismatch (record was modified)',
      }
    }

    if ((r.prev_hash ?? null) !== prev) {
      return {
        token,
        ok: false,
        checked,
        broken_at: Number(r.chain_seq),
        reason: 'prev_hash does not link to previous record',
      }
    }

    const expectedHmac = createHmac('sha256', key)
      .update(String(r.record_hash), 'utf8')
      .digest('hex')

    const a = Buffer.from(expectedHmac)
    const b = Buffer.from(String(r.hmac ?? ''))
    if (b.length === 0 || a.length !== b.length || !timingSafeEqual(a, b)) {
      return {
        token,
        ok: false,
        checked,
        broken_at: Number(r.chain_seq),
        reason: 'hmac verification failed',
      }
    }

    prev = String(r.record_hash)
  }

  return { token, ok: true, checked, broken_at: null, reason: null }
}

export async function GET(req: NextRequest): Promise<NextResponse> {
  const resource = parseResource(req)
  if (!resource) {
    return json<ApiError>({ error: 'resource must be one of stats, attackers, beacons, honeytokens, triage' }, 400)
  }

  const authClient = await createSupabaseServerClient()
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

    try {
      if (resource === 'stats') {
        const total_attackers = mockDb.attackers.length
        const total_beacons = mockDb.beacons.length
        const last_24h_beacons = mockDb.beacons.length
        const active_tokens = mockDb.honeytokens.length
        const last_attacker_ip = mockDb.attackers[0]?.ip || null
        const last_beacon_at = mockDb.beacons[0]?.received_at || null
        return json({
          total_attackers,
          total_beacons,
          last_24h_beacons,
          active_tokens,
          last_attacker_ip,
          last_beacon_at,
        })
      }
      if (resource === 'attackers') return json(mockDb.attackers)
      if (resource === 'beacons') return json(mockDb.beacons)
      if (resource === 'triage') return json(mockDb.triage)
      if (resource === 'canaries') return json(mockDb.canaries)
      if (resource === 'evidence') return json(mockDb.evidence)
      if (resource === 'evidenceVerify') return json(mockDb.evidenceVerify)
      return json(mockDb.honeytokens)
    } catch (err) {
      return json<ApiError>({ error: 'Mock query failed', detail: err instanceof Error ? err.message : 'Unknown' }, 500)
    }
  }

  const { data: claimsData, error: claimsError } = await authClient.auth.getClaims()
  if (claimsError || !claimsData?.claims) {
    return json<ApiError>({ error: 'unauthorized', detail: 'Sign in to access dashboard data.' }, 401)
  }

  const client = getServerClient()
  if (!client) {
    return json<ApiError>(
      {
        error: 'Supabase server client not configured',
        detail: 'Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY for dashboard API reads.',
      },
      503,
    )
  }

  try {
    if (resource === 'evidence' || resource === 'evidenceVerify') {
      const token = req.nextUrl.searchParams.get('token')
      if (!token) {
        return json<ApiError>({ error: 'token query parameter is required' }, 400)
      }
      if (resource === 'evidence') {
        return json(await getEvidenceChain(client, token))
      }
      return json(await verifyEvidenceChain(client, token))
    }
    if (resource === 'stats') return json(await getStats(client))
    if (resource === 'attackers') return json(await getAttackers(client, parseLimit(req, 100, 500)))
    if (resource === 'beacons') return json(await getBeacons(client, parseLimit(req, 50, 500)))
    if (resource === 'triage') return json(await getTriage(client, parseLimit(req, 25, 100)))
    if (resource === 'canaries') return json(await getCanaries(client, parseLimit(req, 50, 200)))
    return json(await getHoneytokens(client, parseLimit(req, 100, 500)))
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unexpected Supabase query error'
    return json<ApiError>({ error: 'Dashboard query failed', detail: message }, 500)
  }
}

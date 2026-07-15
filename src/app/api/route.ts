import { NextRequest, NextResponse } from 'next/server'
import { createClient, type SupabaseClient } from '@supabase/supabase-js'
import type { Attacker, DashboardStats, TriggeredBeacon } from '@/lib/mirage/types'
import { createSupabaseServerClient } from '@/lib/supabase/server'
import { mockDb } from '@/lib/mirage/mock-db'
import { isProductionRuntime } from '@/lib/mirage/runtime'

export const dynamic = 'force-dynamic'

type MirageResource = 'stats' | 'attackers' | 'beacons' | 'honeytokens'

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
    resource === 'honeytokens'
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

export async function GET(req: NextRequest): Promise<NextResponse> {
  const resource = parseResource(req)
  if (!resource) {
    return json<ApiError>({ error: 'resource must be one of stats, attackers, beacons, honeytokens' }, 400)
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
    if (resource === 'stats') return json(await getStats(client))
    if (resource === 'attackers') return json(await getAttackers(client, parseLimit(req, 100, 500)))
    if (resource === 'beacons') return json(await getBeacons(client, parseLimit(req, 50, 500)))
    return json(await getHoneytokens(client, parseLimit(req, 100, 500)))
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unexpected Supabase query error'
    return json<ApiError>({ error: 'Dashboard query failed', detail: message }, 500)
  }
}

import { NextRequest, NextResponse } from 'next/server'

import { mockDb } from '@/lib/mirage/mock-db'
import { isLocalDevelopmentRuntime, isProductionRuntime, type RuntimeEnv } from '@/lib/mirage/runtime'

export const dynamic = 'force-dynamic'

const TRANSPARENT_PNG = Buffer.from(
  '89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c630001000000050001000d0a2db40000000049454e44ae426082',
  'hex',
)

export function isNextTrackRouteEnabled(env: RuntimeEnv = process.env): boolean {
  return isLocalDevelopmentRuntime(env) && !isProductionRuntime(env)
}

export function classifyOpenerApp(userAgent: string): string {
  const ua = userAgent.toLowerCase()
  if (ua.includes('libreoffice')) return 'libreoffice'
  if (ua.includes('microsoft office') || ua.includes('excel')) return 'excel'
  if (ua.includes('numbers')) return 'numbers'
  if (ua.includes('google')) return 'google-sheets'
  if (ua.includes('mozilla')) return 'browser'
  return 'unknown'
}

function disabledTrackResponse(): NextResponse {
  return NextResponse.json(
    {
      error: 'next_track_route_disabled',
      detail:
        'The Next.js /api/track route is local-demo only. Use the canonical Supabase Edge Function beacon receiver in production.',
      canonical_receiver: 'scripts/mirage-edge/functions/beacon-receiver',
    },
    {
      status: 410,
      headers: {
        'Cache-Control': 'no-store',
        'X-Content-Type-Options': 'nosniff',
        'X-MIRAGE-Canonical-Receiver': 'scripts/mirage-edge/functions/beacon-receiver',
      },
    },
  )
}

function pixelResponse(): NextResponse {
  return new NextResponse(TRANSPARENT_PNG, {
    status: 200,
    headers: {
      'Content-Type': 'image/png',
      'Content-Length': String(TRANSPARENT_PNG.length),
      'Cache-Control': 'no-store, no-cache, must-revalidate, proxy-revalidate',
      Pragma: 'no-cache',
      Expires: '0',
    },
  })
}

export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ token: string }> },
): Promise<NextResponse> {
  if (!isNextTrackRouteEnabled()) {
    return disabledTrackResponse()
  }

  const { token } = await params
  const ip = req.headers.get('x-forwarded-for') || req.headers.get('x-real-ip') || '127.0.0.1'
  const userAgent = req.headers.get('user-agent') || 'Unknown Office App'
  const openerApp = classifyOpenerApp(userAgent)
  const receivedAt = new Date().toISOString()

  // Local demo only: this route intentionally writes to in-memory mockDb.
  // Production beacon evidence must go through scripts/mirage-edge/functions/beacon-receiver.
  mockDb.beacons.unshift({
    id: `b-${mockDb.beacons.length + 1}`,
    token,
    ip,
    user_agent: userAgent,
    received_at: receivedAt,
    opener_app: openerApp,
  })

  const existingAttacker = mockDb.attackers.find((a) => a.ip === ip)
  if (existingAttacker) {
    existingAttacker.hit_count += 1
    existingAttacker.last_seen = receivedAt
    existingAttacker.last_user_agent = userAgent
    existingAttacker.last_token = token
  } else {
    mockDb.attackers.unshift({
      id: `a-${mockDb.attackers.length + 1}`,
      ip,
      first_seen: receivedAt,
      last_seen: receivedAt,
      hit_count: 1,
      last_user_agent: userAgent,
      last_token: token,
      tags: openerApp === 'browser' ? ['scanner'] : ['active-compromise'],
    })
  }

  const existingToken = mockDb.honeytokens.find((t) => t.token === token)
  if (existingToken) {
    existingToken.triggered_count = (existingToken.triggered_count || 0) + 1
    existingToken.last_triggered_at = receivedAt
  } else {
    mockDb.honeytokens.unshift({
      token,
      label: `auto-registered-${openerApp}`,
      full_url: req.url,
      row_count: 100,
      triggered_count: 1,
      issued_at: receivedAt,
      last_triggered_at: receivedAt,
    })
  }

  console.log(`[MIRAGE LOCAL BEACON] Triggered: token=${token} | IP=${ip} | App=${openerApp}`)
  return pixelResponse()
}

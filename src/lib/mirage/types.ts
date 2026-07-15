/**
 * MIRAGE Dashboard — Tip tanımları
 *
 * Bu tipler hem frontend hem backend (Next.js API routes) tarafından
 * paylaşılır. Backend Supabase'ten gelen satırları bu tiplere map eder.
 */

export interface Attacker {
  id: string
  ip: string
  first_seen: string  // ISO8601
  last_seen: string   // ISO8601
  hit_count: number
  last_user_agent: string | null
  last_token: string | null
  tags: string[]
}

export interface TriggeredBeacon {
  id: string
  token: string
  ip: string
  user_agent: string | null
  received_at: string  // ISO8601
  opener_app: string   // 'libreoffice' | 'excel' | 'numbers' | 'google-sheets' | 'browser' | 'unknown'
}

export interface DashboardStats {
  total_attackers: number
  total_beacons: number
  last_24h_beacons: number
  active_tokens: number
  last_attacker_ip: string | null
  last_beacon_at: string | null
}

/**
 * Ofis uygulamasını User-Agent string'inden tespit et.
 * Backend migration'daki generated column ile aynı mantık.
 */
export function detectOpenerApp(userAgent: string | null | undefined): string {
  if (!userAgent) return 'unknown'
  const ua = userAgent.toLowerCase()
  if (ua.includes('libreoffice')) return 'libreoffice'
  if (ua.includes('microsoft office') || ua.includes('excel')) return 'excel'
  if (ua.includes('numbers')) return 'numbers'
  if (ua.includes('google')) return 'google-sheets'
  if (ua.includes('mozilla') || ua.includes('chrome') || ua.includes('safari')) return 'browser'
  return 'unknown'
}

/**
 * ISO8601 timestamp'i "5 minutes ago" formatına çevir.
 * Türkçe lokalize — dashboard Turkish.
 */
export function relativeTime(iso: string): string {
  const now = Date.now()
  const then = new Date(iso).getTime()
  const diffMs = now - then
  const diffSec = Math.floor(diffMs / 1000)
  const diffMin = Math.floor(diffSec / 60)
  const diffHour = Math.floor(diffMin / 60)
  const diffDay = Math.floor(diffHour / 24)

  if (diffSec < 60) return 'az önce'
  if (diffMin < 60) return `${diffMin} dk önce`
  if (diffHour < 24) return `${diffHour} saat önce`
  if (diffDay < 7) return `${diffDay} gün önce`
  // 7 günden eski — tarih göster
  return new Date(iso).toLocaleDateString('tr-TR', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  })
}

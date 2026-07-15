/**
 * MIRAGE Task 02 (Production) — Supabase client + Realtime hooks
 *
 * Bu modül, dashboard'un mock-data.ts yerine gerçek Supabase'ten
 * veri çekmesini ve realtime updates almasını sağlar.
 *
 * Zero Mock Policy: Bu modül hiçbir mock içermez. Dashboard reads go
 * through the server-side /api proxy so RLS can stay closed to anon clients.
 * Realtime remains optional and uses the public Supabase anon key when set.
 */

import { useEffect, useState, useRef, useCallback } from 'react'
import { createBrowserClient } from '@supabase/ssr'
import type { SupabaseClient } from '@supabase/supabase-js'
import type {
  Attacker,
  TriggeredBeacon,
  DashboardStats,
} from './types'
import { getSupabasePublishableKey, getSupabaseUrl } from '@/lib/supabase/env'

async function fetchMirageApi<T>(resource: string, params: Record<string, string | number> = {}): Promise<T> {
  const search = new URLSearchParams({ resource })
  for (const [key, value] of Object.entries(params)) {
    search.set(key, String(value))
  }

  const response = await fetch(`/api?${search.toString()}`, { cache: 'no-store' })
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { error?: string; detail?: string } | null
    const message = body?.detail || body?.error || `MIRAGE API request failed (${response.status})`
    throw new Error(message)
  }
  return response.json() as Promise<T>
}

// =============================================================================
// Singleton client (lazy init)
// =============================================================================
let _client: SupabaseClient | null = null
let _initAttempted = false

export function createMirageSupabaseClient(): SupabaseClient | null {
  if (_client) return _client
  if (_initAttempted) return _client
  _initAttempted = true

  const url = getSupabaseUrl()
  const anonKey = getSupabasePublishableKey()

  if (!url || !anonKey) {
    // Fail-safe: env yoksa null döner, dashboard polling fallback'e düşer
    if (typeof console !== 'undefined') {
      console.warn(
        '[MIRAGE] NEXT_PUBLIC_SUPABASE_URL or NEXT_PUBLIC_SUPABASE_ANON_KEY not set — dashboard will use polling fallback'
      )
    }
    return null
  }

  _client = createBrowserClient(url, anonKey, {
    realtime: { params: { eventsPerSecond: 10 } },
  })
  return _client
}

/** Test hook — reset singleton. */
export function _resetMirageClientForTesting(): void {
  _client = null
  _initAttempted = false
}

// =============================================================================
// Realtime subscription hook
// =============================================================================
export type RealtimeStatus = 'idle' | 'connecting' | 'connected' | 'error'

export interface UseRealtimeOptions {
  table: 'triggered_beacons' | 'attackers' | 'honeytokens'
  onInsert?: (row: Record<string, unknown>) => void
  onUpdate?: (row: Record<string, unknown>) => void
  enabled?: boolean
}

export interface UseRealtimeResult {
  status: RealtimeStatus
  lastEvent: { type: 'INSERT' | 'UPDATE'; row: Record<string, unknown> } | null
}

/**
 * Supabase postgres_changes subscription'ı yöneten hook.
 * - Unmount'ta subscription otomatik temizlenir.
 * - Connection status state olarak expose edilir.
 * - Hata durumunda 'error' status'a düşer, retry mantığı caller'a bırakılır.
 */
export function useMirageRealtime(opts: UseRealtimeOptions): UseRealtimeResult {
  const { table, onInsert, onUpdate, enabled = true } = opts
  const [status, setStatus] = useState<RealtimeStatus>('idle')
  const [lastEvent, setLastEvent] = useState<UseRealtimeResult['lastEvent']>(null)
  // Refs to avoid stale closures in subscription callback
  const onInsertRef = useRef(onInsert)
  const onUpdateRef = useRef(onUpdate)

  useEffect(() => {
    onInsertRef.current = onInsert
    onUpdateRef.current = onUpdate
  }, [onInsert, onUpdate])

  useEffect(() => {
    if (!enabled) return

    // Initial status: 'connecting' (will be updated by subscription callback)
    // Use a microtask to defer the state update (avoids cascading render warning)
    Promise.resolve().then(() => setStatus('connecting'))

    let cancelled = false
    let channel: ReturnType<NonNullable<SupabaseClient>['channel']> | null = null

    // Defer subscription setup to a microtask so setState isn't sync
    Promise.resolve().then(() => {
      if (cancelled) return
      const client = createMirageSupabaseClient()
      if (!client) {
        if (!cancelled) setStatus('error')
        return
      }

      channel = client
        .channel(`mirage-${table}`)
        .on(
          'postgres_changes',
          { event: 'INSERT', schema: 'public', table },
          (payload) => {
            const row = payload.new as Record<string, unknown>
            setLastEvent({ type: 'INSERT', row })
            onInsertRef.current?.(row)
          }
        )
        .on(
          'postgres_changes',
          { event: 'UPDATE', schema: 'public', table },
          (payload) => {
            const row = payload.new as Record<string, unknown>
            setLastEvent({ type: 'UPDATE', row })
            onUpdateRef.current?.(row)
          }
        )
        .subscribe((subStatus: string) => {
          if (cancelled) return
          if (subStatus === 'SUBSCRIBED') setStatus('connected')
          else if (subStatus === 'CHANNEL_ERROR' || subStatus === 'TIMED_OUT')
            setStatus('error')
        })
    })

    return () => {
      cancelled = true
      const client = createMirageSupabaseClient()
      if (client && channel) client.removeChannel(channel)
      Promise.resolve().then(() => setStatus('idle'))
    }
  }, [table, enabled])

  return { status, lastEvent }
}

// =============================================================================
// Stats (KPI) hook
// =============================================================================
export interface UseMirageStatsResult {
  stats: DashboardStats | null
  loading: boolean
  error: Error | null
  refresh: () => void
}

export function useMirageStats(): UseMirageStatsResult {
  const [stats, setStats] = useState<DashboardStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<Error | null>(null)
  const [refreshKey, setRefreshKey] = useState(0)

  const refresh = useCallback(() => setRefreshKey((k) => k + 1), [])

  useEffect(() => {
    let cancelled = false
    const fetchStats = async () => {
      try {
        setLoading(true)
        const data = await fetchMirageApi<DashboardStats>('stats')
        if (cancelled) return
        setStats(data)
        setError(null)
      } catch (err) {
        if (!cancelled) setError(err as Error)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    fetchStats()

    // Refresh every 10 seconds as a safety net (realtime hook handles
    // live updates, this is for cases where realtime disconnects)
    const interval = setInterval(fetchStats, 10_000)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [refreshKey])

  return { stats, loading, error, refresh }
}

// =============================================================================
// Attackers list hook (with realtime refresh)
// =============================================================================
export interface UseMirageAttackersResult {
  attackers: Attacker[]
  loading: boolean
  error: Error | null
  refresh: () => void
}

export function useMirageAttackers(limit = 100): UseMirageAttackersResult {
  const [attackers, setAttackers] = useState<Attacker[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<Error | null>(null)
  const [refreshKey, setRefreshKey] = useState(0)

  const refresh = useCallback(() => setRefreshKey((k) => k + 1), [])

  // Realtime subscription — yeni beacon geldiğinde attackers listesi refresh
  const { status: rtStatus } = useMirageRealtime({
    table: 'triggered_beacons',
    enabled: true,
    onInsert: () => setRefreshKey((k) => k + 1),
  })

  useEffect(() => {
    let cancelled = false
    const fetchAttackers = async () => {
      try {
        setLoading(true)
        const data = await fetchMirageApi<Attacker[]>('attackers', { limit })
        if (cancelled) return
        setAttackers(data)
        setError(null)
      } catch (err) {
        if (!cancelled) setError(err as Error)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    fetchAttackers()
    return () => { cancelled = true }
  }, [limit, refreshKey, rtStatus])

  return { attackers, loading, error, refresh }
}

// =============================================================================
// Beacons list hook
// =============================================================================
export interface UseMirageBeaconsResult {
  beacons: TriggeredBeacon[]
  loading: boolean
  error: Error | null
  refresh: () => void
}

export function useMirageBeacons(limit = 50): UseMirageBeaconsResult {
  const [beacons, setBeacons] = useState<TriggeredBeacon[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<Error | null>(null)
  const [refreshKey, setRefreshKey] = useState(0)

  const refresh = useCallback(() => setRefreshKey((k) => k + 1), [])

  // Realtime — yeni beacon geldiğinde listeye prepend et
  const { status: rtStatus } = useMirageRealtime({
    table: 'triggered_beacons',
    enabled: true,
    onInsert: (row) => {
      setBeacons((prev) => [row as unknown as TriggeredBeacon, ...prev].slice(0, limit))
    },
  })

  useEffect(() => {
    let cancelled = false
    const fetchBeacons = async () => {
      try {
        setLoading(true)
        const data = await fetchMirageApi<TriggeredBeacon[]>('beacons', { limit })
        if (cancelled) return
        setBeacons(data)
        setError(null)
      } catch (err) {
        if (!cancelled) setError(err as Error)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    fetchBeacons()
    return () => { cancelled = true }
  }, [limit, refreshKey, rtStatus])

  return { beacons, loading, error, refresh }
}

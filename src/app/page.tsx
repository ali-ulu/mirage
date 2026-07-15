'use client'

/**
 * MIRAGE Dashboard — Ana Sayfa (Production)
 *
 * Zero Mock Policy: Bu sayfa gerçek Supabase'ten veri çeker.
 *  - useMirageStats: KPI'lar (count queries)
 *  - useMirageAttackers: saldırgan listesi
 *  - useMirageBeacons: son beacon'lar (realtime prepend)
 *  - useMirageRealtime: postgres_changes subscription
 *
 * Supabase env var yoksa error state gösterilir (fail-loud, mock'a düşmez).
 *
 * Neo-Brutalist tasarım korunur:
 *   - border-2, rounded-none, hard shadow, monospace, high contrast
 *   - Sticky footer (mt-auto)
 */
import { KpiCard } from '@/components/mirage/kpi-card'
import { AttackerTable } from '@/components/mirage/attacker-table'
import { BeaconFeed } from '@/components/mirage/beacon-feed'
import Link from 'next/link'
import {
  useMirageStats,
  useMirageAttackers,
  useMirageBeacons,
  useMirageRealtime,
} from '@/lib/mirage/supabase-client'
import { relativeTime } from '@/lib/mirage/types'

export default function Home() {
  const { stats, loading: statsLoading, error: statsError } = useMirageStats()
  const { attackers, loading: attackersLoading, error: attackersError } = useMirageAttackers(100)
  const { beacons, loading: beaconsLoading, error: beaconsError } = useMirageBeacons(50)

  // Realtime status indicator
  const { status: rtStatus } = useMirageRealtime({
    table: 'triggered_beacons',
    enabled: true,
  })

  const isLive = rtStatus === 'connected'
  const isConnecting = rtStatus === 'connecting'
  const hasError = !!statsError || !!attackersError || !!beaconsError

  return (
    <div className="min-h-screen flex flex-col bg-white text-black font-mono">
      {/* Header */}
      <header
        data-testid="dashboard-header"
        className="border-b-4 border-black bg-black text-white"
      >
        <div className="max-w-[1600px] mx-auto px-6 py-4 flex items-center justify-between flex-wrap gap-4">
          <div className="flex items-center gap-4">
            <div className="border-2 border-white px-3 py-1 text-2xl md:text-3xl font-black tracking-tight">
              MIRAGE
            </div>
            <div className="hidden sm:block text-xs uppercase tracking-widest text-white/60">
              Deception Infrastructure
            </div>
            <Link
              href="/logout"
              className="border-2 border-white/40 px-3 py-1 text-xs font-bold uppercase tracking-widest hover:bg-white hover:text-black transition-colors"
            >
              Sign out
            </Link>
          </div>
          <div className="flex items-center gap-3">
            <div
              className={`border-2 border-black px-3 py-1 text-xs font-bold uppercase tracking-widest ${
                isLive
                  ? 'bg-emerald-400 text-black'
                  : isConnecting
                  ? 'bg-yellow-300 text-black'
                  : 'bg-zinc-400 text-black/60'
              }`}
            >
              <span className="inline-block w-2 h-2 bg-black mr-2 align-middle animate-pulse" />
              {isLive ? 'LIVE' : isConnecting ? 'CONNECTING' : 'OFFLINE'}
            </div>
            <div className="text-xs text-white/60 uppercase tracking-widest hidden md:block">
              Last sync: {stats?.last_beacon_at ? relativeTime(stats.last_beacon_at) : '—'}
            </div>
          </div>
        </div>
      </header>

      {/* Main content */}
      <main className="flex-1 max-w-[1600px] w-full mx-auto px-6 py-6 space-y-6">
        {/* Error banner (fail-loud, no mock fallback) */}
        {hasError && (
          <section
            data-testid="error-banner"
            className="border-2 border-black bg-red-200 p-4 shadow-[6px_6px_0_0_#000] flex items-center gap-3"
          >
            <span className="text-2xl">⚠</span>
            <div>
              <div className="text-xs uppercase tracking-widest font-bold text-black/70">
                Connection Error
              </div>
              <div className="text-sm font-mono mt-1">
                {statsError?.message || attackersError?.message || beaconsError?.message}
              </div>
            </div>
          </section>
        )}

        {/* KPI Grid */}
        <section
          data-testid="kpi-grid"
          className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4"
        >
          <KpiCard
            label="Toplam Saldırgan"
            value={statsLoading ? '—' : (stats?.total_attackers ?? 0)}
            sublabel="Benzersiz IP"
            variant="danger"
          />
          <KpiCard
            label="Toplam Beacon"
            value={statsLoading ? '—' : (stats?.total_beacons ?? 0)}
            sublabel="Tetiklenen dosya"
            variant="warning"
          />
          <KpiCard
            label="Son 24 Saat"
            value={statsLoading ? '—' : (stats?.last_24h_beacons ?? 0)}
            sublabel="Aktif tehdit"
            variant="danger"
          />
          <KpiCard
            label="Aktif Token"
            value={statsLoading ? '—' : (stats?.active_tokens ?? 0)}
            sublabel="Dağıtılan honeytoken"
            variant="success"
          />
        </section>

        {/* Two-column layout: attackers + beacon feed */}
        <section className="grid grid-cols-1 xl:grid-cols-3 gap-6">
          <div className="xl:col-span-2 space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="text-sm uppercase tracking-widest font-black">
                Saldırgan Listesi
              </h2>
              <span className="text-xs text-black/60 uppercase">
                {attackersLoading ? 'yükleniyor…' : `${attackers.length} kayıt`}
              </span>
            </div>
            <AttackerTable attackers={attackers} />
          </div>
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="text-sm uppercase tracking-widest font-black">
                Canlı Akış
              </h2>
              {isLive && (
                <span className="inline-flex items-center gap-1 text-xs uppercase tracking-widest text-emerald-700">
                  <span className="w-2 h-2 bg-emerald-600 animate-pulse rounded-full" />
                  realtime
                </span>
              )}
            </div>
            <BeaconFeed beacons={beacons} />
          </div>
        </section>

        {/* Last attacker banner */}
        {stats?.last_attacker_ip && (
          <section
            data-testid="last-attacker-banner"
            className="border-2 border-black bg-yellow-300 p-4 shadow-[6px_6px_0_0_#000] flex items-center justify-between flex-wrap gap-4"
          >
            <div>
              <div className="text-[10px] uppercase tracking-widest font-bold text-black/70">
                Son Tespit Edilen Saldırgan
              </div>
              <div className="text-2xl font-black font-mono mt-1">
                {stats.last_attacker_ip}
              </div>
            </div>
            <div className="text-right">
              <div className="text-[10px] uppercase tracking-widest font-bold text-black/70">
                Son Aktivite
              </div>
              <div className="text-sm font-mono mt-1">
                {stats.last_beacon_at ? relativeTime(stats.last_beacon_at) : '—'}
              </div>
            </div>
          </section>
        )}
      </main>

      {/* Footer */}
      <footer
        role="contentinfo"
        className="mt-auto border-t-2 border-black bg-zinc-100 py-3 px-6 text-xs font-mono uppercase tracking-widest text-black/60"
      >
        <div className="max-w-[1600px] mx-auto flex items-center justify-between flex-wrap gap-2">
          <div>MIRAGE · Deception Infrastructure · v0.4.0</div>
          <div>Passive Honeytoken · No Code Execution</div>
        </div>
      </footer>
    </div>
  )
}

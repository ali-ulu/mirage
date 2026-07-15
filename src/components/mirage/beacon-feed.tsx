/**
 * MIRAGE Dashboard — BeaconFeed Component
 *
 * Tetiklenen son honeytoken beacon'larının gerçek zamanlı akışı.
 * Neo-Brutalist stil.
 */
import { cn } from '@/lib/utils'
import { relativeTime, type TriggeredBeacon } from '@/lib/mirage/types'

interface BeaconFeedProps {
  beacons: TriggeredBeacon[]
  className?: string
}

const openerBadgeClass: Record<string, string> = {
  libreoffice: 'bg-emerald-100 text-emerald-900 border-2 border-emerald-900',
  excel: 'bg-blue-100 text-blue-900 border-2 border-blue-900',
  numbers: 'bg-orange-100 text-orange-900 border-2 border-orange-900',
  'google-sheets': 'bg-yellow-100 text-yellow-900 border-2 border-yellow-900',
  browser: 'bg-purple-100 text-purple-900 border-2 border-purple-900',
  unknown: 'bg-zinc-100 text-zinc-900 border-2 border-zinc-900',
}

export function BeaconFeed({ beacons, className }: BeaconFeedProps) {
  // received_at'a göre descending sırala
  const sorted = [...beacons].sort(
    (a, b) => new Date(b.received_at).getTime() - new Date(a.received_at).getTime()
  )

  return (
    <div
      data-testid="beacon-feed"
      className={cn(
        'border-2 border-black rounded-none bg-white',
        'shadow-[6px_6px_0_0_#000]',
        'flex flex-col',
        className,
      )}
    >
      <div className="bg-black text-white font-mono uppercase text-xs tracking-widest p-3 border-b-2 border-black flex items-center justify-between">
        <span>Son Beaconlar</span>
        <span className="bg-white text-black px-2 py-0.5 font-black">
          {sorted.length}
        </span>
      </div>

      {sorted.length === 0 ? (
        <div className="p-8 text-center font-mono text-sm uppercase tracking-widest text-black/60">
          Henüz beacon tetiklenmedi
        </div>
      ) : (
        <div className="overflow-y-auto max-h-96 font-mono text-sm">
          {sorted.map((b, i) => {
            const opener = b.opener_app || 'unknown'
            return (
              <div
                key={b.id}
                data-testid="beacon-row"
                className={cn(
                  'flex items-center gap-3 p-3 border-b-2 border-black/20',
                  i % 2 === 0 ? 'bg-white' : 'bg-zinc-50',
                )}
              >
                <div className="flex-shrink-0">
                  <span
                    className={cn(
                      'inline-block px-2 py-1 text-xs font-bold uppercase',
                      'border-2 rounded-none',
                      openerBadgeClass[opener] || openerBadgeClass.unknown,
                    )}
                  >
                    {opener}
                  </span>
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-baseline gap-2">
                    <span className="font-black text-black">{b.ip}</span>
                    <span className="text-xs text-black/60">
                      {relativeTime(b.received_at)}
                    </span>
                  </div>
                  <div className="text-xs text-black/70 truncate mt-0.5">
                    <span className="text-black/40">token:</span>{' '}
                    <span className="font-mono">{b.token.slice(0, 8)}…</span>
                  </div>
                  {b.user_agent && (
                    <div className="text-[10px] text-black/50 truncate mt-0.5">
                      {b.user_agent}
                    </div>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

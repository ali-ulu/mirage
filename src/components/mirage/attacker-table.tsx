/**
 * MIRAGE Dashboard — AttackerTable Component
 *
 * Saldırgan listesini gösterir. Neo-Brutalist stil:
 *   - Siyah header, beyaz metin
 *   - border-2 kalın kenarlık
 *   - Monospace font (IP, user-agent)
 *   - Opener app badge'leri renkli
 */
import { cn } from '@/lib/utils'
import { Badge } from '@/components/ui/badge'
import { detectOpenerApp, relativeTime, type Attacker } from '@/lib/mirage/types'

interface AttackerTableProps {
  attackers: Attacker[]
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

export function AttackerTable({ attackers, className }: AttackerTableProps) {
  if (attackers.length === 0) {
    return (
      <div
        data-testid="attacker-table"
        className="border-2 border-black rounded-none p-8 text-center font-mono text-sm uppercase tracking-widest text-black/60"
      >
        Henüz saldırgan tespit edilmedi
      </div>
    )
  }

  return (
    <div
      data-testid="attacker-table"
      className={cn(
        'border-2 border-black rounded-none overflow-auto max-h-96 bg-white',
        'shadow-[6px_6px_0_0_#000]',
        className,
      )}
    >
      <table className="w-full text-sm">
        <thead className="bg-black text-white font-mono uppercase text-xs tracking-widest">
          <tr>
            <th className="text-left p-3 border-r-2 border-white/20">IP</th>
            <th className="text-left p-3 border-r-2 border-white/20">Hits</th>
            <th className="text-left p-3 border-r-2 border-white/20">Opener</th>
            <th className="text-left p-3 border-r-2 border-white/20">İlk Görülme</th>
            <th className="text-left p-3 border-r-2 border-white/20">Son Görülme</th>
            <th className="text-left p-3 border-r-2 border-white/20">User-Agent</th>
            <th className="text-left p-3">Tags</th>
          </tr>
        </thead>
        <tbody className="font-mono">
          {attackers.map((a, i) => {
            const opener = detectOpenerApp(a.last_user_agent)
            return (
              <tr
                key={a.id}
                className={cn(
                  'border-t-2 border-black/20',
                  i % 2 === 0 ? 'bg-white' : 'bg-zinc-50',
                )}
              >
                <td className="p-3 border-r-2 border-black/20 font-mono font-bold text-black">
                  {a.ip}
                </td>
                <td className="p-3 border-r-2 border-black/20 font-mono font-black text-lg">
                  {a.hit_count}
                </td>
                <td className="p-3 border-r-2 border-black/20">
                  <span
                    className={cn(
                      'inline-block px-2 py-1 text-xs font-bold uppercase',
                      'border-2 rounded-none',
                      openerBadgeClass[opener] || openerBadgeClass.unknown,
                    )}
                  >
                    {opener}
                  </span>
                </td>
                <td className="p-3 border-r-2 border-black/20 text-xs text-black/70">
                  {relativeTime(a.first_seen)}
                </td>
                <td className="p-3 border-r-2 border-black/20 text-xs text-black/70">
                  {relativeTime(a.last_seen)}
                </td>
                <td className="p-3 border-r-2 border-black/20 text-xs text-black/70 max-w-xs truncate">
                  {a.last_user_agent || '—'}
                </td>
                <td className="p-3">
                  <div className="flex flex-wrap gap-1">
                    {a.tags.map((tag) => (
                      <span
                        key={tag}
                        className="inline-block px-1.5 py-0.5 text-[10px] font-bold uppercase border border-black bg-white text-black"
                      >
                        {tag}
                      </span>
                    ))}
                  </div>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

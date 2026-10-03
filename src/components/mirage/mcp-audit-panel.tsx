import { cn } from '@/lib/utils'
import {
  relativeTime,
  type McpAuditRecord,
  type McpAuditSummary,
  type McpRiskLevel,
} from '@/lib/mirage/types'

interface McpPanelProps {
  audit: McpAuditSummary | null
  records?: McpAuditRecord[]
  connected: boolean
  loading?: boolean
  className?: string
}

const riskLabel: Record<McpRiskLevel, string> = {
  low: 'Düşük',
  medium: 'Orta',
  high: 'Yüksek',
  critical: 'Kritik',
}

const riskBadgeClass: Record<McpRiskLevel, string> = {
  low: 'bg-zinc-100 text-black border-2 border-black',
  medium: 'bg-yellow-200 text-black border-2 border-black',
  high: 'bg-orange-200 text-black border-2 border-black',
  critical: 'bg-red-600 text-white border-2 border-black',
}

const riskOrder: McpRiskLevel[] = ['critical', 'high', 'medium', 'low']

/**
 * MIRAGE Dashboard — McpAuditPanel
 *
 * MCP gateway'in ajan→araç çağrılarını gösterir: kaç çağrı geçti, kaçı
 * **fail-closed ile engellendi** ve risk kademelerine göre dağılım.
 *
 * Kalıcılık: kayıtlar `mcp_audit` tablosuna yazılır (migration 0009,
 * append-only). Daha önce Python belleğinde tutuluyordu ve restart'ta
 * sıfırlanıyordu — ürün "değiştirilemez kayıt" dediği için bu kabul
 * edilemezdi. Panel artık kalıcı tabloyu okur.
 */
export function McpAuditPanel({
  audit,
  records = [],
  connected,
  loading,
  className,
}: McpPanelProps) {
  if (loading) {
    return (
      <div
        data-testid="mcp-panel"
        className={cn(
          'border-2 border-black rounded-none bg-white p-8 text-center font-mono',
          'text-sm uppercase tracking-widest text-black/60',
          'shadow-[6px_6px_0_0_#000]',
          className,
        )}
      >
        MCP denetimi okunuyor…
      </div>
    )
  }

  if (!connected || !audit) {
    return (
      <div
        data-testid="mcp-panel"
        className={cn(
          'border-2 border-black rounded-none bg-zinc-100 p-6 font-mono text-sm',
          'shadow-[6px_6px_0_0_#000]',
          className,
        )}
      >
        <div className="font-bold uppercase tracking-widest">MCP API bağlantısı yok</div>
        <div className="mt-2 text-xs text-black/70">
          <code>MIRAGE_API_BASE_URL</code> ve <code>MIRAGE_API_TOKEN</code> ayarlanmadan
          gateway denetimi okunamaz. Diğer paneller çalışmaya devam eder.
        </div>
      </div>
    )
  }

  const blockedPct = audit.total > 0 ? Math.round((audit.denied / audit.total) * 100) : 0
  const maxCount = Math.max(1, ...riskOrder.map((l) => audit.by_risk_level[l] ?? 0))

  return (
    <div
      data-testid="mcp-panel"
      className={cn(
        'border-2 border-black rounded-none bg-white flex flex-col',
        'shadow-[6px_6px_0_0_#000]',
        className,
      )}
    >
      <div className="bg-black text-white font-mono uppercase text-xs tracking-widest p-3 border-b-2 border-black flex items-center justify-between gap-2">
        <span>MCP Gateway</span>
        <span
          className={cn(
            'px-2 py-0.5 font-black',
            audit.denied > 0 ? 'bg-red-600 text-white' : 'bg-emerald-400 text-black',
          )}
        >
          {audit.denied} engelli
        </span>
      </div>

      <div className="grid grid-cols-3 border-b-2 border-black">
        <div className="p-3 border-r-2 border-black/20">
          <div className="text-[10px] uppercase tracking-widest text-black/60">Toplam</div>
          <div className="font-black text-2xl">{audit.total}</div>
        </div>
        <div className="p-3 border-r-2 border-black/20">
          <div className="text-[10px] uppercase tracking-widest text-black/60">İzinli</div>
          <div className="font-black text-2xl text-emerald-700">{audit.allowed}</div>
        </div>
        <div className="p-3">
          <div className="text-[10px] uppercase tracking-widest text-black/60">Engelli</div>
          <div className="font-black text-2xl text-red-700">
            {audit.denied}
            <span className="text-xs font-bold text-black/50"> %{blockedPct}</span>
          </div>
        </div>
      </div>

      <div className="p-3 space-y-2">
        <div className="text-[10px] uppercase tracking-widest text-black/60">
          Risk kademesi dağılımı
        </div>
        {riskOrder.map((level) => {
          const count = audit.by_risk_level[level] ?? 0
          const width = Math.round((count / maxCount) * 100)
          return (
            <div key={level} data-testid="mcp-risk-row" className="flex items-center gap-2">
              <span className="text-[10px] uppercase font-bold w-14">{riskLabel[level]}</span>
              <div className="flex-1 h-4 border-2 border-black bg-white">
                {count > 0 && (
                  <div
                    className={cn('h-full', riskBadgeClass[level])}
                    style={{ width: `${width}%` }}
                  />
                )}
              </div>
              <span className="text-[10px] font-mono w-8 text-right">{count}</span>
            </div>
          )
        })}
      </div>

      {records.length > 0 && (
        <div className="border-t-2 border-black max-h-64 overflow-y-auto font-mono text-sm">
          {records.map((r) => (
            <div
              key={r.id}
              data-testid="mcp-record"
              className="p-3 border-b-2 border-black/20"
            >
              <div className="flex items-center gap-2 flex-wrap">
                <span
                  className={cn(
                    'inline-block px-2 py-1 text-xs font-bold uppercase border-2 rounded-none',
                    r.allowed
                      ? 'bg-emerald-100 text-emerald-900 border-emerald-900'
                      : 'bg-red-600 text-white border-black',
                  )}
                >
                  {r.allowed ? 'İZİN' : 'ENGELLENDİ'}
                </span>
                <span className="text-xs font-bold text-black">
                  {r.server}/{r.tool}
                </span>
                <span
                  className={cn(
                    'text-[10px] font-bold uppercase border px-1.5 py-0.5',
                    riskBadgeClass[r.risk_level] || riskBadgeClass.low,
                  )}
                >
                  {riskLabel[r.risk_level]} · {r.risk_score}
                </span>
                <span className="ml-auto text-[10px] text-black/50">
                  {relativeTime(r.occurred_at)}
                </span>
              </div>
              {r.reason && (
                <div className="text-[10px] text-black/60 mt-1">{r.reason}</div>
              )}
            </div>
          ))}
        </div>
      )}

      <div
        data-testid="mcp-persistence-note"
        className="border-t-2 border-black px-3 py-2 text-[10px] font-mono uppercase tracking-widest text-black/50"
      >
        append-only · kalıcı kayıt · restart'ta kaybolmaz
      </div>
    </div>
  )
}
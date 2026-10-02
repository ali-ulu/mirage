import { cn } from '@/lib/utils'
import {
  relativeTime,
  triageSourceLabel,
  type BeaconTriage,
  type TriageSeverity,
} from '@/lib/mirage/types'

interface TriagePanelProps {
  triage: BeaconTriage[]
  loading?: boolean
  error?: Error | null
  className?: string
}

const severityBadgeClass: Record<TriageSeverity, string> = {
  critical: 'bg-red-600 text-white border-2 border-black',
  high: 'bg-orange-200 text-black border-2 border-black',
  medium: 'bg-yellow-200 text-black border-2 border-black',
  low: 'bg-zinc-100 text-black border-2 border-black',
}

const actionLabel: Record<string, string> = {
  ignore: 'Yoksay',
  monitor: 'İzle',
  investigate: 'Araştır',
  escalate: 'Yükselt',
}

/**
 * MIRAGE Dashboard — TriagePanel
 *
 * AI/agent katmanının ürettiği triyaj değerlendirmelerini gösterir.
 * Yeni bir tasarım dili getirmez: mevcut BeaconFeed ile aynı neo-brutalist
 * stili ve `beacon_triage` append-only defterini paylaşır.
 *
 * Neden önemli: dashboard bugün yalnızca "dosya açıldı" bilgisini gösteriyor.
 * Bu panel, sistemin o açılışı *değerlendirdiğini* ve ne yapılmasını önerdiğini
 * görünür kılar — yani ürünün AI tarafının ekranda görünen yüzü.
 */
export function TriagePanel({ triage, loading, error, className }: TriagePanelProps) {
  if (error) {
    return (
      <div
        data-testid="triage-panel"
        className={cn(
          'border-2 border-black rounded-none bg-red-100 p-6 font-mono text-sm',
          'shadow-[6px_6px_0_0_#000]',
          className,
        )}
      >
        <div className="font-bold uppercase tracking-widest">Triyaj verisi okunamadı</div>
        <div className="mt-2 text-xs text-black/70">{error.message}</div>
      </div>
    )
  }

  if (loading) {
    return (
      <div
        data-testid="triage-panel"
        className={cn(
          'border-2 border-black rounded-none bg-white p-8 text-center font-mono',
          'text-sm uppercase tracking-widest text-black/60',
          'shadow-[6px_6px_0_0_#000]',
          className,
        )}
      >
        Triyajlar yükleniyor…
      </div>
    )
  }

  const critical = triage.filter((t) => t.severity === 'critical').length
  const llmCount = triage.filter((t) => t.source.startsWith('llm:')).length

  return (
    <div
      data-testid="triage-panel"
      className={cn(
        'border-2 border-black rounded-none bg-white flex flex-col',
        'shadow-[6px_6px_0_0_#000]',
        className,
      )}
    >
      <div className="bg-black text-white font-mono uppercase text-xs tracking-widest p-3 border-b-2 border-black flex items-center justify-between gap-2">
        <span>AI Triyaj</span>
        <span className="flex items-center gap-2">
          {critical > 0 && (
            <span className="bg-red-600 text-white px-2 py-0.5 font-black">
              {critical} kritik
            </span>
          )}
          <span className="bg-white text-black px-2 py-0.5 font-black">
            {triage.length}
          </span>
        </span>
      </div>

      {triage.length === 0 ? (
        <div className="p-8 text-center font-mono text-sm uppercase tracking-widest text-black/60">
          Henüz triyaj kaydı yok
        </div>
      ) : (
        <div className="overflow-y-auto max-h-96 font-mono text-sm">
          {triage.map((t, i) => (
            <div
              key={t.id}
              data-testid="triage-row"
              className={cn(
                'p-3 border-b-2 border-black/20',
                i % 2 === 0 ? 'bg-white' : 'bg-zinc-50',
              )}
            >
              <div className="flex items-center gap-2 flex-wrap">
                <span
                  className={cn(
                    'inline-block px-2 py-1 text-xs font-bold uppercase border-2 rounded-none',
                    severityBadgeClass[t.severity] || severityBadgeClass.low,
                  )}
                >
                  {t.severity}
                </span>
                <span className="text-xs font-bold uppercase tracking-widest bg-white border-2 border-black px-2 py-1">
                  {actionLabel[t.recommended_action] || t.recommended_action}
                </span>
                <span className="text-[10px] text-black/60 uppercase">
                  {triageSourceLabel(t.source)}
                </span>
                <span className="ml-auto text-[10px] text-black/50">
                  %{Math.round(t.confidence * 100)} güven
                </span>
              </div>

              <div className="text-xs text-black/80 mt-2 leading-relaxed">{t.rationale}</div>

              <div className="flex items-center gap-3 mt-2 text-[10px] text-black/50 flex-wrap">
                <span>
                  <span className="text-black/40">token:</span>{' '}
                  <span className="font-mono">{t.token.slice(0, 8)}…</span>
                </span>
                {t.chain_seq !== null && (
                  <span>
                    <span className="text-black/40">zincir:</span> #{t.chain_seq}
                  </span>
                )}
                {t.chain_verified === true && (
                  <span className="bg-emerald-100 text-emerald-900 border border-emerald-900 px-1.5 py-0.5 font-bold uppercase">
                    kanıt doğrulandı
                  </span>
                )}
                {t.chain_verified === false && (
                  <span className="bg-red-100 text-red-900 border border-red-900 px-1.5 py-0.5 font-bold uppercase">
                    zincir hatası
                  </span>
                )}
                <span className="ml-auto">{relativeTime(t.created_at)}</span>
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="border-t-2 border-black px-3 py-2 text-[10px] font-mono uppercase tracking-widest text-black/50">
        {llmCount}/{triage.length} LLM · {triage.length - llmCount} kural tabanlı
      </div>
    </div>
  )
}
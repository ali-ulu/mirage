import { cn } from '@/lib/utils'
import {
  canaryContextLabel,
  canaryMarkerShort,
  relativeTime,
  type CanaryContext,
  type PromptCanary,
} from '@/lib/mirage/types'

interface CanaryPanelProps {
  canaries: PromptCanary[]
  loading?: boolean
  error?: Error | null
  className?: string
}

const contextBadgeClass: Record<CanaryContext, string> = {
  system_prompt: 'bg-blue-100 text-blue-900 border-2 border-blue-900',
  rag_document: 'bg-orange-100 text-orange-900 border-2 border-orange-900',
  agent_memory: 'bg-purple-100 text-purple-900 border-2 border-purple-900',
}

/**
 * MIRAGE Dashboard — CanaryPanel
 *
 * Prompt-layer canary'leri gösterir: bir AI ajanının sistem prompt'una,
 * RAG dokümanına veya hafızasına gömülmüş yüksek entropili işaretler.
 *
 * Bu panel ürünün ikinci AI yüzünü gösterir. Honeytoken "bir dosya açıldı"
 * diyordu; canary ise "ajanın bağlamı sızdı mı?" diyor. Aynı mantığın
 * veri yüzeyinden ajan yüzeyine taşınmış hâli.
 *
 * Güvenlik: tam canary işareti gösterilmez, kısaltılır. Çünkü paneli
 * gören kişi kendi işaretini tanıyıp izinsiz kullanabilirdi.
 */
export function CanaryPanel({ canaries, loading, error, className }: CanaryPanelProps) {
  if (error) {
    return (
      <div
        data-testid="canary-panel"
        className={cn(
          'border-2 border-black rounded-none bg-red-100 p-6 font-mono text-sm',
          'shadow-[6px_6px_0_0_#000]',
          className,
        )}
      >
        <div className="font-bold uppercase tracking-widest">Canary verisi okunamadı</div>
        <div className="mt-2 text-xs text-black/70">{error.message}</div>
      </div>
    )
  }

  if (loading) {
    return (
      <div
        data-testid="canary-panel"
        className={cn(
          'border-2 border-black rounded-none bg-white p-8 text-center font-mono',
          'text-sm uppercase tracking-widest text-black/60',
          'shadow-[6px_6px_0_0_#000]',
          className,
        )}
      >
        Canary'ler yükleniyor…
      </div>
    )
  }

  const byContext = canaries.reduce<Record<string, number>>((acc, c) => {
    acc[c.context] = (acc[c.context] ?? 0) + 1
    return acc
  }, {})

  return (
    <div
      data-testid="canary-panel"
      className={cn(
        'border-2 border-black rounded-none bg-white flex flex-col',
        'shadow-[6px_6px_0_0_#000]',
        className,
      )}
    >
      <div className="bg-black text-white font-mono uppercase text-xs tracking-widest p-3 border-b-2 border-black flex items-center justify-between gap-2">
        <span>Prompt Canary</span>
        <span className="bg-white text-black px-2 py-0.5 font-black">
          {canaries.length}
        </span>
      </div>

      {canaries.length === 0 ? (
        <div className="p-8 text-center font-mono text-sm uppercase tracking-widest text-black/60">
          Henüz canary gömülmedi
        </div>
      ) : (
        <div className="overflow-y-auto max-h-80 font-mono text-sm">
          {canaries.map((c) => (
            <div
              key={c.id}
              data-testid="canary-row"
              className="p-3 border-b-2 border-black/20"
            >
              <div className="flex items-center gap-2 flex-wrap">
                <span
                  className={cn(
                    'inline-block px-2 py-1 text-xs font-bold uppercase border-2 rounded-none',
                    contextBadgeClass[c.context] || contextBadgeClass.system_prompt,
                  )}
                >
                  {canaryContextLabel(c.context)}
                </span>
                {c.label && (
                  <span className="text-xs font-bold text-black">{c.label}</span>
                )}
                <span className="ml-auto text-[10px] text-black/50">
                  {relativeTime(c.created_at)}
                </span>
              </div>
              <div className="text-[10px] text-black/50 mt-1 font-mono truncate">
                {canaryMarkerShort(c.marker)}
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="border-t-2 border-black px-3 py-2 text-[10px] font-mono uppercase tracking-widest text-black/50">
        sistem: {byContext.system_prompt ?? 0} · rag: {byContext.rag_document ?? 0} · hafıza:{' '}
        {byContext.agent_memory ?? 0}
      </div>
    </div>
  )
}
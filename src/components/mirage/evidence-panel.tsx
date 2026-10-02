import { cn } from '@/lib/utils'
import {
  relativeTime,
  type EvidenceChainRecord,
  type EvidenceVerifyResult,
} from '@/lib/mirage/types'

interface EvidencePanelProps {
  records: EvidenceChainRecord[]
  verification: EvidenceVerifyResult | null
  loading?: boolean
  error?: Error | null
  className?: string
}

/**
 * MIRAGE Dashboard — EvidencePanel
 *
 * Kanıt zincirini gösterir ve zincirin bütünlüğünü sunucu tarafında
 * yaptığımız HMAC doğrulamasının sonucunu sunar.
 *
 * Bu panel ürünün en güçlü iddiasını görünür kılar: "sadece bir dosya
 * açıldı" değil, "bu kayıt değiştirilemez ve bağımsız doğrulanabilir".
 *
 * Tasarım: triyaj panelinden farklı olarak burada bir AI yorumu yok —
 * gösterilen şey kriptografik olarak doğrulanmış bir gerçek. Bu yüzden
 * panel daha sade ve "doğrula" odaklı.
 */
export function EvidencePanel({
  records,
  verification,
  loading,
  error,
  className,
}: EvidencePanelProps) {
  if (error) {
    return (
      <div
        data-testid="evidence-panel"
        className={cn(
          'border-2 border-black rounded-none bg-red-100 p-6 font-mono text-sm',
          'shadow-[6px_6px_0_0_#000]',
          className,
        )}
      >
        <div className="font-bold uppercase tracking-widest">Kanıt okunamadı</div>
        <div className="mt-2 text-xs text-black/70">{error.message}</div>
      </div>
    )
  }

  if (loading) {
    return (
      <div
        data-testid="evidence-panel"
        className={cn(
          'border-2 border-black rounded-none bg-white p-8 text-center font-mono',
          'text-sm uppercase tracking-widest text-black/60',
          'shadow-[6px_6px_0_0_#000]',
          className,
        )}
      >
        Kanıt zinciri doğrulanıyor…
      </div>
    )
  }

  const verified = verification?.ok === true

  return (
    <div
      data-testid="evidence-panel"
      className={cn(
        'border-2 border-black rounded-none bg-white flex flex-col',
        'shadow-[6px_6px_0_0_#000]',
        className,
      )}
    >
      <div className="bg-black text-white font-mono uppercase text-xs tracking-widest p-3 border-b-2 border-black flex items-center justify-between gap-2">
        <span>Kanıt Zinciri</span>
        {verification && (
          <span
            data-testid="evidence-verdict"
            className={cn(
              'px-2 py-0.5 font-black',
              verified
                ? 'bg-emerald-400 text-black'
                : 'bg-red-600 text-white',
            )}
          >
            {verified ? 'DOĞRULANDI' : 'DOĞRULANAMADI'}
          </span>
        )}
      </div>

      {verification && !verified && (
        <div
          data-testid="evidence-reason"
          className="bg-red-100 border-b-2 border-black px-3 py-2 font-mono text-xs"
        >
          {verification.reason || 'Bilinmeyen hata'}
          {verification.broken_at !== null && ` · kırılma: #${verification.broken_at}`}
          {' · kontrol edilen kayıt: '}
          {verification.checked}
        </div>
      )}

      {records.length === 0 ? (
        <div className="p-8 text-center font-mono text-sm uppercase tracking-widest text-black/60">
          Kanıt kaydı yok
        </div>
      ) : (
        <div className="overflow-y-auto max-h-80 font-mono text-sm">
          {records.map((r) => (
            <div
              key={`${r.token}-${r.chain_seq}`}
              data-testid="evidence-row"
              className="p-3 border-b-2 border-black/20"
            >
              <div className="flex items-center gap-2 flex-wrap">
                <span className="bg-black text-white px-2 py-0.5 text-xs font-black uppercase">
                  #{r.chain_seq}
                </span>
                <span className="text-xs text-black/70">{r.ip || '—'}</span>
                <span className="ml-auto text-[10px] text-black/50">
                  {relativeTime(r.received_at)}
                </span>
              </div>
              <div className="text-[10px] text-black/50 mt-1 truncate">
                hash: <span className="font-mono">{r.record_hash || '—'}</span>
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="border-t-2 border-black px-3 py-2 text-[10px] font-mono uppercase tracking-widest text-black/50">
        {records.length} kayıt · HMAC-SHA256 · append-only
      </div>
    </div>
  )
}
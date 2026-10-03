'use client'

import { useState } from 'react'
import { cn } from '@/lib/utils'
import {
  ragActionLabel,
  type RagAction,
  type RagInspectResponse,
} from '@/lib/mirage/types'

interface RagPanelProps {
  className?: string
}

const actionBadgeClass: Record<RagAction, string> = {
  allow: 'bg-emerald-100 text-emerald-900 border-2 border-emerald-900',
  quarantine: 'bg-yellow-200 text-black border-2 border-black',
  reject: 'bg-red-600 text-white border-2 border-black',
}

/**
 * MIRAGE Dashboard — RagPanel
 *
 * RAG guard'ı CANLI denemeye açar: bir metin yapıştırılır, karar
 * (kabul / karantina / ret) ve gerekçeleri anında görülür.
 *
 * Neden salt-okunur bir panel değil: RAG kararları **hesaplanan** bir
 * sonuçtur, kayıt tablosu yoktur (MCP'nin aksine). "Son kararlar" listesi
 * göstermek uydurma olurdu. Doğru olan ürünü göstermek: metni gir,
 * kararı al.
 *
 * Güvenlik: taranan metin sunucu tarafında Python API'ye gider ve buraya
 * YALNIZCA karar + gerekçe döner. Dokümanın kendisi geri taşınmaz.
 */
export function RagPanel({ className }: RagPanelProps) {
  const [text, setText] = useState('')
  const [result, setResult] = useState<RagInspectResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [scanning, setScanning] = useState(false)

  const scan = async () => {
    if (!text.trim()) return
    setScanning(true)
    setError(null)
    setResult(null)
    try {
      const res = await fetch('/api?resource=ragInspect', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text }),
      })
      const body = await res.json()
      if (!res.ok) {
        setError(body?.detail || body?.error || `İstek başarısız (${res.status})`)
        return
      }
      setResult(body as RagInspectResponse)
    } catch {
      setError('Ağ hatası — Python API erişilemiyor')
    } finally {
      setScanning(false)
    }
  }

  const verdict = result?.verdicts?.[0]

  return (
    <div
      data-testid="rag-panel"
      className={cn(
        'border-2 border-black rounded-none bg-white flex flex-col',
        'shadow-[6px_6px_0_0_#000]',
        className,
      )}
    >
      <div className="bg-black text-white font-mono uppercase text-xs tracking-widest p-3 border-b-2 border-black">
        RAG Guard
      </div>

      <div className="p-3 space-y-2">
        <label
          htmlFor="rag-text"
          className="block text-[10px] uppercase tracking-widest text-black/60 font-bold"
        >
          Taranacak doküman metni
        </label>
        <textarea
          id="rag-text"
          data-testid="rag-input"
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={5}
          placeholder="Retrieval sonucu dönen metni buraya yapıştırın…"
          className="w-full border-2 border-black rounded-none p-2 font-mono text-xs bg-white focus:outline-none"
        />
        <button
          type="button"
          data-testid="rag-scan"
          onClick={scan}
          disabled={scanning || !text.trim()}
          className="w-full border-2 border-black bg-black text-white px-3 py-2 font-mono text-xs font-bold uppercase tracking-widest disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {scanning ? 'Taranıyor…' : 'Tara'}
        </button>
      </div>

      {error && (
        <div
          data-testid="rag-error"
          className="mx-3 mb-3 bg-red-100 border-2 border-black p-3 font-mono text-xs"
        >
          <div className="font-bold uppercase">Tarama yapılamadı</div>
          <div className="mt-1 text-black/70">{error}</div>
          <div className="mt-2 text-[10px] text-black/60">
            Bu bir bağlantı hatasıdır — &quot;belge güvenli&quot; demek DEĞİLDİR.
          </div>
        </div>
      )}

      {verdict && (
        <div className="border-t-2 border-black p-3" data-testid="rag-result">
          <span
            data-testid="rag-verdict"
            className={cn(
              'inline-block px-2 py-1 text-xs font-bold uppercase border-2 rounded-none',
              actionBadgeClass[verdict.action] || actionBadgeClass.allow,
            )}
          >
            {ragActionLabel(verdict.action)}
          </span>

          {verdict.severity && (
            <span className="ml-2 text-[10px] uppercase font-bold text-black/60">
              {verdict.severity}
            </span>
          )}

          {verdict.reasons.length > 0 && (
            <ul className="mt-2 space-y-1" data-testid="rag-reasons">
              {verdict.reasons.map((r, i) => (
                <li key={i} className="text-[10px] text-black/70 font-mono">
                  · {r}
                </li>
              ))}
            </ul>
          )}

          {verdict.findings.length > 0 && (
            <div className="mt-2 text-[10px] font-mono uppercase text-black/50">
              {verdict.findings.length} bulgu
            </div>
          )}
        </div>
      )}

      <div className="border-t-2 border-black px-3 py-2 text-[10px] font-mono uppercase tracking-widest text-black/50">
        allow · quarantine · reject
      </div>
    </div>
  )
}
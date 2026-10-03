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
  critical_triages?: number
}

/**
 * Beacon triyaj kaydı — AI/agent katmanının ürettiği değerlendirme.
 *
 * Kaynak: `public.beacon_triage` tablosu (migration 0004). Bu tablo
 * append-only'dir: kayıt üretildikten sonra değiştirilemez/silinemez.
 * `source` alanı değerlendirmeyi kimin ürettiğini açıkça söyler
 * ("llm:openai" | "llm:anthropic" | "heuristic") — dashboard'da bu
 * ayrım kullanıcıya gösterilir, çünkü heuristic ile LLM triyajı
 * aynı güvenilirlikte değildir.
 */
/**
 * Beacon triyaj kaydı — AI/agent katmanının ürettiği değerlendirme.
 *
 * Kaynak: `public.beacon_triage` tablosu (migration 0004). Bu tablo
 * append-only'dir: kayıt üretildikten sonra değiştirilemez/silinemez.
 * `source` alanı değerlendirmeyi kimin ürettiğini açıkça söyler
 * ("llm:openai" | "llm:anthropic" | "heuristic") — dashboard'da bu
 * ayrım kullanıcıya gösterilir, çünkü heuristic ile LLM triyajı
 * aynı güvenilirlikte değildir.
 */
/**
 * Kanıt zinciri kaydı — `triggered_beacons` tablosunun kanıt alanları.
 *
 * `record_hash` bir önceki kaydın hash'ini, `hmac` ise imzayı taşır.
 * Doğrulama sunucu tarafında yapılır; `hmac` alanı frontend'e sadece
 * "imzalı mı" bilgisi olarak özetlenir.
 */
export interface EvidenceChainRecord {
  token: string
  ip: string | null
  user_agent: string | null
  received_at: string
  chain_seq: number
  record_hash: string | null
}

/** Zincir doğrulama sonucu — Python `/beacon/evidence/{token}/verify` sözleşmesi. */
export interface EvidenceVerifyResult {
  token: string
  ok: boolean
  checked: number
  broken_at: number | null
  reason: string | null
}

export type TriageSeverity = 'low' | 'medium' | 'high' | 'critical'
export type TriageAction = 'ignore' | 'monitor' | 'investigate' | 'escalate'

/** Prompt canary'nin gömüldüğü bağlam — Python `ck_prompt_canary_context` ile aynı. */
export type CanaryContext = 'system_prompt' | 'rag_document' | 'agent_memory'

/**
 * Prompt-layer canary — `public.prompt_canaries` tablosu (migration 0005).
 *
 * Bir AI ajanının bağlamına gömülen yüksek entropili işaret. Aynı işaret
 * başka bir yerde görünürse bağlam sızmıştır. Tablo append-only'dir ve
 * restart dayanıklılığı için kalıcıdır (bellekte tutulsaydı sıfırlanırdı).
 *
 * `marker` alanı `[[MIRAGE-CANARY:<token>]]` biçimindedir ve frontend'de
 * **kısaltılarak** gösterilir: tam işaret ekranda görünürse, ekranı gören
 * kişi kendi canary'sini kullanabilir.
 */
export interface PromptCanary {
  id: string
  token: string
  marker: string
  context: CanaryContext
  label: string
  created_at: string // ISO8601
}

/** Canary'nin gömüldüğü bağlamı Türkçeye çevirir. */
export function canaryContextLabel(context: string): string {
  switch (context) {
    case 'system_prompt':
      return 'Sistem Prompt'
    case 'rag_document':
      return 'RAG Doküman'
    case 'agent_memory':
      return 'Ajan Hafızası'
    default:
      return context
  }
}

/**
 * Canary işaretini ekranda gösterilecek kısa biçime çevirir.
 *
 * `[[MIRAGE-CANARY:550e8400-...]]` → `MIRAGE-CANARY:550e8400…`
 * Tam işaret göstermek, işareti olan kişiye kendi işaretini
 * tanımlama imkânı verir — bu yüzden kısaltılır.
 */
export function canaryMarkerShort(marker: string): string {
  if (!marker) return '—'
  const inner = marker.replace(/^\[\[/, '').replace(/\]\]$/, '')
  const [prefix, tokenPart] = inner.split(':')
  if (!tokenPart) return inner
  return `${prefix}:${tokenPart.slice(0, 8)}…`
}

/** MCP sunucu risk seviyesi — migration 0009 `ck_mcp_audit_risk_level` ile aynı. */
export type McpRiskLevel = 'low' | 'medium' | 'high' | 'critical'

/**
 * MCP gateway denetim kaydı — `public.mcp_audit` tablosu (migration 0009).
 *
 * `allowed=false` gateway'in **fail-closed** kararıdır: çağrı engellendi.
 * Bu yüzden panelde "denied" değil "ENGELLENDİ" denir — kullanıcıya ne
 * olduğunu açık söylemek gerekir.
 */
export interface McpAuditRecord {
  id: string
  occurred_at: string // ISO8601
  actor: string
  server: string
  tool: string
  allowed: boolean
  reason: string
  risk_score: number
  risk_level: McpRiskLevel
}

/** Kalıcı denetim özeti — `/mcp/audit/log` yanıtının `summary` alanı. */
export interface McpAuditSummary {
  total: number
  allowed: number
  denied: number
  by_risk_level: Partial<Record<McpRiskLevel, number>>
}

/** `/mcp/audit/log` yanıtının tamamı. */
export interface McpAuditResponse {
  count: number
  summary: McpAuditSummary
  records: McpAuditRecord[]
}

/** RAG guard kararı — `allow | quarantine | reject`. Python `RAGVerdict` ile aynı. */
export type RagAction = 'allow' | 'quarantine' | 'reject'

/**
 * Tek bir doküman için RAG guard kararı (`POST /rag/inspect`).
 *
 * `sanitized_text` BİLİNÇLİ OLARAK response'a girmiyor: reddedilen
 * dokümanın metnini taşımak, taranan içeriği ikinci bir kanal üzerinden
 * yaymak olurdu. Panel yalnızca kararı ve gerekçeleri görür.
 */
export interface RagVerdict {
  source_id: string
  action: RagAction
  allowed: boolean
  severity: TriageSeverity | null
  findings: { name?: string; severity?: string; detail?: string }[]
  reasons: string[]
}

/** `/rag/inspect` yanıtının tamamı. */
export interface RagInspectResponse {
  verdicts: RagVerdict[]
  summary: {
    total: number
    allowed: number
    quarantined: number
    rejected: number
  }
}

const RAG_ACTION_LABELS: Record<RagAction, string> = {
  allow: 'Kabul edildi',
  quarantine: 'Karantinaya alındı',
  reject: 'Reddedildi',
}

/** RAG kararını Türkçeye çevirir. */
export function ragActionLabel(action: string): string {
  return RAG_ACTION_LABELS[action as RagAction] ?? action
}

export interface BeaconTriage {
  id: string
  token: string
  chain_seq: number | null
  severity: TriageSeverity
  confidence: number
  rationale: string
  recommended_action: TriageAction
  source: string
  chain_verified: boolean | null
  model: string | null
  created_at: string // ISO8601
}

/**
 * Triyaj kaydının LLM mi heuristic mi ürettiğini söyler.
 * LLM kayıtlarında model adı varsa onu da döndürür.
 */
export function triageSourceLabel(source: string): string {
  if (source.startsWith('llm:')) {
    const provider = source.slice(4)
    return provider === 'openai' ? 'LLM · OpenAI' : `LLM · ${provider}`
  }
  if (source === 'heuristic') return 'Kural tabanlı'
  return source
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

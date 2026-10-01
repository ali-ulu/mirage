// MIRAGE — Kanıt zinciri (evidence chain) çekirdeği (Deno / Web Crypto).
//
// Bu modül, Python karşılığı `scripts/mirage/evidence.py` ile BİREBİR aynı
// kanonikleştirme ve hash/HMAC mantığını uygular. Parite, `evidence_chain_test.ts`
// içindeki altın (golden) fixture'larla doğrulanır.
//
// Kanonik (imzalanan) alanlar:
//   token, ip, user_agent, received_at, chain_seq, prev_hash
//
// `opener_app` gibi DB tarafında türetilen görüntü kolonları kanonik kayda
// dahil edilmez (bkz. migration 0003 tasarım notu).

export const GENESIS_HASH = "0".repeat(64);

export const EVIDENCE_FIELDS = [
  "token",
  "ip",
  "user_agent",
  "received_at",
  "chain_seq",
  "prev_hash",
] as const;

export type EvidenceField = (typeof EVIDENCE_FIELDS)[number];

export interface EvidenceInput {
  token: string;
  ip: string;
  user_agent: string;
  received_at: string;
  chain_seq: number;
  prev_hash: string;
}

export interface EvidenceRecord extends EvidenceInput {
  record_hash: string;
  hmac: string;
}

const encoder = new TextEncoder();

function toHex(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let out = "";
  for (const b of bytes) out += b.toString(16).padStart(2, "0");
  return out;
}

/**
 * Kanonik JSON: yalnızca kanonik alanlar, anahtarlar sıralı, boşluksuz.
 * Python `json.dumps(..., sort_keys=True, separators=(",",":"), ensure_ascii=False)`
 * ile aynı çıktıyı üretmelidir.
 */
export function canonicalJson(record: Record<string, unknown>): string {
  const sortedKeys = [...EVIDENCE_FIELDS].sort();
  const ordered: Record<string, unknown> = {};
  for (const k of sortedKeys) {
    ordered[k] = (record as Record<string, unknown>)[k];
  }
  return JSON.stringify(ordered);
}

export async function recordHash(record: Record<string, unknown>): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", encoder.encode(canonicalJson(record)));
  return toHex(digest);
}

export async function computeHmac(key: string, recordHashHex: string): Promise<string> {
  const cryptoKey = await crypto.subtle.importKey(
    "raw",
    encoder.encode(key),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const sig = await crypto.subtle.sign("HMAC", cryptoKey, encoder.encode(recordHashHex));
  return toHex(sig);
}

export async function verifyHmac(
  key: string,
  recordHashHex: string,
  expectedHmac: string,
): Promise<boolean> {
  if (!expectedHmac) return false;
  const actual = await computeHmac(key, recordHashHex);
  // Sabit-zamanlı karşılaştırma
  if (actual.length !== expectedHmac.length) return false;
  let diff = 0;
  for (let i = 0; i < actual.length; i++) {
    diff |= actual.charCodeAt(i) ^ expectedHmac.charCodeAt(i);
  }
  return diff === 0;
}

export async function buildEvidenceRecord(
  input: EvidenceInput,
  key: string,
): Promise<EvidenceRecord> {
  const rh = await recordHash(input as unknown as Record<string, unknown>);
  const mac = await computeHmac(key, rh);
  return { ...input, record_hash: rh, hmac: mac };
}

/**
 * Kanıt imzalama anahtarını çözer.
 *   - MIRAGE_EVIDENCE_HMAC_KEY set ise onu kullanır.
 *   - Yerel açık dry-run'da sabit bir yerel anahtar döner (kod yolu yine test
 *     edilsin diye; kalıcı kayıt yapılmaz).
 *   - Aksi halde "" döner → çağıran taraf fail-closed davranmalıdır.
 */
export function resolveEvidenceKey(): string {
  const key = (Deno.env.get("MIRAGE_EVIDENCE_HMAC_KEY") || "").trim();
  if (key) return key;
  const production = (Deno.env.get("MIRAGE_ENV") || "").toLowerCase() === "production";
  const dry = (Deno.env.get("MIRAGE_EDGE_DRY_RUN") || "").trim().toLowerCase();
  const dryRun = dry === "1" || dry === "true" || dry === "yes" || dry === "on";
  if (!production && dryRun) return "mirage-local-dry-run-evidence-key";
  return "";
}

/**
 * Bir token'a ait tüm kanıt kayıtlarını chain_seq sırasıyla getirir.
 */
export async function listChain(
  client: { from(table: string): any },
  token: string,
): Promise<Array<Record<string, unknown>>> {
  const result = await client
    .from("triggered_beacons")
    .select("token, ip, user_agent, received_at, chain_seq, prev_hash, record_hash, hmac")
    .eq("token", token)
    .order("chain_seq", { ascending: true });
  if (result?.error) throw result.error;
  return Array.isArray(result?.data) ? result.data : [];
}

/**
 * Zincir başındaki (en yüksek chain_seq'li) kaydı döndürür; yoksa null.
 */
export async function getChainHead(
  client: { from(table: string): any },
  token: string,
): Promise<{ chain_seq: number; record_hash: string } | null> {
  const result = await client
    .from("triggered_beacons")
    .select("chain_seq, record_hash")
    .eq("token", token)
    .order("chain_seq", { ascending: false })
    .limit(1);
  if (result?.error) throw result.error;
  const row = Array.isArray(result?.data) ? result.data[0] : null;
  if (!row || row.chain_seq == null) return null;
  return { chain_seq: Number(row.chain_seq), record_hash: String(row.record_hash) };
}

export interface ChainVerifyResult {
  ok: boolean;
  checked: number;
  broken_at: number | null;
  reason: string | null;
}

/**
 * Sıralı kanıt kayıtlarını doğrular (Python `verify_chain` ile aynı kurallar).
 */
export async function verifyChain(
  records: Array<Record<string, unknown>>,
  key: string,
): Promise<ChainVerifyResult> {
  const ordered = [...records].sort(
    (a, b) => Number(a.chain_seq) - Number(b.chain_seq),
  );
  let prev = GENESIS_HASH;
  let checked = 0;
  for (const r of ordered) {
    checked += 1;
    const expected = await recordHash(r);
    if (expected !== r.record_hash) {
      return {
        ok: false,
        checked,
        broken_at: Number(r.chain_seq),
        reason: "record_hash mismatch (record was modified)",
      };
    }
    if (r.prev_hash !== prev) {
      return {
        ok: false,
        checked,
        broken_at: Number(r.chain_seq),
        reason: "prev_hash does not link to previous record",
      };
    }
    const hmacOk = await verifyHmac(key, String(r.record_hash), String(r.hmac ?? ""));
    if (!hmacOk) {
      return {
        ok: false,
        checked,
        broken_at: Number(r.chain_seq),
        reason: "hmac verification failed",
      };
    }
    prev = String(r.record_hash);
  }
  return { ok: true, checked, broken_at: null, reason: null };
}

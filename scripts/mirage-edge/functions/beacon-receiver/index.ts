// MIRAGE Task 03 — Beacon Receiver Edge Function
//
// Yasal çerçeve:
//   - Bu fonksiyon, honeytoken XLSX dosyaları açıldığında tetiklenen HTTP GET
//     isteklerini alır.
//   - Sadece IP adresi ve User-Agent bilgisi toplanır (Office uygulaması
//     otomatik olarak bu header'ları gönderir).
//   - DNS tunneling, makine manipülasyonu, process listesi, dosya okuma gibi
//     veriler KESİNLİKLE kabul edilmez.
//   - Tüm veri Supabase'e parametrize query ile yazılır (SQL injection'a karşı
//     dirençli).
//
// Endpoint: /functions/v1/beacon-receiver
// Methods:  GET, POST, OPTIONS
// Path:     /track/{token}  veya  query ?token={token}  veya  body {token}

import {
  createClient,
  type SupabaseClient as RealSupabaseClient,
} from "https://esm.sh/@supabase/supabase-js@2";

// =============================================================================
// Tipler
// =============================================================================

/**
 * Test edilebilirlik için Supabase client arayüzünü soyutluyoruz.
 * Gerçek uygulamada createClient() ile üretilen client bunu sağlar;
 * testlerde MockSupabaseClient kullanırız.
 */
export interface SupabaseClient {
  from(table: string): any;
}

/**
 * Honeytoken beacon'ı ile ilgili toplanan veri.
 * Yasal olarak yalnızca HTTP request'ten elde edilebilen bilgiler:
 *   - token (URL'den)
 *   - ip (CF-Connecting-IP / X-Real-IP header'larından)
 *   - user_agent (User-Agent header'ından)
 *
 * NOT: Hiçbir makine manipülasyon verisi yoktur. Bu alanların hiçbiri
 * kurban makinede kod çalıştırılarak elde edilemez.
 */
export interface BeaconPayload {
  token: string;
  ip: string;
  user_agent: string;
  received_at: string; // ISO8601
}

/**
 * MIRAGE'ın yasal çizgisi: aşağıdaki alanlar ASLA kabul edilmez.
 * Bu alanlardan herhangi biri gelen payload'da varsa istek reddedilir.
 *
 * Bunlar kurban makinede kod çalıştırarak elde edilmesi gereken bilgilerdir
 * ve MIRAGE bu tip veri toplamayı YASAKLAR.
 */
export const FORBIDDEN_PAYLOAD_KEYS: readonly string[] = [
  "process_info",      // process listesi — makine manipülasyon
  "mac_address",       // MAC adresi — makine manipülasyon
  "dns_query",         // DNS tunneling verisi
  "local_files",       // dosya içeriği — makine manipülasyon
  "shell_output",      // komut çıktısı — makine manipülasyon
  "powershell_output", // PowerShell çıktısı — makine manipülasyon
  "cmd_output",        // cmd çıktısı — makine manipülasyon
  "env_vars",          // environment değişkenleri — makine manipülasyon
  "registry",          // Windows registry — makine manipülasyon
  "screenshot",        // ekran görüntüsü — makine manipülasyon
  "clipboard",         // clipboard içeriği — makine manipülasyon
  "keylog",            // keylogger verisi — makine manipülasyon
  "credentials",       // parola çaldırma — makine manipülasyon
];

// UUID v4 regex (case-insensitive)
const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

// IPv4 validator (private range'ler hariç)
const IPV4_RE =
  /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/;

function isProduction(): boolean {
  return (Deno.env.get("MIRAGE_ENV") || "").toLowerCase() === "production";
}

function isPublicIPv4(ip: string): boolean {
  const m = IPV4_RE.exec(ip);
  if (!m) return false;
  const [a, b] = [parseInt(m[1]), parseInt(m[2])];
  if (a === 10) return false;            // 10.0.0.0/8
  if (a === 172 && b >= 16 && b <= 31) return false;  // 172.16.0.0/12
  if (a === 192 && b === 168) return false;             // 192.168.0.0/16
  if (a === 127) return false;            // loopback
  if (a === 169 && b === 254) return false; // link-local
  if (a === 0) return false;              // 0.0.0.0/8
  if (a === 100 && b >= 64 && b <= 127) return false; // CGNAT 100.64.0.0/10
  return true;
}

// =============================================================================
// Payload validation
// =============================================================================
export interface ValidationResult {
  valid: boolean;
  errors: string[];
}

export function validatePayload(input: Record<string, unknown> | object): ValidationResult {
  const errors: string[] = [];
  const obj = input as Record<string, unknown>;

  // Token kontrolü
  const token = obj.token;
  if (typeof token !== "string" || !UUID_RE.test(token)) {
    errors.push("field 'token' must be a valid UUID");
  }

  // IP kontrolü
  const ip = obj.ip;
  if (typeof ip !== "string" || !isPublicIPv4(ip)) {
    errors.push("field 'ip' must be a public IPv4 address");
  }

  // Yasaklı key'ler
  const inputKeys = Object.keys(obj);
  for (const forbidden of FORBIDDEN_PAYLOAD_KEYS) {
    if (inputKeys.includes(forbidden)) {
      errors.push(`forbidden field '${forbidden}' present — MIRAGE does not collect machine-side data`);
    }
  }

  // User-Agent opsiyonel ama string olmalı
  if ("user_agent" in obj && typeof obj.user_agent !== "string") {
    errors.push("field 'user_agent' must be a string");
  }

  return { valid: errors.length === 0, errors };
}

// =============================================================================
// Token extraction
// =============================================================================
/**
 * Token'ı URL path, query veya body'den çeker.
 * Async çünkü POST body'sini parse etmek gerekebilir.
 *
 * Testlerde direkt await ile çağrılır.
 */
export async function extractToken(req: Request): Promise<string | null> {
  // 1. URL path: /track/{token}
  const url = new URL(req.url);
  const pathMatch = /\/track\/([0-9a-f-]{36})/i.exec(url.pathname);
  if (pathMatch) {
    const token = pathMatch[1].toLowerCase();
    if (UUID_RE.test(token)) return token;
  }

  // 2. Query parametresi
  const queryToken = url.searchParams.get("token");
  if (queryToken && UUID_RE.test(queryToken)) {
    return queryToken.toLowerCase();
  }

  // 3. Body (POST/PUT)
  if (req.method === "POST" || req.method === "PUT") {
    try {
      const text = await req.clone().text();
      if (text) {
        const body = JSON.parse(text);
        if (
          body && typeof body === "object" &&
          typeof body.token === "string" &&
          UUID_RE.test(body.token)
        ) {
          return body.token.toLowerCase();
        }
      }
    } catch {
      // body JSON değil — yut
    }
  }

  return null;
}

// =============================================================================
// Client info extraction
// =============================================================================
export interface ClientInfo {
  ip: string;
  userAgent: string;
}

export function extractClientInfo(req: Request): ClientInfo {
  const headers = req.headers;
  // Prod'da yalnızca trusted proxy header'ını kabul et.
  // Local/test çalıştırmalarında X-Real-IP fallback'i koru.
  const ip = headers.get("cf-connecting-ip") ||
    (isProduction() ? "" : headers.get("x-real-ip") || "");
  const userAgent = headers.get("user-agent") || "";
  return { ip, userAgent };
}

// =============================================================================
// Rate Limiter (in-memory, per-instance)
// =============================================================================
export interface RateLimiterConfig {
  windowMs: number;
  maxRequests: number;
}

export class RateLimiter {
  private hits: Map<string, number[]> = new Map();
  private config: RateLimiterConfig;

  constructor(config: RateLimiterConfig) {
    this.config = config;
  }

  check(key: string): boolean {
    const now = Date.now();
    const windowStart = now - this.config.windowMs;
    const history = this.hits.get(key) || [];
    // Window dışındaki kayıtları temizle
    const recent = history.filter((t) => t > windowStart);
    if (recent.length >= this.config.maxRequests) {
      this.hits.set(key, recent);
      return false;
    }
    recent.push(now);
    this.hits.set(key, recent);
    return true;
  }

  // Test'ler için: state'i temizle
  reset(): void {
    this.hits.clear();
  }
}

async function checkDatabaseRateLimit(
  client: SupabaseClient,
  ip: string,
  windowMs: number,
  maxRequests: number,
): Promise<boolean> {
  const since = new Date(Date.now() - windowMs).toISOString();
  const query = client
    .from("triggered_beacons")
    .select("id", { count: "exact", head: true })
    .eq("ip", ip)
    .gt("received_at", since);
  const result = await query;
  if (result?.error) {
    throw result.error;
  }
  const count = typeof result?.count === "number" ? result.count : 0;
  return count < maxRequests;
}

async function logSabotageEvent(
  client: SupabaseClient,
  event: {
    eventType: string;
    token?: string | null;
    ip?: string | null;
    details?: Record<string, unknown>;
  },
): Promise<void> {
  try {
    await client.from("sabotage_logs").insert({
      event_type: event.eventType,
      token: event.token ?? null,
      ip: event.ip ?? null,
      details: event.details ?? null,
    });
  } catch (err) {
    console.error("sabotage_logs insert failed:", err);
  }
}

// =============================================================================
// Ana handler
// =============================================================================
const CORS_HEADERS: Record<string, string> = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET, POST, OPTIONS",
  "access-control-allow-headers": "Content-Type, Authorization",
  "access-control-max-age": "86400",
};

function jsonResponse(
  status: number,
  body: unknown,
  extraHeaders: Record<string, string> = {},
): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "content-type": "application/json",
      ...CORS_HEADERS,
      ...extraHeaders,
    },
  });
}

export async function handleRequest(
  req: Request,
  client: SupabaseClient,
  rateLimiter: RateLimiter,
): Promise<Response> {
  // 1. CORS preflight
  if (req.method === "OPTIONS") {
    return new Response(null, { status: 200, headers: CORS_HEADERS });
  }

  // 2. Method kontrolü
  if (req.method !== "GET" && req.method !== "POST") {
    return jsonResponse(405, { error: "method not allowed" }, {
      "allow": "GET, POST, OPTIONS",
    });
  }

  // 3. Token'ı çek
  const token = await extractToken(req);
  if (!token) {
    await logSabotageEvent(client, {
      eventType: "missing_or_invalid_token",
      details: {
        method: req.method,
      },
    });
    return jsonResponse(400, { error: "missing or invalid token" });
  }

  // 3b. POST body'sini de validate et — yasaklı alanlar içeriyorsa reddet
  // (defense in depth: kullanmasak bile, saldırganın bunları göndermeye çalışması
  //  MIRAGE'ın yasal çizgisini test ettiği için reddedilmeli)
  if (req.method === "POST") {
    try {
      const text = await req.clone().text();
      if (text) {
        const body = JSON.parse(text);
        if (body && typeof body === "object") {
          const bodyKeys = Object.keys(body);
          const forbidden = FORBIDDEN_PAYLOAD_KEYS.filter((k) => bodyKeys.includes(k));
          if (forbidden.length > 0) {
            await logSabotageEvent(client, {
              eventType: "forbidden_payload",
              token,
              ip: extractClientInfo(req).ip || null,
              details: {
                fields: forbidden,
              },
            });
            return jsonResponse(400, {
              error: "forbidden fields in payload",
              details: forbidden.map((k) =>
                `field '${k}' is not accepted — MIRAGE does not collect machine-side data`
              ),
            });
          }
        }
      }
    } catch {
      // body JSON değil — yut
    }
  }

  // 4. Client info
  const clientInfo = extractClientInfo(req);
  if (isProduction() && !clientInfo.ip) {
    await logSabotageEvent(client, {
      eventType: "missing_trusted_ip",
      token,
      details: {
        source: "production",
      },
    });
    return jsonResponse(400, { error: "missing trusted client ip" });
  }

  // 5. Rate limit (IP bazlı)
  const rateLimitKey = clientInfo.ip || "unknown";
  const rateLimitAllowed = isProduction()
    ? await checkDatabaseRateLimit(client, rateLimitKey, 60_000, 30)
    : rateLimiter.check(rateLimitKey);
  if (!rateLimitAllowed) {
    await logSabotageEvent(client, {
      eventType: "rate_limited",
      token,
      ip: clientInfo.ip || null,
      details: {
        window_ms: 60_000,
        max_requests: 30,
        source: isProduction() ? "database" : "memory",
      },
    });
    return jsonResponse(429, { error: "rate limit exceeded" }, {
      "retry-after": "60",
    });
  }

  // 6. Payload'ı oluştur (sadece yasal alanlar)
  const payload: BeaconPayload = {
    token,
    ip: clientInfo.ip,
    user_agent: clientInfo.userAgent,
    received_at: new Date().toISOString(),
  };

  // 7. Validate (private IP, format vs.)
  const validation = validatePayload(payload);
  if (!validation.valid) {
    await logSabotageEvent(client, {
      eventType: "validation_failed",
      token,
      ip: clientInfo.ip || null,
      details: {
        errors: validation.errors,
      },
    });
    return jsonResponse(400, { error: "validation failed", details: validation.errors });
  }

  // 8. triggered_beacons tablosuna insert
  // (sabotage_logs tablosu DB-side trigger ile triggered_beacons insert'inde
  // otomatik doldurulur — burada ayrıca yazmaya gerek yok)
  try {
    await client.from("triggered_beacons").insert({
      token: payload.token,
      ip: payload.ip,
      user_agent: payload.user_agent,
      received_at: payload.received_at,
    });
  } catch (err) {
    console.error("triggered_beacons insert failed:", err);
    return jsonResponse(500, { error: "internal error" });
  }

  return jsonResponse(200, { status: "ok", token: payload.token });
}

// =============================================================================
// Supabase Edge Function entry point
//
// Deno.serve, supabase functions CLI tarafından çağrılır. Local testlerde
// handleRequest doğrudan test edilir; bu blok sadece production için.
// =============================================================================

export interface RuntimeConfig {
  supabaseUrl: string;
  supabaseServiceRoleKey: string;
  dryRunRequested: boolean;
  production: boolean;
}

function envFlag(name: string): boolean {
  const value = (Deno.env.get(name) || "").trim().toLowerCase();
  return value === "1" || value === "true" || value === "yes" || value === "on";
}

export function getRuntimeConfig(): RuntimeConfig {
  return {
    supabaseUrl: Deno.env.get("SUPABASE_URL") || "",
    supabaseServiceRoleKey: Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "",
    dryRunRequested: envFlag("MIRAGE_EDGE_DRY_RUN"),
    production: isProduction(),
  };
}

export function getRuntimeConfigError(config: RuntimeConfig = getRuntimeConfig()): string | null {
  const hasSupabase = Boolean(config.supabaseUrl && config.supabaseServiceRoleKey);
  if (hasSupabase) return null;
  if (!config.production && config.dryRunRequested) return null;
  if (config.production) {
    return "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required in production";
  }
  return "Supabase config missing; set MIRAGE_EDGE_DRY_RUN=true only for explicit local dry-run";
}

export function shouldUseDryRun(config: RuntimeConfig = getRuntimeConfig()): boolean {
  return !config.production && config.dryRunRequested && !(config.supabaseUrl && config.supabaseServiceRoleKey);
}

let cachedClient: SupabaseClient | null = null;

// Null client — explicit local/test dry-run mode only.
class NullSupabaseClient implements SupabaseClient {
  from(_table: string) {
    const noop = async () => ({ data: null, error: null });
    const chain = {
      insert: (_p: Record<string, unknown>) => Promise.resolve({ data: null, error: null }),
      select: () => chain,
      eq: () => chain,
      gt: () => chain,
      then: (resolve: (value: unknown) => unknown, reject: (reason?: unknown) => unknown) =>
        Promise.resolve({ data: null, count: 0, error: null }).then(resolve, reject),
      catch: (reject: (reason?: unknown) => unknown) =>
        Promise.resolve({ data: null, count: 0, error: null }).catch(reject),
    };
    return chain;
  }
}

function getClient(): SupabaseClient {
  if (cachedClient) return cachedClient;
  const config = getRuntimeConfig();
  const configError = getRuntimeConfigError(config);
  if (configError) {
    throw new Error(configError);
  }
  if (shouldUseDryRun(config)) {
    console.log("[MIRAGE] Running in explicit local DRY-RUN mode");
    cachedClient = new NullSupabaseClient();
    return cachedClient;
  }
  const real = createClient(config.supabaseUrl, config.supabaseServiceRoleKey, {
    auth: { persistSession: false },
  }) as unknown as SupabaseClient;
  cachedClient = real;
  return real;
}

function getLimiter(): RateLimiter {
  return new RateLimiter({
    windowMs: 60_000,
    maxRequests: 30,
  });
}

// Sadece supabase CLI üzerinden çalıştırıldığında aktif olmalı
// Test'lerde handleRequest doğrudan çağrılır, Deno.serve çalıştırılmaz
// (Test'lerde DENO_TESTING env set edilir)
if (typeof Deno.serve === "function" && !Deno.env.get("DENO_TESTING")) {
  Deno.serve(async (req: Request) => {
    const configError = getRuntimeConfigError();
    if (configError) {
      return jsonResponse(503, { error: "supabase config missing", detail: configError });
    }

    try {
      return await handleRequest(req, getClient(), getLimiter());
    } catch (err) {
      console.error("unhandled error:", err);
      return jsonResponse(500, { error: "internal server error" });
    }
  });
}

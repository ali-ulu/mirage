// MIRAGE Task 03 — Beacon Receiver Edge Function Test Suite (TDD)
//
// Bu testler, /functions/v1/beacon-receiver Edge Function'ının davranışlarını
// doğrular. TDD prensibi: önce testler yazıldı, sonra implementasyon.
//
// Çalıştırma:
//   deno test --allow-net --allow-env --allow-read tests/beacon_receiver_test.ts
//
// Test kategorileri:
//   1. Payload validation (geçersiz istekler reddedilir)
//   2. Token extraction (URL path'inden token çekilir)
//   3. Rate limiting (aynı IP'den çok fazla istek reddedilir)
//   4. SQL injection koruması (parametrize query, hiçbir user input SQL'e gömülmez)
//   5. HTTP metod kısıtı (sadece GET ve POST kabul edilir)
//   6. Veri yazımı (mock Supabase'e doğru alanlar yazılır)
//   7. CORS headers (OPTIONS preflight)
//   8. Yasal sınırlar (DNS tunneling verisi, makine manipülasyon verisi KESİNLİKLE kabul edilmez)

import {
  assert,
  assertEquals,
  assertNotEquals,
  assertObjectMatch,
} from "https://deno.land/std@0.224.0/assert/mod.ts";
import {
  stub,
  type Stub,
} from "https://deno.land/std@0.224.0/testing/mock.ts";

// Test edilen modül (henüz yok — RED expected)
import {
  handleRequest,
  extractToken,
  validatePayload,
  RateLimiter,
  extractClientInfo,
  FORBIDDEN_PAYLOAD_KEYS,
  type BeaconPayload,
  type SupabaseClient,
} from "../functions/beacon-receiver/index.ts";

// --- Mock Supabase Client ---------------------------------------------------
//
// Edge function gerçek Supabase'e yazmaz; bunun yerine bize verilen client
// objesinin .from(table).insert(payload) metodunu çağırır. Testlerde bu
// client'ı stub'lıyoruz.

type InsertCall = { table: string; payload: Record<string, unknown> };

class MockSupabaseClient implements SupabaseClient {
  public inserts: InsertCall[] = [];

  from(table: string) {
    const filters: Record<string, unknown> = {};
    const selectOpts: Record<string, unknown> = {};
    const builder: Record<string, any> = {};

    builder.insert = (payload: Record<string, unknown>) => {
      this.inserts.push({ table, payload });
      return Promise.resolve({ data: null, error: null });
    };

    builder.select = (_columns: string, opts?: Record<string, unknown>) => {
      Object.assign(selectOpts, opts || {});
      return builder;
    };

    builder.eq = (column: string, value: unknown) => {
      filters[column] = value;
      return builder;
    };

    builder.gt = (column: string, value: unknown) => {
      filters[`gt_${column}`] = value;
      return builder;
    };

    builder.order = () => builder;
    builder.limit = () => builder;
    builder.is = () => builder;

    builder.execute = async () => {
      if (table === "triggered_beacons" && selectOpts.count === "exact") {
        const ip = String(filters.ip || "");
        const since = String(filters.gt_received_at || "");
        const count = this.inserts.filter((row) => {
          if (row.table !== "triggered_beacons") return false;
          const payload = row.payload;
          const rowIp = String(payload.ip || "");
          const rowReceivedAt = String(payload.received_at || "");
          return rowIp === ip && rowReceivedAt > since;
        }).length;
        return { data: null, count, error: null };
      }
      return { data: null, count: null, error: null };
    };

    builder.then = (resolve: (value: any) => any, reject: (reason?: any) => any) =>
      Promise.resolve(builder.execute()).then(resolve, reject);
    builder.catch = (reject: (reason?: any) => any) =>
      Promise.resolve(builder.execute()).catch(reject);

    return builder;
  }
}

// Helper: HTTP istek objesi oluştur
function makeRequest(
  method: string,
  url: string,
  body?: unknown,
  headers: Record<string, string> = {},
): Request {
  const init: RequestInit = {
    method,
    headers: new Headers(headers),
  };
  if (body !== undefined && method !== "GET" && method !== "HEAD") {
    init.body = typeof body === "string" ? body : JSON.stringify(body);
    if (!headers["content-type"]) {
      (init.headers as Headers).set("content-type", "application/json");
    }
  }
  return new Request(url, init);
}

// =============================================================================
// 1. PAYERLOAD VALIDATION
// =============================================================================
Deno.test("validatePayload: geçerli token + IP kabul edilir", () => {
  const result = validatePayload({
    token: "550e8400-e29b-41d4-a716-446655440000",
    ip: "203.0.113.42",
    user_agent: "Mozilla/5.0",
  });
  assertEquals(result.valid, true);
  assertEquals(result.errors.length, 0);
});

Deno.test("validatePayload: geçersiz UUID token reddedilir", () => {
  const result = validatePayload({
    token: "not-a-uuid",
    ip: "203.0.113.42",
  });
  assertEquals(result.valid, false);
  assert(result.errors.some((e: string) => e.includes("token")));
});

Deno.test("validatePayload: eksik token reddedilir", () => {
  const result = validatePayload({ ip: "203.0.113.42" });
  assertEquals(result.valid, false);
});

Deno.test("validatePayload: geçersiz IP reddedilir", () => {
  const result = validatePayload({
    token: "550e8400-e29b-41d4-a716-446655440000",
    ip: "not-an-ip",
  });
  assertEquals(result.valid, false);
  assert(result.errors.some((e: string) => e.includes("ip")));
});

Deno.test("validatePayload: private IP reddedilir (saldırgan olamaz)", () => {
  // 10.0.0.1, 192.168.1.1 gibi adresler kabul edilmemeli — bunlar internal
  // networklerdir, saldırganın gerçek kaynağı olamazlar.
  const privateIps = ["10.0.0.1", "192.168.1.1", "172.16.0.1", "127.0.0.1"];
  for (const ip of privateIps) {
    const result = validatePayload({
      token: "550e8400-e29b-41d4-a716-446655440000",
      ip,
    });
    assertEquals(result.valid, false, `private IP ${ip} should be rejected`);
  }
});

Deno.test("handleRequest: yasaklÄ± payload alanÄ± 400 dÃ¶ner ve audit yazar", async () => {
  const mockClient = new MockSupabaseClient();
  const limiter = new RateLimiter({ windowMs: 1000, maxRequests: 100 });
  const req = makeRequest(
    "POST",
    "https://beacon.example/track/550e8400-e29b-41d4-a716-446655440000",
    {
      token: "550e8400-e29b-41d4-a716-446655440000",
      process_info: ["powershell.exe"],
    },
    { "x-real-ip": "203.0.113.42" },
  );
  const res = await handleRequest(req, mockClient, limiter);
  assertEquals(res.status, 400);
  assertEquals(mockClient.inserts.filter((x) => x.table === "triggered_beacons").length, 0);
  assertEquals(mockClient.inserts.filter((x) => x.table === "sabotage_logs").length, 1);
});

Deno.test("handleRequest: private IP validation hatasÄ± audit'e dÃ¼ÅŸer", async () => {
  const mockClient = new MockSupabaseClient();
  const limiter = new RateLimiter({ windowMs: 1000, maxRequests: 100 });
  const token = "550e8400-e29b-41d4-a716-446655440000";
  const req = makeRequest("GET", `https://beacon.example/track/${token}`, null, {
    "x-real-ip": "10.0.0.1",
  });
  const res = await handleRequest(req, mockClient, limiter);
  assertEquals(res.status, 400);
  assertEquals(mockClient.inserts.filter((x) => x.table === "triggered_beacons").length, 0);
  assertEquals(mockClient.inserts.filter((x) => x.table === "sabotage_logs").length, 1);
});

// =============================================================================
// 2. GÜVENLİK — Yasaklı payload key'leri (DNS tunneling, makine manipülasyon)
// =============================================================================
Deno.test("FORBIDDEN_PAYLOAD_KEYS: makine manipülasyon verisi yasaklı", () => {
  // Aşağıdaki alanlar MIRAGE'ın yasal çizgisini ihlal eder:
  // - process_info: kurban makinede process listesi → makine manipülasyon
  // - mac_address: kurban makinenin MAC adresi → makine manipülasyon
  // - dns_query: DNS tunneling için query → yasaklı teknik
  // - local_files: kurban makinede dosya okuma → makine manipülasyon
  // - shell_output: komut çıktısı → makine manipülasyon
  const expected = [
    "process_info",
    "mac_address",
    "dns_query",
    "local_files",
    "shell_output",
    "powershell_output",
    "cmd_output",
    "env_vars",
    "registry",
    "screenshot",
  ];
  for (const k of expected) {
    assert(
      FORBIDDEN_PAYLOAD_KEYS.includes(k),
      `Yasaklı key eksik: ${k}`,
    );
  }
});

Deno.test("validatePayload: yasaklı key içeren payload reddedilir", () => {
  const result = validatePayload({
    token: "550e8400-e29b-41d4-a716-446655440000",
    ip: "203.0.113.42",
    mac_address: "AA:BB:CC:DD:EE:FF", // YASAKLI
  });
  assertEquals(result.valid, false);
  assert(result.errors.some((e: string) => e.toLowerCase().includes("forbidden")));
});

Deno.test("validatePayload: birden fazla yasaklı key reddedilir", () => {
  const result = validatePayload({
    token: "550e8400-e29b-41d4-a716-446655440000",
    ip: "203.0.113.42",
    process_info: "list of running processes",
    local_files: "/etc/passwd",
    dns_query: "evil.example.com",
  });
  assertEquals(result.valid, false);
  assert(result.errors.length >= 3);
});

// =============================================================================
// 3. TOKEN EXTRACTION
// =============================================================================
Deno.test("extractToken: /track/{token} yolundan UUID çekilir", async () => {
  const token = "550e8400-e29b-41d4-a716-446655440000";
  const req = makeRequest("GET", `https://beacon.example/track/${token}`);
  const extracted = await extractToken(req);
  assertEquals(extracted, token);
});

Deno.test("extractToken: query parametresinden token çekilir", async () => {
  const token = "550e8400-e29b-41d4-a716-446655440000";
  const req = makeRequest("GET", `https://beacon.example/?token=${token}`);
  const extracted = await extractToken(req);
  assertEquals(extracted, token);
});

Deno.test("extractToken: body'deki token çekilir (POST)", async () => {
  const token = "550e8400-e29b-41d4-a716-446655440000";
  const req = makeRequest("POST", "https://beacon.example/", { token });
  const extracted = await extractToken(req);
  assertEquals(extracted, token);
});

Deno.test("extractToken: token yoksa null döner", async () => {
  const req = makeRequest("GET", "https://beacon.example/");
  const extracted = await extractToken(req);
  assertEquals(extracted, null);
});

Deno.test("extractToken: geçersiz format token null döner", async () => {
  const req = makeRequest("GET", "https://beacon.example/track/not-a-uuid");
  const extracted = await extractToken(req);
  assertEquals(extracted, null);
});

// =============================================================================
// 4. RATE LIMITING
// =============================================================================
Deno.test("RateLimiter: ilk N istek kabul edilir", () => {
  const limiter = new RateLimiter({ windowMs: 1000, maxRequests: 5 });
  const ip = "203.0.113.42";
  for (let i = 0; i < 5; i++) {
    const ok = limiter.check(ip);
    assertEquals(ok, true, `request ${i + 1} should be allowed`);
  }
});

Deno.test("RateLimiter: limit aşılınca reddedilir", () => {
  const limiter = new RateLimiter({ windowMs: 1000, maxRequests: 3 });
  const ip = "203.0.113.42";
  for (let i = 0; i < 3; i++) limiter.check(ip);
  const result = limiter.check(ip);
  assertEquals(result, false);
});

Deno.test("RateLimiter: farklı IP'ler ayrı sayılır", () => {
  const limiter = new RateLimiter({ windowMs: 1000, maxRequests: 2 });
  const ip1 = "203.0.113.42";
  const ip2 = "203.0.113.43";
  assertEquals(limiter.check(ip1), true);
  assertEquals(limiter.check(ip1), true);
  assertEquals(limiter.check(ip2), true); // farklı IP, ayrı limit
  assertEquals(limiter.check(ip1), false); // ip1 limit doldu
});

Deno.test("RateLimiter: window sonrası reset", async () => {
  const limiter = new RateLimiter({ windowMs: 50, maxRequests: 1 });
  const ip = "203.0.113.42";
  assertEquals(limiter.check(ip), true);
  assertEquals(limiter.check(ip), false);
  await new Promise((r) => setTimeout(r, 60));
  assertEquals(limiter.check(ip), true);
});

// =============================================================================
// 5. CLIENT INFO EXTRACTION
// =============================================================================
Deno.test("extractClientInfo: X-Real-IP tercih edilir", () => {
  const req = makeRequest("GET", "https://beacon.example/track/x", null, {
    "x-real-ip": "203.0.113.42",
    "user-agent": "LibreOffice/7.5",
  });
  const info = extractClientInfo(req);
  assertEquals(info.ip, "203.0.113.42");
  assertEquals(info.userAgent, "LibreOffice/7.5");
});

Deno.test("extractClientInfo: CF-Connecting-IP fallback", () => {
  const req = makeRequest("GET", "https://beacon.example/track/x", null, {
    "cf-connecting-ip": "198.51.100.7",
    "user-agent": "Excel/16.0",
  });
  const info = extractClientInfo(req);
  assertEquals(info.ip, "198.51.100.7");
});

Deno.test("extractClientInfo: headers yoksa boş string", () => {
  const req = makeRequest("GET", "https://beacon.example/track/x");
  const info = extractClientInfo(req);
  assert(typeof info.ip === "string");
  assert(typeof info.userAgent === "string");
});

// =============================================================================
// 6. HTTP METOD KISITLARI
// =============================================================================
Deno.test("handleRequest: GET isteği kabul edilir", async () => {
  const mockClient = new MockSupabaseClient();
  const limiter = new RateLimiter({ windowMs: 1000, maxRequests: 100 });
  const token = "550e8400-e29b-41d4-a716-446655440000";
  const req = makeRequest("GET", `https://beacon.example/track/${token}`, null, {
    "x-real-ip": "203.0.113.42",
    "user-agent": "LibreOffice/7.5",
  });
  const res = await handleRequest(req, mockClient, limiter);
  assertEquals(res.status, 200);
  // Mock client'a yazım yapılmış mı
  assertEquals(mockClient.inserts.length, 1);
  assertEquals(mockClient.inserts[0].table, "triggered_beacons");
});

Deno.test("handleRequest: POST isteği kabul edilir", async () => {
  const mockClient = new MockSupabaseClient();
  const limiter = new RateLimiter({ windowMs: 1000, maxRequests: 100 });
  const token = "550e8400-e29b-41d4-a716-446655440000";
  // IP header'dan geliyor (X-Real-IP), body'den değil
  const req = makeRequest(
    "POST",
    "https://beacon.example/",
    { token, user_agent: "Excel/16.0" },
    { "x-real-ip": "203.0.113.42" },
  );
  const res = await handleRequest(req, mockClient, limiter);
  assertEquals(res.status, 200);
  assertEquals(mockClient.inserts.length, 1);
});

Deno.test("handleRequest: DELETE metodu reddedilir (405)", async () => {
  const mockClient = new MockSupabaseClient();
  const limiter = new RateLimiter({ windowMs: 1000, maxRequests: 100 });
  const req = makeRequest("DELETE", "https://beacon.example/track/x");
  const res = await handleRequest(req, mockClient, limiter);
  assertEquals(res.status, 405);
  assertEquals(mockClient.inserts.filter((x) => x.table === "triggered_beacons").length, 0);
  assertEquals(mockClient.inserts.filter((x) => x.table === "sabotage_logs").length, 1);
});

Deno.test("handleRequest: PUT metodu reddedilir (405)", async () => {
  const mockClient = new MockSupabaseClient();
  const limiter = new RateLimiter({ windowMs: 1000, maxRequests: 100 });
  const req = makeRequest("PUT", "https://beacon.example/track/x");
  const res = await handleRequest(req, mockClient, limiter);
  assertEquals(res.status, 405);
});

Deno.test("handleRequest: PATCH metodu reddedilir (405)", async () => {
  const mockClient = new MockSupabaseClient();
  const limiter = new RateLimiter({ windowMs: 1000, maxRequests: 100 });
  const req = makeRequest("PATCH", "https://beacon.example/track/x");
  const res = await handleRequest(req, mockClient, limiter);
  assertEquals(res.status, 405);
});

// =============================================================================
// 7. CORS / OPTIONS PREFLIGHT
// =============================================================================
Deno.test("handleRequest: OPTIONS preflight 200 + CORS headers", async () => {
  const mockClient = new MockSupabaseClient();
  const limiter = new RateLimiter({ windowMs: 1000, maxRequests: 100 });
  const req = makeRequest("OPTIONS", "https://beacon.example/track/x");
  const res = await handleRequest(req, mockClient, limiter);
  assertEquals(res.status, 200);
  assert(res.headers.get("access-control-allow-origin") !== null);
  assert(res.headers.get("access-control-allow-methods") !== null);
});

// =============================================================================
// 8. RATE LIMIT ENFORCEMENT
// =============================================================================
Deno.test("handleRequest: rate limit aşıldığında 429 döner", async () => {
  const mockClient = new MockSupabaseClient();
  const limiter = new RateLimiter({ windowMs: 10000, maxRequests: 2 });
  const token = "550e8400-e29b-41d4-a716-446655440000";
  const headers = { "x-real-ip": "203.0.113.99", "user-agent": "x" };

  // İlk 2 istek başarılı
  for (let i = 0; i < 2; i++) {
    const r = await handleRequest(
      makeRequest("GET", `https://beacon.example/track/${token}`, null, headers),
      mockClient,
      limiter,
    );
    assertEquals(r.status, 200);
  }
  // 3. istek reddedilir
  const r = await handleRequest(
    makeRequest("GET", `https://beacon.example/track/${token}`, null, headers),
    mockClient,
    limiter,
  );
  assertEquals(r.status, 429);
  // Mock client'a sadece 2 yazım yapılmış olmalı
  assertEquals(mockClient.inserts.filter((x) => x.table === "triggered_beacons").length, 2);
  assertEquals(mockClient.inserts.filter((x) => x.table === "sabotage_logs").length, 1);
});

// =============================================================================
// 9. VERİ YAZIMI — mock client'a doğru alanlar yazılıyor mu
// =============================================================================
Deno.test("handleRequest: triggered_beacons tablosuna doğru şema yazılır", async () => {
  const mockClient = new MockSupabaseClient();
  const limiter = new RateLimiter({ windowMs: 1000, maxRequests: 100 });
  const token = "550e8400-e29b-41d4-a716-446655440000";
  const req = makeRequest(
    "GET",
    `https://beacon.example/track/${token}`,
    null,
    {
      "x-real-ip": "203.0.113.42",
      "user-agent": "LibreOffice/7.5",
    },
  );
  await handleRequest(req, mockClient, limiter);

  const insert = mockClient.inserts[0];
  assertEquals(insert.table, "triggered_beacons");
  const payload = insert.payload;
  assertEquals(payload.token, token);
  assertEquals(payload.ip, "203.0.113.42");
  assertEquals(payload.user_agent, "LibreOffice/7.5");
  assert(typeof payload.received_at === "string");
  // Yasaklı alanlar yazılmamış olmalı
  for (const key of FORBIDDEN_PAYLOAD_KEYS) {
    assert(!(key in payload), `Yasaklı alan ${key} veritabanına yazıldı!`);
  }
});

Deno.test("handleRequest: attacker güncellemesini DB trigger'a bırakır", async () => {
  // Çift sayaç bug'ını önlemek için Edge Function yalnızca triggered_beacons insert eder.
  // attackers tablosu, migration'daki trg_upsert_attacker trigger'ı ile güncellenir.
  const mockClient = new MockSupabaseClient();
  const limiter = new RateLimiter({ windowMs: 1000, maxRequests: 100 });
  const token = "550e8400-e29b-41d4-a716-446655440000";
  const req = makeRequest(
    "GET",
    `https://beacon.example/track/${token}`,
    null,
    { "x-real-ip": "203.0.113.42", "user-agent": "Excel/16.0" },
  );
  await handleRequest(req, mockClient, limiter);

  assertEquals(mockClient.inserts.length, 1);
  assertEquals(mockClient.inserts[0].table, "triggered_beacons");
});

// =============================================================================
// 10. GEÇERSİZ TOKEN — kayıt yazılmaz ama loglanır
// =============================================================================
Deno.test("handleRequest: geçersiz token 400 döner, DB'ye yazılmaz", async () => {
  const mockClient = new MockSupabaseClient();
  const limiter = new RateLimiter({ windowMs: 1000, maxRequests: 100 });
  const req = makeRequest(
    "GET",
    "https://beacon.example/track/not-a-uuid",
    null,
    { "x-real-ip": "203.0.113.42" },
  );
  const res = await handleRequest(req, mockClient, limiter);
  assertEquals(res.status, 400);
  assertEquals(mockClient.inserts.filter((x) => x.table === "triggered_beacons").length, 0);
  assertEquals(mockClient.inserts.filter((x) => x.table === "sabotage_logs").length, 1);
});

// =============================================================================
// 11. SQL INJECTION KORUMASI — parametrize query kullanımı
// =============================================================================
Deno.test("handleRequest: user input SQL'e gömülmez (parametrize)", async () => {
  // SQL injection denemesi — User-Agent header'ına kötü niyetli string koy.
  // IP geçerli bir public IPv4 olmalı (validation), ama User-Agent
  // serbest formatlı string — Supabase client parametrize query kullandığı
  // için bu bir sorun değil.
  const mockClient = new MockSupabaseClient();
  const limiter = new RateLimiter({ windowMs: 1000, maxRequests: 100 });
  const req = makeRequest(
    "GET",
    "https://beacon.example/track/550e8400-e29b-41d4-a716-446655440000",
    null,
    {
      "x-real-ip": "203.0.113.42",
      "user-agent": "'; DELETE FROM triggered_beacons; --",
    },
  );
  const res = await handleRequest(req, mockClient, limiter);
  assertEquals(res.status, 200);
  // Eğer user input SQL'e gömülseydi Supabase client patlardı.
  // Parametrize query sayesinde string literal olarak saklandı:
  const insert = mockClient.inserts[0];
  assertEquals(
    insert.payload.user_agent,
    "'; DELETE FROM triggered_beacons; --",
  );
  assertEquals(insert.payload.ip, "203.0.113.42");
});

// =============================================================================
// 12. URL YANSITMA — üretilen response başarılı olduğunda tracking URL'i içerir
// =============================================================================
Deno.test("handleRequest: 200 response küçük JSON döner (debugging için)", async () => {
  const mockClient = new MockSupabaseClient();
  const limiter = new RateLimiter({ windowMs: 1000, maxRequests: 100 });
  const token = "550e8400-e29b-41d4-a716-446655440000";
  const req = makeRequest("GET", `https://beacon.example/track/${token}`, null, {
    "x-real-ip": "203.0.113.42",
  });
  const res = await handleRequest(req, mockClient, limiter);
  assertEquals(res.status, 200);
  const body = await res.json();
  assert(typeof body === "object");
  assertEquals(body.status, "ok");
});
Deno.test("handleRequest: production'ta trusted IP yoksa reddeder", async () => {
  const oldEnv = Deno.env.get("MIRAGE_ENV");
  Deno.env.set("MIRAGE_ENV", "production");
  try {
    const mockClient = new MockSupabaseClient();
    const limiter = new RateLimiter({ windowMs: 1000, maxRequests: 100 });
    const token = "550e8400-e29b-41d4-a716-446655440000";
    const req = makeRequest("GET", `https://beacon.example/track/${token}`);
    const res = await handleRequest(req, mockClient, limiter);
    assertEquals(res.status, 400);
    assertEquals(mockClient.inserts.filter((x) => x.table === "triggered_beacons").length, 0);
    assertEquals(mockClient.inserts.filter((x) => x.table === "sabotage_logs").length, 1);
  } finally {
    if (oldEnv === undefined) Deno.env.delete("MIRAGE_ENV");
    else Deno.env.set("MIRAGE_ENV", oldEnv);
  }
});

Deno.test("handleRequest: production'ta DB tabanlı rate limit kalıcıdır", async () => {
  const oldEnv = Deno.env.get("MIRAGE_ENV");
  Deno.env.set("MIRAGE_ENV", "production");
  try {
    const mockClient = new MockSupabaseClient();
    const limiter = new RateLimiter({ windowMs: 1000, maxRequests: 100 });
    const token = "550e8400-e29b-41d4-a716-446655440000";
    const headers = {
      "cf-connecting-ip": "203.0.113.42",
      "user-agent": "LibreOffice/7.5",
    };

    for (let i = 0; i < 30; i++) {
      const res = await handleRequest(
        makeRequest("GET", `https://beacon.example/track/${token}`, null, headers),
        mockClient,
        limiter,
      );
      assertEquals(res.status, 200);
    }

    const blocked = await handleRequest(
      makeRequest("GET", `https://beacon.example/track/${token}`, null, headers),
      mockClient,
      limiter,
    );
    assertEquals(blocked.status, 429);
    assertEquals(mockClient.inserts.filter((x) => x.table === "triggered_beacons").length, 30);
    assertEquals(mockClient.inserts.filter((x) => x.table === "sabotage_logs").length, 1);
  } finally {
    if (oldEnv === undefined) Deno.env.delete("MIRAGE_ENV");
    else Deno.env.set("MIRAGE_ENV", oldEnv);
  }
});

Deno.test("runtime config: production without Supabase secrets fails closed", async () => {
  const oldEnv = Deno.env.get("MIRAGE_ENV");
  const oldUrl = Deno.env.get("SUPABASE_URL");
  const oldKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  const oldDryRun = Deno.env.get("MIRAGE_EDGE_DRY_RUN");
  try {
    Deno.env.set("MIRAGE_ENV", "production");
    Deno.env.delete("SUPABASE_URL");
    Deno.env.delete("SUPABASE_SERVICE_ROLE_KEY");
    Deno.env.set("MIRAGE_EDGE_DRY_RUN", "true");
    const { getRuntimeConfig, getRuntimeConfigError, shouldUseDryRun } = await import("../functions/beacon-receiver/index.ts");
    const config = getRuntimeConfig();
    assertEquals(shouldUseDryRun(config), false);
    assert(getRuntimeConfigError(config)?.includes("required in production"));
  } finally {
    if (oldEnv === undefined) Deno.env.delete("MIRAGE_ENV"); else Deno.env.set("MIRAGE_ENV", oldEnv);
    if (oldUrl === undefined) Deno.env.delete("SUPABASE_URL"); else Deno.env.set("SUPABASE_URL", oldUrl);
    if (oldKey === undefined) Deno.env.delete("SUPABASE_SERVICE_ROLE_KEY"); else Deno.env.set("SUPABASE_SERVICE_ROLE_KEY", oldKey);
    if (oldDryRun === undefined) Deno.env.delete("MIRAGE_EDGE_DRY_RUN"); else Deno.env.set("MIRAGE_EDGE_DRY_RUN", oldDryRun);
  }
});

Deno.test("runtime config: local dry-run must be explicit", async () => {
  const oldEnv = Deno.env.get("MIRAGE_ENV");
  const oldUrl = Deno.env.get("SUPABASE_URL");
  const oldKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  const oldDryRun = Deno.env.get("MIRAGE_EDGE_DRY_RUN");
  try {
    Deno.env.delete("MIRAGE_ENV");
    Deno.env.delete("SUPABASE_URL");
    Deno.env.delete("SUPABASE_SERVICE_ROLE_KEY");
    Deno.env.delete("MIRAGE_EDGE_DRY_RUN");
    const { getRuntimeConfig, getRuntimeConfigError, shouldUseDryRun } = await import("../functions/beacon-receiver/index.ts");
    const noDryRun = getRuntimeConfig();
    assertEquals(shouldUseDryRun(noDryRun), false);
    assert(getRuntimeConfigError(noDryRun)?.includes("MIRAGE_EDGE_DRY_RUN=true"));

    Deno.env.set("MIRAGE_EDGE_DRY_RUN", "true");
    const explicitDryRun = getRuntimeConfig();
    assertEquals(shouldUseDryRun(explicitDryRun), true);
    assertEquals(getRuntimeConfigError(explicitDryRun), null);
  } finally {
    if (oldEnv === undefined) Deno.env.delete("MIRAGE_ENV"); else Deno.env.set("MIRAGE_ENV", oldEnv);
    if (oldUrl === undefined) Deno.env.delete("SUPABASE_URL"); else Deno.env.set("SUPABASE_URL", oldUrl);
    if (oldKey === undefined) Deno.env.delete("SUPABASE_SERVICE_ROLE_KEY"); else Deno.env.set("SUPABASE_SERVICE_ROLE_KEY", oldKey);
    if (oldDryRun === undefined) Deno.env.delete("MIRAGE_EDGE_DRY_RUN"); else Deno.env.set("MIRAGE_EDGE_DRY_RUN", oldDryRun);
  }
});

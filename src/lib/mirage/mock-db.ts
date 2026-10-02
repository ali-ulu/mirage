export interface MockDb {
  attackers: any[]
  beacons: any[]
  honeytokens: any[]
  triage: any[]
  evidence: any[]
  evidenceVerify: any
}

// Global variable to persist across Next.js hot-reloads in development
const globalForMockDb = global as unknown as { mockDb?: MockDb }

export const mockDb: MockDb = globalForMockDb.mockDb || {
  attackers: [
    {
      id: "a-1",
      ip: "192.168.1.15",
      first_seen: new Date(Date.now() - 3600000).toISOString(),
      last_seen: new Date(Date.now() - 1800000).toISOString(),
      hit_count: 2,
      last_user_agent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Microsoft Excel/16.0",
      last_token: "b24044f4-d07a-4a94-82a4-69ad215924a1",
      tags: ["suspicious"]
    }
  ],
  beacons: [
    {
      id: "b-1",
      token: "b24044f4-d07a-4a94-82a4-69ad215924a1",
      ip: "192.168.1.15",
      user_agent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Microsoft Excel/16.0",
      received_at: new Date(Date.now() - 1800000).toISOString(),
      opener_app: "excel"
    }
  ],
  honeytokens: [
    {
      token: "b24044f4-d07a-4a94-82a4-69ad215924a1",
      label: "finance-decoy-local",
      full_url: "http://localhost:3000/api/track/b24044f4-d07a-4a94-82a4-69ad215924a1",
      row_count: 50,
      triggered_count: 1,
      issued_at: new Date(Date.now() - 7200000).toISOString(),
      last_triggered_at: new Date(Date.now() - 1800000).toISOString()
    }
  ],
  // Local demo triyaj kayıtları — AI katmanının ürettiği değerlendirmeler.
  // Production'da bu kayıtlar FastAPI /beacon/triage üzerinden yazılır.
  triage: [
    {
      id: "t-1",
      token: "b24044f4-d07a-4a94-82a4-69ad215924a1",
      chain_seq: 1,
      severity: "critical",
      confidence: 0.92,
      rationale: "Bilinen saldırgan IP, kurumsal ağ aralığı dışında ve token ilk kez açılıyor.",
      recommended_action: "escalate",
      source: "llm:openai",
      chain_verified: true,
      model: "gpt-4o-mini",
      created_at: new Date(Date.now() - 1500000).toISOString()
    },
    {
      id: "t-2",
      token: "b24044f4-d07a-4a94-82a4-69ad215924a1",
      chain_seq: 2,
      severity: "low",
      confidence: 0.41,
      rationale: "Beyaz listedeki ofis uygulaması, normal çalışma saatleri.",
      recommended_action: "monitor",
      source: "heuristic",
      chain_verified: true,
      model: null,
      created_at: new Date(Date.now() - 600000).toISOString()
    }
  ],
  // Kanıt zinciri demo kayıtları. Gerçek zincir `triggered_beacons`
  // tablosundaki prev_hash/record_hash/hmac alanlarıdır; mock'ta
  // yalnızca görüntülenecek kısım bulunur (hash'ler kısaltılmıştır).
  evidence: [
    {
      token: "b24044f4-d07a-4a94-82a4-69ad215924a1",
      ip: "192.168.1.15",
      user_agent: "Mozilla/5.0 Microsoft Excel/16.0",
      received_at: new Date(Date.now() - 1800000).toISOString(),
      chain_seq: 1,
      record_hash: "a1b2c3d4e5f6a7b8…"
    },
    {
      token: "b24044f4-d07a-4a94-82a4-69ad215924a1",
      ip: "192.168.1.15",
      user_agent: "Mozilla/5.0 Microsoft Excel/16.0",
      received_at: new Date(Date.now() - 900000).toISOString(),
      chain_seq: 2,
      record_hash: "f6e5d4c3b2a1c0d9…"
    }
  ],
  evidenceVerify: {
    token: "b24044f4-d07a-4a94-82a4-69ad215924a1",
    ok: true,
    checked: 2,
    broken_at: null,
    reason: null
  }
}

if (process.env.NODE_ENV !== "production") {
  globalForMockDb.mockDb = mockDb
}


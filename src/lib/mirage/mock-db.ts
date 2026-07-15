export interface MockDb {
  attackers: any[]
  beacons: any[]
  honeytokens: any[]
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
  ]
}

if (process.env.NODE_ENV !== "production") {
  globalForMockDb.mockDb = mockDb
}


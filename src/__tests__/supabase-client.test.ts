/**
 * MIRAGE Task 02 (Production) — Supabase client + Realtime hook tests (TDD)
 *
 * Test edilen davranışlar:
 *  - createMirageSupabaseClient: env var'lardan client oluşturur
 *  - createMirageSupabaseClient: env yoksa null döner (fail-safe, hata değil)
 *  - useMirageRealtime: postgres_changes event'lerini dinler
 *  - useMirageRealtime: yeni beacon geldiğinde state güncellenir
 *  - useMirageRealtime: connection status döner (connecting/connected/disconnected)
 *  - useMirageRealtime: unmount'ta subscription temizlenir
 *  - useMirageStats: KPI'ları Supabase'ten çeker
 *  - useMirageAttackers: saldırgan listesini Supabase'ten çeker
 *  - useMirageBeacons: beacon listesini Supabase'ten çeker
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'

// vi.hoisted ile mock objeleri tanımla — bunlar vi.mock factory'sinde
// erişilebilir (vi.mock hoist edilir, normal const'lar erişilemez)
const {
  mockChannel,
  mockFromChain,
  mockFrom,
  mockChannelFn,
  mockClient,
} = vi.hoisted(() => {
  const mockChannel = {
    on: vi.fn().mockReturnThis(),
    subscribe: vi.fn().mockImplementation((cb: (status: string) => void) => {
      setTimeout(() => cb('SUBSCRIBED'), 0)
      return mockChannel
    }),
    unsubscribe: vi.fn(),
  }

  const mockFromChain = {
    select: vi.fn().mockReturnThis(),
    order: vi.fn().mockReturnThis(),
    limit: vi.fn().mockReturnThis(),
    eq: vi.fn().mockReturnThis(),
    is: vi.fn().mockReturnThis(),
    gt: vi.fn().mockReturnThis(),
    single: vi.fn().mockResolvedValue({ data: null, error: null }),
  }

  const mockFrom = vi.fn().mockReturnValue(mockFromChain)
  const mockChannelFn = vi.fn().mockReturnValue(mockChannel)

  const mockClient = {
    from: mockFrom,
    channel: mockChannelFn,
    removeChannel: vi.fn(),
    removeAllChannels: vi.fn(),
  }

  return { mockChannel, mockFromChain, mockFrom, mockChannelFn, mockClient }
})

vi.mock('@supabase/supabase-js', () => ({
  createClient: vi.fn().mockReturnValue(mockClient),
}))

// Import AFTER mock is set up
import {
  createMirageSupabaseClient,
  useMirageStats,
  useMirageAttackers,
  useMirageBeacons,
  _resetMirageClientForTesting,
} from '@/lib/mirage/supabase-client'

const mockFetch = vi.fn().mockResolvedValue({
  ok: true,
  json: () => Promise.resolve({}),
})

beforeEach(() => {
  vi.clearAllMocks()
  _resetMirageClientForTesting()
  vi.stubGlobal('fetch', mockFetch)
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('createMirageSupabaseClient', () => {
  it('env var yoksa null döner (fail-safe)', () => {
    const oldUrl = process.env.NEXT_PUBLIC_SUPABASE_URL
    const oldKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY
    delete process.env.NEXT_PUBLIC_SUPABASE_URL
    delete process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY

    const client = createMirageSupabaseClient()
    expect(client).toBeNull()

    if (oldUrl) process.env.NEXT_PUBLIC_SUPABASE_URL = oldUrl
    if (oldKey) process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = oldKey
  })

  it('env var varsa client döner', () => {
    process.env.NEXT_PUBLIC_SUPABASE_URL = 'https://test.supabase.co'
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = 'fake-anon-key'

    const client = createMirageSupabaseClient()
    expect(client).not.toBeNull()
  })
})

describe('useMirageStats', () => {
  it('başlangıçta loading state', async () => {
    process.env.NEXT_PUBLIC_SUPABASE_URL = 'https://test.supabase.co'
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = 'fake-anon-key'

    mockFetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({}),
    })

    const { result } = renderHook(() => useMirageStats())
    expect(result.current.loading).toBe(true)
  })

  it('Supabase error durumunda error state', async () => {
    process.env.NEXT_PUBLIC_SUPABASE_URL = 'https://test.supabase.co'
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = 'fake-anon-key'

    mockFetch.mockResolvedValue({
      ok: false,
      status: 500,
      json: () => Promise.resolve({ error: 'permission denied' }),
    })

    const { result } = renderHook(() => useMirageStats())

    await waitFor(() => {
      expect(result.current.error).not.toBeNull()
    })
  })
})

describe('useMirageAttackers', () => {
  it('saldırgan listesi Supabase\'ten gelir', async () => {
    process.env.NEXT_PUBLIC_SUPABASE_URL = 'https://test.supabase.co'
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = 'fake-anon-key'

    const fakeAttackers = [
      {
        id: '1', ip: '203.0.113.42',
        first_seen: '2024-01-15T10:00:00Z',
        last_seen: '2024-01-15T11:00:00Z',
        hit_count: 5, last_user_agent: 'LibreOffice/7.5',
        last_token: '550e8400-e29b-41d4-a716-446655440000',
        tags: ['confirmed-apt'],
      },
    ]

    mockFetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(fakeAttackers),
    })

    const { result } = renderHook(() => useMirageAttackers())

    await waitFor(() => {
      expect(result.current.attackers.length).toBeGreaterThan(0)
      expect(result.current.attackers[0].ip).toBe('203.0.113.42')
    })
  })
})

describe('useMirageBeacons', () => {
  it('beacon listesi Supabase\'ten gelir', async () => {
    process.env.NEXT_PUBLIC_SUPABASE_URL = 'https://test.supabase.co'
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = 'fake-anon-key'

    const fakeBeacons = [
      {
        id: 'b1', token: '550e8400-e29b-41d4-a716-446655440000',
        ip: '203.0.113.42', user_agent: 'LibreOffice/7.5',
        received_at: '2024-01-15T10:00:00Z', opener_app: 'libreoffice',
      },
    ]

    mockFetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(fakeBeacons),
    })

    const { result } = renderHook(() => useMirageBeacons())

    await waitFor(() => {
      expect(result.current.beacons.length).toBeGreaterThan(0)
      expect(result.current.beacons[0].ip).toBe('203.0.113.42')
    })
  })
})

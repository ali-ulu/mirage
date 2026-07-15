/**
 * MIRAGE Dashboard — Ana sayfa testi
 *
 * Dashboard artık Supabase hook'ları kullandığı için, hook'ları mock'lıyoruz.
 * Hook'ların kendileri kendi test dosyalarında test ediliyor (supabase-client.test.ts).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

// Mock Supabase hook'ları
vi.mock('@/lib/mirage/supabase-client', () => ({
  useMirageStats: vi.fn(() => ({
    stats: {
      total_attackers: 4,
      total_beacons: 7,
      last_24h_beacons: 5,
      active_tokens: 4,
      last_attacker_ip: '203.0.113.42',
      last_beacon_at: new Date(Date.now() - 5 * 60 * 1000).toISOString(),
    },
    loading: false,
    error: null,
    refresh: vi.fn(),
  })),
  useMirageAttackers: vi.fn(() => ({
    attackers: [
      {
        id: 'a1',
        ip: '203.0.113.42',
        first_seen: '2024-01-15T10:00:00Z',
        last_seen: new Date(Date.now() - 5 * 60 * 1000).toISOString(),
        hit_count: 12,
        last_user_agent: 'LibreOffice/7.5',
        last_token: '550e8400-e29b-41d4-a716-446655440000',
        tags: ['confirmed-apt'],
      },
    ],
    loading: false,
    error: null,
    refresh: vi.fn(),
  })),
  useMirageBeacons: vi.fn(() => ({
    beacons: [
      {
        id: 'b1',
        token: '550e8400-e29b-41d4-a716-446655440000',
        ip: '203.0.113.42',
        user_agent: 'LibreOffice/7.5',
        received_at: new Date(Date.now() - 5 * 60 * 1000).toISOString(),
        opener_app: 'libreoffice',
      },
    ],
    loading: false,
    error: null,
    refresh: vi.fn(),
  })),
  useMirageRealtime: vi.fn(() => ({
    status: 'connected' as const,
    lastEvent: null,
  })),
}))

import Home from '@/app/page'

describe('MIRAGE Dashboard Home', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('MIRAGE başlığını render eder', async () => {
    render(<Home />)
    await waitFor(() => {
      const header = screen.getByTestId('dashboard-header')
      expect(header.textContent).toMatch(/MIRAGE/)
    })
  })

  it('slogan gösterir (deception / counter-intelligence)', async () => {
    render(<Home />)
    await waitFor(() => {
      const header = screen.getByTestId('dashboard-header')
      expect(header.textContent).toMatch(/deception|counter|intelligence/i)
    })
  })

  it('KPI cards render edilir (Toplam Saldırgan, Toplam Beacon, Son 24s, Aktif Token)', async () => {
    render(<Home />)
    await waitFor(() => {
      expect(screen.getByText(/toplam saldırgan/i)).toBeInTheDocument()
    })
    expect(screen.getByText(/toplam beacon/i)).toBeInTheDocument()
    expect(screen.getByText(/son 24 saat/i)).toBeInTheDocument()
    expect(screen.getByText(/aktif token/i)).toBeInTheDocument()
  })

  it('KPI değerleri API\'den gelir', async () => {
    render(<Home />)
    await waitFor(() => {
      const values = screen.getAllByTestId('kpi-value')
      expect(values.length).toBe(4)
      const texts = values.map((v) => v.textContent)
      // Mock useMirageStats returns 4 attackers / 4 tokens
      expect(texts).toContain('4')
    })
  })

  it('AttackerTable render edilir', async () => {
    render(<Home />)
    await waitFor(() => {
      expect(screen.getByTestId('attacker-table')).toBeInTheDocument()
    })
  })

  it('BeaconFeed render edilir', async () => {
    render(<Home />)
    await waitFor(() => {
      expect(screen.getByTestId('beacon-feed')).toBeInTheDocument()
    })
  })

  it('real-time status indicator gösterir (LIVE)', async () => {
    render(<Home />)
    await waitFor(() => {
      const header = screen.getByTestId('dashboard-header')
      expect(header.textContent).toMatch(/LIVE|AKTİF|CANLI/i)
    })
  })

  it('footer MIRAGE copyright içerir', async () => {
    render(<Home />)
    await waitFor(() => {
      const footer = screen.getByRole('contentinfo')
      expect(footer.textContent).toMatch(/mirage/i)
    })
  })

  it('sticky footer (mt-auto ile)', async () => {
    const { container } = render(<Home />)
    await waitFor(() => {
      const footer = container.querySelector('footer')
      expect(footer).not.toBeNull()
      expect(footer!.className).toMatch(/mt-auto/)
    })
  })

  it('Neo-Brutalist tema — border-2 everywhere', async () => {
    render(<Home />)
    await waitFor(() => {
      const header = screen.getByTestId('dashboard-header')
      expect(header.className).toMatch(/border-(2|4|b-4)/)
    })
    const cards = screen.getAllByTestId('kpi-card')
    expect(cards.length).toBe(4)
    cards.forEach((c) => {
      expect(c.className).toMatch(/border-2/)
    })
  })
})

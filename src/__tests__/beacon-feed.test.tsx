/**
 * MIRAGE Dashboard — BeaconFeed Component Test (TDD)
 *
 * Son tetiklenen beacon'ların gerçek zamanlı akışı.
 */
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { BeaconFeed } from '@/components/mirage/beacon-feed'
import type { TriggeredBeacon } from '@/lib/mirage/types'

const sampleBeacons: TriggeredBeacon[] = [
  {
    id: 'b1',
    token: '550e8400-e29b-41d4-a716-446655440000',
    ip: '203.0.113.42',
    user_agent: 'LibreOffice/7.5',
    received_at: new Date(Date.now() - 5 * 60 * 1000).toISOString(), // 5 dk önce
    opener_app: 'libreoffice',
  },
  {
    id: 'b2',
    token: '660f9511-f30c-52e5-b827-557766551111',
    ip: '198.51.100.7',
    user_agent: 'Excel/16.0',
    received_at: new Date(Date.now() - 10 * 60 * 1000).toISOString(),
    opener_app: 'excel',
  },
  {
    id: 'b3',
    token: '770fa622-041d-63f6-c938-668877662222',
    ip: '203.0.113.99',
    user_agent: 'Microsoft Office Excel',
    received_at: new Date(Date.now() - 15 * 60 * 1000).toISOString(),
    opener_app: 'excel',
  },
]

describe('BeaconFeed', () => {
  it('boş array verildiğinde empty state gösterir', () => {
    render(<BeaconFeed beacons={[]} />)
    expect(screen.getByText(/henüz beacon tetiklenmedi/i)).toBeInTheDocument()
  })

  it('her beacon için bir satır render eder', () => {
    render(<BeaconFeed beacons={sampleBeacons} />)
    expect(screen.getByText('203.0.113.42')).toBeInTheDocument()
    expect(screen.getByText('198.51.100.7')).toBeInTheDocument()
    expect(screen.getByText('203.0.113.99')).toBeInTheDocument()
  })

  it('relative timestamp gösterir (5 dk önce)', () => {
    render(<BeaconFeed beacons={sampleBeacons} />)
    // Anchored regex — "5 dk önce" ama "15 dk önce" değil
    expect(screen.getByText(/^5 dk önce$/)).toBeInTheDocument()
    expect(screen.getByText(/^10 dk önce$/)).toBeInTheDocument()
    expect(screen.getByText(/^15 dk önce$/)).toBeInTheDocument()
  })

  it('token kısaltılmış gösterilir (ilk 8 karakter)', () => {
    render(<BeaconFeed beacons={sampleBeacons} />)
    // 550e8400-... → "550e8400"
    expect(screen.getByText(/550e8400/)).toBeInTheDocument()
  })

  it('opener app badge olarak gösterilir', () => {
    render(<BeaconFeed beacons={sampleBeacons} />)
    // 2 libreoffice + 1 excel değil, 1 libreoffice + 2 excel
    expect(screen.getAllByText(/^libreoffice$/i).length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText(/^excel$/i).length).toBeGreaterThanOrEqual(1)
  })

  it('data-testid="beacon-feed" taşır', () => {
    const { container } = render(<BeaconFeed beacons={sampleBeacons} />)
    expect(container.querySelector('[data-testid="beacon-feed"]')).not.toBeNull()
  })

  it('neo-brutalist stil uygulanır (border-2 + hard shadow)', () => {
    const { container } = render(<BeaconFeed beacons={sampleBeacons} />)
    const feed = container.querySelector('[data-testid="beacon-feed"]')
    expect(feed!.className).toMatch(/border-2/)
    expect(feed!.className).toMatch(/shadow-\[/)
  })

  it('scroll için max-height uygulanır', () => {
    const { container } = render(<BeaconFeed beacons={sampleBeacons} />)
    // Wrapper veya içindeki scroll container'dan birinde max-h/overflow olmalı
    const feed = container.querySelector('[data-testid="beacon-feed"]')
    const scrollContainer = feed?.querySelector('.overflow-y-auto')
    const combined = (feed?.className || '') + ' ' + (scrollContainer?.className || '')
    expect(combined).toMatch(/max-h|overflow/)
  })

  it('en yeni beacon en üstte gösterilir (sorted desc)', () => {
    // sampleBeacons zaten desc sıralı, ama karışık verilse bile sıralanmalı
    const shuffled = [sampleBeacons[2], sampleBeacons[0], sampleBeacons[1]]
    const { container } = render(<BeaconFeed beacons={shuffled} />)
    const rows = container.querySelectorAll('[data-testid="beacon-row"]')
    expect(rows.length).toBe(3)
    // İlk satırda en yeni (5 dk önce) olmalı
    const firstRow = rows[0]
    expect(firstRow.textContent).toMatch(/5 dk önce/)
  })

  it('header başlığı "Son Beaconlar" gösterir', () => {
    render(<BeaconFeed beacons={sampleBeacons} />)
    expect(screen.getByText(/son beaconlar/i)).toBeInTheDocument()
  })
})

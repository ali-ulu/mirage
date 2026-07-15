/**
 * MIRAGE Dashboard — AttackerTable Component Test (TDD)
 */
import { describe, it, expect } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import { AttackerTable } from '@/components/mirage/attacker-table'
import type { Attacker } from '@/lib/mirage/types'

const sampleAttackers: Attacker[] = [
  {
    id: '1',
    ip: '203.0.113.42',
    first_seen: '2024-01-15T10:00:00Z',
    last_seen: '2024-01-15T11:30:00Z',
    hit_count: 5,
    last_user_agent: 'LibreOffice/7.5',
    last_token: '550e8400-e29b-41d4-a716-446655440000',
    tags: ['confirmed-apt'],
  },
  {
    id: '2',
    ip: '198.51.100.7',
    first_seen: '2024-01-14T09:00:00Z',
    last_seen: '2024-01-14T09:05:00Z',
    hit_count: 1,
    last_user_agent: 'Excel/16.0',
    last_token: '660f9511-f30c-52e5-b827-557766551111',
    tags: [],
  },
]

describe('AttackerTable', () => {
  it('boş array verildiğinde empty state gösterir', () => {
    render(<AttackerTable attackers={[]} />)
    expect(screen.getByText(/henüz saldırgan tespit edilmedi/i)).toBeInTheDocument()
  })

  it('her saldırgan için bir satır render eder', () => {
    render(<AttackerTable attackers={sampleAttackers} />)
    expect(screen.getByText('203.0.113.42')).toBeInTheDocument()
    expect(screen.getByText('198.51.100.7')).toBeInTheDocument()
  })

  it('hit_count gösterir', () => {
    render(<AttackerTable attackers={sampleAttackers} />)
    expect(screen.getByText('5')).toBeInTheDocument()
    expect(screen.getByText('1')).toBeInTheDocument()
  })

  it('user_agent gösterir', () => {
    render(<AttackerTable attackers={sampleAttackers} />)
    expect(screen.getByText(/LibreOffice\/7\.5/)).toBeInTheDocument()
    expect(screen.getByText(/Excel\/16\.0/)).toBeInTheDocument()
  })

  it('opener app otomatik tespit edilir (libreoffice → badge)', () => {
    render(<AttackerTable attackers={sampleAttackers} />)
    // Badge spesifik olarak işaretli
    const openerBadges = screen.getAllByText(/^libreoffice$/i)
    expect(openerBadges.length).toBeGreaterThanOrEqual(1)
    const excelBadges = screen.getAllByText(/^excel$/i)
    expect(excelBadges.length).toBeGreaterThanOrEqual(1)
  })

  it('timestamp human-readable format\'a çevrilir', () => {
    render(<AttackerTable attackers={sampleAttackers} />)
    // İlk görülme zamanı relative olarak gösterilir
    expect(screen.getAllByText(/ago|önce|2024/)).toHaveLength(4) // first_seen + last_seen × 2 satır
  })

  it('tags gösterilir (confirmed-apt)', () => {
    render(<AttackerTable attackers={sampleAttackers} />)
    expect(screen.getByText(/confirmed-apt/i)).toBeInTheDocument()
  })

  it('neo-brutalist stil uygulanır (border-2 wrapper)', () => {
    const { container } = render(<AttackerTable attackers={sampleAttackers} />)
    const wrapper = container.querySelector('[data-testid="attacker-table"]')
    expect(wrapper).not.toBeNull()
    expect(wrapper!.className).toMatch(/border-2/)
  })

  it('header satırı siyah arka plan + beyaz text', () => {
    const { container } = render(<AttackerTable attackers={sampleAttackers} />)
    const thead = container.querySelector('thead')
    expect(thead).not.toBeNull()
    expect(thead!.className.toLowerCase()).toMatch(/bg-black|bg-zinc-900/)
  })

  it('data-testid="attacker-table" taşır', () => {
    const { container } = render(<AttackerTable attackers={sampleAttackers} />)
    expect(container.querySelector('[data-testid="attacker-table"]')).not.toBeNull()
  })

  it('scroll için max-height uygulanır (uzun liste için)', () => {
    const { container } = render(<AttackerTable attackers={sampleAttackers} />)
    const wrapper = container.querySelector('[data-testid="attacker-table"]')
    // max-h-* veya overflow sınıfı olmalı
    expect(wrapper!.className).toMatch(/max-h|overflow/)
  })
})

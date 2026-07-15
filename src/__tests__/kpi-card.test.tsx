/**
 * MIRAGE Dashboard — KpiCard Component Test (TDD)
 *
 * Test edilen davranışlar:
 *  - Belirli bir label + value render eder
 *  - Neo-Brutalist stil uygulanır (border-2, hard shadow, monospace font)
 *  - İsteğe bağlı alt başlık (sublabel) render edilir
 *  - Sayısal değer büyük punto ile gösterilir
 *  - Negatif/pozitif trend göstergesi opsiyonel
 */
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { KpiCard } from '@/components/mirage/kpi-card'

describe('KpiCard', () => {
  it('label ve value render eder', () => {
    render(<KpiCard label="Toplam Saldırgan" value={42} />)
    expect(screen.getByText(/Toplam Saldırgan/i)).toBeInTheDocument()
    expect(screen.getByText('42')).toBeInTheDocument()
  })

  it('sublabel opsiyonel olarak render edilir', () => {
    render(
      <KpiCard
        label="Aktif Token'lar"
        value={7}
        sublabel="Son 24 saatte üretilen"
      />
    )
    expect(screen.getByText(/Son 24 saatte üretilen/i)).toBeInTheDocument()
  })

  it('sublabel verilmediğinde render edilmez', () => {
    const { container } = render(<KpiCard label="X" value={1} />)
    // Sublabel için ayrı bir element olmamalı
    expect(container.querySelectorAll('[data-testid="kpi-sublabel"]')).toHaveLength(0)
  })

  it('büyük sayısal değer render edilir (1,234,567)', () => {
    render(<KpiCard label="Total Hits" value={1234567} />)
    // Sayıyı binlik ayraç ile veya düz göster — her ikisi de kabul
    expect(screen.getByText(/1,234,567|1234567/)).toBeInTheDocument()
  })

  it('string değer de kabul eder (örn. "203.0.113.42")', () => {
    render(<KpiCard label="Son Saldırgan IP" value="203.0.113.42" />)
    expect(screen.getByText('203.0.113.42')).toBeInTheDocument()
  })

  it('neo-brutalist sınıflar uygulanır (border-2 + hard shadow)', () => {
    const { container } = render(<KpiCard label="X" value={1} />)
    const card = container.firstElementChild
    expect(card).not.toBeNull()
    const cls = card!.className
    // border-2 veya border-4 olmalı
    expect(cls).toMatch(/border-(2|4)/)
    // hard shadow (offset, no blur) — shadow-[NxN_0_0_color]
    expect(cls).toMatch(/shadow-\[/)
  })

  it('monospace font sınıfı uygulanır (value için)', () => {
    const { container } = render(<KpiCard label="X" value={42} />)
    // Value element'inde mono sınıfı olmalı
    const valueEl = container.querySelector('[data-testid="kpi-value"]')
    expect(valueEl).not.toBeNull()
    expect(valueEl!.className).toMatch(/font-mono|mono/)
  })

  it('data-testid="kpi-card" attribute\'u taşır', () => {
    const { container } = render(<KpiCard label="X" value={1} />)
    expect(container.querySelector('[data-testid="kpi-card"]')).not.toBeNull()
  })

  it('accent color opsiyonel (variant prop)', () => {
    // variant="danger" → kırmızı accent
    const { container } = render(
      <KpiCard label="X" value={1} variant="danger" />
    )
    const card = container.firstElementChild
    // kırmızı bir class olmalı (red, danger)
    expect(card!.className.toLowerCase()).toMatch(/red|danger|alert/)
  })

  it('variant="success" → yeşil accent', () => {
    const { container } = render(
      <KpiCard label="X" value={1} variant="success" />
    )
    const card = container.firstElementChild
    expect(card!.className.toLowerCase()).toMatch(/green|success|emerald/)
  })
})

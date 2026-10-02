import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { CanaryPanel } from '@/components/mirage/canary-panel'
import {
  canaryContextLabel,
  canaryMarkerShort,
  type PromptCanary,
} from '@/lib/mirage/types'

const canaries: PromptCanary[] = [
  {
    id: 'c-1',
    token: '550e8400-e29b-41d4-a716-446655440000',
    marker: '[[MIRAGE-CANARY:550e8400-e29b-41d4-a716-446655440000]]',
    context: 'system_prompt',
    label: 'destek-botu-v2',
    created_at: new Date(Date.now() - 60000).toISOString(),
  },
  {
    id: 'c-2',
    token: '6ba7b810-9dad-11d1-80b4-00c04fd430c8',
    marker: '[[MIRAGE-CANARY:6ba7b810-9dad-11d1-80b4-00c04fd430c8]]',
    context: 'rag_document',
    label: 'urun-katalogu',
    created_at: new Date(Date.now() - 120000).toISOString(),
  },
]

describe('canaryMarkerShort', () => {
  it('tam isareti kisaltir', () => {
    expect(canaryMarkerShort(canaries[0].marker)).toBe('MIRAGE-CANARY:550e8400…')
  })

  it('tam UUID sizmaz', () => {
    expect(canaryMarkerShort(canaries[0].marker)).not.toContain(
      'e29b-41d4-a716-446655440000'
    )
  })

  it('bos girdide tire doner', () => {
    expect(canaryMarkerShort('')).toBe('—')
  })

  it('beklenmeyen bicimi oldugu gibi doner', () => {
    expect(canaryMarkerShort('MARKER')).toBe('MARKER')
  })
})

describe('canaryContextLabel', () => {
  it('system_prompt Turkceye cevirir', () => {
    expect(canaryContextLabel('system_prompt')).toBe('Sistem Prompt')
  })

  it('rag_document Turkceye cevirir', () => {
    expect(canaryContextLabel('rag_document')).toBe('RAG Doküman')
  })

  it('agent_memory Turkceye cevirir', () => {
    expect(canaryContextLabel('agent_memory')).toBe('Ajan Hafızası')
  })

  it('bilinmeyen baglami oldugu gibi doner', () => {
    expect(canaryContextLabel('bilinmeyen')).toBe('bilinmeyen')
  })
})

describe('CanaryPanel', () => {
  it('basligi ve kayit sayisini gosterir', () => {
    render(<CanaryPanel canaries={canaries} />)
    const panel = screen.getByTestId('canary-panel')
    expect(panel.textContent).toMatch(/Prompt Canary/i)
    expect(panel.textContent).toContain('2')
  })

  it('her canary icin satir render eder', () => {
    render(<CanaryPanel canaries={canaries} />)
    expect(screen.getAllByTestId('canary-row').length).toBe(2)
  })

  it('baglami Turkce rozetle gosterir', () => {
    render(<CanaryPanel canaries={canaries} />)
    const rows = screen.getAllByTestId('canary-row')
    expect(rows[0].textContent).toContain('Sistem Prompt')
    expect(rows[1].textContent).toContain('RAG Doküman')
  })

  it('etiketi gosterir', () => {
    render(<CanaryPanel canaries={canaries} />)
    expect(screen.getByTestId('canary-panel').textContent).toContain('destek-botu-v2')
  })

  it('canary isaretini KISALTILMIS halde gosterir', () => {
    render(<CanaryPanel canaries={canaries} />)
    const panel = screen.getByTestId('canary-panel')
    expect(panel.textContent).toContain('MIRAGE-CANARY:550e8400…')
    expect(panel.textContent).not.toContain('550e8400-e29b-41d4-a716-446655440000')
  })

  it('alt bilgide baglam dagilimini yazar', () => {
    render(<CanaryPanel canaries={canaries} />)
    const panel = screen.getByTestId('canary-panel')
    expect(panel.textContent).toMatch(/sistem: 1/)
    expect(panel.textContent).toMatch(/rag: 1/)
  })

  it('bos durumda mesaj gosterir', () => {
    render(<CanaryPanel canaries={[]} />)
    expect(screen.getByTestId('canary-panel').textContent).toMatch(
      /henüz canary gömülmedi/i
    )
  })

  it('loading durumunda mesaj gosterir', () => {
    render(<CanaryPanel canaries={[]} loading />)
    expect(screen.getByTestId('canary-panel').textContent).toMatch(/yükleniyor/i)
  })

  it('error durumunda hata mesajini gosterir', () => {
    render(<CanaryPanel canaries={[]} error={new Error('Supabase timeout')} />)
    const panel = screen.getByTestId('canary-panel')
    expect(panel.textContent).toMatch(/okunamadı/i)
    expect(panel.textContent).toContain('Supabase timeout')
  })

  it('etiketi olmayan canary icin bos alan birakmaz', () => {
    const unlabeled = { ...canaries[0], label: '' }
    render(<CanaryPanel canaries={[unlabeled]} />)
    expect(screen.getByTestId('canary-row')).toBeTruthy()
  })
})
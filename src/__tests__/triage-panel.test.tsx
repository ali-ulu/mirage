import { describe, it, expect } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import { TriagePanel } from '@/components/mirage/triage-panel'
import type { BeaconTriage } from '@/lib/mirage/types'

const triageRecord: BeaconTriage = {
  id: 't-1',
  token: 'b24044f4-d07a-4a94-82a4-69ad215924a1',
  chain_seq: 7,
  severity: 'critical',
  confidence: 0.92,
  rationale: 'Kurumsal ağ aralığı dışından ilk kez açılış.',
  recommended_action: 'escalate',
  source: 'llm:openai',
  chain_verified: true,
  model: 'gpt-4o-mini',
  created_at: new Date(Date.now() - 60000).toISOString(),
}

describe('TriagePanel', () => {
  it('başlığı ve kayıt sayısını gösterir', () => {
    render(<TriagePanel triage={[triageRecord]} />)
    const panel = screen.getByTestId('triage-panel')
    expect(panel).toBeTruthy()
    expect(panel.textContent).toMatch(/AI Triyaj/i)
    expect(panel.textContent).toContain('1')
  })

  it('severity ve önerilen aksiyonu gösterir', () => {
    render(<TriagePanel triage={[triageRecord]} />)
    const row = screen.getByTestId('triage-row')
    expect(within(row).getByText('critical')).toBeTruthy()
    // Önerilen aksiyon Türkçe etiketle görünür
    expect(row.textContent).toContain('Yükselt')
  })

  it('LLM kaynağını kullanıcıya ayırır', () => {
    render(<TriagePanel triage={[triageRecord]} />)
    expect(screen.getByTestId('triage-panel').textContent).toContain('LLM')
  })

  it('kural tabanlı kaynağı "Kural tabanlı" gösterir', () => {
    const heuristic = { ...triageRecord, id: 't-2', source: 'heuristic', severity: 'low' as const, recommended_action: 'monitor' as const }
    render(<TriagePanel triage={[heuristic]} />)
    expect(screen.getByTestId('triage-panel').textContent).toContain('Kural tabanlı')
  })

  it('gerekçe metnini gösterir', () => {
    render(<TriagePanel triage={[triageRecord]} />)
    expect(screen.getByTestId('triage-row').textContent).toContain(
      'Kurumsal ağ aralığı dışından ilk kez açılış.'
    )
  })

  it('kanıt doğrulandı işaretini gösterir', () => {
    render(<TriagePanel triage={[triageRecord]} />)
    expect(screen.getByTestId('triage-panel').textContent).toMatch(/kanıt doğrulandı/i)
  })

  it('kanıt doğrulanmadıysa hata işareti gösterir', () => {
    const bad = { ...triageRecord, id: 't-3', chain_verified: false }
    render(<TriagePanel triage={[bad]} />)
    expect(screen.getByTestId('triage-panel').textContent).toMatch(/zincir hatası/i)
  })

  it('kritik kayıt sayısını başlıkta gösterir', () => {
    render(<TriagePanel triage={[triageRecord]} />)
    expect(screen.getByTestId('triage-panel').textContent).toMatch(/1 kritik/i)
  })

  it('kritik yoksa kritik rozetini göstermez', () => {
    const low = { ...triageRecord, severity: 'low' as const }
    render(<TriagePanel triage={[low]} />)
    expect(screen.getByTestId('triage-panel').textContent).not.toMatch(/kritik/i)
  })

  it('boş durumda mesaj gösterir', () => {
    render(<TriagePanel triage={[]} />)
    expect(screen.getByTestId('triage-panel').textContent).toMatch(/henüz triyaj kaydı yok/i)
  })

  it('loading durumunda mesaj gösterir', () => {
    render(<TriagePanel triage={[]} loading />)
    expect(screen.getByTestId('triage-panel').textContent).toMatch(/yükleniyor/i)
  })

  it('error durumunda hata mesajını gösterir', () => {
    render(<TriagePanel triage={[]} error={new Error('Supabase timeout')} />)
    const panel = screen.getByTestId('triage-panel')
    expect(panel.textContent).toMatch(/okunamadı/i)
    expect(panel.textContent).toContain('Supabase timeout')
  })

  it('güven yüzdesini gösterir', () => {
    render(<TriagePanel triage={[triageRecord]} />)
    expect(screen.getByTestId('triage-panel').textContent).toContain('%92')
  })
})
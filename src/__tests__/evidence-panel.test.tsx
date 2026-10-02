import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { EvidencePanel } from '@/components/mirage/evidence-panel'
import type { EvidenceChainRecord, EvidenceVerifyResult } from '@/lib/mirage/types'

const records: EvidenceChainRecord[] = [
  {
    token: '550e8400-e29b-41d4-a716-446655440000',
    ip: '203.0.113.42',
    user_agent: 'LibreOffice/7.5',
    received_at: new Date(Date.now() - 60000).toISOString(),
    chain_seq: 1,
    record_hash: 'a1b2c3d4e5f6a7b8',
  },
  {
    token: '550e8400-e29b-41d4-a716-446655440000',
    ip: '203.0.113.42',
    user_agent: 'LibreOffice/7.5',
    received_at: new Date(Date.now() - 30000).toISOString(),
    chain_seq: 2,
    record_hash: 'f6e5d4c3b2a1c0d9',
  },
]

const verified: EvidenceVerifyResult = {
  token: '550e8400-e29b-41d4-a716-446655440000',
  ok: true,
  checked: 2,
  broken_at: null,
  reason: null,
}

describe('EvidencePanel', () => {
  it('başlığı gösterir', () => {
    render(<EvidencePanel records={records} verification={verified} />)
    expect(screen.getByTestId('evidence-panel').textContent).toMatch(/Kanıt Zinciri/i)
  })

  it('doğrulanmış zincirde DOĞRULANDI rozeti gösterir', () => {
    render(<EvidencePanel records={records} verification={verified} />)
    expect(screen.getByTestId('evidence-verdict').textContent).toMatch(/DOĞRULANDI/i)
  })

  it('kırık zincirde DOĞRULANAMADI rozeti gösterir', () => {
    const broken: EvidenceVerifyResult = {
      ...verified,
      ok: false,
      broken_at: 2,
      reason: 'hmac verification failed',
    }
    render(<EvidencePanel records={records} verification={broken} />)
    expect(screen.getByTestId('evidence-verdict').textContent).toMatch(/DOĞRULANAMADI/i)
  })

  it('kırık zincirde sebebi ve kırılma noktasını gösterir', () => {
    const broken: EvidenceVerifyResult = {
      ...verified,
      ok: false,
      broken_at: 2,
      reason: 'prev_hash does not link to previous record',
    }
    render(<EvidencePanel records={records} verification={broken} />)
    const reason = screen.getByTestId('evidence-reason')
    expect(reason.textContent).toContain('prev_hash')
    expect(reason.textContent).toContain('#2')
  })

  it('doğrulama başarılıysa sebep alanı göstermez', () => {
    render(<EvidencePanel records={records} verification={verified} />)
    expect(screen.queryByTestId('evidence-reason')).toBeNull()
  })

  it('her zincir kaydını zincir sırasıyla gösterir', () => {
    render(<EvidencePanel records={records} verification={verified} />)
    const rows = screen.getAllByTestId('evidence-row')
    expect(rows.length).toBe(2)
    expect(rows[0].textContent).toContain('#1')
    expect(rows[1].textContent).toContain('#2')
  })

  it('kayıt hash ini gösterir', () => {
    render(<EvidencePanel records={records} verification={verified} />)
    // İki kayıt var; her biri kendi hash'ini göstermeli
    const rows = screen.getAllByTestId('evidence-row')
    expect(rows[0].textContent).toContain('a1b2c3d4e5f6a7b8')
    expect(rows[1].textContent).toContain('f6e5d4c3b2a1c0d9')
  })

  it('IP adresini gösterir', () => {
    render(<EvidencePanel records={records} verification={verified} />)
    expect(screen.getByTestId('evidence-panel').textContent).toContain('203.0.113.42')
  })

  it('alt bilgide kayıt sayisi ve HMAC algoritmasini yazar', () => {
    render(<EvidencePanel records={records} verification={verified} />)
    const panel = screen.getByTestId('evidence-panel')
    expect(panel.textContent).toContain('2 kayıt')
    expect(panel.textContent).toMatch(/HMAC-SHA256/i)
    expect(panel.textContent).toMatch(/append-only/i)
  })

  it('boş kayit durumunda mesaj gösterir', () => {
    render(<EvidencePanel records={[]} verification={null} />)
    expect(screen.getByTestId('evidence-panel').textContent).toMatch(/Kanıt kaydı yok/i)
  })

  it('loading durumunda mesaj gösterir', () => {
    render(<EvidencePanel records={[]} verification={null} loading />)
    expect(screen.getByTestId('evidence-panel').textContent).toMatch(/doğrulanıyor/i)
  })

  it('error durumunda hata mesajini gosterir', () => {
    render(<EvidencePanel records={[]} verification={null} error={new Error('Supabase timeout')} />)
    const panel = screen.getByTestId('evidence-panel')
    expect(panel.textContent).toMatch(/okunamadı/i)
    expect(panel.textContent).toContain('Supabase timeout')
  })

  it('dogrulama sonucu yoksa karar rozeti gostermez', () => {
    render(<EvidencePanel records={records} verification={null} />)
    expect(screen.queryByTestId('evidence-verdict')).toBeNull()
  })

  it('imza veya prev_hash degerlerini GOSTERMEZ', () => {
    // Bu alanlar frontend e gomulurse zincir taklit edilebilir
    const record = { ...records[0] } as unknown as EvidenceChainRecord
    render(<EvidencePanel records={[record]} verification={verified} />)
    const panel = screen.getByTestId('evidence-panel')
    expect(panel.textContent).not.toContain('hmac')
    expect(panel.textContent).not.toContain('prev_hash')
  })
})
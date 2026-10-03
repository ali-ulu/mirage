import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { McpAuditPanel } from '@/components/mirage/mcp-audit-panel'
import type { McpAuditRecord, McpAuditSummary } from '@/lib/mirage/types'

const summary: McpAuditSummary = {
  total: 128,
  allowed: 112,
  denied: 16,
  by_risk_level: { low: 84, medium: 30, high: 10, critical: 4 },
}

const records: McpAuditRecord[] = [
  {
    id: 'm-1',
    occurred_at: new Date(Date.now() - 60000).toISOString(),
    actor: 'satis-ajanlari',
    server: 'shell',
    tool: 'exec_command',
    allowed: false,
    reason: 'risk eşiği aşıldı',
    risk_score: 95,
    risk_level: 'critical',
  },
  {
    id: 'm-2',
    occurred_at: new Date(Date.now() - 120000).toISOString(),
    actor: 'destek-botu',
    server: 'filesystem',
    tool: 'read_file',
    allowed: true,
    reason: 'politika sağlandı',
    risk_score: 20,
    risk_level: 'low',
  },
]

describe('McpAuditPanel', () => {
  it('basligi gosterir', () => {
    render(<McpAuditPanel audit={summary} connected loading={false} />)
    expect(screen.getByTestId('mcp-panel').textContent).toMatch(/MCP Gateway/i)
  })

  it('toplam izinli engelli sayilarini gosterir', () => {
    render(<McpAuditPanel audit={summary} connected records={records} />)
    const panel = screen.getByTestId('mcp-panel')
    expect(panel.textContent).toContain('128')
    expect(panel.textContent).toContain('112')
    expect(panel.textContent).toContain('16')
  })

  it('engellenen cagri oranini gosterir', () => {
    render(<McpAuditPanel audit={summary} connected records={records} />)
    // 16 / 128 = %12.5 -> %13
    expect(screen.getByTestId('mcp-panel').textContent).toContain('%13')
  })

  it('engellenen cagri varsa baslikta uyari rozeti gosterir', () => {
    render(<McpAuditPanel audit={summary} connected records={records} />)
    expect(screen.getByTestId('mcp-panel').textContent).toMatch(/16 engelli/i)
  })

  it('engellenen cagri yoksa uyari rozeti gostermez', () => {
    const clean: McpAuditSummary = { ...summary, denied: 0, total: 10, allowed: 10 }
    render(<McpAuditPanel audit={clean} connected />)
    expect(screen.getByTestId('mcp-panel').textContent).toMatch(/0 engelli/i)
  })

  it('risk kademesi dagilimini dort satirda gosterir', () => {
    render(<McpAuditPanel audit={summary} connected records={records} />)
    expect(screen.getAllByTestId('mcp-risk-row').length).toBe(4)
  })

  it('risk kademelerini Turkce etiketler', () => {
    render(<McpAuditPanel audit={summary} connected records={records} />)
    const panel = screen.getByTestId('mcp-panel')
    expect(panel.textContent).toContain('Kritik')
    expect(panel.textContent).toContain('Yüksek')
    expect(panel.textContent).toContain('Orta')
    expect(panel.textContent).toContain('Düşük')
  })

  it('kayit listesi icin her kaydi ayri satirda gosterir', () => {
    render(<McpAuditPanel audit={summary} connected records={records} />)
    expect(screen.getAllByTestId('mcp-record').length).toBe(2)
  })

  it('engellenen kaydi ENGELLENDI olarak isaretler', () => {
    render(<McpAuditPanel audit={summary} connected records={records} />)
    const rows = screen.getAllByTestId('mcp-record')
    expect(rows[0].textContent).toContain('ENGELLENDİ')
    expect(rows[1].textContent).toContain('İZİN')
  })

  it('sunucu ve arac adini gosterir', () => {
    render(<McpAuditPanel audit={summary} connected records={records} />)
    const rows = screen.getAllByTestId('mcp-record')
    expect(rows[0].textContent).toContain('shell/exec_command')
    expect(rows[1].textContent).toContain('filesystem/read_file')
  })

  it('risk skorunu gosterir', () => {
    render(<McpAuditPanel audit={summary} connected records={records} />)
    const rows = screen.getAllByTestId('mcp-record')
    expect(rows[0].textContent).toContain('95')
  })

  it('engelleme gerekcesini gosterir', () => {
    render(<McpAuditPanel audit={summary} connected records={records} />)
    // İki kayıt var; gerekçeleri kendi satırlarında olmalı
    const rows = screen.getAllByTestId('mcp-record')
    expect(rows[0].textContent).toContain('risk eşiği aşıldı')
    expect(rows[1].textContent).toContain('politika sağlandı')
  })

  it('kayit yoksa liste bolumunu gostermeyebilir', () => {
    render(<McpAuditPanel audit={summary} connected records={[]} />)
    expect(screen.queryAllByTestId('mcp-record').length).toBe(0)
  })

  it('kalici kayit oldugunu alt bilgide yazar', () => {
    render(<McpAuditPanel audit={summary} connected records={records} />)
    const note = screen.getByTestId('mcp-persistence-note')
    expect(note.textContent).toMatch(/kalıcı/i)
    expect(note.textContent).not.toMatch(/bellek içi/i)
  })

  it('api baglantisi yoksa acikca yazar', () => {
    render(<McpAuditPanel audit={null} connected={false} />)
    const panel = screen.getByTestId('mcp-panel')
    expect(panel.textContent).toMatch(/bağlantısı yok/i)
    expect(panel.textContent).toContain('MIRAGE_API_BASE_URL')
  })

  it('baglanti yokken sessizce bos liste gostermez', () => {
    render(<McpAuditPanel audit={null} connected={false} />)
    expect(screen.queryAllByTestId('mcp-record').length).toBe(0)
    expect(screen.getByTestId('mcp-panel').textContent).toMatch(/bağlantısı yok/i)
  })

  it('loading durumunda mesaj gosterir', () => {
    render(<McpAuditPanel audit={null} connected={false} loading />)
    expect(screen.getByTestId('mcp-panel').textContent).toMatch(/okunuyor/i)
  })
})
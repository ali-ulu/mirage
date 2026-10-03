import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { RagPanel } from '@/components/mirage/rag-panel'
import { ragActionLabel } from '@/lib/mirage/types'

const fetchMock = vi.fn()

beforeEach(() => {
  fetchMock.mockReset()
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

function okResponse(body: unknown) {
  return { ok: true, json: async () => body }
}

function verdictBody(action: string, extra: Record<string, unknown> = {}) {
  return {
    verdicts: [
      {
        source_id: 'panel',
        action,
        allowed: action === 'allow',
        severity: null,
        findings: [],
        reasons: [],
        ...extra,
      },
    ],
    summary: { total: 1, allowed: 1, quarantined: 0, rejected: 0 },
  }
}

describe('ragActionLabel', () => {
  it('allow Turkceye cevirir', () => {
    expect(ragActionLabel('allow')).toBe('Kabul edildi')
  })

  it('quarantine Turkceye cevirir', () => {
    expect(ragActionLabel('quarantine')).toBe('Karantinaya alındı')
  })

  it('reject Turkceye cevirir', () => {
    expect(ragActionLabel('reject')).toBe('Reddedildi')
  })

  it('bilinmeyen degeri oldugu gibi doner', () => {
    expect(ragActionLabel('bilinmeyen')).toBe('bilinmeyen')
  })
})

describe('RagPanel', () => {
  it('basligi gosterir', () => {
    render(<RagPanel />)
    expect(screen.getByTestId('rag-panel').textContent).toMatch(/RAG Guard/i)
  })

  it('tarama butonu bos metinle devre disidir', () => {
    render(<RagPanel />)
    expect((screen.getByTestId('rag-scan') as HTMLButtonElement).disabled).toBe(true)
  })

it('kabul kararini gosterir', async () => {
    const user = userEvent.setup()
    fetchMock.mockResolvedValue(okResponse(verdictBody('allow')))
    render(<RagPanel />)
    await user.type(screen.getByTestId('rag-input'), 'guvenli metin')
    await user.click(screen.getByTestId('rag-scan'))

    await waitFor(() => {
      expect(screen.getByTestId('rag-verdict').textContent).toBe('Kabul edildi')
    })
  })

  it('reddetme kararini ve gerekceyi gosterir', async () => {
    const user = userEvent.setup()
    fetchMock.mockResolvedValue(
      okResponse(
        verdictBody('reject', {
          severity: 'high',
          findings: [{ name: 'prompt_injection' }],
          reasons: ['prompt injection iması bulundu'],
        })
      )
    )
    render(<RagPanel />)
    await user.type(screen.getByTestId('rag-input'), 'zararli metin')
    await user.click(screen.getByTestId('rag-scan'))

    await waitFor(() => {
      expect(screen.getByTestId('rag-verdict').textContent).toBe('Reddedildi')
    })
    expect(screen.getByTestId('rag-reasons').textContent).toContain(
      'prompt injection iması bulundu'
    )
  })

  it('karantina kararini gosterir', async () => {
    const user = userEvent.setup()
    fetchMock.mockResolvedValue(
      okResponse(verdictBody('quarantine', { severity: 'medium' }))
    )
    render(<RagPanel />)
    await user.type(screen.getByTestId('rag-input'), 'supheli metin')
    await user.click(screen.getByTestId('rag-scan'))

    await waitFor(() => {
      expect(screen.getByTestId('rag-verdict').textContent).toBe(
        'Karantinaya alındı'
      )
    })
  })

  it('tarama POST ile yapilir ve resource=ragInspect gider', async () => {
    const user = userEvent.setup()
    fetchMock.mockResolvedValue(okResponse(verdictBody('allow')))
    render(<RagPanel />)
    await user.type(screen.getByTestId('rag-input'), 'abc')
    await user.click(screen.getByTestId('rag-scan'))

    await waitFor(() => expect(fetchMock).toHaveBeenCalled())
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toContain('resource=ragInspect')
    expect(init.method).toBe('POST')
  })

  it('baglanti hatasinda guvenli DEmez, acikca yazar', async () => {
    const user = userEvent.setup()
    fetchMock.mockResolvedValue({
      ok: false,
      status: 503,
      json: async () => ({
        error: 'RAG guard unavailable',
        detail: 'MIRAGE_API_BASE_URL yok',
      }),
    })
    render(<RagPanel />)
    await user.type(screen.getByTestId('rag-input'), 'abc')
    await user.click(screen.getByTestId('rag-scan'))

    await waitFor(() => {
      const err = screen.getByTestId('rag-error')
      expect(err.textContent).toContain('Tarama yapılamadı')
      expect(err.textContent).toContain('MIRAGE_API_BASE_URL')
    })
    expect(screen.queryByTestId('rag-verdict')).toBeNull()
  })

  it('tarama oncesi sonuc gostermez', () => {
    render(<RagPanel />)
    expect(screen.queryByTestId('rag-result')).toBeNull()
    expect(screen.queryByTestId('rag-error')).toBeNull()
  })

  it('tarama sirasinda buton Taraniyor olur', async () => {
    const user = userEvent.setup()
    let release: (v: unknown) => void = () => {}
    fetchMock.mockReturnValue(
      new Promise((res) => {
        release = res
      })
    )

    render(<RagPanel />)
    await user.type(screen.getByTestId('rag-input'), 'abc')
    await user.click(screen.getByTestId('rag-scan'))

    await waitFor(() => {
      expect(screen.getByTestId('rag-scan').textContent).toContain('Taranıyor')
    })
    release(okResponse(verdictBody('allow')))
  })
})
  it('metin girilince buton etkinlesir', async () => {
    const user = userEvent.setup()
    render(<RagPanel />)
    await user.type(screen.getByTestId('rag-input'), 'test metni')
    expect((screen.getByTestId('rag-scan') as HTMLButtonElement).disabled).toBe(false)
  })
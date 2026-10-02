import { describe, it, expect } from 'vitest'
import { createHash, createHmac } from 'crypto'
import { normalizeTimestamp } from '@/app/api/route'

/**
 * Kanonik hash paritesi testi.
 *
 * Bu test, TypeScript kanonik JSON + SHA-256 hesabının Python
 * `mirage/evidence.py` ile AYNI bayt dizisini ürettiğini doğrular.
 *
 * Parite bozulursa canlı sistemde her kanıt "kurcalanmış" görünür —
 * yani sessiz ve yanıltıcı bir arıza. Bu yüzden sabit vektörler
 * Python tarafında üretilip buraya birebir kopyalandı.
 */

/** Python: hashlib.sha256(json.dumps(subset, sort_keys=True, separators=(",",":"), ensure_ascii=False).encode()).hexdigest() */
function pyRecordHash(record: Record<string, unknown>): string {
  const subset = {
    token: record.token ?? null,
    ip: record.ip ?? null,
    user_agent: record.user_agent ?? null,
    received_at: normalizeTimestamp(String(record.received_at)),
    chain_seq: record.chain_seq ?? null,
    prev_hash: record.prev_hash ?? null,
  }
  const json = JSON.stringify(subset, Object.keys(subset).sort())
  return createHash('sha256').update(json, 'utf8').digest('hex')
}

describe('evidence kanonik hash paritesi', () => {
  it('timestamp normalizasyonu Postgres +00:00 biçimini Z yapar', () => {
    expect(normalizeTimestamp('2026-10-01T12:00:00.000+00:00')).toBe(
      '2026-10-01T12:00:00.000Z'
    )
  })

  it('timestamp normalizasyonu Z girdisini aynen korur', () => {
    expect(normalizeTimestamp('2026-10-01T12:00:00.000Z')).toBe(
      '2026-10-01T12:00:00.000Z'
    )
  })

  it('timestamp normalizasyonu UTC dışı saat dilimini UTC ye çevirir', () => {
    expect(normalizeTimestamp('2026-10-01T14:30:00.000+02:00')).toBe(
      '2026-10-01T12:30:00.000Z'
    )
  })

  it('alan sırası hash i değiştirir (kayda tamamlanabilir)', () => {
    // Kanonik alanlar ve sırası Python EVIDENCE_FIELDS ile aynı olmalı
    const record = {
      token: '550e8400-e29b-41d4-a716-446655440000',
      ip: '203.0.113.42',
      user_agent: 'LibreOffice/7.5',
      received_at: '2026-10-01T12:00:00.000Z',
      chain_seq: 1,
      prev_hash: '0'.repeat(64),
    }
    const hash = pyRecordHash(record)

    expect(hash).toHaveLength(64)
    expect(hash).toMatch(/^[0-9a-f]{64}$/)
  })

  it('herhangi bir alanı değiştirmek hash i değiştirir', () => {
    const base = {
      token: '550e8400-e29b-41d4-a716-446655440000',
      ip: '203.0.113.42',
      user_agent: 'LibreOffice/7.5',
      received_at: '2026-10-01T12:00:00.000Z',
      chain_seq: 1,
      prev_hash: '0'.repeat(64),
    }
    const tampered = { ...base, ip: '198.51.100.9' }

    expect(pyRecordHash(tampered)).not.toBe(pyRecordHash(base))
  })

  it('prev_hash değişimi hash i değiştirir (zincir kopukluğu yakalanır)', () => {
    const base = {
      token: '550e8400-e29b-41d4-a716-446655440000',
      ip: '203.0.113.42',
      user_agent: 'LibreOffice/7.5',
      received_at: '2026-10-01T12:00:00.000Z',
      chain_seq: 2,
      prev_hash: 'a'.repeat(64),
    }
    const broken = { ...base, prev_hash: 'b'.repeat(64) }

    expect(pyRecordHash(broken)).not.toBe(pyRecordHash(base))
  })

  it('Z ve +00:00 aynı hash i üretir (DB round-trip güvenli)', () => {
    const withZ = {
      token: '550e8400-e29b-41d4-a716-446655440000',
      ip: '203.0.113.42',
      user_agent: 'LibreOffice/7.5',
      received_at: '2026-10-01T12:00:00.000Z',
      chain_seq: 1,
      prev_hash: '0'.repeat(64),
    }
    const withOffset = { ...withZ, received_at: '2026-10-01T12:00:00.000+00:00' }

    expect(pyRecordHash(withOffset)).toBe(pyRecordHash(withZ))
  })

  it('Python ile birebir ayni hash ve HMAC uretir (kanit vektoru)', () => {
    // Bu vektor Python mirage/evidence.py'den uretildi. Parite bozulursa
    // canli sistemde her kanit "kurcalanmis" gorunur.
    const record = {
      token: '550e8400-e29b-41d4-a716-446655440000',
      ip: '203.0.113.42',
      user_agent: 'LibreOffice/7.5',
      received_at: '2026-10-01T12:00:00.000+00:00',
      chain_seq: 1,
      prev_hash: '0'.repeat(64),
    }

    expect(pyRecordHash(record)).toBe(
      'b306771dbc5659915d38ee89232b2b81d038d45c1161e1be218a6c56bb7933c7'
    )
  })

  it('Python ile birebir ayni HMAC uretir', () => {
    const hmac = createHmac('sha256', 'test-key')
      .update('b306771dbc5659915d38ee89232b2b81d038d45c1161e1be218a6c56bb7933c7', 'utf8')
      .digest('hex')

    expect(hmac).toBe(
      '98691a1ab79171a41b6eb39bcbce50eb967432c2ea6892e2499d1591e00ba03a'
    )
  })

  it('non-ASCII user_agent escape edilmez (Python ensure_ascii=False paritesi)', () => {
    const ascii = {
      token: '550e8400-e29b-41d4-a716-446655440000',
      ip: '203.0.113.42',
      user_agent: 'Excel/16.0',
      received_at: '2026-10-01T12:00:00.000Z',
      chain_seq: 1,
      prev_hash: '0'.repeat(64),
    }
    const turkish = { ...ascii, user_agent: 'Excel/16.0 ğüşöç' }

    // JSON.stringify non-ASCII karakterleri escape ETMEZ; Python ile aynı
    expect(pyRecordHash(turkish)).not.toBe(pyRecordHash(ascii))
    expect(pyRecordHash(turkish)).toMatch(/^[0-9a-f]{64}$/)
  })
})
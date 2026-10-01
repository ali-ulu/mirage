// MIRAGE — Kanıt zinciri (evidence chain) testleri (Deno).
//
// Çalıştırma:
//   deno test --no-check --allow-net --allow-env --allow-read tests/evidence_chain_test.ts
//
// Kapsam:
//   1. Python <-> TS paritesi (altın fixture'lar; evidence.py ile birebir)
//   2. Zincir bütünlüğü / kurcalama / kopukluk / sahte HMAC
//   3. getChainHead (zincir başı çözümü)

import { assert, assertEquals, assertNotEquals } from "https://deno.land/std@0.224.0/assert/mod.ts";
import {
  buildEvidenceRecord,
  canonicalJson,
  computeHmac,
  GENESIS_HASH,
  getChainHead,
  normalizeTimestamp,
  recordHash,
  verifyChain,
  verifyHmac,
  type EvidenceInput,
} from "../functions/beacon-receiver/evidence.ts";

const KEY = "test-key-0123456789abcdef";

// Python `scripts/test_evidence_chain.py` ile aynı altın fixture'lar.
const GOLDEN_1: EvidenceInput = {
  token: "550e8400-e29b-41d4-a716-446655440000",
  ip: "203.0.113.42",
  user_agent: "LibreOffice/7.5",
  received_at: "2026-10-01T12:00:00.000Z",
  chain_seq: 1,
  prev_hash: GENESIS_HASH,
};
const GOLDEN_1_HASH = "b306771dbc5659915d38ee89232b2b81d038d45c1161e1be218a6c56bb7933c7";
const GOLDEN_1_HMAC = "962fcde9fa9a9a9aba0753228e3772c8db9fe9c994d14c6f962619e34415a9d7";

const GOLDEN_2: EvidenceInput = {
  token: "550e8400-e29b-41d4-a716-446655440000",
  ip: "198.51.100.7",
  user_agent: "Excel/16.0",
  received_at: "2026-10-01T12:05:00.000Z",
  chain_seq: 2,
  prev_hash: GOLDEN_1_HASH,
};
const GOLDEN_2_HASH = "44f3aaaa150500bfe21c1f6c1304ca699ae45d519685334d8e2279f553ecd344";
const GOLDEN_2_HMAC = "0a1b6e09a069b4559e3e715920ae0d05be27497df38bc66dad63382fddf6e112";

async function chain(n: number) {
  const records: Array<Record<string, unknown>> = [];
  let prev = GENESIS_HASH;
  for (let seq = 1; seq <= n; seq++) {
    const rec = await buildEvidenceRecord(
      {
        token: GOLDEN_1.token,
        ip: GOLDEN_1.ip,
        user_agent: GOLDEN_1.user_agent,
        received_at: `2026-10-01T12:${String(seq).padStart(2, "0")}:00.000Z`,
        chain_seq: seq,
        prev_hash: prev,
      },
      KEY,
    );
    records.push(rec);
    prev = rec.record_hash;
  }
  return records;
}

// ---------------------------------------------------------------------------
// 1. Python <-> TS paritesi
// ---------------------------------------------------------------------------
Deno.test("parite: canonicalJson altın fixture ile eşleşir", async () => {
  const expected =
    '{"chain_seq":1,"ip":"203.0.113.42","prev_hash":"' + GENESIS_HASH +
    '","received_at":"2026-10-01T12:00:00.000Z","token":"550e8400-e29b-41d4-a716-446655440000","user_agent":"LibreOffice/7.5"}';
  assertEquals(canonicalJson(GOLDEN_1 as unknown as Record<string, unknown>), expected);
});

Deno.test("parite: canonicalJson anahtar sırasından bağımsız", async () => {
  const shuffled = {
    prev_hash: GOLDEN_1.prev_hash,
    token: GOLDEN_1.token,
    user_agent: GOLDEN_1.user_agent,
    chain_seq: GOLDEN_1.chain_seq,
    received_at: GOLDEN_1.received_at,
    ip: GOLDEN_1.ip,
  };
  assertEquals(canonicalJson(shuffled), canonicalJson(GOLDEN_1 as unknown as Record<string, unknown>));
});

Deno.test("parite: record_hash Python ile birebir", async () => {
  assertEquals(await recordHash(GOLDEN_1 as unknown as Record<string, unknown>), GOLDEN_1_HASH);
  assertEquals(await recordHash(GOLDEN_2 as unknown as Record<string, unknown>), GOLDEN_2_HASH);
});

Deno.test("parite: hmac Python ile birebir", async () => {
  assertEquals(await computeHmac(KEY, GOLDEN_1_HASH), GOLDEN_1_HMAC);
  assertEquals(await computeHmac(KEY, GOLDEN_2_HASH), GOLDEN_2_HMAC);
});

Deno.test("parite: buildEvidenceRecord altın fixture ile eşleşir", async () => {
  const rec = await buildEvidenceRecord(GOLDEN_1, KEY);
  assertEquals(rec.record_hash, GOLDEN_1_HASH);
  assertEquals(rec.hmac, GOLDEN_1_HMAC);
});

Deno.test("parite: normalizeTimestamp kanonik UTC üretir", () => {
  assertEquals(normalizeTimestamp("2026-10-01T12:00:00.000Z"), "2026-10-01T12:00:00.000Z");
  assertEquals(normalizeTimestamp("2026-10-01T12:00:00+00:00"), "2026-10-01T12:00:00.000Z");
  assertEquals(normalizeTimestamp("2026-10-01T15:00:00+03:00"), "2026-10-01T12:00:00.000Z");
});

Deno.test("parite: DB timestamptz biçimi hash'i bozmaz", async () => {
  const dbForm = { ...GOLDEN_1, received_at: "2026-10-01T12:00:00+00:00" };
  assertEquals(await recordHash(dbForm as unknown as Record<string, unknown>), GOLDEN_1_HASH);
});

// ---------------------------------------------------------------------------
// 2. Zincir bütünlüğü
// ---------------------------------------------------------------------------
Deno.test("verifyChain: bozulmamış zincir ok", async () => {
  const result = await verifyChain(await chain(5), KEY);
  assertEquals(result.ok, true);
  assertEquals(result.checked, 5);
  assertEquals(result.broken_at, null);
});

Deno.test("verifyChain: alan kurcalanınca kırılır", async () => {
  const records = await chain(3);
  records[1].ip = "10.0.0.1";
  const result = await verifyChain(records, KEY);
  assertEquals(result.ok, false);
  assertEquals(result.broken_at, 2);
  assert(result.reason!.includes("record_hash mismatch"));
});

Deno.test("verifyChain: yanlış prev_hash (kopukluk) reddedilir", async () => {
  const records = await chain(3);
  records[2] = await buildEvidenceRecord(
    {
      token: GOLDEN_1.token,
      ip: GOLDEN_1.ip,
      user_agent: GOLDEN_1.user_agent,
      received_at: "2026-10-01T12:03:00.000Z",
      chain_seq: 3,
      prev_hash: "a".repeat(64),
    },
    KEY,
  );
  const result = await verifyChain(records, KEY);
  assertEquals(result.ok, false);
  assertEquals(result.broken_at, 3);
  assert(result.reason!.includes("prev_hash"));
});

Deno.test("verifyChain: sahte hmac reddedilir", async () => {
  const records = await chain(2);
  records[1].hmac = "0".repeat(64);
  const result = await verifyChain(records, KEY);
  assertEquals(result.ok, false);
  assertEquals(result.broken_at, 2);
  assert(result.reason!.includes("hmac"));
});

Deno.test("verifyHmac: doğru/yanlış/boş", async () => {
  assertEquals(await verifyHmac(KEY, GOLDEN_1_HASH, GOLDEN_1_HMAC), true);
  assertEquals(await verifyHmac(KEY, GOLDEN_1_HASH, "deadbeef"), false);
  assertEquals(await verifyHmac(KEY, GOLDEN_1_HASH, ""), false);
  assertEquals(await verifyHmac("wrong-key", GOLDEN_1_HASH, GOLDEN_1_HMAC), false);
});

// ---------------------------------------------------------------------------
// 3. getChainHead
// ---------------------------------------------------------------------------
Deno.test("getChainHead: boş zincirde null", async () => {
  const client = {
    from: () => ({
      select: () => ({ eq: () => ({ order: () => ({ limit: () => Promise.resolve({ data: [], error: null }) }) }) }),
    }),
  };
  assertEquals(await getChainHead(client, GOLDEN_1.token), null);
});

Deno.test("getChainHead: zincir başını döndürür", async () => {
  const client = {
    from: () => ({
      select: () => ({
        eq: () => ({
          order: () => ({
            limit: () => Promise.resolve({ data: [{ chain_seq: 7, record_hash: "abc" }], error: null }),
          }),
        }),
      }),
    }),
  };
  const head = await getChainHead(client, GOLDEN_1.token);
  assertEquals(head, { chain_seq: 7, record_hash: "abc" });
});

Deno.test("verifyChain: sıra karışık gelse de chain_seq'e göre doğrular", async () => {
  const records = await chain(4);
  const shuffled = [records[2], records[0], records[3], records[1]];
  const result = await verifyChain(shuffled, KEY);
  assertEquals(result.ok, true);
  assertEquals(result.checked, 4);
});

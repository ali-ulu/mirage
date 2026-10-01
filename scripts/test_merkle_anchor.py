"""
PR — Merkle ağacı + harici zaman damgası çapası testleri.

Kapsam:
  - `MerkleTree`: kök determinizmi, tek/çift/tek-kalan düğüm, RFC 6962 kuralı.
  - `merkle_proof` + `verify_proof`: dahil olma kanıtı doğru/yanlış öğe.
  - `NullAnchor`: deterministik yerel çapa.
  - `HttpTimestampAnchor`: enjekte edilen `post` ile token; hata → fail-closed.
  - `anchor_evidence_chain`: chain_seq sırası, boş/kayıtsız davranış.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pytest  # noqa: E402

from mirage.merkle_anchor import (  # noqa: E402
    AnchorError,
    HttpTimestampAnchor,
    MerkleTree,
    NullAnchor,
    anchor_evidence_chain,
    merkle_proof,
    merkle_root,
    verify_proof,
)


# ---------------------------------------------------------------------------
# tree
# ---------------------------------------------------------------------------
def test_single_item_root_is_leaf():
    from mirage.merkle_anchor import _leaf_hash

    assert merkle_root(["a"]) == _leaf_hash("a").hex()


def test_root_is_deterministic():
    assert merkle_root(["a", "b", "c"]) == merkle_root(["a", "b", "c"])


def test_root_changes_with_content():
    assert merkle_root(["a", "b"]) != merkle_root(["a", "c"])


def test_odd_node_is_duplicated():
    # 3 yaprak: son seviyede (b,c) birleşir, sonra a ile birlikte kök.
    tree = MerkleTree(["a", "b", "c"])
    assert tree.root == merkle_root(["a", "b", "c"])
    assert len(tree.proof(2)) >= 1


def test_empty_raises():
    with pytest.raises(ValueError):
        merkle_root([])


# ---------------------------------------------------------------------------
# proof
# ---------------------------------------------------------------------------
def test_proof_verifies_for_each_item():
    items = ["h0", "h1", "h2", "h3", "h4"]
    root = merkle_root(items)
    for i, item in enumerate(items):
        proof = merkle_proof(items, i)
        assert verify_proof(item, proof, root) is True


def test_proof_rejects_wrong_item():
    items = ["h0", "h1", "h2"]
    root = merkle_root(items)
    proof = merkle_proof(items, 1)
    assert verify_proof("tampered", proof, root) is False


def test_proof_rejects_wrong_root():
    items = ["h0", "h1"]
    proof = merkle_proof(items, 0)
    assert verify_proof("h0", proof, "0" * 64) is False


def test_proof_index_out_of_range():
    with pytest.raises(IndexError):
        merkle_proof(["a", "b"], 5)


# ---------------------------------------------------------------------------
# anchors
# ---------------------------------------------------------------------------
def test_null_anchor_receipt():
    r = NullAnchor().anchor("ab" * 32)
    assert r.provider == "null" and r.root == "ab" * 32
    assert r.reference and r.anchored_at


def test_null_anchor_deterministic_with_now():
    from datetime import datetime, timezone

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    a = NullAnchor().anchor("cd" * 32, now=now)
    b = NullAnchor().anchor("cd" * 32, now=now)
    assert a == b


def test_http_anchor_uses_injected_post():
    calls = {}

    def fake_post(url, payload):
        calls["url"] = url
        calls["payload"] = payload
        return b"timestamp-token"

    anchor = HttpTimestampAnchor("https://tsa.example/ts", post=fake_post)
    receipt = anchor.anchor("ef" * 32)
    assert receipt.provider == "http" and receipt.token is not None
    assert calls["url"] == "https://tsa.example/ts"
    assert calls["payload"] == bytes.fromhex("ef" * 32)


def test_http_anchor_fail_closed():
    def boom(url, payload):
        raise RuntimeError("network down")

    with pytest.raises(AnchorError):
        HttpTimestampAnchor("https://tsa.example/ts", post=boom).anchor("aa" * 32)


# ---------------------------------------------------------------------------
# chain helper
# ---------------------------------------------------------------------------
def test_anchor_evidence_chain_orders_by_chain_seq():
    records = [
        {"chain_seq": 2, "record_hash": "b" * 64},
        {"chain_seq": 1, "record_hash": "a" * 64},
    ]
    receipt = anchor_evidence_chain(records)
    assert receipt.root == merkle_root(["a" * 64, "b" * 64])


def test_anchor_evidence_chain_skips_missing_hash():
    records = [
        {"chain_seq": 1, "record_hash": "a" * 64},
        {"chain_seq": 2},
    ]
    receipt = anchor_evidence_chain(records)
    assert receipt.root == merkle_root(["a" * 64])


def test_anchor_evidence_chain_empty_raises():
    with pytest.raises(ValueError):
        anchor_evidence_chain([])

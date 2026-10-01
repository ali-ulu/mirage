"""
MIRAGE — Merkle ağacı + harici zaman damgası çapası.

Kanıt zinciri sıralı (blockchain-benzeri) bir HMAC zinciridir. Bu katman onu
**Merkle köküne** indirger ve kökü harici bir zaman damgası servisine
çapalayarak "bu kanıt kümesi şu andan önce vardı" iddiasını kanıtlar. Böylece
MIRAGE'nin non-repudiable kanıt iddiası, tek bir sunucunun saatine/DB'sine
bağımlı olmaktan çıkar (RFC 3161 / OpenTimestamps uyumlu çapa yüzeyi).

Tasarım:
  - Saf/deterministik Merkle ağacı (RFC 6962 tarzı): yaprak = sha256(0x00||veri),
    iç düğüm = sha256(0x01||sol||sağ); tek kalan düğüm kendini kopyalar.
  - `MerkleAnchor` soyutlaması: `anchor(root) -> AnchorReceipt`. Gerçek TSA/OTS
    istemcisi enjekte edilir; test/CI için `NullAnchor` deterministik yerel çapa.
  - `verify_proof`: bir kaydın köke dahil olduğunu yalnızca kök + yol ile kanıtlar
    (tüm zinciri yeniden okumaya gerek yok).
  - Fail-closed: gerçek çapa servisi hata verirse `AnchorError` yükselir.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Optional


class AnchorError(RuntimeError):
    """Harici zaman damgası çapası başarısız oldu (fail-closed)."""


def _sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def _leaf_hash(item: str) -> bytes:
    return _sha256(b"\x00" + item.encode("utf-8"))


def _node_hash(left: bytes, right: bytes) -> bytes:
    return _sha256(b"\x01" + left + right)


@dataclass(frozen=True)
class ProofStep:
    """Merkle yolunun bir adımı: kardeş düğüm ve onun konumu."""

    position: str  # "left" | "right"
    hash: str


@dataclass(frozen=True)
class AnchorReceipt:
    """Bir Merkle kökünün harici çapasına dair makbuz."""

    root: str
    provider: str
    anchored_at: str
    reference: str  # TSA token özeti / OTS yolu / yerel imza
    token: Optional[str] = None  # ham çapa kanıtı (base64) — varsa

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MerkleTree:
    """
    Bir dizi öğeden (genelde `record_hash` hex) deterministik Merkle ağacı.

    Ağaç, seviye seviye indirgenir; her seviyede tek kalan düğüm kendini
    kopyalar (RFC 6962). Boş girdi desteklenmez.
    """

    def __init__(self, items: Iterable[str]):
        self.items: list[str] = list(items)
        if not self.items:
            raise ValueError("Merkle ağacı boş olamaz")
        self._levels: list[list[bytes]] = self._build_levels()

    def _build_levels(self) -> list[list[bytes]]:
        levels: list[list[bytes]] = []
        current = [_leaf_hash(x) for x in self.items]
        levels.append(current)
        while len(current) > 1:
            nxt: list[bytes] = []
            for i in range(0, len(current), 2):
                left = current[i]
                right = current[i + 1] if i + 1 < len(current) else current[i]
                nxt.append(_node_hash(left, right))
            levels.append(nxt)
            current = nxt
        return levels

    @property
    def root(self) -> str:
        return self._levels[-1][0].hex()

    def proof(self, index: int) -> list[ProofStep]:
        """`index`'teki öğe için köke giden Merkle yolunu üretir."""
        if not 0 <= index < len(self.items):
            raise IndexError(f"index out of range: {index}")
        steps: list[ProofStep] = []
        idx = index
        for level in self._levels[:-1]:
            sibling = idx + 1 if idx % 2 == 0 else idx - 1
            if sibling < len(level):
                steps.append(ProofStep(
                    position="right" if idx % 2 == 0 else "left",
                    hash=level[sibling].hex(),
                ))
            else:
                # Kardeş yoksa düğüm kendini kopyalar → yine "right" olarak eklenir.
                steps.append(ProofStep(position="right", hash=level[idx].hex()))
            idx //= 2
        return steps


def merkle_root(items: Iterable[str]) -> str:
    return MerkleTree(items).root


def merkle_proof(items: Iterable[str], index: int) -> list[ProofStep]:
    return MerkleTree(items).proof(index)


def verify_proof(item: str, proof: Iterable[ProofStep], root: str) -> bool:
    """`item`'in, verilen Merkle yoluyla `root`'a bağlandığını doğrular."""
    node = _leaf_hash(item)
    for step in proof:
        sibling = bytes.fromhex(step.hash)
        if step.position == "left":
            node = _node_hash(sibling, node)
        else:
            node = _node_hash(node, sibling)
    return node.hex() == root


# ---------------------------------------------------------------------------
# Çapa (anchor)
# ---------------------------------------------------------------------------
class MerkleAnchor:
    """Kökü harici bir zaman damgasına bağlayan çapa arayüzü."""

    provider = "abstract"

    def anchor(self, root: str, *, now: Optional[datetime] = None) -> AnchorReceipt:
        raise NotImplementedError


class NullAnchor(MerkleAnchor):
    """
    Dış servis yokken deterministik yerel çapa (test/CI).

    `reference`, kök + zamanın SHA-256 özetidir; kriptografik bir üçüncü taraf
    iddiası taşımaz (non-claim: yalnızca yerel bütünlük).
    """

    provider = "null"

    def anchor(self, root: str, *, now: Optional[datetime] = None) -> AnchorReceipt:
        ts = (now or datetime.now(timezone.utc)).isoformat()
        reference = hashlib.sha256(f"{root}|{ts}".encode("utf-8")).hexdigest()
        return AnchorReceipt(root=root, provider=self.provider, anchored_at=ts, reference=reference)


class HttpTimestampAnchor(MerkleAnchor):
    """
    Gerçek RFC 3161 / OpenTimestamps uç noktasına kökü gönderen çapa.

    `post` enjekte edilebilir bir çağrılabilirdir: `post(url, payload: bytes) ->
    bytes` (ham çapa token'ı). Verilmezse `httpx` ile POST edilir (lazy).
    Hata durumunda **fail-closed** `AnchorError` yükselir.
    """

    provider = "http"

    def __init__(
        self,
        url: str,
        *,
        post: Optional[Callable[[str, bytes], bytes]] = None,
        headers: Optional[dict[str, str]] = None,
        timeout: float = 10.0,
    ):
        self.url = url
        self._post = post
        self.headers = headers or {"Content-Type": "application/octet-stream"}
        self.timeout = timeout

    def anchor(self, root: str, *, now: Optional[datetime] = None) -> AnchorReceipt:
        payload = bytes.fromhex(root)
        try:
            token_bytes = self._post_fn()(self.url, payload)
        except AnchorError:
            raise
        except Exception as exc:  # ağ/parse hatası → fail-closed
            raise AnchorError(f"timestamp anchor failed: {exc}") from exc
        ts = (now or datetime.now(timezone.utc)).isoformat()
        reference = hashlib.sha256(token_bytes).hexdigest()
        import base64

        return AnchorReceipt(
            root=root,
            provider=self.provider,
            anchored_at=ts,
            reference=reference,
            token=base64.b64encode(token_bytes).decode("ascii"),
        )

    def _post_fn(self) -> Callable[[str, bytes], bytes]:
        if self._post is not None:
            return self._post

        def _httpx_post(url: str, payload: bytes) -> bytes:
            import httpx  # tembel/opsiyonel bağımlılık

            resp = httpx.post(url, content=payload, headers=self.headers, timeout=self.timeout)
            resp.raise_for_status()
            return resp.content

        return _httpx_post


def anchor_evidence_chain(
    records: Iterable[dict[str, Any]],
    *,
    anchor: Optional[MerkleAnchor] = None,
    now: Optional[datetime] = None,
) -> AnchorReceipt:
    """
    Kanıt kayıtlarının `record_hash`'lerinden Merkle kökü kurar ve çapalar.

    Kayıtlar `chain_seq`'e göre sıralanır (kanonik sıra); `record_hash` yoksa
    atlanır. Kayıt yoksa `ValueError`.
    """
    ordered = sorted(
        (r for r in records if r.get("record_hash")),
        key=lambda r: int(r.get("chain_seq", 0)),
    )
    hashes = [str(r["record_hash"]) for r in ordered]
    root = merkle_root(hashes)
    return (anchor or NullAnchor()).anchor(root, now=now)


__all__ = [
    "AnchorError",
    "AnchorReceipt",
    "HttpTimestampAnchor",
    "MerkleAnchor",
    "MerkleTree",
    "NullAnchor",
    "ProofStep",
    "anchor_evidence_chain",
    "merkle_proof",
    "merkle_root",
    "verify_proof",
]

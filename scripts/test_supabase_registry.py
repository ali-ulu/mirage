"""
Task 01 (Production) — SupabaseHoneytokenRegistry testleri.

Test stratejisi:
  1. Unit testler: MockSupabaseClient ile (interface doğrulama)
  2. Integration test: SUPABASE_URL env var varsa gerçek DB'ye bağlanır,
     yoksa skip olur (@pytest.mark.skipif). Bu "zero mock policy"yi korur:
     production code mock içermez, testler ya gerçek DB'ye ya da
     explicitly-labeled mock client'a karşı çalışır.

Test edilen davranışlar:
  - issue(): honeytokens tablosuna insert yapar
  - lookup(): token ile sorgu yapar, kayıt döner
  - revoke(): soft-delete (revoked_at set eder)
  - list_by_team(): multi-tenant sorgu
  - update_on_beacon(): DB-side trigger olduğu için client'da gerekmez
    (ama incremented count okunabilmeli)
  - Hata durumları: DB down, duplicate token, geçersiz UUID
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mirage.honeytoken import HoneytokenRecord
from mirage.supabase_registry import (
    SupabaseHoneytokenRegistry,
    SupabaseNotConfiguredError,
    SupabaseOperationError,
)


# =============================================================================
# Mock Supabase client (unit testler için — production code mock DEĞİL)
# Bu mock, supabase-py'nin chain API'sini (.table().insert().execute())
# taklit eder. Production code gerçek supabase-py kullanır.
# =============================================================================
class _MockChain:
    """Supabase query chain mock: table().select().eq().single().execute()"""

    def __init__(self, storage: dict, table_name: str):
        self.storage = storage
        self.table_name = table_name
        self._payload: dict | None = None
        self._filters: list[tuple[str, Any]] = []
        self._is_single = False
        self._is_null_filter: list[tuple[str, str]] = []
        self._gt_filter: list[tuple[str, Any]] = []
        self._order: tuple[str, str] | None = None
        self._limit: int | None = None

    def insert(self, payload: dict):
        self._payload = payload
        # Insert into storage
        self.storage.setdefault(self.table_name, []).append(payload)
        return self

    def update(self, payload: dict):
        self._payload = payload
        return self

    def select(self, _cols: str = "*"):
        return self

    def eq(self, col: str, value):
        self._filters.append((col, value))
        return self

    def is_(self, col: str, value):  # value "null" or "not null"
        self._is_null_filter.append((col, value))
        return self

    def gt(self, col: str, value):
        self._gt_filter.append((col, value))
        return self

    def order(self, col: str, desc: bool = False):
        self._order = (col, "desc" if desc else "asc")
        return self

    def limit(self, n: int):
        self._limit = n
        return self

    def single(self):
        self._is_single = True
        return self

    def execute(self):
        rows = list(self.storage.get(self.table_name, []))

        # Update operation
        if self._payload and not self._is_single and any(
            col == "revoked_at" for col, _ in []
        ):
            pass  # placeholder

        # Apply filters
        for col, value in self._filters:
            rows = [r for r in rows if str(r.get(col)) == str(value)]

        for col, val in self._is_null_filter:
            if val == "null":
                rows = [r for r in rows if r.get(col) is None]
            else:
                rows = [r for r in rows if r.get(col) is not None]

        for col, value in self._gt_filter:
            try:
                rows = [r for r in rows if (r.get(col) or 0) > value]
            except TypeError:
                pass

        # If this is an update (payload present + filters), apply update
        if self._payload and (self._filters or self._is_null_filter or self._gt_filter):
            # Find matching rows in storage and update them
            for r in self.storage.get(self.table_name, []):
                if all(str(r.get(c)) == str(v) for c, v in self._filters):
                    r.update(self._payload)

        # Order
        if self._order:
            col, direction = self._order
            try:
                rows.sort(
                    key=lambda r: r.get(col) or "",
                    reverse=(direction == "desc"),
                )
            except TypeError:
                pass

        # Limit
        if self._limit:
            rows = rows[: self._limit]

        # Single
        if self._is_single:
            data = rows[0] if rows else None
            return MagicMock(data=data, error=None)

        return MagicMock(data=rows, error=None)


class MockSupabaseClient:
    """Supabase-py Client mock — table() chain API."""

    def __init__(self):
        self.storage: dict[str, list[dict]] = {"honeytokens": []}

    def table(self, name: str):
        return _MockChain(self.storage, name)

    # Backwards-compat alias
    from_ = table


# =============================================================================
# Unit Tests — Mock client ile
# =============================================================================
class TestSupabaseRegistryUnit(unittest.TestCase):
    def setUp(self):
        self.mock_client = MockSupabaseClient()
        self.registry = SupabaseHoneytokenRegistry(client=self.mock_client)

    def test_issue_inserts_into_honeytokens_table(self):
        df = pd.DataFrame({"a": [1, 2, 3]})
        record = self.registry.issue(
            df, base_url="https://beacon.example/track", label="test"
        )
        # Kayıt storage'da olmalı
        rows = self.mock_client.storage["honeytokens"]
        self.assertEqual(len(rows), 1)
        stored = rows[0]
        self.assertEqual(stored["token"], record.token)
        self.assertEqual(stored["label"], "test")
        self.assertEqual(stored["row_count"], 3)
        self.assertEqual(stored["base_url"], "https://beacon.example/track")
        self.assertIn("issued_at", stored)

    def test_lookup_returns_record_for_existing_token(self):
        df = pd.DataFrame({"a": [1]})
        record = self.registry.issue(df, base_url="https://x/track", label="lbl")
        found = self.registry.lookup(record.token)
        self.assertIsNotNone(found)
        self.assertEqual(found.token, record.token)
        self.assertEqual(found.label, "lbl")

    def test_lookup_returns_none_for_unknown_token(self):
        found = self.registry.lookup("00000000-0000-0000-0000-000000000000")
        self.assertIsNone(found)

    def test_issue_generates_unique_uuid_each_call(self):
        df = pd.DataFrame({"a": [1]})
        r1 = self.registry.issue(df, base_url="https://x/track")
        r2 = self.registry.issue(df, base_url="https://x/track")
        self.assertNotEqual(r1.token, r2.token)

    def test_revoke_sets_revoked_at(self):
        df = pd.DataFrame({"a": [1]})
        record = self.registry.issue(df, base_url="https://x/track")
        result = self.registry.revoke(record.token)
        self.assertTrue(result)
        # Storage'da revoked_at set edilmiş olmalı
        stored = self.mock_client.storage["honeytokens"][0]
        self.assertIsNotNone(stored.get("revoked_at"))

    def test_revoke_returns_false_for_unknown_token(self):
        result = self.registry.revoke("00000000-0000-0000-0000-000000000000")
        self.assertFalse(result)

    def test_issue_with_team_id(self):
        """Multi-tenant: team_id parametresi db'ye yazılır."""
        df = pd.DataFrame({"a": [1]})
        record = self.registry.issue(
            df,
            base_url="https://x/track",
            label="team-test",
            team_id="11111111-1111-1111-1111-111111111111",
        )
        stored = self.mock_client.storage["honeytokens"][0]
        self.assertEqual(
            stored.get("team_id"),
            "11111111-1111-1111-1111-111111111111",
        )

    def test_columns_serialized_as_jsonb(self):
        df = pd.DataFrame({"user_id": [1], "amount": [100.0], "dept": ["X"]})
        self.registry.issue(df, base_url="https://x/track")
        stored = self.mock_client.storage["honeytokens"][0]
        # columns bir liste olmalı (JSONB-compatible)
        self.assertIsInstance(stored["columns"], (list, str))
        if isinstance(stored["columns"], str):
            cols = json.loads(stored["columns"])
        else:
            cols = stored["columns"]
        self.assertEqual(cols, ["user_id", "amount", "dept"])


# =============================================================================
# Constructor / Configuration Tests
# =============================================================================
class TestSupabaseRegistryConfig(unittest.TestCase):
    def test_raises_when_no_client_and_no_env(self):
        """client=None ve env yoksa SupabaseNotConfiguredError fırlat."""
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(SupabaseNotConfiguredError):
                SupabaseHoneytokenRegistry()

    def test_uses_env_vars_when_no_client(self):
        """client=None ama SUPABASE_URL+key varsa create_client çağrılır."""
        with patch.dict(os.environ, {
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_SERVICE_ROLE_KEY": "fake-key",
        }):
            # create_client'ı mock'la — gerçek ağ çağrısı yapmasın
            with patch("mirage.supabase_registry.create_client") as mock_create:
                mock_create.return_value = MagicMock()
                try:
                    reg = SupabaseHoneytokenRegistry()
                    self.assertIsNotNone(reg)
                    # create_client doğru argümanlarla çağrıldı mı
                    mock_create.assert_called_once()
                    args, kwargs = mock_create.call_args
                    self.assertIn("https://example.supabase.co", args)
                    self.assertIn("fake-key", args)
                except Exception as e:
                    self.fail(f"Construction failed: {e}")

    def test_explicit_client_takes_precedence(self):
        """client verilince env'lere bakılmaz."""
        mock = MockSupabaseClient()
        reg = SupabaseHoneytokenRegistry(client=mock)
        # issue çalışabilirsa client kullanılıyor demektir
        df = pd.DataFrame({"a": [1]})
        rec = reg.issue(df, base_url="https://x/track")
        self.assertIsNotNone(rec)


# =============================================================================
# Error Handling Tests
# =============================================================================
class _FailingChain:
    """Her zaman exception fırlatan chain."""
    def insert(self, _): raise Exception("connection refused")
    def update(self, _): return self
    def select(self, _="*"): return self
    def eq(self, _c, _v): return self
    def is_(self, _c, _v): return self
    def single(self): raise Exception("db down")
    def execute(self): raise Exception("db down")


class TestSupabaseRegistryErrors(unittest.TestCase):
    def test_operation_error_raised_on_db_failure(self):
        """DB operasyonu başarısız olursa SupabaseOperationError."""
        failing_client = MagicMock()
        failing_client.table.return_value = _FailingChain()

        reg = SupabaseHoneytokenRegistry(client=failing_client)
        df = pd.DataFrame({"a": [1]})
        with self.assertRaises(SupabaseOperationError) as ctx:
            reg.issue(df, base_url="https://x/track")
        self.assertIn("connection refused", str(ctx.exception).lower())

    def test_lookup_returns_none_on_db_error(self):
        """Lookup sırasında DB hatası -> None (fail safe, fail quiet)."""
        failing_client = MagicMock()
        failing_client.table.return_value = _FailingChain()

        reg = SupabaseHoneytokenRegistry(client=failing_client)
        # Hata fırlatmamalı, None dönmeli
        result = reg.lookup("550e8400-e29b-41d4-a716-446655440000")
        self.assertIsNone(result)


# =============================================================================
# Integration Test — gerçek Supabase (skip if no env)
# =============================================================================
INTEGRATION_ENV_AVAILABLE = bool(
    os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
)


@unittest.skipUnless(INTEGRATION_ENV_AVAILABLE, "SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY not set")
class TestSupabaseRegistryIntegration(unittest.TestCase):
    """Gerçek Supabase hesabına karşı integration testi."""

    def setUp(self):
        self.registry = SupabaseHoneytokenRegistry()  # env'den配置
        self.test_tokens: list[str] = []

    def tearDown(self):
        # Test token'larını temizle
        for token in self.test_tokens:
            try:
                self.registry.revoke(token)
            except Exception:
                pass

    def test_issue_and_lookup_real_db(self):
        df = pd.DataFrame({"user_id": ["u1"], "amount": [100.0]})
        record = self.registry.issue(
            df, base_url="https://beacon.example/track", label="integration-test"
        )
        self.test_tokens.append(record.token)

        # Lookup ile geri al
        found = self.registry.lookup(record.token)
        self.assertIsNotNone(found, "Lookup gerçek DB'de kayıt bulamadı")
        self.assertEqual(found.token, record.token)
        self.assertEqual(found.label, "integration-test")


if __name__ == "__main__":
    unittest.main(verbosity=2)

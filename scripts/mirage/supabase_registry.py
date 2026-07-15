"""
MIRAGE Task 01 (Production) — Supabase-backed HoneytokenRegistry.

Bu modül, in-memory HoneytokenRegistry'nin production-grade替代ıdır.
Tüm token kayıtları Supabase PostgreSQL'de tutulur → server restart'ından
sonra bile persisted kalır.

Production kullanımı:
    reg = SupabaseHoneytokenRegistry()  # env'den配置
    record = reg.issue(df, base_url=..., label=..., team_id=...)

Test kullanımı (mock client):
    reg = SupabaseHoneytokenRegistry(client=mock_client)

Hata yönetimi:
  - DB bağlantısı yoksa SupabaseNotConfiguredError (construction'da)
  - DB operasyonu başarısızsa SupabaseOperationError (runtime'da)
  - Lookup sessizce None döner (fail-safe)
"""
from __future__ import annotations

import os
import uuid as uuidlib
from datetime import datetime, timezone
from typing import Any, Optional

from .honeytoken import HoneytokenRecord

try:
    from supabase import create_client, Client as SupabaseClient
    try:
        from supabase.lib.client_options import ClientOptions
        _SUPABASE_AVAILABLE = True
    except ImportError:
        ClientOptions = None  # older versions
        _SUPABASE_AVAILABLE = True
except ImportError:
    _SUPABASE_AVAILABLE = False
    create_client = None  # type: ignore[assignment]
    SupabaseClient = Any  # type: ignore
    ClientOptions = None


class SupabaseNotConfiguredError(RuntimeError):
    """SUPABASE_URL/KEY env yok ve client explicit verilmedi."""


class SupabaseOperationError(RuntimeError):
    """Supabase DB operasyonu sırasında hata."""


def _safe_supabase_call(operation_name: str, fn):
    """Bir Supabase çağrısını sar, exception'ı SupabaseOperationError'a çevir."""
    try:
        return fn()
    except Exception as e:
        raise SupabaseOperationError(
            f"Supabase operation '{operation_name}' failed: {e}"
        ) from e


class SupabaseHoneytokenRegistry:
    """
    Production honeytoken registry backed by Supabase PostgreSQL.

    Tablo şeması: public.honeytokens (migration 0002_honeytokens.sql)
    RLS aktif: service_role full access, anon kapalı.
    """

    TABLE_NAME = "honeytokens"

    def __init__(self, client: Optional[SupabaseClient] = None):
        """
        Args:
            client: Optional explicit Supabase client. None ise env'den
                   (SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY) oluşturulur.
        """
        if client is not None:
            self._client = client
        else:
            self._client = self._build_client_from_env()

    @staticmethod
    def _build_client_from_env() -> SupabaseClient:
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        if not url or not key:
            raise SupabaseNotConfiguredError(
                "Supabase registry requires either an explicit client or "
                "SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY environment variables. "
                f"Got: SUPABASE_URL={'set' if url else 'missing'}, "
                f"KEY={'set' if key else 'missing'}"
            )
        if create_client is None:
            raise SupabaseNotConfiguredError(
                "supabase-py not installed. Run: pip install supabase"
            )
        # supabase-py 2.x uses ClientOptions
        if ClientOptions is not None:
            # Server-side (service role) usage — no session, no refresh
            options = ClientOptions(
                auto_refresh_token=False,
                persist_session=False,
            )
            return create_client(url, key, options=options)
        return create_client(url, key)

    # ------------------------------------------------------------------
    # Public API — HoneytokenRecord döndürür (geriye uyumlu)
    # ------------------------------------------------------------------
    def issue(
        self,
        df: Any,  # pd.DataFrame
        base_url: str,
        label: str = "",
        team_id: Optional[str] = None,
        file_name: Optional[str] = None,
        file_sha256: Optional[str] = None,
        file_size_bytes: Optional[int] = None,
        expires_at: Optional[str] = None,
    ) -> HoneytokenRecord:
        """Yeni honeytoken üret, DB'ye yaz, record döndür."""
        token = str(uuidlib.uuid4())
        full_url = f"{base_url.rstrip('/')}/{token}"
        now = datetime.now(timezone.utc).isoformat()

        # DataFrame metadata
        columns = list(df.columns) if hasattr(df, "columns") else []
        row_count = len(df) if hasattr(df, "__len__") else 0

        payload = {
            "token": token,
            "base_url": base_url,
            "full_url": full_url,
            "label": label,
            "row_count": int(row_count),
            "columns": columns,  # JSONB array
            "team_id": team_id,
            "file_name": file_name,
            "file_sha256": file_sha256,
            "file_size_bytes": file_size_bytes,
            "issued_at": now,
            "expires_at": expires_at,
            "triggered_count": 0,
        }

        def _do_insert():
            # supabase-py chain
            result = (
                self._client.table(self.TABLE_NAME)
                .insert(payload)
                .execute()
            )
            return result

        _safe_supabase_call("insert_honeytoken", _do_insert)

        return HoneytokenRecord(
            token=token,
            base_url=base_url,
            full_url=full_url,
            label=label,
            row_count=row_count,
            columns=columns,
            created_at=now,
            file_sha256=file_sha256,
        )

    def lookup(self, token: str) -> Optional[HoneytokenRecord]:
        """Token ile sorgu. Bulunamazsa None (fail-safe)."""
        # UUID validate
        try:
            uuidlib.UUID(token)
        except (ValueError, AttributeError):
            return None

        def _do_lookup():
            return (
                self._client.table(self.TABLE_NAME)
                .select("*")
                .eq("token", token)
                .single()
                .execute()
            )

        try:
            result = _safe_supabase_call("lookup_honeytoken", _do_lookup)
        except SupabaseOperationError:
            return None

        if not result or not result.data:
            return None

        return self._row_to_record(result.data)

    def revoke(self, token: str) -> bool:
        """Soft-delete: revoked_at set eder. Başarılı True, yoksa False."""
        now = datetime.now(timezone.utc).isoformat()

        def _do_revoke():
            return (
                self._client.table(self.TABLE_NAME)
                .update({"revoked_at": now})
                .eq("token", token)
                .execute()
            )

        try:
            result = _safe_supabase_call("revoke_honeytoken", _do_revoke)
        except SupabaseOperationError:
            return False

        return bool(result and result.data and len(result.data) > 0)

    def list_active(
        self,
        team_id: Optional[str] = None,
        limit: int = 100,
    ) -> list[HoneytokenRecord]:
        """Aktif (revoked edilmemiş) token'ları listele."""
        def _do_list():
            query = (
                self._client.table(self.TABLE_NAME)
                .select("*")
                .is_("revoked_at", "null")
                .order("issued_at", desc=True)
                .limit(limit)
            )
            if team_id:
                query = query.eq("team_id", team_id)
            return query.execute()

        try:
            result = _safe_supabase_call("list_active_honeytokens", _do_list)
        except SupabaseOperationError:
            return []

        if not result or not result.data:
            return []

        return [self._row_to_record(row) for row in result.data]

    def list_triggered(
        self,
        team_id: Optional[str] = None,
        limit: int = 50,
    ) -> list[HoneytokenRecord]:
        """Tetiklenmiş (triggered_count > 0) token'ları listele."""
        def _do_list():
            query = (
                self._client.table(self.TABLE_NAME)
                .select("*")
                .gt("triggered_count", 0)
                .order("last_triggered_at", desc=True)
                .limit(limit)
            )
            if team_id:
                query = query.eq("team_id", team_id)
            return query.execute()

        try:
            result = _safe_supabase_call("list_triggered_honeytokens", _do_list)
        except SupabaseOperationError:
            return []

        if not result or not result.data:
            return []

        return [self._row_to_record(row) for row in result.data]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _row_to_record(row: dict) -> HoneytokenRecord:
        """Supabase satırını HoneytokenRecord'a çevir."""
        columns_data = row.get("columns", [])
        # JSONB'den gelmiş olabilir, list veya string
        if isinstance(columns_data, str):
            import json
            try:
                columns_data = json.loads(columns_data)
            except Exception:
                columns_data = []

        return HoneytokenRecord(
            token=str(row["token"]),
            base_url=row.get("base_url", ""),
            full_url=row.get("full_url", ""),
            label=row.get("label", ""),
            row_count=int(row.get("row_count", 0)),
            columns=list(columns_data) if columns_data else [],
            created_at=str(row.get("issued_at", "")),
            file_sha256=row.get("file_sha256"),
        )

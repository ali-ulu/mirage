"""
MIRAGE — Supabase-backed prompt-layer canary kayıt defteri.

`agent.prompt_canary.CanaryRegistry`'nin production-grade karşılığıdır: canary
kayıtları Supabase PostgreSQL'de (`public.prompt_canaries`, migration 0005)
tutulur, böylece server restart'ından sonra da sızıntı tespiti çalışır.

Aynı public API (`issue` / `lookup` / `match` / `all_records`) sunar; bu sayede
sunucu tarafında in-memory ile şeffaf biçimde değiştirilebilir (Liskov).

Hata yönetimi (registry deseniyle aynı):
  - client/env yoksa construction'da SupabaseNotConfiguredError
  - lookup/match sessizce boş döner (fail-safe)
"""
from __future__ import annotations

import uuid as uuidlib
from typing import Optional

from .agent.prompt_canary import (
    VALID_CONTEXTS,
    PromptCanary,
    build_marker,
    detect_canaries,
)
from .supabase_registry import (
    SupabaseClient,
    SupabaseOperationError,
    _safe_supabase_call,
    build_supabase_client_from_env,
)


class SupabaseCanaryRegistry:
    """`prompt_canaries` tablosu için kalıcı canary kayıt defteri."""

    TABLE_NAME = "prompt_canaries"

    def __init__(self, client: Optional[SupabaseClient] = None):
        if client is not None:
            self._client = client
        else:
            self._client = build_supabase_client_from_env()

    def issue(self, context: str, label: str = "") -> PromptCanary:
        """Yeni canary üret, DB'ye yaz, kaydı döndür."""
        if context not in VALID_CONTEXTS:
            raise ValueError(
                f"Invalid context {context!r}; expected one of {VALID_CONTEXTS}"
            )
        token = str(uuidlib.uuid4())
        marker = build_marker(token)
        payload = {"token": token, "marker": marker, "context": context, "label": label}

        def _do_insert():
            return self._client.table(self.TABLE_NAME).insert(payload).execute()

        _safe_supabase_call("insert_prompt_canary", _do_insert)
        # created_at DB tarafından atanır; istemciye dönerken marker/token yeterli.
        return PromptCanary(
            token=token,
            marker=marker,
            context=context,
            label=label,
            created_at="",
        )

    def lookup(self, token: str) -> Optional[PromptCanary]:
        """Token ile sorgu. Bulunamazsa/geçersizse None (fail-safe)."""
        try:
            uuidlib.UUID(token)
        except (ValueError, AttributeError, TypeError):
            return None

        def _do_lookup():
            return (
                self._client.table(self.TABLE_NAME)
                .select("*")
                .eq("token", token)
                .limit(1)
                .execute()
            )

        try:
            result = _safe_supabase_call("lookup_prompt_canary", _do_lookup)
        except SupabaseOperationError:
            return None
        if not result or not result.data:
            return None
        return self._row_to_canary(result.data[0])

    def match(self, text: str) -> list[PromptCanary]:
        """Metinde geçen ve DB'de kayıtlı olan canary'leri (görünme sırasıyla) döndürür."""
        tokens = detect_canaries(text)
        if not tokens:
            return []

        def _do_query():
            return (
                self._client.table(self.TABLE_NAME)
                .select("*")
                .in_("token", tokens)
                .execute()
            )

        try:
            result = _safe_supabase_call("match_prompt_canary", _do_query)
        except SupabaseOperationError:
            return []
        if not result or not result.data:
            return []

        by_token = {row["token"]: self._row_to_canary(row) for row in result.data}
        return [by_token[t] for t in tokens if t in by_token]

    def all_records(self, limit: int = 200) -> list[PromptCanary]:
        """En yeni canary'ler önce olacak şekilde listeler."""
        def _do_list():
            return (
                self._client.table(self.TABLE_NAME)
                .select("*")
                .order("created_at", desc=True)
                .limit(limit)
                .execute()
            )

        try:
            result = _safe_supabase_call("list_prompt_canaries", _do_list)
        except SupabaseOperationError:
            return []
        if not result or not result.data:
            return []
        return [self._row_to_canary(row) for row in result.data]

    @staticmethod
    def _row_to_canary(row: dict) -> PromptCanary:
        return PromptCanary(
            token=str(row.get("token", "")),
            marker=str(row.get("marker", "")),
            context=str(row.get("context", "")),
            label=str(row.get("label", "")),
            created_at=(str(row["created_at"]) if row.get("created_at") is not None else ""),
        )

"""
MIRAGE — Takım üyeliği deposu (Supabase-backed, service_role).

`team_members` (migration 0008) üzerinden kullanıcı-takım üyeliğini yönetir.
Üyeliğin YÖNETİMİ uygulama katmanına (service_role) aittir; RLS ise
`authenticated` istemcilerin yalnızca üye oldukları takımları görmesini sağlar
(0008). Bu ayrım bilinçlidir: üyelik yazımı asla `authenticated` rolüne
bırakılmaz.

Tasarım:
  - Append-only değil (üyelik eklenip kaldırılabilir) — bu yüzden UPDATE/DELETE
    policy'si yok; yönetim service_role ile yapılır.
  - Girdi doğrulaması: user_id/team_id geçerli UUID olmalı, role bilinen bir
    değer olmalı. Geçersiz girdi DB'ye gitmeden ValueError yükseltir.
"""
from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from typing import Any, Optional

from .supabase_registry import (
    SupabaseClient,
    SupabaseOperationError,
    _safe_supabase_call,
    build_supabase_client_from_env,
)

TEAM_MEMBERS_TABLE = "team_members"
VALID_ROLES = ("owner", "admin", "member")


@dataclass(frozen=True)
class TeamMember:
    """Kalıcı üyelik kaydı (DB satırının Python karşılığı)."""

    user_id: str
    team_id: str
    role: str
    created_at: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _validate_uuid(value: str, field: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, AttributeError, TypeError):
        raise ValueError(f"invalid {field}: {value!r} (expected UUID)")


def _validate_role(role: str) -> str:
    if role not in VALID_ROLES:
        raise ValueError(f"invalid role: {role!r} (expected one of {VALID_ROLES})")
    return role


class TeamMembershipStore:
    """`team_members` tablosu için üyelik yönetimi (service_role)."""

    def __init__(self, client: Optional[SupabaseClient] = None):
        if client is not None:
            self._client = client
        else:
            self._client = build_supabase_client_from_env()

    def add(self, *, user_id: str, team_id: str, role: str = "member") -> TeamMember:
        """
        Üyelik ekler. Aynı (user_id, team_id) zaten varsa rolü günceller
        (upsert semantiği — DB'de primary key (user_id, team_id)).
        """
        user_id = _validate_uuid(user_id, "user_id")
        team_id = _validate_uuid(team_id, "team_id")
        role = _validate_role(role)

        payload = {"user_id": user_id, "team_id": team_id, "role": role}

        def _do_upsert():
            return (
                self._client.table(TEAM_MEMBERS_TABLE)
                .upsert(payload, on_conflict="user_id,team_id")
                .execute()
            )

        _safe_supabase_call("upsert_team_member", _do_upsert)
        return TeamMember(user_id=user_id, team_id=team_id, role=role)

    def list_for_team(self, team_id: str) -> list[TeamMember]:
        team_id = _validate_uuid(team_id, "team_id")
        return self._list("team_id", team_id)

    def list_for_user(self, user_id: str) -> list[TeamMember]:
        user_id = _validate_uuid(user_id, "user_id")
        return self._list("user_id", user_id)

    def _list(self, column: str, value: str) -> list[TeamMember]:
        def _do_list():
            return (
                self._client.table(TEAM_MEMBERS_TABLE)
                .select("*")
                .eq(column, value)
                .order("created_at", desc=True)
                .execute()
            )

        try:
            result = _safe_supabase_call("list_team_members", _do_list)
        except SupabaseOperationError:
            return []

        if not result or not result.data:
            return []
        return [self._row_to_member(row) for row in result.data]

    def get_role(self, *, user_id: str, team_id: str) -> Optional[str]:
        """Kullanıcının takımdaki rolü; üye değilse None."""
        user_id = _validate_uuid(user_id, "user_id")
        team_id = _validate_uuid(team_id, "team_id")

        def _do_lookup():
            return (
                self._client.table(TEAM_MEMBERS_TABLE)
                .select("role")
                .eq("user_id", user_id)
                .eq("team_id", team_id)
                .limit(1)
                .execute()
            )

        try:
            result = _safe_supabase_call("get_team_role", _do_lookup)
        except SupabaseOperationError:
            return None
        if not result or not result.data:
            return None
        return str(result.data[0].get("role")) or None

    def is_member(self, *, user_id: str, team_id: str) -> bool:
        return self.get_role(user_id=user_id, team_id=team_id) is not None

    def remove(self, *, user_id: str, team_id: str) -> int:
        """Üyeliği kaldırır; silinen satır sayısını döndürür."""
        user_id = _validate_uuid(user_id, "user_id")
        team_id = _validate_uuid(team_id, "team_id")

        def _do_delete():
            return (
                self._client.table(TEAM_MEMBERS_TABLE)
                .delete()
                .eq("user_id", user_id)
                .eq("team_id", team_id)
                .execute()
            )

        result = _safe_supabase_call("delete_team_member", _do_delete)
        data = getattr(result, "data", None)
        return len(data) if data else 0

    @staticmethod
    def _row_to_member(row: dict) -> TeamMember:
        return TeamMember(
            user_id=str(row.get("user_id", "")),
            team_id=str(row.get("team_id", "")),
            role=str(row.get("role", "member")),
            created_at=row.get("created_at"),
        )


__all__ = [
    "TEAM_MEMBERS_TABLE",
    "VALID_ROLES",
    "TeamMember",
    "TeamMembershipStore",
]

"""
MIRAGE — Migration uygulayıcı (Supabase / PostgreSQL).

`scripts/mirage-edge/migrations/*.sql` dosyalarını dosya adı sırasına göre
idempotent biçimde uygular ve hangi sürümün uygulandığını
`public.schema_migrations` tablosunda tutar (tekrar çalıştırma güvenli).

Neden elle? Supabase CLI bu depoda yok; migration'lar forward-only. Bu betik
hem üretimde (Supabase Postgres DSN) hem de yerel doğrulamada aynı yolu kullanır
— böylece "gerçek Supabase'e uygulama" adımı tekrarlanabilir olur.

Kullanım:
    MIRAGE_PG_DSN="postgresql://..." python3 scripts/apply_migrations.py
    python3 scripts/apply_migrations.py --dsn postgresql://... --dry-run
    python3 scripts/apply_migrations.py --dsn ... --baseline   # var olan şemayı kayıtlı say

Not: Her migration tek bir transaction'da çalışır; hata olursa o dosya geri
alınır ve betik hata ile durur (kısmi uygulama bırakmaz).
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

MIGRATIONS_DIR = Path(__file__).resolve().parent / "mirage-edge" / "migrations"
_NAME_RE = re.compile(r"^(\d+)_.*\.sql$")
LEDGER_DDL = """
create table if not exists public.schema_migrations (
    version    text primary key,
    checksum   text not null,
    applied_at timestamptz not null default now()
);
"""


@dataclass(frozen=True)
class Migration:
    version: str
    path: Path
    sql: str
    checksum: str


def discover_migrations(migrations_dir: Path = MIGRATIONS_DIR) -> list[Migration]:
    """Migration dosyalarını sürüm (dosya adı öneki) sırasına göre döndürür."""
    found: list[Migration] = []
    for path in sorted(migrations_dir.glob("*.sql")):
        match = _NAME_RE.match(path.name)
        if not match:
            continue
        sql = path.read_text(encoding="utf-8")
        found.append(
            Migration(
                version=path.stem,
                path=path,
                sql=sql,
                checksum=hashlib.sha256(sql.encode("utf-8")).hexdigest(),
            )
        )
    found.sort(key=lambda m: m.version)
    return found


def _import_psycopg2():
    try:
        import psycopg2  # noqa: F401
    except ImportError as e:  # pragma: no cover
        raise SystemExit(
            "psycopg2 gerekli. Kur: pip install psycopg2-binary"
        ) from e
    return psycopg2


def apply_migrations(
    dsn: str,
    *,
    migrations_dir: Path = MIGRATIONS_DIR,
    dry_run: bool = False,
    baseline: bool = False,
) -> list[str]:
    """
    Bekleyen migration'ları uygular; uygulanan sürümlerin listesini döndürür.

    baseline=True ise dosyalar YÜRÜTÜLMEZ, yalnızca deftere "uygulandı" yazılır
    (var olan bir şemayı benimsemek için).
    """
    migrations = discover_migrations(migrations_dir)
    psycopg2 = _import_psycopg2()
    conn = psycopg2.connect(dsn)
    try:
        conn.autocommit = False
        applied: list[str] = []
        with conn.cursor() as cur:
            cur.execute(LEDGER_DDL)
            cur.execute("select version from public.schema_migrations")
            done = {row[0] for row in cur.fetchall()}
            conn.commit()

            pending = [m for m in migrations if m.version not in done]
            for mig in pending:
                if dry_run:
                    applied.append(mig.version)
                    continue
                with conn.cursor() as cur:
                    if not baseline:
                        cur.execute(mig.sql)
                    cur.execute(
                        "insert into public.schema_migrations (version, checksum) "
                        "values (%s, %s) on conflict (version) do nothing",
                        (mig.version, mig.checksum),
                    )
                conn.commit()
                applied.append(mig.version)
        return applied
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="MIRAGE migration uygulayıcı")
    parser.add_argument("--dsn", default=os.environ.get("MIRAGE_PG_DSN"))
    parser.add_argument("--dry-run", action="store_true", help="Yalnızca bekleyenleri listele")
    parser.add_argument("--baseline", action="store_true", help="Yürütme; var olanı kayıtlı say")
    args = parser.parse_args(argv)

    if not args.dsn:
        print("MIRAGE_PG_DSN gerekli (veya --dsn).", file=sys.stderr)
        return 2

    applied = apply_migrations(
        args.dsn, dry_run=args.dry_run, baseline=args.baseline
    )
    if not applied:
        print("Uygulanacak migration yok (şema güncel).")
    else:
        verb = "Bekleyen" if args.dry_run else "Uygulandı"
        print(f"{verb}: {', '.join(applied)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

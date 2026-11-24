"""Database connection and migrations.

Connections run in autocommit mode; every unit of work opens an explicit ``conn.transaction()``.
"""

from __future__ import annotations

import os
from pathlib import Path

import psycopg

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"


def default_dsn() -> str:
    return os.environ.get("DATABASE_URL", "dbname=xyz_pm")


def connect(dsn: str | None = None) -> psycopg.Connection:
    return psycopg.connect(dsn or default_dsn(), autocommit=True)


def apply_migrations(conn: psycopg.Connection) -> list[str]:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations (name text PRIMARY KEY, applied_at timestamptz DEFAULT now())"
    )
    done = {r[0] for r in conn.execute("SELECT name FROM schema_migrations")}
    applied = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if path.name in done:
            continue
        with conn.transaction():
            conn.execute(path.read_text(encoding="utf-8"))
            conn.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (path.name,))
        applied.append(path.name)
    return applied


def to_vector(values: list[float]) -> str:
    """pgvector text literal, e.g. '[0.1,0.2]' — cast with ::vector in SQL."""
    return "[" + ",".join(f"{v:.7g}" for v in values) + "]"

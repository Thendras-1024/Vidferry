"""从当前 SQLite schema 生成 PostgreSQL V001 SQL。"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from app.db.data_migration import LOCK_TABLES, TABLE_ORDER
from app.db.postgres_compat import normalize_postgres_sql


REGISTRY_SQL = """CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    checksum TEXT NOT NULL,
    applied_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);"""


def _schema_order(existing):
    ordered = []
    for table in TABLE_ORDER:
        if table in existing:
            ordered.append(table)
        if table == "agent_sessions" and "agent_session_locks" in existing:
            ordered.append("agent_session_locks")
        if table == "youtube_workflow_jobs" and "youtube_workflow_locks" in existing:
            ordered.append("youtube_workflow_locks")
    ordered.extend(sorted(existing - set(ordered)))
    return ordered


def generate_schema(sqlite_path):
    with sqlite3.connect(sqlite_path) as conn:
        table_sql = {
            name: sql
            for name, sql in conn.execute(
                """
                SELECT name, sql FROM sqlite_master
                WHERE type = 'table' AND name NOT LIKE 'sqlite_%' AND sql IS NOT NULL
                """
            )
        }
        indexes = [
            sql
            for (sql,) in conn.execute(
                """
                SELECT sql FROM sqlite_master
                WHERE type = 'index' AND sql IS NOT NULL
                ORDER BY name
                """
            )
        ]
    statements = [REGISTRY_SQL]
    statements.extend(normalize_postgres_sql(table_sql[table]) + ";" for table in _schema_order(set(table_sql)))
    statements.extend(normalize_postgres_sql(sql) + ";" for sql in indexes)
    casefold_index = "CREATE UNIQUE INDEX IF NOT EXISTS idx_youtube_video_groups_name_ci ON youtube_video_groups(lower(name));"
    if not any("idx_youtube_video_groups_name_ci" in sql for sql in statements):
        statements.append(casefold_index)
    return "-- Generated from the current Vidferry SQLite schema.\n\n" + "\n\n".join(statements) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate the PostgreSQL initial schema")
    parser.add_argument("--sqlite", type=Path, default=Path("db/database.db"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("db/migrations/postgresql/V001__initial_schema.sql"),
    )
    args = parser.parse_args(argv)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(generate_schema(args.sqlite), encoding="utf-8")
    print(f"postgresql schema generated : output = {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

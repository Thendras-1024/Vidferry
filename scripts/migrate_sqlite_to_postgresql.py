"""Vidferry SQLite 到 PostgreSQL 的停机迁移命令。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from app.db.data_migration import create_sqlite_backup, migrate_sqlite_to_postgres, sqlite_preflight


def build_parser():
    parser = argparse.ArgumentParser(description="Migrate Vidferry SQLite data to PostgreSQL")
    parser.add_argument("action", choices=["preflight", "migrate"])
    parser.add_argument("--sqlite", type=Path, default=Path("db/database.db"))
    parser.add_argument("--backup-dir", type=Path, default=Path("db/backups"))
    parser.add_argument("--report", type=Path, default=Path("db/postgresql-migration-report.json"))
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.action == "preflight":
        print(json.dumps(sqlite_preflight(args.sqlite), ensure_ascii=False, indent=2))
        return 0
    from app.config import DATABASE_URL

    database_url = DATABASE_URL or os.environ.get("DATABASE_URL", "")
    if not database_url:
        raise SystemExit("migrate requires DATABASE_URL in the local environment")
    sqlite_preflight(args.sqlite)
    from app.db.schema import init_database_tables

    init_database_tables()
    backup = create_sqlite_backup(args.sqlite, args.backup_dir)
    report = migrate_sqlite_to_postgres(backup["path"], database_url)
    report["backup"] = backup
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"migration completed : report = {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""SQLite 到 PostgreSQL 的停机迁移辅助函数。"""

from __future__ import annotations

import datetime as dt
import hashlib
import shutil
import sqlite3
from pathlib import Path

from app.db.postgres_compat import normalize_postgres_sql


LOCK_TABLES = {"agent_session_locks", "youtube_workflow_locks"}
TABLE_ORDER = (
    "app_settings", "app_notifications", "user_info", "file_records", "auth_users",
    "agent_sessions", "agent_rules", "agent_memory_items", "agent_messages", "agent_runs",
    "youtube_video_groups", "youtube_videos", "youtube_search_jobs", "youtube_search_job_items",
    "youtube_workflow_jobs", "youtube_workflow_events", "youtube_workflow_llm_usage_events",
    "youtube_subtitle_audits", "published_youtube_materials", "scheduled_publish_tasks",
    "scheduled_publish_targets", "auth_sessions", "auth_audit_logs",
)


def _rows_hash(rows):
    digest = hashlib.sha256()
    for row in rows:
        normalized = [str(value).replace("T", " ", 1) if isinstance(value, str) else value for value in row]
        digest.update(repr(tuple(normalized)).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _file_digest(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_sqlite_backup(source, backup_dir):
    source, backup_dir = Path(source), Path(backup_dir)
    if not source.is_file():
        raise FileNotFoundError(source)
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"{source.stem}-{dt.datetime.now():%Y%m%d-%H%M%S}{source.suffix}"
    input_conn, output_conn = sqlite3.connect(source), sqlite3.connect(target)
    try:
        input_conn.backup(output_conn)
    finally:
        output_conn.close()
        input_conn.close()
    conn = sqlite3.connect(target)
    try:
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            target.unlink(missing_ok=True)
            raise RuntimeError("SQLite backup integrity check failed")
    finally:
        conn.close()
    return {"path": str(target), "size": target.stat().st_size, "sha256": _file_digest(target)}


def sqlite_preflight(path):
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    with sqlite3.connect(path) as conn:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        tables = [name for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        active_locks = {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in LOCK_TABLES if table in tables}
    if integrity != "ok":
        raise RuntimeError(f"SQLite integrity check failed: {integrity}")
    if any(active_locks.values()):
        raise RuntimeError("runtime lock tables are not empty")
    return {"path": str(path), "size": path.stat().st_size, "tables": sorted(tables), "sha256": _file_digest(path)}


def _schema_statements(conn):
    rows = conn.execute("SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND sql IS NOT NULL").fetchall()
    return {name: normalize_postgres_sql(sql) for name, sql in rows}


def migrate_sqlite_to_postgres(sqlite_path, database_url):
    """将已备份的 SQLite 文件复制到空 PostgreSQL 数据库，不修改源文件。"""
    import psycopg

    source = Path(sqlite_path)
    report = {"source": str(source), "tables": {}, "sourceSha256": _file_digest(source)}
    with sqlite3.connect(source) as sqlite_conn, psycopg.connect(database_url) as pg_conn:
        with pg_conn.cursor() as cursor:
            for table, ddl in _schema_statements(sqlite_conn).items():
                if table not in LOCK_TABLES:
                    cursor.execute(ddl)
            pg_conn.commit()
            for table in TABLE_ORDER:
                if table in LOCK_TABLES or table not in _schema_statements(sqlite_conn):
                    continue
                rows = sqlite_conn.execute(f'SELECT * FROM "{table}"').fetchall()
                if rows:
                    columns = [item[0] for item in sqlite_conn.execute(f'PRAGMA table_info("{table}")')]
                    placeholders = ", ".join(["%s"] * len(columns))
                    cursor.executemany(f'INSERT INTO "{table}" ({", ".join(columns)}) VALUES ({placeholders})', rows)
                report["tables"][table] = {"rows": len(rows), "sha256": _rows_hash(rows)}
            pg_conn.commit()
    return report

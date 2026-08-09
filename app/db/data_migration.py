"""SQLite 到 PostgreSQL 的停机迁移辅助函数。"""

from __future__ import annotations

import datetime as dt
import hashlib
import sqlite3
from pathlib import Path


LOCK_TABLES = {"agent_session_locks", "youtube_workflow_locks"}
DEFAULT_VIDEO_GROUP_NAME = "未分类"
TABLE_ORDER = (
    "app_settings", "app_notifications", "user_info", "file_records", "auth_users",
    "agent_sessions", "agent_session_bindings", "agent_rules", "agent_memory_items", "agent_messages", "agent_runs",
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


def _postgres_columns(cursor):
    rows = cursor.execute(
        """SELECT table_name, column_name FROM information_schema.columns
           WHERE table_schema = current_schema()"""
    ).fetchall()
    columns = {}
    for table, column in rows:
        columns.setdefault(table, set()).add(column)
    return columns


def _remove_generated_default_group(cursor):
    count = cursor.execute("SELECT COUNT(*) FROM youtube_video_groups").fetchone()[0]
    if count != 1:
        return False
    cursor.execute(
        "DELETE FROM youtube_video_groups WHERE name = %s AND is_default = 1",
        (DEFAULT_VIDEO_GROUP_NAME,),
    )
    return True


def _ensure_default_group(cursor):
    cursor.execute(
        """INSERT INTO youtube_video_groups (name, is_default)
           SELECT %s, 1
           WHERE NOT EXISTS (SELECT 1 FROM youtube_video_groups WHERE is_default = 1)
           ON CONFLICT (name) DO NOTHING""",
        (DEFAULT_VIDEO_GROUP_NAME,),
    )


def migrate_sqlite_to_postgres(sqlite_path, database_url):
    """将已备份的 SQLite 文件复制到已初始化且没有业务数据的 PostgreSQL。"""
    import psycopg

    source = Path(sqlite_path)
    report = {"source": str(source), "tables": {}, "skippedTables": [], "sourceSha256": _file_digest(source)}
    with sqlite3.connect(source) as sqlite_conn, psycopg.connect(database_url) as pg_conn:
        with pg_conn.cursor() as cursor:
            pg_columns = _postgres_columns(cursor)
            if not pg_columns:
                raise RuntimeError("PostgreSQL target must be initialized by Vidferry before migration")
            source_tables = {
                name for (name,) in sqlite_conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
            }
            ordered_tables = [table for table in TABLE_ORDER if table in source_tables and table not in LOCK_TABLES]
            ordered_tables.extend(sorted(source_tables - set(ordered_tables) - LOCK_TABLES))
            if "youtube_video_groups" in source_tables:
                _remove_generated_default_group(cursor)
            for table in ordered_tables:
                target_columns = pg_columns.get(table)
                if not target_columns:
                    report["skippedTables"].append(table)
                    continue
                if cursor.execute(f'SELECT EXISTS (SELECT 1 FROM "{table}" LIMIT 1)').fetchone()[0]:
                    raise RuntimeError(f"PostgreSQL target table is not empty: {table}")
                rows = sqlite_conn.execute(f'SELECT * FROM "{table}"').fetchall()
                source_columns = [item[1] for item in sqlite_conn.execute(f'PRAGMA table_info("{table}")')]
                columns = [column for column in source_columns if column in target_columns]
                if rows:
                    placeholders = ", ".join(["%s"] * len(columns))
                    quoted_columns = ", ".join(f'"{column}"' for column in columns)
                    column_positions = [source_columns.index(column) for column in columns]
                    cursor.executemany(
                        f'INSERT INTO "{table}" ({quoted_columns}) VALUES ({placeholders})',
                        [[row[index] for index in column_positions] for row in rows],
                    )
                report["tables"][table] = {"rows": len(rows), "sha256": _rows_hash(rows)}
                id_column = next((item for item in sqlite_conn.execute(f'PRAGMA table_info("{table}")') if item[1] == "id"), None)
                if rows and id_column and "INT" in str(id_column[2]).upper() and "id" in columns:
                    cursor.execute(
                        f"SELECT setval(pg_get_serial_sequence('public.{table}', 'id'), COALESCE((SELECT MAX(id) FROM \"{table}\"), 1), true)"
                    )
            if "youtube_video_groups" in source_tables:
                _ensure_default_group(cursor)
            pg_conn.commit()
    return report

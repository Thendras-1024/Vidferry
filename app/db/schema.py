"""PostgreSQL schema initialization."""

import hashlib
import threading
from pathlib import Path

from app.db.base import _db_connect


_MIGRATION_DIR = Path(__file__).parent / "migrations" / "postgresql"
_REQUIRED_TABLES = (
    "app_settings", "app_notifications", "user_info", "file_records", "auth_users",
    "agent_sessions", "agent_session_bindings", "agent_session_locks", "agent_rules", "agent_memory_items",
    "agent_messages", "agent_runs", "youtube_video_groups", "youtube_videos",
    "youtube_search_jobs", "youtube_search_job_items", "youtube_workflow_jobs",
    "youtube_workflow_locks", "youtube_workflow_events", "youtube_workflow_llm_usage_events",
    "youtube_subtitle_audits", "youtube_content_safety_audits", "published_youtube_materials", "scheduled_publish_tasks",
    "scheduled_publish_targets", "auth_sessions", "auth_audit_logs",
    "task_acknowledgements",
)
_initialized = False
_database_init_lock = threading.Lock()


def _migration_paths():
    return sorted(_MIGRATION_DIR.glob("V*__*.sql"))


def _apply_pending_migrations(conn):
    cursor = conn.cursor()
    has_registry = bool(cursor.execute("SELECT to_regclass(?)", ("public.schema_migrations",)).fetchone()[0])
    applied = set()
    if has_registry:
        applied = {row[0] for row in cursor.execute("SELECT version FROM schema_migrations").fetchall()}
    for path in _migration_paths():
        version = int(path.name[1:].split("__", 1)[0])
        if version in applied:
            continue
        content = path.read_text(encoding="utf-8")
        for statement in content.split(";"):
            if statement.strip():
                cursor.execute(statement)
        checksum = hashlib.sha256(content.encode("utf-8")).hexdigest()
        cursor.execute(
            "INSERT INTO schema_migrations (version, name, checksum) VALUES (?, ?, ?)",
            (version, path.name, checksum),
        )


def _missing_tables(conn):
    rows = conn.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname = current_schema()"
    ).fetchall()
    existing = {row[0] for row in rows}
    return [table for table in _REQUIRED_TABLES if table not in existing]


def init_database_tables():
    global _initialized
    if _initialized:
        return
    with _database_init_lock:
        if _initialized:
            return
        with _db_connect() as conn:
            _apply_pending_migrations(conn)
            missing = _missing_tables(conn)
            if missing:
                raise RuntimeError(f"PostgreSQL schema is incomplete: {', '.join(missing)}")
        _initialized = True


def init_youtube_video_table():
    init_database_tables()


def init_youtube_workflow_table():
    init_database_tables()

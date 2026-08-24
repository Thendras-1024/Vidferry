"""PostgreSQL schema initialization."""

import hashlib
import json
import shutil
import threading
from pathlib import Path

from app.config import BASE_DIR
from app.db.base import _db_connect


# 后端模块由 runtime 执行到 sau_backend 的共享命名空间，不能依赖此处的
# __file__ 推导目录；它会指向兼容入口而非当前模块文件。
_MIGRATION_DIR = Path(BASE_DIR) / "app" / "db" / "migrations" / "postgresql"
_REQUIRED_TABLES = (
    "app_settings", "app_notifications", "user_info", "file_records", "auth_users",
    "agent_sessions", "agent_session_bindings", "agent_session_locks", "agent_rules", "agent_memory_items",
    "agent_messages", "agent_runs", "youtube_video_groups", "youtube_videos",
    "youtube_search_jobs", "youtube_search_job_items", "youtube_workflow_jobs",
    "youtube_workflow_locks", "youtube_workflow_events", "youtube_workflow_llm_usage_events",
    "youtube_subtitle_audits", "youtube_content_safety_audits", "published_youtube_materials", "scheduled_publish_tasks",
    "scheduled_publish_targets", "auth_sessions", "auth_audit_logs",
    "task_acknowledgements", "candidate_analysis_jobs",
    "youtube_subtitle_audits", "youtube_content_safety_audits", "published_youtube_materials", "publish_dispatch_jobs",
    "publish_dispatch_targets", "scheduled_publish_tasks",
    "scheduled_publish_targets", "publish_account_groups", "publish_account_group_members", "auth_sessions", "auth_audit_logs",
    "auth_identities", "auth_phone_challenges", "auth_rate_limit_events",
    "task_acknowledgements", "platform_metric_snapshots", "platform_comment_samples",
    "short_video_projects", "short_video_candidates", "short_video_bgm_tracks", "short_video_channel_whitelist",
)
_initialized = False
_database_init_lock = threading.Lock()


def _migration_paths():
    paths = sorted(_MIGRATION_DIR.glob("V*__*.sql"))
    versions = [int(path.name[1:].split("__", 1)[0]) for path in paths]
    if len(versions) != len(set(versions)):
        raise RuntimeError("PostgreSQL migration versions must be unique")
    return paths


def _dollar_quote_delimiter_at(sql, offset):
    if sql[offset] != "$":
        return None
    end = sql.find("$", offset + 1)
    if end < 0:
        return None
    tag = sql[offset + 1:end]
    if tag and (not (tag[0].isalpha() or tag[0] == "_") or not all(char.isalnum() or char == "_" for char in tag)):
        return None
    return sql[offset:end + 1]


def _split_sql_statements(sql):
    """Split SQL on statement terminators while preserving quoted PostgreSQL blocks."""
    statements = []
    start = 0
    offset = 0
    state = "normal"
    delimiter = None

    while offset < len(sql):
        current = sql[offset]
        following = sql[offset + 1] if offset + 1 < len(sql) else ""

        if state == "line_comment":
            if current == "\n":
                state = "normal"
            offset += 1
            continue
        if state == "block_comment":
            if current == "*" and following == "/":
                state = "normal"
                offset += 2
            else:
                offset += 1
            continue
        if state == "single_quote":
            if current == "'":
                if following == "'":
                    offset += 2
                    continue
                state = "normal"
            offset += 1
            continue
        if state == "double_quote":
            if current == '"':
                if following == '"':
                    offset += 2
                    continue
                state = "normal"
            offset += 1
            continue
        if state == "dollar_quote":
            if sql.startswith(delimiter, offset):
                closing_delimiter = delimiter
                state = "normal"
                delimiter = None
                offset += len(closing_delimiter)
            else:
                offset += 1
            continue

        if current == "-" and following == "-":
            state = "line_comment"
            offset += 2
            continue
        if current == "/" and following == "*":
            state = "block_comment"
            offset += 2
            continue
        if current == "'":
            state = "single_quote"
            offset += 1
            continue
        if current == '"':
            state = "double_quote"
            offset += 1
            continue
        if current == "$":
            delimiter = _dollar_quote_delimiter_at(sql, offset)
            if delimiter:
                state = "dollar_quote"
                offset += len(delimiter)
                continue
        if current == ";":
            statement = sql[start:offset].strip()
            if statement:
                statements.append(statement)
            start = offset + 1
        offset += 1

    statement = sql[start:].strip()
    if statement:
        statements.append(statement)
    return statements


def _apply_pending_migrations(conn):
    cursor = conn.cursor()
    has_registry = bool(cursor.execute("SELECT to_regclass(%s)", ("public.schema_migrations",)).fetchone()[0])
    applied = set()
    if has_registry:
        applied = {row[0] for row in cursor.execute("SELECT version FROM schema_migrations").fetchall()}
    for path in _migration_paths():
        version = int(path.name[1:].split("__", 1)[0])
        if version in applied:
            continue
        content = path.read_text(encoding="utf-8")
        for statement in _split_sql_statements(content):
            cursor.execute(statement)
        checksum = hashlib.sha256(content.encode("utf-8")).hexdigest()
        cursor.execute(
            "INSERT INTO schema_migrations (version, name, checksum) VALUES (%s, %s, %s)",
            (version, path.name, checksum),
        )


def _missing_tables(conn):
    rows = conn.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname = current_schema()"
    ).fetchall()
    existing = {row[0] for row in rows}
    return [table for table in _REQUIRED_TABLES if table not in existing]


def _migrate_legacy_account_ownership(conn):
    cursor = conn.cursor()
    column = cursor.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = 'user_info' AND column_name = 'owner_user_id'"
    ).fetchone()
    if not column:
        return
    legacy_rows = cursor.execute(
        "SELECT id, filePath FROM user_info WHERE owner_user_id IS NULL ORDER BY id"
    ).fetchall()
    groups_need_owner = cursor.execute("SELECT 1 FROM publish_account_groups WHERE owner_user_id IS NULL LIMIT 1").fetchone()
    jobs_need_owner = cursor.execute("SELECT 1 FROM youtube_workflow_jobs WHERE owner_user_id IS NULL LIMIT 1").fetchone()
    if not legacy_rows and not groups_need_owner and not jobs_need_owner:
        return
    admin = cursor.execute(
        "SELECT id FROM auth_users WHERE role = 'admin' ORDER BY created_at, id LIMIT 1"
    ).fetchone()
    if not admin:
        raise RuntimeError("无法迁移历史账号：请先创建管理员用户。")
    owner_user_id = int(admin[0])
    target_dir = (BASE_DIR / "cookiesFile" / str(owner_user_id)).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    source_dir = (BASE_DIR / "cookiesFile").resolve()
    for _, file_path in legacy_rows:
        source = (source_dir / Path(str(file_path or "")).name).resolve()
        target = (target_dir / source.name).resolve()
        if source.is_file() and not target.exists():
            shutil.move(str(source), str(target))
    cursor.execute("UPDATE user_info SET owner_user_id = %s WHERE owner_user_id IS NULL", (owner_user_id,))
    cursor.execute("UPDATE publish_account_groups SET owner_user_id = %s WHERE owner_user_id IS NULL", (owner_user_id,))
    cursor.execute("UPDATE youtube_workflow_jobs SET owner_user_id = %s WHERE owner_user_id IS NULL", (owner_user_id,))


def _migrate_legacy_agent_soul(conn):
    administrator = conn.execute(
        "SELECT id FROM auth_users WHERE role = 'admin' AND status = 'active' ORDER BY created_at, id LIMIT 1"
    ).fetchone()
    source = (BASE_DIR / "soul.md").resolve()
    if not administrator or not source.is_file():
        return
    try:
        content = source.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError):
        return
    if len(content.encode("utf-8")) > 128 * 1024:
        return
    key = f"agent_soul:{int(administrator[0])}"
    conn.execute(
        """
        INSERT INTO app_settings (key, value, updated_at)
        VALUES (%s, %s, CURRENT_TIMESTAMP)
        ON CONFLICT(key) DO NOTHING
        """,
        (key, json.dumps(content, ensure_ascii=False)),
    )


def _migrate_legacy_workflow_settings(conn):
    administrator = conn.execute(
        "SELECT id FROM auth_users WHERE role = 'admin' AND status = 'active' ORDER BY created_at, id LIMIT 1"
    ).fetchone()
    if not administrator:
        return
    row = conn.execute("SELECT value FROM app_settings WHERE key = 'youtube_workflow_settings'").fetchone()
    if not row:
        return
    key = f"youtube_workflow_settings:{int(administrator[0])}"
    conn.execute(
        """
        INSERT INTO app_settings (key, value, updated_at)
        VALUES (%s, %s, CURRENT_TIMESTAMP)
        ON CONFLICT(key) DO NOTHING
        """,
        (key, row[0]),
    )
    conn.execute("DELETE FROM app_settings WHERE key = 'youtube_workflow_settings'")


def init_database_tables():
    global _initialized
    if _initialized:
        return
    with _database_init_lock:
        if _initialized:
            return
        with _db_connect() as conn:
            _apply_pending_migrations(conn)
            _migrate_legacy_account_ownership(conn)
            _migrate_legacy_workflow_settings(conn)
            _migrate_legacy_agent_soul(conn)
            missing = _missing_tables(conn)
            if missing:
                raise RuntimeError(f"PostgreSQL schema is incomplete: {', '.join(missing)}")
        _initialized = True


def init_youtube_video_table():
    init_database_tables()


def init_youtube_workflow_table():
    init_database_tables()

"""数据库建表与表结构增量迁移初始化。"""

from pathlib import Path
import threading

from app.config import BASE_DIR
from app.db.models import (
    ensure_agent_tables,
    ensure_core_tables,
    ensure_file_record_tables,
    ensure_published_youtube_material_tables,
    ensure_workflow_event_tables,
    ensure_workflow_llm_usage_tables,
    ensure_subtitle_audit_tables,
    ensure_youtube_video_table,
    ensure_youtube_workflow_job_table,
)


_initialized_database_paths = set()
_initialized_youtube_paths = set()
_initialized_workflow_paths = set()
_database_init_lock = threading.Lock()


def _database_path_key():
    return str(Path(_db_path()).resolve())


def init_database_tables():
    database_key = _database_path_key()
    if database_key in _initialized_database_paths:
        return
    with _database_init_lock:
        if database_key in _initialized_database_paths:
            return
        _init_database_tables(database_key)


def _init_database_tables(database_key):
    Path(BASE_DIR / "db").mkdir(parents=True, exist_ok=True)
    with _db_connect() as conn:
        cursor = conn.cursor()
        ensure_core_tables(cursor)
        ensure_file_record_tables(cursor)
        ensure_agent_tables(cursor)
        ensure_workflow_event_tables(cursor)
        ensure_workflow_llm_usage_tables(cursor)
        ensure_subtitle_audit_tables(cursor)
        ensure_published_youtube_material_tables(cursor)
        conn.commit()
    _initialized_database_paths.add(database_key)


def init_youtube_video_table():
    init_database_tables()
    database_key = _database_path_key()
    if database_key in _initialized_youtube_paths:
        return
    with _database_init_lock:
        if database_key in _initialized_youtube_paths:
            return
        with _db_connect() as conn:
            ensure_youtube_video_table(conn.cursor())
            foreign_key_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
            if foreign_key_errors:
                raise RuntimeError(f"数据库外键检查失败，共 {len(foreign_key_errors)} 条")
            conn.commit()
        _initialized_youtube_paths.add(database_key)


def init_youtube_workflow_table():
    init_youtube_video_table()
    database_key = _database_path_key()
    if database_key in _initialized_workflow_paths:
        return
    with _database_init_lock:
        if database_key in _initialized_workflow_paths:
            return
        with _db_connect() as conn:
            ensure_youtube_workflow_job_table(conn.cursor())
            conn.commit()
        _initialized_workflow_paths.add(database_key)

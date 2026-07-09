"""数据库建表与表结构增量迁移初始化。"""

from pathlib import Path

from app.config import BASE_DIR
from app.db.models import (
    ensure_agent_tables,
    ensure_core_tables,
    ensure_file_record_tables,
    ensure_published_youtube_material_tables,
    ensure_workflow_event_tables,
    ensure_youtube_video_table,
    ensure_youtube_workflow_job_table,
)


def init_database_tables():
    Path(BASE_DIR / "db").mkdir(parents=True, exist_ok=True)
    with _db_connect() as conn:
        cursor = conn.cursor()
        ensure_core_tables(cursor)
        ensure_file_record_tables(cursor)
        ensure_agent_tables(cursor)
        ensure_workflow_event_tables(cursor)
        ensure_published_youtube_material_tables(cursor)
        conn.commit()


def init_youtube_video_table():
    init_database_tables()
    with _db_connect() as conn:
        ensure_youtube_video_table(conn.cursor())
        conn.commit()


def init_youtube_workflow_table():
    init_youtube_video_table()
    with _db_connect() as conn:
        ensure_youtube_workflow_job_table(conn.cursor())
        conn.commit()

"""数据库连接与通用 SQL 辅助函数。"""

import datetime
import sqlite3
from pathlib import Path

from app.config import BASE_DIR, SQLITE_BUSY_TIMEOUT_MS, SQLITE_ENABLE_WAL


def _db_path():
    return Path(BASE_DIR / "db" / "database.db")


def _local_timestamp():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _connect_database(db_path, *, row_factory=False):
    Path(BASE_DIR / "db").mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=max(1, SQLITE_BUSY_TIMEOUT_MS) / 1000)
    conn.create_function("current_timestamp", 0, _local_timestamp)
    conn.execute(f"PRAGMA busy_timeout = {max(1, SQLITE_BUSY_TIMEOUT_MS)}")
    conn.execute("PRAGMA foreign_keys = ON")
    if SQLITE_ENABLE_WAL:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
    if row_factory:
        conn.row_factory = sqlite3.Row
    return conn


def _db_connect(*, row_factory=False):
    return _connect_database(_db_path(), row_factory=row_factory)

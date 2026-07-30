"""数据库连接与通用 SQL 辅助函数。"""

import datetime
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from app.config import BASE_DIR, SQLITE_BUSY_TIMEOUT_MS, SQLITE_ENABLE_WAL

try:
    import psycopg
except ImportError:  # PostgreSQL 是可选运行时依赖。
    psycopg = None


DATABASE_INTEGRITY_ERRORS = (sqlite3.IntegrityError,) + ((psycopg.IntegrityError,) if psycopg else ())


def close_database_pool():
    """关闭 PostgreSQL 连接池的兼容入口。

    当前 SQLite 默认路径按请求创建连接，无需额外释放资源。
    """
    return None


_wal_configured_paths = set()
_wal_configured_paths_lock = threading.Lock()


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
        database_key = str(Path(db_path).resolve())
        if database_key not in _wal_configured_paths:
            with _wal_configured_paths_lock:
                if database_key not in _wal_configured_paths:
                    conn.execute("PRAGMA journal_mode = WAL")
                    _wal_configured_paths.add(database_key)
        conn.execute("PRAGMA synchronous = NORMAL")
    if row_factory:
        conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def _db_connect(*, row_factory=False):
    conn = _connect_database(_db_path(), row_factory=row_factory)
    try:
        with conn:
            yield conn
    finally:
        conn.close()

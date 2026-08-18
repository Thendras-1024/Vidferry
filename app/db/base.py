"""PostgreSQL connections shared by the application runtime."""

import threading
from collections.abc import Mapping
from contextlib import contextmanager

from app.config import (
    DATABASE_POOL_MAX_SIZE,
    DATABASE_POOL_MIN_SIZE,
    DATABASE_POOL_TIMEOUT_SECONDS,
    DATABASE_URL,
)

try:
    import psycopg
    from psycopg.rows import tuple_row
    from psycopg_pool import ConnectionPool
except ImportError:
    psycopg = None
    ConnectionPool = None


DATABASE_INTEGRITY_ERRORS = (psycopg.IntegrityError,) if psycopg else ()
_database_pool = None
_database_pool_lock = threading.Lock()


def close_database_pool():
    global _database_pool
    with _database_pool_lock:
        if _database_pool is not None:
            _database_pool.close()
            _database_pool = None


def _postgres_pool():
    global _database_pool
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL must be configured for PostgreSQL")
    if not psycopg or not ConnectionPool:
        raise RuntimeError("psycopg is not installed")
    with _database_pool_lock:
        if _database_pool is None:
            _database_pool = ConnectionPool(
                conninfo=DATABASE_URL,
                min_size=DATABASE_POOL_MIN_SIZE,
                max_size=DATABASE_POOL_MAX_SIZE,
                timeout=DATABASE_POOL_TIMEOUT_SECONDS,
                kwargs={"row_factory": tuple_row},
            )
        return _database_pool


class _PostgresCursor:
    def __init__(self, cursor, row_factory):
        self._cursor = cursor
        self._row_factory = row_factory

    def execute(self, sql, params=None):
        self._cursor.execute(sql, params or ())
        return self

    def executemany(self, sql, params_seq):
        self._cursor.executemany(sql, params_seq)
        return self

    def _row(self, value):
        if value is None or not self._row_factory:
            return value
        return PostgresRow([item.name for item in self._cursor.description], value)

    def fetchone(self):
        return self._row(self._cursor.fetchone())

    def fetchall(self):
        return [self._row(value) for value in self._cursor.fetchall()]

    def __iter__(self):
        return iter(self.fetchall())

    def __getattr__(self, name):
        return getattr(self._cursor, name)


class PostgresRow(Mapping):
    """PostgreSQL 查询行，兼容项目现有的序号与字段名访问方式。"""

    def __init__(self, columns, values):
        self._columns = tuple(columns)
        self._values = tuple(values)
        self._by_name = dict(zip(self._columns, self._values))
        self._by_name_casefold = {str(name).casefold(): value for name, value in self._by_name.items()}

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        if key in self._by_name:
            return self._by_name[key]
        return self._by_name_casefold[str(key).casefold()]

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)

    def keys(self):
        return self._columns


class _PostgresConnection:
    def __init__(self, connection, row_factory):
        self._connection = connection
        self.row_factory = row_factory

    def cursor(self):
        return _PostgresCursor(self._connection.cursor(), self.row_factory)

    def execute(self, sql, params=None):
        return self.cursor().execute(sql, params)

    def commit(self):
        self._connection.commit()

    def rollback(self):
        self._connection.rollback()


@contextmanager
def _db_connect(*, row_factory=False):
    with _postgres_pool().connection() as raw_connection:
        try:
            yield _PostgresConnection(raw_connection, row_factory)
            raw_connection.commit()
        except Exception:
            raw_connection.rollback()
            raise

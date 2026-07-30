"""PostgreSQL connections shared by the application runtime."""

import threading
from contextlib import contextmanager

from app.config import (
    DATABASE_POOL_MAX_SIZE,
    DATABASE_POOL_MIN_SIZE,
    DATABASE_POOL_TIMEOUT_SECONDS,
    DATABASE_URL,
)
from app.db.postgres_compat import HybridRow, normalize_postgres_params, normalize_postgres_sql

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
        self._cursor.execute(normalize_postgres_sql(sql), normalize_postgres_params(sql, params or ()))
        return self

    def executemany(self, sql, params_seq):
        self._cursor.executemany(normalize_postgres_sql(sql), params_seq)
        return self

    def _row(self, value):
        if value is None or not self._row_factory:
            return value
        return HybridRow([item.name for item in self._cursor.description], value)

    def fetchone(self):
        return self._row(self._cursor.fetchone())

    def fetchall(self):
        return [self._row(value) for value in self._cursor.fetchall()]

    def __iter__(self):
        return iter(self.fetchall())

    def __getattr__(self, name):
        return getattr(self._cursor, name)


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

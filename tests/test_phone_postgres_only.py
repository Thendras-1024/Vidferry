from contextlib import contextmanager

from app.auth import phone_service


class _Result:
    def fetchone(self):
        return (0,)


class _Connection:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params=()):
        self.calls.append((sql, params))
        return _Result()


def test_phone_rate_limit_and_identity_lock_use_postgresql_advisory_locks(monkeypatch):
    connection = _Connection()

    @contextmanager
    def connect(*_args, **_kwargs):
        yield connection

    monkeypatch.setattr(phone_service, "_db_connect", connect)

    phone_service._consume_rate("scope", "key", 1, phone_service.dt.timedelta(minutes=1))
    phone_service._lock_phone_identity(connection, "phone-key")

    assert "pg_advisory_xact_lock" in connection.calls[0][0]
    assert "COUNT(*)" in connection.calls[1][0]
    assert "INSERT INTO auth_rate_limit_events" in connection.calls[2][0]
    assert "pg_advisory_xact_lock" in connection.calls[3][0]

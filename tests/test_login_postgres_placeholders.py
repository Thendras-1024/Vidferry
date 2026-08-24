from contextlib import contextmanager
from queue import Queue

from app.backend.runtime import create_backend_module
from myUtils import login


class _StatusQueue:
    def put(self, _message):
        pass


class _Cursor:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params):
        self.calls.append((sql, params))

    def fetchone(self):
        return (2, "tencent_existing.json")


class _Connection:
    def __init__(self):
        self.cursor_instance = _Cursor()
        self.committed = False

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        self.committed = True


def test_save_login_account_uses_postgres_placeholders(monkeypatch):
    connection = _Connection()

    @contextmanager
    def connect():
        yield connection

    monkeypatch.setattr(login, "_db_connect", connect)

    assert login.save_login_account(
        2,
        "tencent_existing.json",
        "管理员",
        _StatusQueue(),
        account_id=7,
        owner_user_id=1,
    )
    assert connection.committed
    assert all("?" not in sql for sql, _params in connection.cursor_instance.calls)
    assert all("%s" in sql for sql, _params in connection.cursor_instance.calls)


def test_login_worker_reports_original_exception_type(monkeypatch):
    backend = create_backend_module("test_login_worker_backend")

    async def fail_login(*_args):
        raise RuntimeError("login failed")

    monkeypatch.setattr(backend, "get_tencent_cookie", fail_login)
    status_queue = Queue()

    backend.run_async_function("2", "account", status_queue)

    assert status_queue.get_nowait() == "500"

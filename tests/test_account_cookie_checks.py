from app.backend.runtime import create_backend_module
import json

import pytest

from app.utils.file_util import _safe_cookie_filename


class _Cursor:
    def __init__(self):
        self.updates = []

    def execute(self, statement, params):
        self.updates.append((statement, params))


def _row(status=1):
    return {
        "id": 12,
        "type": 2,
        "filePath": "tencent.json",
        "userName": "视频号1",
        "status": status,
        "owner_user_id": 1,
    }


def test_cookie_filename_allows_json_names_with_s_and_rejects_path_characters():
    assert _safe_cookie_filename("douyin-account.json") == "douyin-account.json"
    with pytest.raises(ValueError):
        _safe_cookie_filename("../account.json")


def test_cookie_check_only_updates_status_for_confirmed_results():
    backend = create_backend_module()
    backend._account_cookie_check_state.clear()
    cursor = _Cursor()

    backend._run_cookie_check_sync = lambda *_args: True
    assert backend._check_account_cookie_row(cursor, _row())["checkStatus"] == "valid"
    assert cursor.updates[-1][1] == (1, 12)

    backend._account_cookie_check_state.clear()
    backend._run_cookie_check_sync = lambda *_args: False
    assert backend._check_account_cookie_row(cursor, _row())["checkStatus"] == "invalid"
    assert cursor.updates[-1][1] == (0, 12)

    backend._account_cookie_check_state.clear()
    backend._run_cookie_check_sync = lambda *_args: (_ for _ in ()).throw(TimeoutError())
    result = backend._check_account_cookie_row(cursor, _row())
    assert result["checkStatus"] == "error"
    assert result["valid"] is True
    assert "视频号页面访问超时" in result["message"]
    assert len(cursor.updates) == 2


def test_cookie_invalid_notification_is_scoped_to_the_publish_account(monkeypatch):
    backend = create_backend_module()
    captured = []
    monkeypatch.setattr(backend, "_sync_notification_issues", lambda issues, **_kwargs: captured.extend(issues))
    task = {
        "publishTaskId": "dispatch-1",
        "platformType": 2,
        "platformName": "视频号",
        "accountId": 12,
        "ownerUserId": 7,
        "title": "测试视频",
    }

    backend.create_publish_cookie_invalid_notification(task, "VF-PUBLISH-COOKIE-INVALID: Cookie 已失效")

    issue = captured[0]
    assert issue["type"] == "publish-cookie-invalid"
    assert issue["sourceRefs"][0]["accountId"] == 12
    assert issue["sourceRefs"][0]["ownerUserId"] == 7
    assert "VF-PUBLISH-COOKIE-INVALID" in issue["content"]


def test_cookie_invalid_marks_only_account_id_and_owner(monkeypatch):
    backend = create_backend_module()

    class Cursor:
        def __init__(self):
            self.calls = []

        def execute(self, statement, params):
            self.calls.append((statement, params))

    class Connection:
        def __init__(self):
            self.cursor_instance = Cursor()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def cursor(self):
            return self.cursor_instance

        def commit(self):
            return None

    connection = Connection()
    notification_calls = []
    monkeypatch.setattr(backend, "_db_connect", lambda: connection)
    monkeypatch.setattr(backend, "create_publish_cookie_invalid_notification", lambda task, reason: notification_calls.append((task, reason)))
    task = {"accountId": 12, "ownerUserId": 7, "platformType": 2, "accountFile": "shared.json"}

    backend._mark_account_abnormal(task, "VF-PUBLISH-COOKIE-INVALID")

    assert connection.cursor_instance.calls[0][1] == (12, 7)
    assert notification_calls == [(task, "VF-PUBLISH-COOKIE-INVALID")]


def test_cookie_invalid_notification_resolves_only_for_the_reconnected_account(monkeypatch):
    backend = create_backend_module()
    source_refs = [
        {"accountId": 12, "ownerUserId": 7},
        {"accountId": 13, "ownerUserId": 7},
    ]

    class Cursor:
        def __init__(self):
            self.updates = []

        def execute(self, _statement, _params=None):
            return None

        def fetchall(self):
            return [
                {"id": 101, "source_refs": json.dumps([source_refs[0]])},
                {"id": 102, "source_refs": json.dumps([source_refs[1]])},
            ]

        def executemany(self, _statement, params):
            self.updates.extend(params)

    class Connection:
        def __init__(self):
            self.cursor_instance = Cursor()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def cursor(self):
            return self.cursor_instance

    connection = Connection()
    monkeypatch.setattr(backend, "_db_connect", lambda **_kwargs: connection)

    backend.resolve_publish_cookie_invalid_notifications(12, 7)

    assert [params[-1] for params in connection.cursor_instance.updates] == [101]


def test_login_success_resolves_cookie_notification_for_the_reconnected_account(monkeypatch):
    backend = create_backend_module()
    messages = []
    resolved = []

    class Queue:
        def put(self, message, *_args, **_kwargs):
            messages.append(message)

    monkeypatch.setattr(
        backend,
        "resolve_publish_cookie_invalid_notifications",
        lambda account_id, owner_user_id: resolved.append((account_id, owner_user_id)),
    )

    queue = backend._LoginStatusQueue(Queue(), 12, 7)
    queue.put("二维码")
    queue.put("200")

    assert messages == ["二维码", "200"]
    assert resolved == [(12, 7)]

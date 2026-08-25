from datetime import datetime

from app.backend.runtime import create_backend_module


class _Cursor:
    def __init__(self, task_row):
        self.calls = []
        self._fetchone_values = [None, task_row]

    def execute(self, statement, params=None):
        self.calls.append((statement, params))

    def fetchone(self):
        return self._fetchone_values.pop(0) if self._fetchone_values else None


class _Connection:
    row_factory = None

    def __init__(self, cursor):
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def cursor(self):
        return self._cursor

    def commit(self):
        return None


def test_scheduled_publish_insert_is_owned_and_duplicate_check_is_user_scoped(monkeypatch):
    backend = create_backend_module()
    task_row = {
        "id": "task-1",
        "video_id": "video-1",
        "material_id": 151,
        "owner_user_id": 42,
    }
    cursor = _Cursor(task_row)
    connection = _Connection(cursor)

    monkeypatch.setattr(backend, "_parse_scheduled_publish_time", lambda _value: datetime(2026, 8, 25, 19, 55))
    monkeypatch.setattr(backend, "_current_account_owner_id", lambda: 42)
    monkeypatch.setattr(backend, "normalize_publish_targets", lambda _data: [{
        "platformType": 5,
        "platformName": "B站",
        "accountId": 7,
    }])
    monkeypatch.setattr(backend, "_validate_publish_processed_files", lambda _files, _owner: (
        ["video.mp4"], [{"id": 151, "owner_user_id": 42, "source_video_id": "video-1"}]
    ))
    monkeypatch.setattr(backend, "_check_accounts_for_publish", lambda _targets: [{
        "id": 7, "name": "账号 A", "filePath": "42/bilibili/account.json"
    }])
    monkeypatch.setattr(backend, "_resolve_publish_tags", lambda *_args: None)
    monkeypatch.setattr(backend, "validate_prepublish_guard_or_raise", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(backend, "_get_youtube_video_record", lambda *_args: {"title": "视频"})
    monkeypatch.setattr(backend, "_archive_published_material", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(backend, "_now_iso", lambda: "2026-08-25 18:33:48")
    monkeypatch.setattr(backend, "_scheduled_task_payload", lambda _cursor, row: row)
    monkeypatch.setattr(backend, "_db_connect", lambda: connection)

    result = backend.create_scheduled_publish_task({
        "scheduledAt": "2026-08-25 19:55",
        "fileList": ["asset-151"],
        "targets": [{"platformType": 5, "accountId": 7}],
    })

    insert_sql, insert_params = next((sql, params) for sql, params in cursor.calls if "INSERT INTO scheduled_publish_tasks" in sql)
    duplicate_sql, duplicate_params = next((sql, params) for sql, params in cursor.calls if "FROM published_youtube_materials" in sql)
    assert "owner_user_id" in insert_sql
    assert 42 in insert_params
    assert "owner_user_id = %s" in duplicate_sql
    assert 42 in duplicate_params
    assert result["owner_user_id"] == 42

from app.backend.runtime import create_backend_module

import pytest


class _TaskCenterCursor:
    def __init__(self):
        self.rows = []

    def execute(self, sql, _params=()):
        if "SELECT * FROM youtube_workflow_jobs" in sql:
            self.rows = [{
                "id": "workflow-1", "owner_user_id": 1, "video_id": "video-1",
                "title": "Original title", "status": "success", "step": "done",
                "operation": "process", "updated_at": "2026-08-24 11:00:00",
                "created_at": "2026-08-24 09:00:00", "started_at": "2026-08-24 09:01:00",
            }]
        elif "SELECT * FROM youtube_workflow_events WHERE job_id IN" in sql:
            self.rows = []
        elif "SELECT owner_user_id, video_id, metadata FROM youtube_workflow_events" in sql:
            self.rows = []
        elif "SELECT * FROM published_youtube_materials" in sql:
            self.rows = []
        elif "FROM publish_dispatch_jobs" in sql:
            row = {"id": "dispatch-1", "source_ref_id": "workflow-1", "status": "confirmed", "message": "发布完成"}
            if "finished_at" in sql:
                row["finished_at"] = "2026-08-24 10:32:00"
            self.rows = [row]
        elif "FROM publish_dispatch_targets" in sql:
            self.rows = [
                {"job_id": "dispatch-1", "platform_type": 1, "status": "confirmed", "message": "完成", "duration_ms": 1, "started_at": "2026-08-24 10:00:00", "finished_at": "2026-08-24 10:32:00"},
                {"job_id": "dispatch-1", "platform_type": 3, "status": "confirmed", "message": "完成", "duration_ms": 1, "started_at": "2026-08-24 10:00:00", "finished_at": "2026-08-24 10:32:00"},
                {"job_id": "dispatch-1", "platform_type": 5, "status": "confirmed", "message": "完成", "duration_ms": 1, "started_at": "2026-08-24 10:00:00", "finished_at": "2026-08-24 10:32:00"},
            ]
        elif "FROM auth_users" in sql:
            self.rows = [{"id": 1, "display_name": "Admin", "username": "admin"}]
        else:
            raise AssertionError(sql)
        return self

    def fetchall(self):
        return self.rows


class _TaskCenterConnection:
    def __init__(self):
        self.cursor_value = _TaskCenterCursor()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def cursor(self):
        return self.cursor_value


def test_task_center_uses_dispatch_finished_at_not_workflow_updated_at(monkeypatch):
    backend = create_backend_module()
    monkeypatch.setattr(backend, "_db_connect", lambda **_kwargs: _TaskCenterConnection())

    job, events, materials = backend._task_load(owner_user_id=1)[0]
    task = backend._task_item(job, events, materials)

    assert task["finishedAt"] == "2026-08-24T10:32:00+08:00"


def test_task_center_keeps_missing_time_empty():
    backend = create_backend_module()

    assert backend._task_iso(None) == ""


@pytest.mark.parametrize(("total", "confirmed", "expected"), [(4, 1, 25), (3, 1, 33)])
def test_publish_task_progress_is_split_by_successful_platforms(total, confirmed, expected):
    backend = create_backend_module()
    job = {
        "id": "workflow-1", "status": "running", "step": "publish", "progress": 97,
        "publishProgress": {"status": "running", "total": total, "completed": confirmed, "confirmed": confirmed, "reused": 0},
    }
    events = [{"stage": "publish", "status": "running", "label": "发布", "message": "发布中"}]

    assert backend._task_item(job, events, [])["progress"] == expected

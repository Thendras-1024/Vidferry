from app.backend.runtime import create_backend_module


class _Cursor:
    def __init__(self):
        self.calls = []

    def execute(self, statement, params):
        self.calls.append((statement, params))

    def fetchone(self):
        return {"id": 7}


def test_archive_starts_a_new_platform_attempt_after_archiving_failures():
    backend = create_backend_module()
    cursor = _Cursor()

    backend._archive_published_material(
        cursor,
            {"id": 1, "owner_user_id": 1, "source_video_id": "video-1", "filename": "video.mp4"},
        {},
        "视频号",
        "2026-08-09T00:00:00",
        platform_type=2,
        status="queued",
    )

    assert "COALESCE(NULLIF(status" not in cursor.calls[0][0]
    assert cursor.calls[0][0].lstrip().startswith("UPDATE published_youtube_materials")


def test_selected_failed_publish_records_must_belong_to_current_task():
    backend = create_backend_module()
    failed = [
        {"id": 11, "status": "failed", "platform": "抖音"},
        {"id": 12, "status": "timeout", "platform": "B站"},
    ]

    assert [item["id"] for item in backend._select_failed_publish_records(failed, [12])] == [12]

    for invalid_ids in ([], [11, 11], [99], ["12"]):
        try:
            backend._select_failed_publish_records(failed, invalid_ids)
        except ValueError:
            continue
        raise AssertionError(f"expected selected IDs to fail validation: {invalid_ids}")


def test_published_material_row_preserves_account_file_for_retry():
    backend = create_backend_module()

    record = backend._row_to_published_material({
        "id": 12,
        "account_file": "1/kuaishou/account.json",
    })

    assert record["accountFile"] == "1/kuaishou/account.json"


def test_publish_availability_checks_the_target_account(monkeypatch):
    backend = create_backend_module()
    queries = []

    class Cursor:
        def execute(self, statement, params):
            queries.append((statement, params))

        def fetchone(self):
            return None

    class Connection:
        row_factory = None

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def cursor(self):
            return Cursor()

    monkeypatch.setattr(backend, "init_database_tables", lambda: None)
    monkeypatch.setattr(backend, "_db_connect", lambda: Connection())
    monkeypatch.setattr(backend, "_reconcile_publish_material_records", lambda *_args, **_kwargs: None)

    backend._assert_publish_targets_available(
        {"source_video_id": "video-1", "owner_user_id": 9},
        [{"platformType": 4, "accountId": 27}],
    )

    assert queries[-1][1] == ("video-1", 4, 9)


def test_retry_api_passes_risk_confirmation_and_returns_guard_conflict(monkeypatch):
    backend = create_backend_module()
    captured = {}

    def prepare(*args):
        captured["args"] = args
        return {"status": "queued"}

    monkeypatch.setattr(backend, "prepare_failed_publish_retry", prepare)
    monkeypatch.setattr(backend, "_current_account_owner_id", lambda: 9)
    with backend.app.test_request_context(
        "/publish/tasks/task-1/retry-failed",
        method="POST",
        json={"targetRecordIds": [12], "riskOverride": {"sourceContentConfirmed": True}},
    ):
        response, status = backend.retry_failed_publish("task-1")

    assert status == 202
    assert captured["args"] == ("task-1", [12], 9, {"sourceContentConfirmed": True})

    def reject(*_args):
        raise backend.AgentGuardError(
            "需要确认",
            "VF-AGENT-REQUIRES-CONFIRMATION",
            409,
            {"requiresSourceContentConfirmation": True},
        )

    monkeypatch.setattr(backend, "prepare_failed_publish_retry", reject)
    with backend.app.test_request_context(
        "/publish/tasks/task-1/retry-failed", method="POST", json={"targetRecordIds": [12]}
    ):
        response, status = backend.retry_failed_publish("task-1")

    assert status == 409
    assert response.get_json()["data"]["errorCode"] == "VF-AGENT-REQUIRES-CONFIRMATION"


def test_workflow_publish_summary_marks_any_failed_platform_as_failed():
    backend = create_backend_module()

    summary = backend._workflow_publish_summary([
        {"platformName": "抖音", "status": "confirmed", "message": "发布成功"},
        {"platformName": "B站", "status": "failed", "message": "网络错误"},
    ])

    assert summary["failed"] is True
    assert summary["successfulPlatforms"] == ["抖音"]
    assert summary["failedPlatforms"] == ["B站"]

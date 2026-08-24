from pathlib import Path

from app.backend.runtime import create_backend_module


def test_retention_requires_every_active_target_to_succeed_and_waits_seven_days():
    backend = create_backend_module("test_youtube_local_retention_backend")

    assert not backend._youtube_local_retention_eligible(
        [{"status": "confirmed"}, {"status": "failed"}],
        "2026-08-01T12:00:00",
        "2026-08-09T11:59:59",
    )
    assert not backend._youtube_local_retention_eligible(
        [{"status": "confirmed"}, {"status": "reused"}],
        "2026-08-01T12:00:00",
        "2026-08-08T11:59:59",
    )
    assert backend._youtube_local_retention_eligible(
        [{"status": "confirmed"}, {"status": "reused"}],
        "2026-08-01T12:00:00",
        "2026-08-08T12:00:00",
    )


def test_retention_migration_keeps_history_and_scopes_success_to_account():
    migration = Path("app/db/migrations/postgresql/V027__youtube_local_retention.sql").read_text(encoding="utf-8")

    assert "local_files_state" in migration
    assert "local_files_purged_at" in migration
    assert "purged_at" in migration
    assert "invalidated_at" in migration
    assert "COALESCE(account_id, 0)" in migration


def test_history_scope_only_returns_purged_videos():
    backend = create_backend_module("test_youtube_local_retention_history_backend")

    assert backend._youtube_storage_scope_clause("history") == ("local_files_state = 'purged'", [])
    assert backend._youtube_storage_scope_clause("active") == ("local_files_state != 'purged'", [])


def test_local_cleanup_candidates_bind_owner_before_cutoff(monkeypatch):
    backend = create_backend_module("test_youtube_local_retention_candidate_params_backend")

    class Cursor:
        def __init__(self):
            self.params = None

        def execute(self, sql, params):
            self.params = params

        def fetchall(self):
            return []

    class Connection:
        row_factory = None

        def __init__(self):
            self.cursor_instance = Cursor()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def cursor(self):
            return self.cursor_instance

    connection = Connection()
    monkeypatch.setattr(backend, "_db_connect", lambda: connection)
    monkeypatch.setattr(backend, "VIDEO_LOCAL_CLEANUP_BATCH_SIZE", 50)

    backend._youtube_local_cleanup_candidates(
        now="2026-08-23T12:00:00",
        owner_user_id=42,
    )

    assert connection.cursor_instance.params == [42, "2026-08-16T12:00:00", 50]


def test_youtube_summary_uses_the_same_storage_scope_as_the_list():
    backend = create_backend_module("test_youtube_local_retention_summary_scope_backend")

    class Cursor:
        def __init__(self):
            self.calls = []

        def execute(self, sql, values):
            self.calls.append((sql, values))

        def fetchone(self):
            if len(self.calls) == 1:
                return {
                    "total": 1,
                    "pending_download": 0,
                    "pending_translate": 0,
                    "ready_publish": 0,
                    "completed": 1,
                    "downloaded": 1,
                    "translated": 1,
                }
            return {"running": 0}

    cursor = Cursor()
    backend._youtube_video_summary(cursor, 9, storage_scope="history")

    assert "local_files_state = 'purged'" in cursor.calls[0][0]
    assert cursor.calls[0][1] == [9]


def test_local_cleanup_runs_immediately_then_every_configured_interval(monkeypatch):
    backend = create_backend_module("test_youtube_local_retention_scheduler_backend")
    monkeypatch.setattr(backend, "VIDEO_LOCAL_CLEANUP_INTERVAL_HOURS", 24)

    assert backend._youtube_local_cleanup_due(0, None)
    assert not backend._youtube_local_cleanup_due(24 * 3600 - 1, 0)
    assert backend._youtube_local_cleanup_due(24 * 3600, 0)


def test_manual_retention_scan_rechecks_overdue_items_and_repairs_history(monkeypatch):
    backend = create_backend_module("test_youtube_local_retention_manual_scan_backend")
    candidate_calls = []

    def fake_candidates(now=None, owner_user_id=None):
        candidate_calls.append(owner_user_id)
        return [{"video_id": "late-video"}] if len(candidate_calls) == 1 else []

    monkeypatch.setattr(backend, "_youtube_local_cleanup_candidates", fake_candidates)
    monkeypatch.setattr(
        backend,
        "run_youtube_local_cleanup_once",
        lambda owner_user_id=None: {
            "mode": "delete",
            "results": [{"status": "purged", "videoId": "late-video"}],
        },
    )
    monkeypatch.setattr(
        backend,
        "_reconcile_youtube_purged_file_states",
        lambda owner_user_id=None: ["repaired-video"],
    )

    result = backend.scan_youtube_local_retention(42)

    assert result == {
        "mode": "delete",
        "scannedCount": 1,
        "purgedCount": 1,
        "repairedCount": 1,
        "repairedVideoIds": ["repaired-video"],
        "overdueCount": 0,
        "overdueVideoIds": [],
    }
    assert candidate_calls == [42, 42]

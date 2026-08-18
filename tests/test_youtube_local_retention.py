from contextlib import contextmanager
from pathlib import Path
import sqlite3

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


def test_cleanup_candidates_skip_blocked_rows_without_starving_later_eligible_video(tmp_path, monkeypatch):
    backend = create_backend_module("test_youtube_local_retention_candidates_backend")
    database = tmp_path / "retention.sqlite"
    with sqlite3.connect(database) as connection:
        connection.executescript('''
        CREATE TABLE youtube_videos (video_id TEXT, owner_user_id INTEGER, local_files_state TEXT, updated_at TEXT);
        CREATE TABLE published_youtube_materials (video_id TEXT, owner_user_id INTEGER, status TEXT, published_at TEXT, deleted_at TEXT, invalidated_at TEXT);
        CREATE TABLE scheduled_publish_tasks (video_id TEXT, owner_user_id INTEGER, status TEXT);
        CREATE TABLE youtube_workflow_jobs (video_id TEXT, owner_user_id INTEGER, status TEXT);
        ''')
        connection.executemany(
            "INSERT INTO youtube_videos VALUES (?, 1, 'available', ?)",
            [("not-due", "2026-08-01"), ("active-job", "2026-08-02"), ("unfinished", "2026-08-03"), ("eligible", "2026-08-04")],
        )
        connection.executemany(
            "INSERT INTO published_youtube_materials VALUES (?, 1, ?, ?, NULL, NULL)",
            [("not-due", "confirmed", "2026-08-09T00:00:00"), ("active-job", "confirmed", "2026-08-01T00:00:00"), ("unfinished", "failed", "2026-08-01T00:00:00"), ("eligible", "reused", "2026-08-01T00:00:00")],
        )
        connection.execute("INSERT INTO youtube_workflow_jobs VALUES ('active-job', 1, 'running')")

    @contextmanager
    def connect(*_args, **_kwargs):
        raw_connection = sqlite3.connect(database)

        class Connection:
            row_factory = False

            def cursor(self):
                raw_connection.row_factory = sqlite3.Row if self.row_factory else None
                return raw_connection.cursor()

            def commit(self):
                raw_connection.commit()

        connection = Connection()
        try:
            yield connection
            connection.commit()
        finally:
            raw_connection.close()

    monkeypatch.setattr(backend, "_db_connect", connect)
    monkeypatch.setattr(backend, "VIDEO_LOCAL_RETENTION_DAYS", 7)

    assert backend._youtube_local_cleanup_candidates("2026-08-10T00:00:00") == [
        {"video_id": "eligible", "owner_user_id": 1},
    ]

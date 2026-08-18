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
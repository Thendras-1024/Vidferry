from pathlib import Path

from app.db.schema import _migration_paths


def test_postgresql_migration_versions_are_unique():
    paths = _migration_paths()
    versions = [int(path.name[1:].split("__", 1)[0]) for path in paths]

    assert len(versions) == len(set(versions))


def test_candidate_analysis_repair_migration_is_after_merged_stream():
    migration = Path("app/db/migrations/postgresql/V031__repair_candidate_analysis_jobs.sql")

    assert migration.exists()
    assert "CREATE TABLE IF NOT EXISTS candidate_analysis_jobs" in migration.read_text(encoding="utf-8")


def test_phone_auto_registration_migration_adds_profile_and_challenge_fields():
    migration = Path("app/db/migrations/postgresql/V032__phone_auto_registration.sql")

    assert migration.exists()
    content = migration.read_text(encoding="utf-8")
    assert "avatar_url" in content
    assert "idempotency_key_hash" in content

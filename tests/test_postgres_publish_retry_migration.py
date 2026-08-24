from pathlib import Path


def test_publish_retry_lineage_migration_is_idempotent_and_complete():
    migration = Path("app/db/migrations/postgresql/V012__published_material_retry_lineage.sql").read_text(encoding="utf-8")

    assert migration.count("ADD COLUMN IF NOT EXISTS") == 3
    assert "retry_of_task_id TEXT" in migration
    assert "retry_of_record_id BIGINT" in migration
    assert "retry_source TEXT" in migration

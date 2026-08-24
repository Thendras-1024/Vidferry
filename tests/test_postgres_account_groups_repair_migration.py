from pathlib import Path


def test_account_groups_repair_migration_restores_final_schema():
    migration = Path("app/db/migrations/postgresql/V016__repair_publish_account_groups.sql").read_text(encoding="utf-8")

    assert migration.count("CREATE TABLE IF NOT EXISTS") == 2
    assert "owner_user_id BIGINT" in migration
    assert "idx_publish_account_groups_owner_name_lower" in migration

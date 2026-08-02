import runpy
from pathlib import Path

from app.db.data_migration import _remove_generated_default_group


_database_url = runpy.run_path("scripts/prepare_local_env.py")["_database_url"]


class _Cursor:
    def __init__(self, group_count):
        self.group_count = group_count
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        return self

    def fetchone(self):
        return (self.group_count,)


def test_migration_removes_only_the_generated_default_group_before_import():
    cursor = _Cursor(group_count=1)

    assert _remove_generated_default_group(cursor) is True
    assert len(cursor.calls) == 2
    assert "DELETE FROM youtube_video_groups" in cursor.calls[1][0]
    assert cursor.calls[1][1] == ("\u672a\u5206\u7c7b",)


def test_migration_keeps_nonempty_group_data_in_target():
    cursor = _Cursor(group_count=2)

    assert _remove_generated_default_group(cursor) is False
    assert len(cursor.calls) == 1


def test_local_database_url_encodes_credentials():
    assert _database_url("vid:user", "pass@word/with space", "video db") == (
        "postgresql://vid%3Auser:pass%40word%2Fwith%20space@127.0.0.1:5432/video%20db"
    )


def test_editing_artifact_migration_defines_all_runtime_columns():
    migration = Path("app/db/migrations/postgresql/V004__youtube_video_editing_artifacts.sql")
    content = migration.read_text(encoding="utf-8")

    for column in (
        "editing_body_path",
        "editing_ass_path",
        "editing_body_signature",
        "editing_intro_signature",
        "editing_highlight_snapshot",
        "editing_intro_status",
    ):
        assert column in content


def test_comment_burn_migration_defines_runtime_columns():
    migration = Path("app/db/migrations/postgresql/V005__comment_burn.sql")
    content = migration.read_text(encoding="utf-8")

    for column in (
        "comment_burn_enabled",
        "comment_burn_snapshot",
        "comment_burn_signature",
        "comment_burn_status",
    ):
        assert column in content


def test_comment_translation_mode_migration_defines_runtime_column():
    migration = Path("app/db/migrations/postgresql/V006__comment_translation_mode.sql")
    content = migration.read_text(encoding="utf-8")

    assert "comment_translation_mode" in content
    assert "google_llm" in content


def test_baseline_schema_contains_all_runtime_migration_additions():
    baseline = Path("app/db/migrations/postgresql/V001__initial_schema.sql")
    content = baseline.read_text(encoding="utf-8")

    for token in (
        "CREATE TABLE IF NOT EXISTS app_notifications",
        "translation_enabled",
        "editing_body_path",
        "INSERT INTO youtube_video_groups",
    ):
        assert token in content

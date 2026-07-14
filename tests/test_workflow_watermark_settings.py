import json
import sqlite3
import tempfile
import types
import unittest
from contextlib import contextmanager
from pathlib import Path


def _load_module(relative_path, globals_dict):
    module = types.ModuleType(f"test_{Path(relative_path).stem}")
    module.__dict__.update(globals_dict)
    path = Path(__file__).parents[1] / relative_path
    exec(compile(path.read_text(encoding="utf-8-sig"), str(path), "exec"), module.__dict__)
    return module


def _load_settings_service(database_path):
    @contextmanager
    def db_connect():
        connection = sqlite3.connect(database_path)
        try:
            yield connection
        finally:
            connection.close()

    def init_database_tables():
        with db_connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT)"
            )

    return _load_module("app/core/settings_service.py", {
        "json": json,
        "_db_connect": db_connect,
        "init_database_tables": init_database_tables,
        "PROCESS_VERSION_TRANSLATION": "translation_v1",
        "PROCESS_VERSIONS": {"translation_v1"},
        "DEFAULT_SUBTITLE_LANGUAGE": "zh-CN",
        "SUBTITLE_LANGUAGES": {"zh-CN": {"label": "中文"}},
        "DEFAULT_BURN_PROFILE": "stable",
        "BURN_PROFILES": {"stable": {}},
        "DEFAULT_SUBTITLE_SIZE": "large",
        "SUBTITLE_SIZE_PRESETS": {"large": {"scale": 1.16}},
        "DEFAULT_TRANSLATOR_LABEL": "Vidferry翻译",
        "YOUTUBE_DEFAULT_QUERY": "foreigner China travel vlog first time in China",
    })


class WorkflowWatermarkSettingsTests(unittest.TestCase):
    def test_workflow_job_changes_only_allow_runtime_fields(self):
        workflow = _load_module("app/core/workflow.py", {
            "get_workflow_settings": lambda: {},
        })

        workflow._validate_workflow_job_changes({"status": "running", "progress": 20})
        with self.assertRaises(ValueError):
            workflow._validate_workflow_job_changes({"status = 'success' --": ""})

    def test_saved_watermark_survives_reload_and_is_used_as_a_job_default(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "database.db"
            initial_settings = _load_settings_service(database_path)
            saved = initial_settings.update_workflow_settings({
                "watermarkEnabled": True,
                "watermarkText": "Vidferry",
                "searchQuery": "foreigners in China daily life",
            })
            disabled = initial_settings.update_workflow_settings({"watermarkEnabled": False})
            initial_settings.update_workflow_settings({"watermarkEnabled": True})

            restored_settings = _load_settings_service(database_path)
            restored = restored_settings.get_workflow_settings()
            workflow = _load_module("app/core/workflow.py", {
                "get_workflow_settings": restored_settings.get_workflow_settings,
            })
            inherited = workflow._workflow_watermark_settings({})
            overridden = workflow._workflow_watermark_settings({
                "watermarkEnabled": False,
                "watermarkText": "",
            })

        self.assertTrue(saved["watermarkEnabled"])
        self.assertEqual(disabled["watermarkText"], "Vidferry")
        self.assertEqual(restored["searchQuery"], "foreigners in China daily life")
        self.assertEqual(restored["watermarkText"], "Vidferry")
        self.assertEqual(inherited, (True, "Vidferry"))
        self.assertEqual(overridden, (False, ""))


if __name__ == "__main__":
    unittest.main()

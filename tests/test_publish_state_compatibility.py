import sqlite3

import app.config as config
from app.core.llm_provider import provider_optional_fields
from app.core.publish_state import aggregate_publish_status, publish_progress, workflow_status_from_dispatch
from app.backend.runtime import create_backend_module


class _SqliteConnection:
    def __init__(self, connection):
        self._connection = connection

    @property
    def row_factory(self):
        return self._connection.row_factory

    @row_factory.setter
    def row_factory(self, value):
        self._connection.row_factory = sqlite3.Row if value else None

    def cursor(self):
        return self._connection.cursor()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self._connection.close()


def test_publish_state_remains_compatible_with_dispatch_results():
    targets = [{"status": "confirmed"}, {"status": "uncertain"}]

    assert aggregate_publish_status(targets) == "uncertain"
    assert publish_progress(targets) == {
        "total": 2,
        "queued": 0,
        "running": 0,
        "confirmed": 1,
        "failed": 0,
        "uncertain": 1,
        "cancelled": 0,
        "reused": 0,
        "waiting_existing": 0,
        "completed": 2,
        "percentage": 100,
    }
    assert workflow_status_from_dispatch("uncertain") == ("needs_verification", "publish")


def test_published_material_list_qualifies_status_after_material_join(monkeypatch):
    backend = create_backend_module("test_published_material_list_backend")
    connection = sqlite3.connect(":memory:")
    connection.executescript("""
        CREATE TABLE published_youtube_materials (
            id INTEGER PRIMARY KEY,
            material_id INTEGER,
            owner_user_id INTEGER,
            status TEXT,
            deleted_at TEXT,
            published_at TEXT,
            updated_at TEXT,
            created_at TEXT
        );
        CREATE TABLE file_records (
            id INTEGER PRIMARY KEY,
            asset_id TEXT,
            status TEXT
        );
        INSERT INTO published_youtube_materials
            (id, material_id, owner_user_id, status, created_at)
        VALUES (1, 10, 7, 'confirmed', '2026-08-17T00:00:00');
        INSERT INTO file_records (id, asset_id, status)
        VALUES (10, 'asset-1', 'ready');
    """)
    connection.commit()
    monkeypatch.setattr(backend, "init_database_tables", lambda: None)
    monkeypatch.setattr(backend, "_db_connect", lambda: _SqliteConnection(connection))

    records = backend.list_published_youtube_materials(owner_user_id=7)

    assert [record["id"] for record in records] == [1]
    assert records[0]["assetId"] == "asset-1"


def test_deepseek_profiles_explicitly_switch_thinking_mode():
    assert provider_optional_fields("deepseek", disable_thinking=True)["thinking"] == {"type": "disabled"}
    assert provider_optional_fields("deepseek", disable_thinking=False)["thinking"] == {"type": "enabled"}


def test_agent_uses_agent_profile_but_search_translation_uses_text_profile(monkeypatch):
    backend = create_backend_module("test_agent_llm_profiles_backend")
    calls = []
    monkeypatch.setattr(backend, "AGENT_LLM_MODEL", "agent-model")
    monkeypatch.setattr(backend, "AGENT_LLM_API_KEY", "agent-key")
    monkeypatch.setattr(backend, "AGENT_LLM_BASE_URL", "https://agent.example")
    monkeypatch.setattr(backend, "TEXT_LLM_MODEL", "text-model")
    monkeypatch.setattr(backend, "TEXT_LLM_API_KEY", "text-key")
    monkeypatch.setattr(backend, "TEXT_LLM_BASE_URL", "https://text.example")

    def fake_call_json_contract(**kwargs):
        calls.append(kwargs)
        return {"query": "english query"}, {}, {}

    monkeypatch.setattr(backend, "call_json_contract", fake_call_json_contract)
    backend._call_agent_contract([], "agent_action", lambda value: value)
    assert calls[-1]["model"] == "agent-model"
    assert calls[-1]["profile_channel"] == "agent"

    assert backend._agent_english_search_query("中文关键词") == "english query"
    assert calls[-1]["model"] == "text-model"
    assert calls[-1]["profile_channel"] == "text"


def test_llm_status_probes_agent_with_thinking_enabled(monkeypatch):
    calls = []

    def fake_probe(model, api_key, base_url, provider, timeout, **kwargs):
        calls.append((model, kwargs["disable_thinking"]))
        return {
            "provider": provider,
            "model": model,
            "ready": True,
            "visionReady": not kwargs["multimodal"],
            "thinkingRequested": kwargs["disable_thinking"],
            "thinkingDisabled": kwargs["disable_thinking"],
            "removedOptionalFields": [],
            "message": "",
        }

    monkeypatch.setattr(config, "TEXT_LLM_MODEL", "text-model")
    monkeypatch.setattr(config, "TEXT_LLM_API_KEY", "text-key")
    monkeypatch.setattr(config, "TEXT_LLM_BASE_URL", "https://text.example")
    monkeypatch.setattr(config, "TEXT_LLM_PROVIDER", "deepseek")
    monkeypatch.setattr(config, "AGENT_LLM_MODEL", "agent-model")
    monkeypatch.setattr(config, "AGENT_LLM_API_KEY", "agent-key")
    monkeypatch.setattr(config, "AGENT_LLM_BASE_URL", "https://agent.example")
    monkeypatch.setattr(config, "AGENT_LLM_PROVIDER", "deepseek")
    monkeypatch.setattr(config, "MULTIMODAL_LLM_MODEL", "vision-model")
    monkeypatch.setattr(config, "MULTIMODAL_LLM_API_KEY", "vision-key")
    monkeypatch.setattr(config, "MULTIMODAL_LLM_BASE_URL", "https://vision.example")
    monkeypatch.setattr(config, "MULTIMODAL_LLM_PROVIDER", "deepseek")
    monkeypatch.setattr(config, "LLM_DISABLE_THINKING", True)
    monkeypatch.setattr(config, "AGENT_LLM_ENABLE_THINKING", True)
    monkeypatch.setattr(config, "_LLM_CONFIG_STATUS_CACHE", None)
    monkeypatch.setattr(config, "probe_provider", fake_probe)

    status = config.get_llm_config_status()

    assert status["agent"]["ready"] is True
    assert calls == [("text-model", True), ("agent-model", False), ("vision-model", True)]

import json
import sqlite3
import time
from contextlib import nullcontext
from pathlib import Path

import pytest

from app.backend.runtime import create_backend_module


def test_agent_processing_options_use_defaults_and_reject_invalid_values(monkeypatch):
    backend = create_backend_module()
    monkeypatch.setattr(
        backend,
        "get_workflow_settings",
        lambda: {"watermarkEnabled": True, "commentBurnEnabled": False},
    )

    assert backend._agent_processing_options() == {
        "watermarkEnabled": True,
        "commentBurnEnabled": False,
    }
    assert backend._agent_processing_options({"commentBurnEnabled": True}) == {
        "watermarkEnabled": True,
        "commentBurnEnabled": True,
    }

    with pytest.raises(ValueError, match="处理选项"):
        backend._agent_processing_options({"watermarkEnabled": "true"})
    with pytest.raises(ValueError, match="处理选项"):
        backend._agent_processing_options({"unexpected": True})


def test_import_confirmation_passes_processing_options_to_workflow_and_history(monkeypatch):
    backend = create_backend_module()
    proposal_id = "proposal-processing"
    session_id = "session-processing"
    backend._AGENT_IMPORT_PROPOSALS[proposal_id] = {
        "sessionId": session_id,
        "query": "Agent test",
        "groupId": "",
        "requestedAction": "workflow_process",
        "items": [{"id": "video-1", "url": "https://example.com/video-1", "title": "测试视频"}],
        "expiresAt": time.time() + 60,
    }
    created_payloads = []
    persisted = []
    submitted = []
    monkeypatch.setattr(
        backend,
        "save_one_youtube_video",
        lambda *_args, **_kwargs: {
            "decision": "created",
            "item": {
                "id": "video-1",
                "url": "https://example.com/video-1",
                "title": "测试视频",
                "publishDraft": {"tags": ["topic"]},
            },
        },
    )
    monkeypatch.setattr(
        backend,
        "create_youtube_workflow_job",
        lambda payload: created_payloads.append(payload) or {"id": "job-1"},
    )
    monkeypatch.setattr(
        backend,
        "_submit_background_task",
        lambda resource, _runner, job_id: submitted.append((resource, job_id)),
    )
    monkeypatch.setattr(backend, "workflow_job_resource", lambda _job: "processing")
    monkeypatch.setattr(backend, "update_agent_proposal_state", lambda *args, **kwargs: persisted.append((args, kwargs)))

    result = backend.confirm_agent_import_proposal(
        proposal_id,
        session_id,
        ["video-1"],
        processing_options={"watermarkEnabled": True, "commentBurnEnabled": True},
    )

    assert result["workflowJobCount"] == 1
    assert submitted == [("processing", "job-1")]
    assert created_payloads == [{
        "videoId": "video-1",
        "url": "https://example.com/video-1",
        "channel": "",
        "subscribers": "",
        "publishedAt": "",
        "title": "测试视频",
        "description": "",
        "tags": ["topic"],
        "customTags": [],
        "schedule": "",
        "publishToDouyin": False,
        "publishToBilibili": False,
        "publishToXiaohongshu": False,
        "publishToKuaishou": False,
        "publishToTencent": False,
        "processVersion": backend.PROCESS_VERSION_EDITING,
        "watermarkEnabled": True,
        "commentBurnEnabled": True,
    }]
    assert persisted[0][1]["processing_options"] == {
        "watermarkEnabled": True,
        "commentBurnEnabled": True,
    }


def test_execution_confirmation_rejects_duplicate_platform_accounts(monkeypatch):
    backend = create_backend_module()
    proposal_id = "proposal-targets"
    session_id = "session-targets"
    backend._AGENT_EXECUTION_PROPOSALS[proposal_id] = {
        "sessionId": session_id,
        "action": "workflow_publish",
        "videoId": "video-1",
        "requiresTargets": True,
        "requiresProcessingOptions": True,
        "expiresAt": time.time() + 60,
    }
    monkeypatch.setattr(backend, "_agent_execution_video", lambda _payload: {"id": "video-1", "downloadStatus": 1})

    with pytest.raises(ValueError, match="每个平台只能选择一个账号"):
        backend.confirm_agent_execution_proposal(
            proposal_id,
            session_id,
            targets=[
                {"platformType": 3, "accountId": 1},
                {"platformType": 3, "accountId": 2},
            ],
            processing_options={"watermarkEnabled": False, "commentBurnEnabled": False},
        )


def test_execution_publish_creates_workflow_without_direct_publish(monkeypatch):
    backend = create_backend_module()
    proposal_id = "proposal-queue"
    session_id = "session-queue"
    backend._AGENT_EXECUTION_PROPOSALS[proposal_id] = {
        "sessionId": session_id,
        "action": "workflow_publish",
        "videoId": "video-1",
        "requiresTargets": True,
        "requiresProcessingOptions": True,
        "expiresAt": time.time() + 60,
    }
    queued = []
    monkeypatch.setattr(
        backend,
        "_agent_execution_video",
        lambda _payload: {"id": "video-1", "downloadStatus": 1, "title": "测试视频", "publishDraft": {"tags": ["topic"]}},
    )
    monkeypatch.setattr(
        backend,
        "_agent_execution_targets",
        lambda _targets: [{"platformType": 3, "accountId": 1, "accountName": "douyin-account"}],
    )
    monkeypatch.setattr(backend, "create_youtube_workflow_job", lambda payload: queued.append(payload) or {"id": "job-1"})
    monkeypatch.setattr(backend, "workflow_job_resource", lambda _job: "workflow")
    monkeypatch.setattr(backend, "_submit_background_task", lambda resource, _runner, job_id: queued.append((resource, job_id)))
    monkeypatch.setattr(backend, "update_agent_proposal_state", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(backend, "_publish_payload", lambda *_args: pytest.fail("Agent 处理后发布不能直接提交平台发布"))

    result = backend.confirm_agent_execution_proposal(
        proposal_id,
        session_id,
        targets=[{"platformType": 3, "accountId": 1}],
        processing_options={"watermarkEnabled": False, "commentBurnEnabled": False},
    )

    assert result["job"]["id"] == "job-1"
    assert queued[0]["account"] == "douyin-account"
    assert queued[1] == ("workflow", "job-1")


def test_agent_confirmation_routes_reject_invalid_processing_options(monkeypatch):
    backend = create_backend_module()
    backend.app.config["AUTH_TEST_BYPASS"] = True
    monkeypatch.setattr(backend, "confirm_agent_import_proposal", lambda *_args, **_kwargs: pytest.fail("非法处理选项不应进入确认逻辑"))

    response = backend.app.test_client().post(
        "/agents/import-proposals/proposal-1/confirm",
        json={
            "sessionId": "session-1",
            "selectedIds": ["video-1"],
            "processingOptions": {"watermarkEnabled": "true"},
        },
    )

    assert response.status_code == 400
    assert "处理选项" in response.get_json()["msg"]


def test_agent_proposal_state_persists_processing_options(monkeypatch, tmp_path):
    backend = create_backend_module()
    database_path = tmp_path / "agent-state.sqlite"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE agent_sessions (id TEXT PRIMARY KEY, deleted_at TEXT, owner_user_id INTEGER);
            CREATE TABLE agent_messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT, context TEXT);
            INSERT INTO agent_sessions (id, deleted_at, owner_user_id) VALUES ('session-1', NULL, 1);
            INSERT INTO agent_messages (id, session_id, role, content, context)
            VALUES (1, 'session-1', 'assistant', '', '{"executionProposal":{"proposalId":"proposal-1"}}');
            """
        )

    def connect(*_args, **_kwargs):
        connection = sqlite3.connect(database_path)
        connection.row_factory = sqlite3.Row
        return connection

    monkeypatch.setattr(backend, "_db_connect", connect)
    monkeypatch.setattr(backend, "agent_session_guard", lambda _session_id: nullcontext())
    monkeypatch.setattr(backend, "_agent_current_user_id", lambda: None)
    monkeypatch.setattr(backend, "_agent_owner_filter", lambda *_args: ("", ()))

    assert backend.update_agent_proposal_state(
        "session-1",
        "proposal-1",
        "executionProposal",
        "confirmed",
        processing_options={"watermarkEnabled": True, "commentBurnEnabled": False},
    )

    with sqlite3.connect(database_path) as connection:
        context = json.loads(connection.execute("SELECT context FROM agent_messages WHERE id = 1").fetchone()[0])
    assert context["executionProposal"]["processingOptions"] == {
        "watermarkEnabled": True,
        "commentBurnEnabled": False,
    }


def test_agent_workspace_sends_processing_options_only_for_processing_proposals():
    root = Path(__file__).resolve().parents[1]
    workspace = (root / "sau_frontend/src/components/AgentWorkspace.vue").read_text(encoding="utf-8")
    composable = (root / "sau_frontend/src/composables/useAgentWorkspace.js").read_text(encoding="utf-8")

    assert "message.importProposal.requiresProcessingOptions" in workspace
    assert "message.executionProposal.requiresProcessingOptions" in workspace
    assert "importProcessingOptions" in composable
    assert "executionProcessingOptions" in composable
    assert "processingOptions: proposal.requiresProcessingOptions ? message.importProcessingOptions : undefined" in composable
    assert "processingOptions: proposal.requiresProcessingOptions ? message.executionProcessingOptions : undefined" in composable

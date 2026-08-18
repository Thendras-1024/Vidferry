import datetime
import time

import pytest

from app.backend.runtime import create_backend_module


def _backend():
    return create_backend_module("test_agent_controlled_actions_backend")


def test_video_short_code_and_explicit_message_identifier():
    backend = _backend()

    compact = backend._agent_compact_video({"id": "AbCdEf12345", "title": "Video"})

    assert compact["shortCode"] == "#AbCdEf12345"
    assert backend._agent_message_video_id("处理 #AbCdEf12345") == "AbCdEf12345"


def test_video_selection_requires_current_session_card(monkeypatch):
    backend = _backend()
    session_id = "session-1"
    card_id = "card-1"
    captured = {}
    monkeypatch.setattr(backend, "get_agent_session", lambda value: {"context": {}} if value == session_id else None)
    monkeypatch.setattr(backend, "update_agent_session_context", lambda value, context: captured.update(context) or context)
    monkeypatch.setattr(backend, "invalidate_agent_copywriting_selection", lambda _session_id: None)
    monkeypatch.setattr(backend, "_agent_video_card_cleanup", lambda: None)
    backend._AGENT_VIDEO_CARD_SNAPSHOTS[card_id] = {
        "sessionId": session_id,
        "expiresAt": time.time() + 60,
        "items": [{"id": "AbCdEf12345"}],
    }

    result = backend.update_agent_video_selection(session_id, ["AbCdEf12345"], card_id)

    assert result["videoIds"] == ["AbCdEf12345"]
    assert captured["agentVideoSelectionCardId"] == card_id
    with pytest.raises(ValueError, match="视频卡片"):
        backend.update_agent_video_selection(session_id, ["other-video"], card_id)
    with pytest.raises(ValueError, match="失效"):
        backend.update_agent_video_selection(session_id, ["AbCdEf12345"], "foreign-card")


def test_video_card_snapshot_survives_backend_memory_reset(monkeypatch):
    backend = _backend()
    session_id = "session-1"
    card_id = "card-1"
    snapshot = {
        "cardId": card_id,
        "sessionId": session_id,
        "status": "initial",
        "label": "待处理",
        "createdAt": time.time() - 120,
        "expiresAt": time.time() - 60,
        "items": [{"id": "AbCdEf12345"}, {"id": "ZyXwVu98765"}],
    }
    captured = {}
    monkeypatch.setattr(backend, "get_agent_session", lambda value: {
        "context": {"agentVideoCardSnapshots": {card_id: snapshot}}
    } if value == session_id else None)
    monkeypatch.setattr(backend, "update_agent_session_context", lambda _value, context: captured.update(context) or context)
    monkeypatch.setattr(backend, "invalidate_agent_copywriting_selection", lambda _session_id: None)
    backend._AGENT_VIDEO_CARD_SNAPSHOTS.clear()

    page = backend.get_agent_video_status_card_page(card_id, session_id, 1)
    selection = backend.update_agent_video_selection(session_id, ["AbCdEf12345"], card_id)

    assert page["items"] == snapshot["items"]
    assert selection["videoIds"] == ["AbCdEf12345"]
    assert captured["agentVideoSelectionCardId"] == card_id
    restored = captured["agentVideoCardSnapshots"][card_id]
    assert restored["expiresAt"] > time.time()


def test_prepare_action_requires_card_selection(monkeypatch):
    backend = _backend()
    monkeypatch.setattr(backend, "get_agent_video_selection", lambda _session_id: [])

    with pytest.raises(ValueError, match="视频卡片"):
        backend.prepare_video_action("process", "session-1")

    monkeypatch.setattr(backend, "get_agent_video_selection", lambda _session_id: ["AbCdEf12345"])
    proposal = backend.prepare_video_action("process", "session-1")

    assert proposal == {
        "action": "process",
        "actionLabel": "处理视频",
        "videoIds": ["AbCdEf12345"],
        "requiresConfirmation": True,
    }


def test_published_platform_is_rejected_for_any_account(monkeypatch):
    backend = _backend()
    monkeypatch.setattr(backend, "get_publish_platforms", lambda _video_id: {
        "items": [{"platformType": 3, "platform": "抖音", "accountName": "first"}],
    })
    video = {"id": "AbCdEf12345", "title": "Video"}

    with pytest.raises(backend.WorkflowConflictError, match="不能重复发布"):
        backend._agent_assert_not_published_platform([video], [{"platformType": 3, "accountId": 99}])

    backend._agent_assert_not_published_platform([video], [{"platformType": 4, "accountId": 99}])


def test_agent_processing_payload_uses_saved_workflow_settings(monkeypatch):
    backend = _backend()
    monkeypatch.setattr(backend, "get_workflow_settings", lambda: {
        "processVersion": "editing_v1",
        "subtitleLanguage": "zh-CN",
        "highlightIntroEnabled": True,
        "coverIntroEnabled": True,
        "commentBurnEnabled": True,
        "highlightCount": 2,
    })

    payload = backend._agent_execution_workflow_payload({"id": "AbCdEf12345", "title": "Video"})

    assert payload["processVersion"] == "editing_v1"
    assert payload["highlightIntroEnabled"] is True
    assert payload["commentBurnEnabled"] is True


def test_published_processed_video_can_update_local_copywriting():
    backend = _backend()

    assert backend._agent_copywriting_is_ready_video({"translateStatus": 1, "publishStatus": 1})
    assert not backend._agent_copywriting_is_ready_video({"translateStatus": 0, "publishStatus": 1})


def test_copywriting_prompt_serializes_datetime_video_metadata():
    messages = _backend().llm_prompts.agent_copywriting_messages(
        "改写文案",
        {"id": "video-1", "processedAt": datetime.datetime(2026, 8, 17, 23, 30, 28)},
    )

    assert "2026-08-17 23:30:28" in messages[1]["content"]

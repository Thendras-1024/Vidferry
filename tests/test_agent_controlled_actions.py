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


def test_local_video_status_query_does_not_search_youtube():
    backend = _backend()

    assert backend._agent_search_request("有哪些待处理的视频？") is None
    assert backend._agent_rule_lead_intent("有哪些待处理的视频？") is True
    assert backend._select_agent_tools("有哪些待处理的视频？") == [
        ("list_videos_by_status", {"status": "initial"}),
    ]


def test_selected_video_allows_controlled_publish_proposal():
    backend = _backend()

    decision = backend.agent_policy_check("请帮我发布", {"videoSelection": ["AbCdEf12345"]})

    assert decision["allowed"] is True
    assert decision["category"] == "confirmed_proposal"


def test_processing_pending_video_uses_full_download_and_process_workflow(monkeypatch):
    backend = _backend()
    submitted = []
    video = {"id": "AbCdEf12345", "title": "Video", "downloadStatus": 0}
    monkeypatch.setattr(backend, "create_youtube_workflow_job", lambda _payload: {"id": "job-1", "ownerUserId": 7})
    monkeypatch.setattr(backend, "_submit_background_task", lambda resource, runner, job_id, owner_user_id: submitted.append((resource, runner, job_id, owner_user_id)))
    monkeypatch.setattr(backend, "_agent_execution_workflow_payload", lambda _video: {"videoId": _video["id"]})

    prepared = backend._agent_execution_prepare_videos("process", [video], [], "")
    result = backend._agent_execution_submit_one("process", video, [])

    assert prepared == [None]
    assert result["videoId"] == video["id"]
    assert submitted == [("processing", backend.run_youtube_workflow, "job-1", 7)]


def test_processing_downloaded_video_reuses_download(monkeypatch):
    backend = _backend()
    submitted = []
    video = {"id": "AbCdEf12345", "title": "Video", "downloadStatus": 1}
    monkeypatch.setattr(backend, "create_youtube_workflow_job", lambda _payload: {"id": "job-1", "ownerUserId": 7})
    monkeypatch.setattr(backend, "_submit_background_task", lambda resource, runner, job_id, owner_user_id: submitted.append((resource, runner, job_id, owner_user_id)))
    monkeypatch.setattr(backend, "_agent_execution_workflow_payload", lambda _video: {"videoId": _video["id"]})

    backend._agent_execution_submit_one("process", video, [])

    assert submitted == [("processing", backend.run_youtube_translate_job, "job-1", 7)]


def test_workflow_without_publish_targets_completes_after_processing(monkeypatch):
    backend = _backend()
    updates = []
    job = {"id": "job-1", "videoId": "AbCdEf12345", "ownerUserId": 7}
    monkeypatch.setattr(backend, "get_youtube_workflow_job", lambda _job_id: job)
    monkeypatch.setattr(backend, "_get_youtube_video_record", lambda *_args: {})
    monkeypatch.setattr(backend, "_ensure_workflow_publish_schedule", lambda _job_id, value: (value, ""))
    monkeypatch.setattr(backend, "start_workflow_event", lambda *_args, **_kwargs: "event-1")
    monkeypatch.setattr(backend, "finish_workflow_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(backend, "update_youtube_workflow_job", lambda _job_id, **changes: updates.append(changes) or {**job, **changes})

    result = backend._publish_workflow_outputs("job-1", job, "processed.mp4", {"file_path": "processed.mp4"})

    assert result == []
    assert updates[-1]["status"] == "success"
    assert "未配置发布平台账号" in updates[-1]["message"]


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


def test_new_status_card_clears_previous_video_selection(monkeypatch):
    backend = _backend()
    session_id = "session-1"
    captured = []
    monkeypatch.setattr(backend, "get_agent_session", lambda value: {"context": {}} if value == session_id else None)
    monkeypatch.setattr(backend, "_agent_video_card_status_items", lambda _status: [])
    monkeypatch.setattr(backend, "_agent_video_card_details", lambda videos: videos)
    monkeypatch.setattr(backend, "_agent_video_card_store_snapshot", lambda _snapshot: None)
    monkeypatch.setattr(backend, "update_agent_video_selection", lambda value, video_ids, card_id: captured.append((value, video_ids, card_id)))

    card = backend.create_agent_video_status_card(session_id, "initial", "待处理")

    assert captured == [(session_id, [], card["cardId"])]


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
    monkeypatch.setattr(backend, "_agent_current_user_id", lambda: 7)
    monkeypatch.setattr(backend, "get_workflow_settings", lambda: {
        "processVersion": "editing_v1",
        "subtitleLanguage": "zh-CN",
        "highlightIntroEnabled": True,
        "coverIntroEnabled": True,
        "commentBurnEnabled": True,
        "highlightCount": 2,
    })

    payload = backend._agent_execution_workflow_payload({"id": "AbCdEf12345", "title": "Video"})

    assert payload["ownerUserId"] == 7
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

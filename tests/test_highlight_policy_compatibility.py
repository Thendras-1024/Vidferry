import json
import sys
import types
from pathlib import Path

import pytest

from app.backend.runtime import create_backend_module
from app.core.error_catalog import classify_workflow_exception
from app.core.errors import WorkflowContextError
from app.core.highlight_review_service import _validate_text_shortlist
from app.core.llm_harness import validate_editing_plan
from app.core.llm_prompts import build_editing_analysis_prompt, editing_analysis_system_prompt
from app.publish_runner import _parse_tags
from app.utils.format_util import _build_default_publish_draft, _parse_publish_draft


def _candidate(index, start):
    return {
        "candidateId": f"candidate-{index}",
        "start": start,
        "end": start + 8,
        "type": "moment",
        "reason": "test reason",
        "suggested_caption": "test caption",
    }


def test_text_shortlist_preserves_model_ranking_and_rejects_duplicates():
    candidates = [_candidate(index, 60 + index * 10) for index in range(1, 9)]
    selected = _validate_text_shortlist(
        {
            "selected": [
                {"candidateId": "candidate-8", "reason": "best"},
                {"candidateId": "candidate-4", "reason": "next"},
                {"candidateId": "candidate-6", "reason": "third"},
                {"candidateId": "candidate-2", "reason": "fourth"},
            ]
        },
        candidates,
    )

    assert [item["candidateId"] for item in selected] == ["candidate-8", "candidate-4", "candidate-6", "candidate-2"]
    assert [item["textShortlistRank"] for item in selected] == [1, 2, 3, 4]

    with pytest.raises(ValueError, match="重复"):
        _validate_text_shortlist(
            {"selected": [{"candidateId": "candidate-1", "reason": "a"}] * 4},
            candidates,
        )


def test_editing_plan_normalizes_highlights_to_chronological_order():
    result = validate_editing_plan(
        {
            "summary": "test summary",
            "china_view_angle": "test angle",
            "title_options": ["test title"],
            "cover_title_options": ["test\ncover", "another\ncover"],
            "publish_copy": "test copy",
            "tags": ["test"],
            "highlight_segments": [
                {"start": 82, "end": 90, "type": "moment", "reason": "later", "suggested_caption": "later"},
                {"start": 61, "end": 69, "type": "moment", "reason": "earlier", "suggested_caption": "earlier"},
            ],
            "risk_notes": [],
            "editing_focus": "test focus",
        },
        max_timestamp=120,
    )

    assert [item["start"] for item in result["highlight_segments"]] == [61.0, 82.0]


def test_editing_plan_keeps_all_ranked_tag_candidates_in_model_order():
    tags = [f"topic-{index}" for index in range(12)]
    titles = ["ranked-title-1", "ranked-title-2"]
    cover_titles = ["first\ncover", "second\ncover"]
    result = validate_editing_plan(
        {
            "summary": "test summary",
            "china_view_angle": "test angle",
            "title_options": titles,
            "cover_title_options": cover_titles,
            "publish_copy": "test copy",
            "tags": ["#topic-0", *tags, "topic-3", ""],
            "highlight_segments": [],
            "risk_notes": [],
            "editing_focus": "test focus",
        },
        max_timestamp=120,
    )

    assert result["tags"] == tags
    assert result["title_options"] == titles
    assert result["cover_title_options"] == cover_titles


def test_editing_plan_loads_research_context_for_job_owner(monkeypatch):
    backend = create_backend_module("test_editing_plan_research_context_backend")
    context_calls = []

    def load_context(video_id, owner_user_id):
        context_calls.append((video_id, owner_user_id))
        return {"title": "research title"}

    monkeypatch.setattr(backend, "youtube_video_research_context", load_context)
    monkeypatch.setattr(backend, "_format_transcript_for_model", lambda _segments: "test transcript")
    monkeypatch.setattr(backend, "_max_transcript_seconds", lambda _segments: 120)
    monkeypatch.setattr(backend, "_unsafe_transcript_ranges", lambda _segments: [])
    monkeypatch.setattr(backend, "_summarize_transcript_chunks", lambda *_args: ("test transcript", {}))
    monkeypatch.setattr(
        backend,
        "_call_editing_contract",
        lambda *_args, **_kwargs: (
            {
                "summary": "test summary",
                "china_view_angle": "test angle",
                "title_options": ["test title"],
                "cover_title_options": ["test\\ncover"],
                "publish_copy": "test copy",
                "tags": ["test"],
                "highlight_segments": [],
                "risk_notes": [],
                "editing_focus": "test focus",
            },
            {"totalTokens": 0},
            {"attemptCount": 1, "validationRetries": 0, "softWarnings": []},
        ),
    )

    backend._generate_editing_plan_impl({"videoId": "video-1", "ownerUserId": 42}, [])

    assert context_calls == [("video-1", 42)]


def test_editing_plan_context_type_error_uses_workflow_exception(monkeypatch):
    backend = create_backend_module("test_editing_plan_context_error_backend")

    def fail_context(_video_id, _owner_user_id):
        raise TypeError("context loader failed")

    monkeypatch.setattr(backend, "youtube_video_research_context", fail_context)

    with pytest.raises(WorkflowContextError) as caught:
        backend._generate_editing_plan_impl({"videoId": "video-1", "ownerUserId": 42}, [])

    assert isinstance(caught.value.__cause__, TypeError)
    error = classify_workflow_exception(caught.value)
    assert error["error_code"] == "VF-WORKFLOW-CONTEXT-FAILED"
    assert error["error_type"] == "WORKFLOW_CONTEXT_FAILED"


def test_youtube_media_stream_403_has_actionable_download_error():
    error = classify_workflow_exception(
        RuntimeError("ERROR: unable to download video data: HTTP Error 403: Forbidden")
    )

    assert error["error_code"] == "VF-DOWNLOAD-YOUTUBE-FORBIDDEN"
    assert error["error_type"] == "YOUTUBE_DOWNLOAD_FORBIDDEN"
    assert "HTTP 403" in error["error_reason"]
    assert "Cookie" in error["error_reason"]


_YOUTUBE_PRIMARY_FORMAT = "bv*+ba/b"


def _fake_yt_dlp(outcomes, calls):
    class FakeYoutubeDL:
        def __init__(self, options):
            self.options = options

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def extract_info(self, _url, download):
            assert download is True
            calls.append(self.options)
            outcome = outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            Path(self.options["outtmpl"].replace("%(ext)s", "mp4")).write_bytes(b"video")

    return types.SimpleNamespace(YoutubeDL=FakeYoutubeDL)


def _youtube_download_job():
    return {
        "id": "job-1",
        "videoId": "video-1",
        "url": "https://www.youtube.com/watch?v=video-1",
    }


def test_youtube_download_uses_default_player_client(tmp_path, monkeypatch):
    backend = create_backend_module("test_youtube_download_default_client_backend")
    calls = []
    monkeypatch.setattr(backend, "YOUTUBE_DOWNLOAD_DIR", tmp_path)
    monkeypatch.setitem(sys.modules, "yt_dlp", _fake_yt_dlp([None], calls))

    source_file = backend._download_youtube_video(_youtube_download_job())

    assert source_file == tmp_path / "video-1.mp4"
    assert calls[0]["format"] == _YOUTUBE_PRIMARY_FORMAT
    assert "extractor_args" not in calls[0]


def test_publish_tags_fill_douyin_limit_by_common_custom_and_selected_priority(monkeypatch):
    backend = create_backend_module()
    monkeypatch.setattr(
        backend,
        "get_publish_tag_presets",
        lambda _owner_user_id: {"presets": {"3": ["#common", "热点"]}},
    )
    targets = backend.normalize_publish_targets({
        "targets": [{
            "platformType": 3,
            "accountFile": "account.json",
            "selectedTags": ["#candidate", "热点", "llm-two", "llm-three"],
            "customTags": ["custom", "#common"],
            "accountId": 1,
        }],
    })
    targets[0]["ownerUserId"] = 11

    backend._resolve_publish_tags(targets)

    assert targets[0]["tags"] == ["common", "热点", "custom", "candidate", "llm-two"]
    assert targets[0]["_resolvedTags"] is True

    monkeypatch.setattr(
        backend,
        "get_publish_tag_presets",
        lambda _owner_user_id: {"presets": {"3": ["new-common"]}},
    )
    stored_target = {
        "platformType": 3,
        "tags": ["common", "热点", "custom", "candidate", "llm-two", "llm-three"],
        "_resolvedTags": True,
    }
    backend._resolve_publish_target_tags(stored_target)

    assert stored_target["tags"] == ["common", "热点", "custom", "candidate", "llm-two"]


def test_publish_draft_keeps_legacy_tags_selected_and_stores_video_custom_tags_separately():
    result = {"title_options": ["title"], "publish_copy": "copy", "tags": ["热点", "话题"]}
    default_draft = _build_default_publish_draft(result)
    legacy_draft = _parse_publish_draft(json.dumps({"tags": ["#已选", "手工标签", "已选"]}), result)

    assert default_draft["tags"] == ["热点", "话题"]
    assert default_draft["customTags"] == []
    assert legacy_draft["tags"] == ["已选", "手工标签"]
    assert legacy_draft["customTags"] == []


def test_publish_tag_limit_only_truncates_platforms_with_known_limit():
    backend = create_backend_module()

    topics = [f"topic-{index}" for index in range(8)]

    assert backend.merge_publish_tags(3, ["common"], ["custom"], topics) == [
        "common", "custom", "topic-0", "topic-1", "topic-2",
    ]
    assert backend.merge_publish_tags(4, ["common"], ["custom"], topics) == [
        "common", "custom", "topic-0", "topic-1",
    ]
    assert backend.merge_publish_tags(5, ["common"], ["custom"], topics) == [
        "common", "custom", *topics,
    ]


def test_publish_tags_are_split_before_douyin_limit_is_applied():
    backend = create_backend_module()

    tags = backend.merge_publish_tags(3, selected_tags=["a,b,c", "d", "e", "f", "g"])

    assert tags == ["a", "b", "c", "d", "e"]
    assert _parse_tags(",".join(tags)) == tags


def test_editing_prompts_require_ranked_fact_based_titles_covers_and_tags():
    ranking_rule = "title_options、cover_title_options、tags 均必须按预计传播和点击吸引力从高到低排列"
    evidence_rule = "只有标题、检索词或转写明确支持时，才可优先使用已有公共认知的品牌、人物、事件或主题"
    prompt = build_editing_analysis_prompt({"title": "测试", "query": "测试"}, "测试转写")

    assert ranking_rule in editing_analysis_system_prompt()
    assert ranking_rule in prompt
    assert evidence_rule in editing_analysis_system_prompt()
    assert evidence_rule in prompt


def test_publish_tag_preset_endpoint_hides_unknown_error(monkeypatch):
    backend = create_backend_module()
    backend.app.config["AUTH_TEST_BYPASS"] = True
    monkeypatch.setattr(backend, "_current_account_owner_id", lambda: 11)
    monkeypatch.setattr(backend, "get_publish_tag_presets", lambda _owner_user_id: (_ for _ in ()).throw(RuntimeError("db host leaked")))

    response = backend.app.test_client().get("/publish/tag-presets")

    assert response.status_code == 500
    assert response.get_json()["msg"] == "获取平台通用标签失败"


def test_tag_editors_and_platform_selection_are_explicit():
    root = Path(__file__).resolve().parents[1]
    publish_center = (root / "sau_frontend/src/views/PublishCenter.vue").read_text(encoding="utf-8")
    youtube_research = (root / "sau_frontend/src/views/YoutubeResearch.vue").read_text(encoding="utf-8")
    material_management = (root / "sau_frontend/src/views/MaterialManagement.vue").read_text(encoding="utf-8")

    assert "selectedTopicsByPlatform" in publish_center
    assert "videoCustomTopics" in publish_center
    assert "selectedTags: selectedTopicsForTarget" in publish_center
    assert "topicItemsForTarget" in publish_center
    assert "本次不发布" in publish_center
    assert "平台通用标签请在“平台通用标签”中管理" in publish_center
    assert "publish-topic--skipped" in publish_center
    assert ":closable=\"item.source === 'platform'\"" in publish_center
    assert "暂无已知标签数量限制" not in publish_center
    assert "const buildPublishData = (tab, targets = publishTargets(tab), includeResolvedTags = false)" in publish_center
    assert "...(includeResolvedTags ? { tags: topicsForTarget(tab, target) } : {})" in publish_center
    assert "buildPublishData(tab, targets, true)" in publish_center
    assert "customTags" in youtube_research
    assert "customTags" in material_management
    assert "新增话题" in youtube_research
    assert "新增话题" in material_management

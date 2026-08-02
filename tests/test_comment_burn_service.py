import threading

import app.core.comment_burn_service as comment_burn_service
from app.core.comment_burn_service import (
    _is_allowed_comment_avatar_url,
    _is_chinese_comment,
    _validate_comment_review,
    build_comment_review_items,
    normalize_comment_candidates,
    schedule_comment_burn,
)
from app.backend.runtime import load_backend_namespace


def test_normalize_comment_candidates_keeps_valid_unique_comments():
    comments = normalize_comment_candidates([
        {"id": "a", "author": "Alice", "text": "This is useful", "like_count": "12"},
        {"id": "b", "author": "Bob", "text": "this is useful", "like_count": 5},
        {"id": "c", "author": "Chris", "text": "https://example.com", "like_count": 3},
        {"id": "d", "author": "Dana", "text": "Nice explanation", "like_count": -1},
    ])

    assert [(item["id"], item["likeCount"]) for item in comments] == [("a", 12), ("d", 0)]


def test_comment_timestamp_is_rendered_as_calendar_date_with_relative_fallback():
    comments = normalize_comment_candidates([
        {"id": "dated", "author": "Alice", "text": "Useful", "timestamp": 1777766400, "_time_text": "3 months ago"},
        {"id": "relative", "author": "Bob", "text": "Also useful", "timestamp": "invalid", "_time_text": "2 months ago"},
    ])

    assert [item["timeText"] for item in comments] == ["2026-05-03", "2 months ago"]


def test_comment_profanity_filter_does_not_reject_single_chinese_character():
    comments = normalize_comment_candidates([
        {"id": "safe", "author": "A", "text": "操场旁边的讲解很清楚"},
        {"id": "blocked", "author": "B", "text": "操你妈，别再这样说"},
    ])

    assert [item["id"] for item in comments] == ["safe"]


def test_comment_review_items_keep_rejection_reason_and_selected_translation():
    review_items = []
    candidates = normalize_comment_candidates([
        {"id": "safe", "author": "Alice", "text": "Very clear explanation"},
        {"id": "blocked", "author": "Bob", "text": "操你妈，别再这样说"},
    ], review_items=review_items)

    items = build_comment_review_items(
        review_items,
        {"screenedIds": ["safe"], "selectedIds": ["safe"]},
        [{**candidates[0], "translationRequired": True, "translationZh": "讲解得非常清楚"}],
    )

    assert [(item["id"], item["status"], item["filterReason"]) for item in items] == [
        ("safe", "selected", "已选中并可烧制"),
        ("blocked", "rejected", "命中严格脏话规则"),
    ]
    assert items[0]["translationZh"] == "讲解得非常清楚"


def test_comment_review_requires_non_chinese_translation_and_preserves_chinese():
    candidates = [
        {"id": "english", "author": "Alice", "text": "Great explanation", "likeCount": 2},
        {"id": "chinese", "author": "王五", "text": "讲得很清楚", "likeCount": 3},
    ]

    selected = _validate_comment_review({
        "comments": [
            {"id": "english", "translationRequired": True, "translationZh": "解释得很好"},
            {"id": "chinese", "translationRequired": False, "translationZh": ""},
        ]
    }, candidates)

    assert selected[0]["translationZh"] == "解释得很好"
    assert selected[1]["translationZh"] == ""


def test_comment_review_discards_redundant_translation_for_chinese_comment():
    selected = _validate_comment_review({
        "comments": [
            {"id": "chinese", "translationRequired": True, "translationZh": "讲解得很清楚"},
        ]
    }, [{"id": "chinese", "author": "王五", "text": "讲得很清楚", "likeCount": 3}])

    assert selected == [{
        "id": "chinese",
        "author": "王五",
        "text": "讲得很清楚",
        "likeCount": 3,
        "translationRequired": False,
        "translationZh": "",
    }]


def test_japanese_comment_is_not_treated_as_chinese():
    assert _is_chinese_comment("讲得很清楚") is True
    assert _is_chinese_comment("這個講解很清楚") is True
    assert _is_chinese_comment("This explanation 很 clear") is False
    assert _is_chinese_comment("説明がわかりやすい") is False


def test_comment_schedule_leaves_an_eight_second_gap_after_each_display():
    scheduled = schedule_comment_burn({
        "comments": [
            {"id": "a", "author": "A", "text": "First"},
            {"id": "b", "author": "B", "text": "Second"},
            {"id": "c", "author": "C", "text": "Third"},
        ]
    }, 100)

    assert [(item["id"], item["displayStart"], item["displayEnd"]) for item in scheduled["comments"]] == [
        ("a", 60, 68),
        ("b", 76, 84),
        ("c", 92, 100),
    ]
    assert scheduled["status"] == "success"


def test_comment_avatar_urls_are_limited_to_google_https_hosts():
    assert _is_allowed_comment_avatar_url("https://yt3.ggpht.com/avatar")
    assert _is_allowed_comment_avatar_url("https://lh3.googleusercontent.com/avatar")
    assert not _is_allowed_comment_avatar_url("http://yt3.ggpht.com/avatar")
    assert not _is_allowed_comment_avatar_url("https://127.0.0.1/avatar")
    assert not _is_allowed_comment_avatar_url("https://yt3.ggpht.com.evil.example/avatar")


def test_comment_avatar_assets_keep_comment_order_with_parallel_downloads(monkeypatch, tmp_path):
    monkeypatch.setattr(comment_burn_service, "_download_comment_avatar", lambda _url, target: str(target))
    assets = comment_burn_service.prepare_comment_avatar_assets({"comments": [
        {"authorThumbnail": "https://yt3.ggpht.com/first", "displayStart": 60, "displayEnd": 68, "text": "first"},
        {"authorThumbnail": "https://yt3.ggpht.com/second", "displayStart": 76, "displayEnd": 84, "text": "second"},
    ]}, tmp_path)

    assert [item["text"] for item in assets] == ["first", "second"]


def test_runtime_ass_contains_comment_metadata_content_likes_and_translation(tmp_path):
    namespace = load_backend_namespace({})
    ass_file = namespace["_build_ass_file"](
        {"subtitleLanguage": "zh-CN", "translationEnabled": True},
        [],
        tmp_path / "comments.ass",
        120,
        {"width": 1080, "height": 1920},
        include_subtitles=False,
        comment_snapshot={
            "comments": [{
                "author": "Alice",
                "timeText": "2 days ago",
                "text": "Great explanation",
                "likeCount": 42,
                "translationRequired": True,
                "translationZh": "讲解得很好",
                "displayStart": 60,
                "displayEnd": 68,
            }]
        },
    )
    content = ass_file.read_text(encoding="utf-8")

    assert "Style: CommentMeta" in content
    assert "Style: CommentMeta,Microsoft YaHei,36," in content
    assert "Style: CommentText,Microsoft YaHei,43," in content
    assert "Style: CommentTranslation,Microsoft YaHei,35," in content
    assert "Dialogue: 4,0:01:00.00,0:01:08.00,CommentMeta" in content
    assert "Alice  2 days ago" in content
    assert "Great explanation" in content
    assert "讲解得很好" in content
    assert "👍 42" in content
    assert r"\fad(480,280)" in content
    assert r"\move(" in content
    assert r"\t(0,300,\fscx102\fscy102)" in content
    assert ",Info,,0,0,0,," not in content


def test_comment_avatar_layout_uses_final_scaled_video_dimensions(tmp_path):
    namespace = load_backend_namespace({})
    avatar_file = tmp_path / "avatar.png"
    avatar_file.write_bytes(b"avatar")
    filter_complex, _ = namespace["_comment_avatar_filter_complex"](
        tmp_path / "comments.ass",
        ["subtitles='comments.ass'", "scale=1920:1080", "setsar=1"],
        [{"path": avatar_file, "start": 60, "end": 68, "text": "Great explanation", "translationRequired": True, "translationZh": "讲解得很好"}],
        {"width": 1920, "height": 1080},
    )

    assert "scale=101:101" in filter_complex
    assert "overlay=x=44:y='" in filter_complex
    assert "fade=t=in:st=0:d=0.48:alpha=1" in filter_complex
    assert "fade=t=out:st=7.72:d=0.28:alpha=1" in filter_complex
    assert "eval=frame" in filter_complex


def test_comment_review_screens_100_candidates_in_batches_and_selects_20(monkeypatch):
    batches = []

    def screen(_job, candidates, _telemetry):
        batches.append(candidates)
        return [{**item, "_score": 90 - index} for index, item in enumerate(candidates[:5])], {"tokens": 1}, {}

    candidates = [{"id": str(index), "author": "A", "text": f"comment {index}", "likeCount": index} for index in range(100)]
    monkeypatch.setattr(comment_burn_service, "_screen_comment_batch", screen)
    monkeypatch.setattr(comment_burn_service, "_translate_selected_comments", lambda _job, items, _telemetry: (items, {}))
    monkeypatch.setattr(comment_burn_service, "call_json_contract", lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("timeout")))

    comments, _, metadata = comment_burn_service.review_youtube_comment_candidates({"commentTranslationMode": "google"}, candidates)

    assert [len(batch) for batch in batches] == [20, 20, 20, 20, 20]
    assert len(comments) == 20
    assert metadata["screenedCount"] == 25


def test_comment_review_screens_batches_with_bounded_concurrency(monkeypatch):
    barrier = threading.Barrier(2, timeout=1)

    def screen(_job, candidates, _telemetry):
        barrier.wait()
        return [{**candidates[0], "_score": 80}], {}, {}

    monkeypatch.setattr(comment_burn_service, "_screen_comment_batch", screen)
    monkeypatch.setattr(comment_burn_service, "_translate_selected_comments", lambda _job, items, _telemetry: (items, {}))
    monkeypatch.setattr(comment_burn_service, "call_json_contract", lambda **kwargs: (kwargs["validator"]({"comments": [{"id": "0"}, {"id": "20"}]}), {}, {}))

    candidates = [{"id": str(index), "author": "A", "text": f"comment {index}", "likeCount": 0} for index in range(40)]
    comments, _, metadata = comment_burn_service.review_youtube_comment_candidates({}, candidates)

    assert [item["id"] for item in comments] == ["0", "20"]
    assert [item["status"] for item in metadata["screenBatches"]] == ["success", "success"]


def test_comment_review_keeps_successful_batches_when_one_batch_fails(monkeypatch):
    def screen(_job, candidates, _telemetry):
        if candidates[0]["id"] == "20":
            raise RuntimeError("timeout")
        return [{**candidates[0], "_score": 80}], {}, {}

    monkeypatch.setattr(comment_burn_service, "_screen_comment_batch", screen)
    monkeypatch.setattr(comment_burn_service, "_translate_selected_comments", lambda _job, items, _telemetry: (items, {}))
    monkeypatch.setattr(comment_burn_service, "call_json_contract", lambda **kwargs: (kwargs["validator"]({"comments": [{"id": "0"}, {"id": "40"}]}), {}, {}))
    candidates = [{"id": str(index), "author": "A", "text": f"comment {index}", "likeCount": 0} for index in range(60)]

    comments, _, metadata = comment_burn_service.review_youtube_comment_candidates({}, candidates)

    assert [item["id"] for item in comments] == ["0", "40"]
    assert [item["status"] for item in metadata["screenBatches"]] == ["success", "failed", "success"]


def test_comment_review_logs_batch_and_fallback(monkeypatch, caplog):
    monkeypatch.setattr(comment_burn_service, "_screen_comment_batch", lambda _job, candidates, _telemetry: ([{**candidates[0], "_score": 80}], {}, {}))
    monkeypatch.setattr(comment_burn_service, "_translate_selected_comments", lambda _job, items, _telemetry: (items, {}))
    monkeypatch.setattr(comment_burn_service, "call_json_contract", lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("timeout")))

    comment_burn_service.review_youtube_comment_candidates(
        {"id": "job-1"}, [{"id": "1", "author": "A", "text": "comment", "likeCount": 0}],
    )

    assert "评论初筛开始 job_id=job-1" in caplog.text
    assert "评论最终筛选失败，按初筛评分回退 job_id=job-1" in caplog.text


def test_comment_translation_google_mode_translates_only_non_chinese(monkeypatch):
    monkeypatch.setattr(comment_burn_service, "_translate_segments", lambda segments, _language: [{"subtitle": "中文译文"} for _ in segments], raising=False)
    comments, metadata = comment_burn_service._translate_selected_comments(
        {"commentTranslationMode": "google"},
        [
            {"id": "en", "text": "Useful comment"},
            {"id": "zh", "text": "讲得很清楚"},
        ],
    )

    assert comments == [
        {"id": "en", "text": "Useful comment", "translationRequired": True, "translationZh": "中文译文"},
        {"id": "zh", "text": "讲得很清楚", "translationRequired": False, "translationZh": ""},
    ]
    assert metadata == {"googleFailedCount": 0, "googleFailedIds": [], "llmFallbackCount": 0}


def test_comment_translation_keeps_google_result_when_llm_revision_fails(monkeypatch):
    monkeypatch.setattr(comment_burn_service, "_translate_segments", lambda segments, _language: [{"subtitle": "Google 初译"} for _ in segments], raising=False)
    monkeypatch.setattr(comment_burn_service, "review_translated_segments", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("timeout")), raising=False)

    comments, metadata = comment_burn_service._translate_selected_comments(
        {"commentTranslationMode": "google_llm"}, [{"id": "en", "text": "Useful comment"}],
    )

    assert comments[0]["translationZh"] == "Google 初译"
    assert metadata["llmFallbackCount"] == 1


def test_comment_translation_reports_google_failure_without_burning_comment(monkeypatch):
    monkeypatch.setattr(
        comment_burn_service,
        "_translate_segments",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("network")),
        raising=False,
    )

    comments, metadata = comment_burn_service._translate_selected_comments(
        {"commentTranslationMode": "google"}, [{"id": "en", "text": "Useful comment"}],
    )

    assert comments == []
    assert metadata == {"googleFailedCount": 1, "googleFailedIds": ["en"], "llmFallbackCount": 0}


def test_comment_preparation_records_fetch_count_and_translation_failure_reason(monkeypatch):
    saved = []
    finished = []
    namespace = load_backend_namespace({})
    monkeypatch.setitem(namespace, "comment_burn_signature", lambda _job: "signature")
    monkeypatch.setitem(namespace, "get_youtube_comment_burn_snapshot", lambda _video_id: {})
    monkeypatch.setitem(namespace, "start_workflow_event", lambda *_args, **_kwargs: "event")
    monkeypatch.setitem(namespace, "finish_workflow_event", lambda *_args, **_kwargs: finished.append(_args))
    monkeypatch.setitem(namespace, "build_workflow_llm_telemetry", lambda *_args, **_kwargs: None)
    monkeypatch.setitem(
        namespace,
        "fetch_youtube_comment_candidates",
        lambda _url, stats, review_items: (stats.update({"fetchedCount": 12, "regexFilteredCount": 2}) or review_items.extend([{"id": "en", "status": "pending"}]) or [{"id": "en"}]),
    )
    monkeypatch.setitem(
        namespace,
        "review_youtube_comment_candidates",
        lambda *_args: ([], {}, {"selectedCount": 1, "translation": {"googleFailedCount": 1}}),
    )
    monkeypatch.setitem(namespace, "save_youtube_comment_burn_snapshot", lambda *_args: saved.append(_args[1]))

    snapshot = namespace["_run_comment_burn_preparation"]({
        "id": "job", "videoId": "video", "url": "https://example.test", "commentBurnEnabled": True,
    })

    assert snapshot["fetchedCount"] == 12
    assert snapshot["selectedCount"] == 1
    assert snapshot["translatedCount"] == 0
    assert snapshot["reason"] == "评论翻译失败，未生成可烧制评论"
    assert saved[-1]["fetchedCount"] == 12
    assert finished[-1][2] == "评论翻译失败，未生成可烧制评论"

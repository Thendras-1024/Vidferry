from app.core.comment_burn_service import _comment_rejection_reason
from app.core.comment_burn_service import _validate_comment_screen, _validate_comment_selection
from app.core.comment_burn_service import build_comment_review_items
from app.core.comment_burn_service import normalize_comment_candidates
from app.core.comment_burn_service import prepare_comment_avatar_assets
from app.core import llm_prompts


def _raw(comment_id, text):
    return {"id": comment_id, "author": "tester", "text": text}


def test_local_filter_only_rejects_standalone_filler_and_explicit_profanity():
    assert _comment_rejection_reason(_raw("filler", "wow!!!"))
    assert not _comment_rejection_reason(_raw("sentence", "Wow, this explains why the train is so efficient."))
    assert _comment_rejection_reason(_raw("profanity", "This is bullshit."))
    assert _comment_rejection_reason(_raw("korean", "이건 씨발 너무 별로야"))


def test_local_filter_deduplicates_only_identical_comments():
    review_items = []
    candidates = normalize_comment_candidates([
        _raw("one", "Useful explanation with a concrete example."),
        _raw("two", "Useful explanation with a concrete example."),
        _raw("three", "Useful explanation with another concrete example."),
    ], review_items=review_items)

    assert [item["id"] for item in candidates] == ["one", "three"]
    assert review_items[1]["status"] == "rejected"


def test_llm_filter_codes_are_complete_and_map_to_review_text():
    candidates = [
        {"id": "one", "author": "a", "text": "Relevant comment", "likeCount": 0},
        {"id": "two", "author": "b", "text": "Duplicate idea", "likeCount": 0},
    ]
    reviewed = _validate_comment_screen({"keep": [1]}, candidates)

    assert reviewed[0]["_keep"] is True
    review_items = [{"id": "two", "status": "pending"}]
    removed = _validate_comment_selection({"remove": [{"no": 2, "reasonCode": "SIMILAR"}]}, candidates)
    items = build_comment_review_items(
        review_items,
        {"llmFilterCodes": {removed[0]["id"]: removed[0]["_filterCode"]}, "screenedIds": ["two"], "initialScreenIds": ["one"]},
        [],
    )
    assert items[0]["filterCode"] == "SIMILAR"


def test_llm_screen_contract_accepts_empty_keep_and_rejects_extra_fields():
    candidates = [_raw("one", "Useful comment")]
    assert _validate_comment_screen({"keep": []}, candidates) == []
    try:
        _validate_comment_screen({"keep": [1], "extra": True}, candidates)
    except ValueError:
        pass
    else:
        raise AssertionError("extra fields must be rejected")


def test_failed_screen_batch_has_explicit_reason():
    items = build_comment_review_items(
        [{"id": "one", "status": "pending"}],
        {"failedBatchIds": ["one"], "failureCode": "LLM_OUTPUT_FORMAT_ERROR"},
        [],
    )
    assert items[0]["filterReason"] == "初筛批次失败"


def test_missing_required_comment_fields_are_filtered_locally():
    review_items = []
    candidates = normalize_comment_candidates([
        {"id": "missing-author", "text": "Useful comment"},
        {"id": "missing-text", "author": "tester"},
        _raw("valid", "Useful comment"),
    ], review_items=review_items)

    assert [item["id"] for item in candidates] == ["valid"]
    assert all(item["status"] == "rejected" for item in review_items[:2])


def test_avatar_assets_are_disabled_and_llm_sees_codes_only(tmp_path):
    assert prepare_comment_avatar_assets({"comments": [{"authorThumbnail": "https://example.com/avatar"}]}, tmp_path) == []
    prompt = llm_prompts.comment_screen_system_prompt()
    assert '"keep"' in prompt
    assert "与视频主题无关" not in prompt

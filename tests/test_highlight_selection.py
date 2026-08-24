import pytest

from app.core import highlight_review_service as review
from app.core import llm_harness


def _candidate(index, start=None):
    start = start if start is not None else 60 + index * 20
    return {
        "candidateId": f"candidate-{index}",
        "start": start,
        "end": start + 8,
        "type": "highlight",
        "reason": f"看点 {index}",
        "suggested_caption": f"字幕 {index}",
    }


def test_highlight_start_boundary_is_sixty_seconds():
    assert review.HIGHLIGHT_MIN_START_SECONDS == 60

    valid = _candidate(1, start=60)
    invalid = _candidate(0, start=59.99)
    assert llm_harness._highlight_segments([{key: value for key, value in valid.items() if key != "candidateId"}], 120, [], max_items=8)
    assert llm_harness._highlight_segments([{key: value for key, value in invalid.items() if key != "candidateId"}], 120, [], max_items=8) == []


def test_text_shortlist_requires_four_unique_known_candidates():
    candidates = [_candidate(index) for index in range(8)]
    selected = review._validate_text_shortlist(
        {"selected": [{"candidateId": f"candidate-{index}", "reason": "更适合作为开头"} for index in (7, 6, 5, 4)]},
        candidates,
    )
    assert [item["candidateId"] for item in selected] == ["candidate-7", "candidate-6", "candidate-5", "candidate-4"]

    with pytest.raises(ValueError):
        review._validate_text_shortlist(
            {"selected": [{"candidateId": "candidate-7", "reason": "重复"}] * 4},
            candidates,
        )


def test_text_shortlist_prompt_is_time_ordered_input_and_attraction_selection():
    candidates = [_candidate(index) for index in range(8)]
    prompt = review.llm_prompts.build_highlight_text_shortlist_prompt(candidates, candidates)
    assert "candidate-0" in prompt and "candidate-7" in prompt
    assert "按时间先后" in prompt
    assert "吸引力" in prompt


def test_vision_unavailable_uses_text_shortlist_order(monkeypatch):
    candidates = [_candidate(index) for index in range(8)]
    shortlist = [_candidate(index) for index in (7, 6, 5, 4)]
    monkeypatch.setattr(review, "_text_shortlist_candidates", lambda *_args, **_kwargs: (shortlist, {"status": "success", "selected": shortlist}))
    monkeypatch.setattr(review, "get_llm_config_status", lambda: {"multimodal": {"ready": False, "visionReady": False, "message": "unavailable"}})

    selected, metadata = review.refine_highlight_segments({"highlightCount": 3}, "video.mp4", [], candidates, 300)

    assert [item["candidateId"] for item in selected] == ["candidate-7", "candidate-6", "candidate-5"]
    assert metadata["selectionSource"] == "text_shortlist"


def test_vision_reviews_text_shortlist_and_overrides_its_order(monkeypatch):
    candidates = [_candidate(index) for index in range(8)]
    shortlist = [_candidate(index) for index in (7, 6, 5, 4)]
    reviewed_ids = []
    scores = {"candidate-7": 70, "candidate-6": 99, "candidate-5": 80, "candidate-4": 90}

    monkeypatch.setattr(review, "_text_shortlist_candidates", lambda *_args, **_kwargs: (shortlist, {"status": "success", "selected": shortlist}))
    monkeypatch.setattr(review, "get_llm_config_status", lambda: {"multimodal": {"ready": True, "visionReady": True}})
    monkeypatch.setattr(review, "_blocked_ranges", lambda _segments: [])

    def fake_review(candidate, *_args, **_kwargs):
        reviewed_ids.append(candidate["candidateId"])
        return {"start": candidate["start"], "end": candidate["end"], "score": scores[candidate["candidateId"]], "reason": "画面完整"}

    monkeypatch.setattr(review, "_review_candidate", fake_review)
    selected, metadata = review.refine_highlight_segments({"highlightCount": 3}, "video.mp4", [], candidates, 300)

    assert reviewed_ids == ["candidate-7", "candidate-6", "candidate-5", "candidate-4"]
    assert [item["candidateId"] for item in selected] == ["candidate-6", "candidate-4", "candidate-5"]
    assert metadata["selectionSource"] == "vision"

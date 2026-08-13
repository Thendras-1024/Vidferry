import pytest

from app.core.highlight_review_service import _validate_text_shortlist
from app.core.llm_harness import validate_editing_plan


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

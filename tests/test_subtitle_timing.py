import pytest

from app.backend.runtime import create_backend_module


@pytest.fixture(scope="module")
def subtitle_cues_builder():
    return create_backend_module()._build_subtitle_cues


def _segment(words, text=None):
    return {
        "text": text or " ".join(word["word"] for word in words),
        "start": words[0]["start"],
        "end": words[-1]["end"],
        "words": words,
    }


def test_short_phrase_with_light_pause_stays_in_one_cue(subtitle_cues_builder):
    segment = _segment([
        {"word": "I", "start": 0.0, "end": 0.35},
        {"word": "think", "start": 0.82, "end": 1.35},
        {"word": "so", "start": 1.48, "end": 1.76},
    ], "I think so")

    cues = subtitle_cues_builder([segment], "en")

    assert len(cues) == 1
    assert cues[0]["text"] == "I think so"
    assert cues[0]["start"] == 0.0
    assert cues[0]["end"] == 1.76


def test_long_phrase_still_respects_visible_character_limit(subtitle_cues_builder):
    words = [
        {"word": "one", "start": 0.0, "end": 0.5},
        {"word": "two", "start": 0.6, "end": 1.1},
        {"word": "three", "start": 1.2, "end": 1.7},
        {"word": "four", "start": 1.8, "end": 2.3},
        {"word": "five", "start": 2.4, "end": 2.9},
        {"word": "six", "start": 3.0, "end": 3.5},
        {"word": "seven", "start": 3.6, "end": 4.1},
        {"word": "eight", "start": 4.2, "end": 4.7},
        {"word": "nine", "start": 4.8, "end": 5.3},
        {"word": "ten", "start": 5.4, "end": 5.9},
    ]

    cues = subtitle_cues_builder([_segment(words)], "en")

    assert len(cues) >= 2
    assert all(len("".join(cue["text"].split())) <= 42 for cue in cues)


def test_adjacent_translated_fragments_are_merged_when_source_has_no_sentence_end():
    backend = create_backend_module()
    cues = [
        {"start": 0.0, "end": 0.8, "text": "I think", "subtitle": "我觉得", "words": []},
        {"start": 1.0, "end": 1.5, "text": "so", "subtitle": "是这样", "words": []},
    ]

    merged = backend._merge_rendered_fragment_cues(cues, "zh-CN", 18)

    assert len(merged) == 1
    assert merged[0]["subtitle"] == "我觉得是这样"
    assert merged[0]["end"] == 1.5

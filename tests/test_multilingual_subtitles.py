import sys
from types import ModuleType, SimpleNamespace

import pytest

from app.backend.runtime import create_backend_module
from app.core import subtitle_review


def test_source_language_is_normalized_for_subtitle_audit_responses():
    backend = create_backend_module()

    assert backend._normalize_source_language("ja") == "ja"
    assert backend._normalize_source_language("ko-KR") == "ko"
    assert backend._normalize_source_language("en-US") == "en"
    assert backend._normalize_source_language("hi") == "hi"
    assert backend._normalize_source_language("unknown-language") == ""
    assert backend._subtitle_audit_list_item({"source_language": "ja"})["sourceLanguage"] == "ja"


def test_ass_keeps_asr_source_text_in_a_neutral_source_style(tmp_path):
    backend = create_backend_module()
    ass_file = tmp_path / "subtitles.ass"

    backend._build_ass_file(
        {"subtitleLanguage": "zh-CN", "translationEnabled": True},
        [{"start": 0, "end": 1, "text": "こんにちは", "subtitle": "你好"}],
        ass_file,
        2,
        {"width": 1080, "height": 1920},
    )

    content = ass_file.read_text(encoding="utf-8")
    assert "Style: Source," in content
    assert "Dialogue: 0,0:00:00.00,0:00:01.00,Source" in content
    assert "こんにちは" in content
    assert "Style: English," not in content


def test_multilingual_source_copy_keeps_chinese_redaction_behavior():
    backend = create_backend_module()

    assert "英文" not in backend.subtitle_review_system_prompt()
    assert "原音识别文本" in backend.subtitle_review_system_prompt()
    assert "原音识别文本" in backend.validate_editing_plan(
        {
            "summary": "测试",
            "china_view_angle": "测试",
            "title_options": ["测试标题"],
            "cover_title_options": ["测试\n封面", "字幕\n测试"],
            "publish_copy": "测试文案",
            "tags": ["测试"],
            "highlight_segments": [],
            "risk_notes": [],
            "editing_focus": "测试",
        },
        60,
        blocked_ranges=[{"start": 1, "end": 2}],
    )["risk_notes"][-1]


def test_processed_output_is_reused_even_if_current_editing_options_changed(tmp_path):
    backend = create_backend_module()
    processed_file = tmp_path / "processed.mp4"
    processed_file.write_bytes(b"video")

    assert backend._video_has_processed_output(
        {"translateStatus": 1, "processedFilePath": str(processed_file)},
        {"processVersion": backend.PROCESS_VERSION_EDITING, "subtitleMaskEnabled": True},
    )


def test_workflow_resource_uses_video_artifact_state(monkeypatch):
    backend = create_backend_module()
    monkeypatch.setattr(backend, "_get_youtube_video_record", lambda _video_id, _owner_id: {"downloadStatus": 1, "translateStatus": 1})
    monkeypatch.setattr(backend, "_video_has_processed_output", lambda record, _job: record.get("translateStatus") == 1)

    assert backend.workflow_job_resource({"videoId": "processed"}) == "publish"

    monkeypatch.setattr(backend, "_get_youtube_video_record", lambda _video_id, _owner_id: {"downloadStatus": 1, "translateStatus": 0})
    assert backend.workflow_job_resource({"videoId": "downloaded"}) == "processing"

    monkeypatch.setattr(backend, "_get_youtube_video_record", lambda _video_id, _owner_id: {"downloadStatus": 0, "translateStatus": 0})
    assert backend.workflow_job_resource({"videoId": "lead"}) == "processing"


@pytest.mark.parametrize(("source_language", "expected_source"), [
    ("ja-JP", "ja"), ("ko-KR", "ko"), ("es-MX", "es"), ("ru-RU", "ru"),
    ("zh", "zh-CN"), ("yue", "auto"), ("", "auto"),
])
def test_google_translation_uses_normalized_asr_source_language(monkeypatch, source_language, expected_source):
    backend = create_backend_module()
    captured = []

    class FakeGoogleTranslator:
        def __init__(self, source, target):
            captured.append((source, target))

        def translate(self, text):
            return "\n".join("译文" for _ in text.splitlines())

    google_module = ModuleType("deep_translator.google")
    google_module.requests = SimpleNamespace(get=lambda *args, **kwargs: None)
    translator_module = ModuleType("deep_translator")
    translator_module.GoogleTranslator = FakeGoogleTranslator
    translator_module.google = google_module
    constants_module = ModuleType("deep_translator.constants")
    constants_module.GOOGLE_LANGUAGES_TO_CODES = {
        "japanese": "ja",
        "korean": "ko",
        "spanish": "es",
        "russian": "ru",
        "chinese (simplified)": "zh-CN",
    }
    monkeypatch.setitem(sys.modules, "deep_translator", translator_module)
    monkeypatch.setitem(sys.modules, "deep_translator.google", google_module)
    monkeypatch.setitem(sys.modules, "deep_translator.constants", constants_module)

    translated = backend._translate_segments(
        [{"text": "source text"}], "zh-CN", source_language=source_language,
    )

    assert captured == [(expected_source, "zh-CN")]
    assert translated[0]["subtitle"] == "译文"


@pytest.mark.parametrize(("source_language", "marker"), [
    ("ja-JP", "日语源文规则"), ("ko-KR", "韩语源文规则"),
    ("es-MX", "西班牙语源文规则"), ("ru-RU", "俄语源文规则"),
])
def test_llm_review_uses_source_language_guidance(monkeypatch, source_language, marker):
    calls = []

    def fake_call_json_contract(**kwargs):
        calls.append(kwargs["messages"])
        return {"items": [{"index": 0, "subtitle": "修订字幕"}]}, {"totalTokens": 1}, {"attemptCount": 1}

    monkeypatch.setattr(subtitle_review, "SUBTITLE_LLM_REVIEW_ENABLED", True)
    monkeypatch.setattr(subtitle_review, "TEXT_LLM_MODEL", "test-model")
    monkeypatch.setattr(subtitle_review, "TEXT_LLM_API_KEY", "test-key")
    monkeypatch.setattr(subtitle_review, "TEXT_LLM_BASE_URL", "https://test.invalid")
    monkeypatch.setattr(subtitle_review, "call_json_contract", fake_call_json_contract)
    review_metadata = {}

    reviewed = subtitle_review.review_translated_segments(
        [{"text": "source text", "subtitle": "初译字幕"}],
        "zh-CN",
        job={"title": "test", "channel": "test"},
        source_language=source_language,
        review_metadata=review_metadata,
    )

    assert calls
    assert marker in calls[0][0]["content"]
    assert '"sourceLanguage": "' + source_language[:2] + '"' in calls[0][1]["content"]
    assert reviewed == [{"text": "source text", "subtitle": "修订字幕"}]
    assert review_metadata["status"] == "success"

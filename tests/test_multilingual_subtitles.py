from app.backend.runtime import create_backend_module


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

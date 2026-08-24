from app.core import source_subtitle_service


def _enable_multimodal(monkeypatch):
    monkeypatch.setattr(source_subtitle_service, "MULTIMODAL_LLM_API_KEY", "test")
    monkeypatch.setattr(source_subtitle_service, "MULTIMODAL_LLM_BASE_URL", "https://example.test/v1")
    monkeypatch.setattr(source_subtitle_service, "MULTIMODAL_LLM_MODEL", "vision-test")
    monkeypatch.setattr(
        source_subtitle_service,
        "get_llm_config_status",
        lambda: {"multimodal": {"ready": True, "visionReady": True}},
    )


def _frames():
    return [
        {"frameIndex": index, "timestampSeconds": float(index), "dataUrl": "data:image/jpeg;base64,test"}
        for index in range(1, 4)
    ]


def test_auto_masks_non_chinese_source_subtitles(monkeypatch):
    _enable_multimodal(monkeypatch)
    captured = {}
    monkeypatch.setattr(source_subtitle_service, "_extract_source_subtitle_frames", lambda *_args: _frames())

    def call_json_contract(**kwargs):
        captured.update(kwargs)
        return {
            "classification": "non_zh",
            "reason": "检测到韩语对白字幕",
        }, {}, {}

    monkeypatch.setattr(source_subtitle_service, "call_json_contract", call_json_contract)

    analysis, _usage = source_subtitle_service.analyze_source_subtitles(
        {"subtitleMode": "auto"}, "source.mp4", 60,
    )

    assert analysis["analysisVersion"] == 3
    assert analysis["status"] == "success"
    assert analysis["burnSubtitles"] is True
    assert analysis["subtitleMaskEnabled"] is True
    assert analysis["decision"]["effectiveAction"] == "mask_and_burn"
    assert analysis["classification"] == "non_zh"
    assert "bbox" not in captured["messages"][1]["content"][0]["text"]
    assert captured["prompt_version"] == "source-subtitle-v3"


def test_auto_rechecks_with_new_frames_and_failure_reason(monkeypatch):
    _enable_multimodal(monkeypatch)
    extracted = []
    calls = []

    def extract_frames(*_args):
        extracted.append(True)
        return _frames()

    def call_json_contract(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise ValueError("第一次契约校验失败")
        return {"classification": "non_zh", "reason": "第二次检查确认韩语字幕"}, {}, {}

    monkeypatch.setattr(source_subtitle_service, "_extract_source_subtitle_frames", extract_frames)
    monkeypatch.setattr(source_subtitle_service, "call_json_contract", call_json_contract)

    analysis, _usage = source_subtitle_service.analyze_source_subtitles(
        {"subtitleMode": "auto"}, "source.mp4", 60,
    )

    assert len(extracted) == 2
    assert len(calls) == 2
    assert calls[0]["max_tokens"] == 3000
    assert calls[0]["max_attempts"] == 1
    assert calls[1]["max_tokens"] == 6000
    assert calls[1]["max_attempts"] == 1
    retry_text = calls[1]["messages"][1]["content"][0]["text"]
    assert "第一次契约校验失败" in retry_text
    assert analysis["status"] == "success"
    assert analysis["classification"] == "non_zh"
    assert analysis["subtitleMaskEnabled"] is True


def test_auto_degrades_after_second_check_failure(monkeypatch):
    _enable_multimodal(monkeypatch)
    extracted = []
    calls = []

    monkeypatch.setattr(
        source_subtitle_service,
        "_extract_source_subtitle_frames",
        lambda *_args: extracted.append(True) or _frames(),
    )

    def call_json_contract(**kwargs):
        calls.append(kwargs)
        raise ValueError(f"失败第 {len(calls)} 次")

    monkeypatch.setattr(source_subtitle_service, "call_json_contract", call_json_contract)

    analysis, _usage = source_subtitle_service.analyze_source_subtitles(
        {"subtitleMode": "auto"}, "source.mp4", 60,
    )

    assert len(extracted) == 2
    assert len(calls) == 2
    assert analysis["status"] == "degraded"
    assert analysis["classification"] == "unknown"
    assert analysis["subtitleMaskEnabled"] is True
    assert analysis["decision"]["effectiveAction"] == "mask_and_burn"
    assert "失败第 2 次" in analysis["reason"]


def test_auto_burns_without_mask_when_source_subtitles_are_absent(monkeypatch):
    _enable_multimodal(monkeypatch)
    monkeypatch.setattr(source_subtitle_service, "_extract_source_subtitle_frames", lambda *_args: _frames())
    monkeypatch.setattr(
        source_subtitle_service,
        "call_json_contract",
        lambda **_kwargs: ({"classification": "none", "reason": "未发现原视频对白字幕"}, {}, {}),
    )

    analysis, _usage = source_subtitle_service.analyze_source_subtitles(
        {"subtitleMode": "auto"}, "source.mp4", 60,
    )

    assert analysis["burnSubtitles"] is True
    assert analysis["subtitleMaskEnabled"] is False
    assert analysis["decision"]["effectiveAction"] == "burn"


def test_auto_keeps_chinese_source_subtitles(monkeypatch):
    _enable_multimodal(monkeypatch)
    monkeypatch.setattr(source_subtitle_service, "_extract_source_subtitle_frames", lambda *_args: _frames())
    monkeypatch.setattr(
        source_subtitle_service,
        "call_json_contract",
        lambda **_kwargs: ({"classification": "zh", "reason": "原视频已经是中文字幕"}, {}, {}),
    )

    analysis, _usage = source_subtitle_service.analyze_source_subtitles(
        {"subtitleMode": "auto"}, "source.mp4", 60,
    )

    assert analysis["burnSubtitles"] is False
    assert analysis["subtitleMaskEnabled"] is False
    assert analysis["decision"]["effectiveAction"] == "original_zh"


def test_auto_degrades_to_burn_without_mask(monkeypatch):
    _enable_multimodal(monkeypatch)
    monkeypatch.setattr(source_subtitle_service, "get_llm_config_status", lambda: {"multimodal": {"ready": False}})

    analysis, _usage = source_subtitle_service.analyze_source_subtitles(
        {"id": "job-1", "subtitleMode": "auto"}, "source.mp4", 60,
    )

    assert analysis["status"] == "degraded"
    assert analysis["classification"] == "unknown"
    assert analysis["burnSubtitles"] is True
    assert analysis["subtitleMaskEnabled"] is True
    assert analysis["decision"]["effectiveAction"] == "mask_and_burn"


def test_force_burn_and_original_skip_llm(monkeypatch):
    monkeypatch.setattr(
        source_subtitle_service,
        "call_json_contract",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("LLM must not be called")),
    )

    forced, _ = source_subtitle_service.analyze_source_subtitles(
        {"subtitleMode": "force_burn", "subtitleMaskEnabled": True}, "source.mp4", 60,
    )
    original, _ = source_subtitle_service.analyze_source_subtitles(
        {"subtitleMode": "original", "subtitleMaskEnabled": True}, "source.mp4", 60,
    )

    assert forced["status"] == "skipped"
    assert forced["decision"]["effectiveAction"] == "mask_and_burn"
    assert original["status"] == "skipped"
    assert original["decision"]["effectiveAction"] == "original"


def test_legacy_keeps_existing_processing_flags(monkeypatch):
    monkeypatch.setattr(
        source_subtitle_service,
        "call_json_contract",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("LLM must not be called")),
    )

    analysis, _ = source_subtitle_service.analyze_source_subtitles(
        {"subtitleMode": "legacy", "translationEnabled": True, "subtitleMaskEnabled": True},
        "source.mp4",
        60,
    )

    assert analysis["burnSubtitles"] is True
    assert analysis["subtitleMaskEnabled"] is True
    assert analysis["decision"] is None


def test_source_subtitle_contract_requires_known_classification():
    assert source_subtitle_service.validate_source_subtitle_result({
        "classification": "zh",
        "reason": "原视频已经是中文字幕",
    })["classification"] == "zh"

    try:
        source_subtitle_service.validate_source_subtitle_result({
            "classification": "other",
            "reason": "无效组合",
        })
    except ValueError as exc:
        assert "classification" in str(exc)
    else:
        raise AssertionError("unknown classification must be rejected")

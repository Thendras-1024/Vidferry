from app.core.error_catalog import classify_workflow_exception


def test_video_encoder_configuration_error_is_not_hidden_by_subtitle_burn_wrapper():
    error = RuntimeError("SUBTITLE_BURN_FAILED: RUNTIME_CONFIG_FAILED:VIDEO_ENCODER: NVENC unavailable")

    result = classify_workflow_exception(error)

    assert result["error_code"] == "VF-VIDEO-ENCODER-CONFIG"

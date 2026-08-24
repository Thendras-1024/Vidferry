from app.backend.runtime import create_backend_module


def test_task_center_never_uses_publish_title_as_original_title_translation():
    backend = create_backend_module()
    item = backend._task_item(
        {
            "id": "job-1",
            "video_id": "video-1",
            "title": "My Parents came to USE the Hospital in China",
            "status": "success",
            "step": "done",
            "progress": 100,
        },
        [],
        [{"publish_title": "英国父亲看病等"}],
    )

    assert item["chineseTitle"] == ""
    assert item["englishTitle"] == "My Parents came to USE the Hospital in China"


def test_processing_settings_snapshot_excludes_publish_accounts():
    backend = create_backend_module()
    snapshot = backend._processing_settings_snapshot({
        "processVersion": "editing_v1",
        "subtitleLanguage": "zh-CN",
        "burnProfile": "stable",
        "subtitleSize": "large",
        "translatorLabel": "Vidferry",
        "translationEnabled": True,
        "watermarkEnabled": True,
        "watermarkText": "Vidferry",
        "highlightIntroEnabled": True,
        "highlightCount": 3,
        "coverIntroEnabled": True,
        "coverTitle": "封面标题",
        "coverSignature": "Vidferry",
        "commentBurnEnabled": True,
        "commentBurnCount": 20,
        "commentTranslationMode": "google",
        "contentSafetyReviewEnabled": True,
        "account": "douyin-account",
        "publishToDouyin": 1,
    })

    assert snapshot["commentBurnCount"] == 20
    assert snapshot["contentSafetyReviewEnabled"] is True
    assert "account" not in snapshot
    assert "publishToDouyin" not in snapshot


def test_cover_reburn_operation_is_distinct_from_intro_refresh():
    backend = create_backend_module()

    assert backend._is_cover_reburn({"operation": "cover_reburn"}) is True
    assert backend._is_cover_reburn({"operation": "intro_refresh"}) is False

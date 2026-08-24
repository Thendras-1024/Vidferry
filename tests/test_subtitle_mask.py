from pathlib import Path
import inspect
from contextlib import contextmanager

from app.backend.runtime import create_backend_module
from app.core.source_subtitle_service import (
    resolve_source_subtitle_decision,
    validate_source_subtitle_result,
)


def test_subtitle_mask_defaults_and_job_snapshot():
    backend = create_backend_module()

    assert backend._normalize_workflow_settings({})["subtitleMode"] == "auto"
    assert backend._normalize_workflow_settings({})["subtitleMaskEnabled"] is False
    job = backend._row_to_workflow_job({
        "subtitle_mask_enabled": 1,
        "subtitle_mode": "auto",
        "source_subtitle_analysis": (
            '{"analysisVersion":2,"burnSubtitles":true,"subtitleMaskEnabled":true,'
            '"reason":"原字幕干扰阅读"}'
        ),
    })
    assert job["subtitleMaskEnabled"] is True
    assert job["subtitleMode"] == "auto"
    assert job["sourceSubtitleAnalysis"]["burnSubtitles"] is True
    snapshot = backend._processing_settings_snapshot(job)
    assert snapshot["subtitleMaskEnabled"] is True
    assert snapshot["sourceSubtitleAnalysis"]["subtitleMaskEnabled"] is True


def test_subtitle_mask_is_even_and_precedes_ass_subtitles():
    backend = create_backend_module()

    for width, height in ((1920, 1080), (1080, 1920)):
        x, y, mask_width, mask_height, pixel_width, pixel_height = backend._subtitle_mask_geometry(width, height)
        assert (x, y, mask_width, mask_height, pixel_width, pixel_height) == tuple(
            value // 2 * 2 for value in (x, y, mask_width, mask_height, pixel_width, pixel_height)
        )
        assert abs(mask_width - width * 0.88) <= 2
        assert x == (width - mask_width) // 2
        assert mask_height == int(height * 0.155) // 2 * 2

    assert backend._subtitle_mask_geometry(1920, 1080)[:4] == (116, 906, 1688, 166)

    filter_graph = backend._subtitle_mask_filter("input", "masked", 1920, 1080)
    assert "scale=" in filter_graph
    assert "gblur=sigma=" in filter_graph
    assert "colorchannelmixer" not in filter_graph
    assert "overlay=" in filter_graph

    intro_source = inspect.getsource(backend.render_editing_intro_assets)
    assert intro_source.index("_subtitle_mask_filter") < intro_source.index("overlay_filters")

    migration = Path("app/db/migrations/postgresql/V017__subtitle_mask.sql").read_text(encoding="utf-8")
    assert "subtitle_mask_enabled" in migration
    source_migration = Path("app/db/migrations/postgresql/V019__source_subtitle_analysis.sql").read_text(encoding="utf-8")
    assert "subtitle_mode" in source_migration
    assert "source_subtitle_analysis" in source_migration


def test_source_subtitle_contract_and_fixed_mask_decisions():
    result = validate_source_subtitle_result({
        "classification": "non_zh",
        "reason": "原字幕干扰阅读",
    })
    assert result["classification"] == "non_zh"
    assert resolve_source_subtitle_decision("auto", "non_zh", True)["effectiveAction"] == "mask_and_burn"
    assert resolve_source_subtitle_decision("auto", "zh", True)["effectiveAction"] == "original_zh"
    assert resolve_source_subtitle_decision("auto", "unknown")["effectiveAction"] == "mask_and_burn"
    assert resolve_source_subtitle_decision("force_burn", requested_mask=True)["subtitleMaskEnabled"] is True
    assert resolve_source_subtitle_decision("original")["translationEnabled"] is False


def test_source_subtitle_degradation_notifies_once_per_workflow_job(monkeypatch, tmp_path):
    backend = create_backend_module("test_source_subtitle_degradation_notification_backend")
    job = {
        "id": "source-subtitle-job",
        "videoId": "source-subtitle-video",
        "ownerUserId": 7,
        "title": "测试视频",
        "subtitleMode": "auto",
        "subtitleMaskEnabled": True,
    }
    analysis = {
        "analysisVersion": 2,
        "status": "degraded",
        "burnSubtitles": True,
        "subtitleMaskEnabled": False,
        "reason": "RuntimeError: 多模态模型接口不可用",
        "decision": {"translationEnabled": True, "subtitleMaskEnabled": False, "effectiveAction": "burn"},
    }
    notifications = []

    monkeypatch.setattr(backend, "start_workflow_event", lambda *_args, **_kwargs: "event-1")
    monkeypatch.setattr(backend, "_get_video_info", lambda *_args: {"duration": 1})
    monkeypatch.setattr(backend, "analyze_source_subtitles", lambda *_args: (analysis, {}))
    monkeypatch.setattr(backend, "build_workflow_llm_telemetry", lambda *_args: {})
    monkeypatch.setattr(backend, "update_youtube_workflow_job", lambda _job_id, **changes: {**job, **changes})
    monkeypatch.setattr(backend, "finish_workflow_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        backend,
        "_sync_notification_issues",
        lambda issues, owner_user_id, **_kwargs: notifications.extend((owner_user_id, issue) for issue in issues),
    )

    backend._resolve_source_subtitle_processing(job, tmp_path / "source.mp4")

    assert notifications == [
        (7, {
            "type": "source-subtitle-degraded",
            "severity": "warning",
            "aggregateKey": "source-subtitle-degraded:source-subtitle-job",
            "title": "原视频字幕识别已降级",
            "content": "测试视频：RuntimeError: 多模态模型接口不可用",
            "actionRoute": {"path": "/youtube-research", "query": {"focusJob": "source-subtitle-job", "focusAction": "error"}},
            "sourceRefs": [{"id": "source-subtitle-job", "title": "测试视频", "reason": "RuntimeError: 多模态模型接口不可用"}],
        }),
    ]


def test_old_auto_subtitle_analysis_is_rechecked(monkeypatch, tmp_path):
    backend = create_backend_module("test_source_subtitle_analysis_recheck_backend")
    job = {
        "id": "source-subtitle-job",
        "videoId": "source-subtitle-video",
        "subtitleMode": "auto",
        "subtitleMaskEnabled": True,
        "translationEnabled": True,
        "sourceSubtitleAnalysis": {
            "analysisVersion": 2,
            "decision": {"translationEnabled": True, "subtitleMaskEnabled": True},
        },
    }
    rechecked = []
    new_analysis = {
        "analysisVersion": 2,
        "status": "success",
        "burnSubtitles": False,
        "subtitleMaskEnabled": False,
        "reason": "保留原字幕",
        "decision": {"translationEnabled": False, "subtitleMaskEnabled": False, "effectiveAction": "original"},
    }

    monkeypatch.setattr(backend, "start_workflow_event", lambda *_args, **_kwargs: "event-1")
    monkeypatch.setattr(backend, "_get_video_info", lambda *_args: {"duration": 1})
    def analyze(*_args):
        rechecked.append(True)
        return new_analysis, {}

    monkeypatch.setattr(backend, "analyze_source_subtitles", analyze)
    monkeypatch.setattr(backend, "build_workflow_llm_telemetry", lambda *_args: {})
    monkeypatch.setattr(backend, "update_youtube_workflow_job", lambda _job_id, **changes: {**job, **changes})
    monkeypatch.setattr(backend, "finish_workflow_event", lambda *_args, **_kwargs: None)

    updated = backend._resolve_source_subtitle_processing(job, tmp_path / "source.mp4")

    assert rechecked == [True]
    assert updated["translation_enabled"] == 0
    assert updated["subtitle_mask_enabled"] == 0
    assert updated["source_subtitle_analysis"] == new_analysis


def test_new_workflow_job_insert_includes_auto_subtitle_snapshot(monkeypatch):
    backend = create_backend_module()
    inserted = {}

    class Cursor:
        rowcount = 1

        def execute(self, sql, params=()):
            if "INSERT INTO youtube_workflow_jobs" in sql:
                assert sql.count("%s") == len(params)
                inserted["sql"] = sql
                inserted["params"] = params
            return self

        def fetchone(self):
            return None

    class Connection:
        row_factory = None

        def cursor(self):
            return Cursor()

        def commit(self):
            pass

    @contextmanager
    def connect():
        yield Connection()

    monkeypatch.setattr(backend, "_db_connect", connect)
    monkeypatch.setattr(backend, "init_youtube_workflow_table", lambda: None)
    monkeypatch.setattr(backend, "get_workflow_settings", lambda owner_user_id: backend._default_workflow_settings())
    monkeypatch.setattr(backend, "resolve_publish_account_group", lambda _value: None)
    monkeypatch.setattr(backend, "get_youtube_workflow_job", lambda job_id: {"id": job_id, "subtitleMode": "auto"})

    job = backend.create_youtube_workflow_job({"url": "https://www.youtube.com/watch?v=abcdefghijk", "ownerUserId": 1})

    assert job["subtitleMode"] == "auto"
    assert "subtitle_mode" in inserted["sql"]
    assert "source_subtitle_analysis" in inserted["sql"]


def test_masked_body_never_reuses_legacy_unmasked_output():
    backend = create_backend_module()
    job = {"translationEnabled": False, "subtitleMaskEnabled": False}
    record = {"editingBodySignature": backend.editing_legacy_body_signature(job)}

    assert backend._editing_body_signature_compatible(record, job, None) is True
    assert backend._editing_body_signature_compatible(record, {**job, "subtitleMaskEnabled": True}, None) is False

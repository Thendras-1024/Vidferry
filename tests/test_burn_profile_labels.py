from pathlib import Path


def test_burn_profile_labels_describe_resolution_and_quality():
    research = Path("sau_frontend/src/views/YoutubeResearch.vue").read_text(encoding="utf-8")
    settings = Path("sau_frontend/src/views/ProcessingSettings.vue").read_text(encoding="utf-8")
    materials = Path("sau_frontend/src/views/MaterialManagement.vue").read_text(encoding="utf-8")
    workflow = Path("app/core/workflow.py").read_text(encoding="utf-8")

    for label in ("标准 1080p（推荐）", "快速 1080p", "2K 高画质（需 2K 原片）"):
        assert label in research
        assert label in settings
    assert "'2k': '2K 高画质（需 2K 原片）'" in materials
    assert "2K 高画质（需 2K 原片）仅支持原视频" in workflow

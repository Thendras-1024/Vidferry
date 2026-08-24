from pathlib import Path


def test_custom_topic_field_omits_the_platform_scope_hint():
    source = (
        Path(__file__).resolve().parents[1]
        / "sau_frontend/src/views/YoutubeResearch.vue"
    ).read_text(encoding="utf-8")

    assert "仅追加到当前视频的所有发布平台" not in source

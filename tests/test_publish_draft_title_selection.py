from pathlib import Path


def test_custom_publish_title_option_displays_the_selected_title():
    source = (
        Path(__file__).resolve().parents[1]
        / "sau_frontend/src/views/YoutubeResearch.vue"
    ).read_text(encoding="utf-8")

    assert ':label="publishDraftForm(row).selectedTitle || \'自定义标题\'"' in source
    assert '<el-option label="自定义标题" :value="CUSTOM_TITLE_VALUE" />' not in source

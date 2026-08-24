from pathlib import Path


def test_publish_center_analysis_button_sends_single_record_context():
    source = Path("sau_frontend/src/views/PublishCenter.vue").read_text(encoding="utf-8")
    assert "分析数据" in source
    assert "analyzePublishedRecord(video, record)" in source
    assert "publishRecordId: record.id" in source
    assert "只查询快手，不读取评论" in source


def test_agent_event_can_submit_the_contextual_prompt():
    source = Path("sau_frontend/src/composables/useAgentWorkspace.js").read_text(encoding="utf-8")
    assert "if (detail.message)" in source
    assert "await sendAgentMessage(detail.message" in source

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_publish_progress_is_visible_and_waiting_publish_is_polled():
    source = (ROOT / "sau_frontend/src/views/YoutubeResearch.vue").read_text(encoding="utf-8")
    assert "waiting_publish" in source
    assert "publishProgress" in source
    assert "workflowProgressText" in source


def test_task_history_defaults_to_all_tasks():
    source = (ROOT / "sau_frontend/src/views/TaskHistory.vue").read_text(encoding="utf-8")
    assert "route.query.status || 'all'" in source


def test_task_center_acknowledges_all_problem_statuses():
    source = (ROOT / "sau_frontend/src/components/TaskCenter.vue").read_text(encoding="utf-8")
    assert "item.canAcknowledge" in source
    assert "我知道了" in source


def test_youtube_detail_shows_platform_times_and_auto_subtitle_decision():
    source = (ROOT / "sau_frontend/src/views/YoutubeResearch.vue").read_text(encoding="utf-8")
    assert "target.publishedAt" in source
    assert "formatDetailTime(target.publishedAt)" in source
    assert "youtubeApi.listWorkflowJobs" in source
    assert "sourceSubtitleAnalysis" in source
    assert "烧制字幕 + 启用遮罩" in source


def test_publish_center_renders_delivery_states_and_refreshes_server_notifications():
    source = (ROOT / "sau_frontend/src/views/PublishCenter.vue").read_text(encoding="utf-8")

    assert "reused: '复用已发布结果'" in source
    assert "waiting_existing: '等待已有任务'" in source
    assert "uncertain: '待核验'" in source
    assert "await notificationStore.refresh()" in source
    assert "addDirectPublishFailureMessage" in source
    assert "'waiting_existing'" in source


def test_publish_center_clears_stale_material_selection_after_publish_rejection():
    source = (ROOT / "sau_frontend/src/views/PublishCenter.vue").read_text(encoding="utf-8")

    assert "const isUnavailablePublishMaterialError" in source
    assert "tab.fileList = []" in source
    assert "该素材已失效，已从当前批次移除，请重新选择处理后视频" in source
    assert "if (unavailableMaterial) clearUnavailablePublishMaterial(tab)" in source
    assert "if (!unavailableMaterial)" in source


def test_task_detail_renders_reused_and_uncertain_publish_targets():
    service = (ROOT / "app/core/task_center_service.py").read_text(encoding="utf-8")
    dialog = (ROOT / "sau_frontend/src/components/TaskFlowDialog.vue").read_text(encoding="utf-8")

    assert '"needs_verification"' in service
    assert "node-reused" in dialog
    assert "node-needs_verification" in dialog


def test_task_detail_renders_retry_publish_edge_labels():
    service = (ROOT / "app/core/task_center_service.py").read_text(encoding="utf-8")
    dialog = (ROOT / "sau_frontend/src/components/TaskFlowDialog.vue").read_text(encoding="utf-8")

    assert '"label": "重试发布"' in service
    assert "flow-edge-label" in dialog
    assert "edgeLabelPosition" in dialog


def test_notification_center_uses_target_level_publish_issues_without_workflow_duplicates():
    service = (ROOT / "app/core/notification_service.py").read_text(encoding="utf-8")

    assert "publish-target-uncertain" in service
    assert "publish-target-failed" in service
    assert "status IN ('failed', 'abnormal', 'waiting_confirmation')" in service


def test_web_video_uploaders_wait_five_seconds_before_first_upload():
    uploaders = {
        "douyin": (ROOT / "uploader/douyin_uploader/main.py").read_text(encoding="utf-8"),
        "xiaohongshu": (ROOT / "uploader/xiaohongshu_uploader/main.py").read_text(encoding="utf-8"),
        "kuaishou": (ROOT / "uploader/ks_uploader/main.py").read_text(encoding="utf-8"),
        "tencent": (ROOT / "uploader/tencent_uploader/main.py").read_text(encoding="utf-8"),
    }

    assert "await asyncio.sleep(5)\n            await self.set_video_file_for_upload(page)" in uploaders["douyin"]
    assert "await asyncio.sleep(5)\n        await self.set_upload_files(page.locator" in uploaders["xiaohongshu"]
    assert "await asyncio.sleep(5)\n\n            upload_button = page.locator" in uploaders["kuaishou"]
    assert "await self.wait_for_upload_page_ready()\n            await self.upload_video_file(page, self.file_path)" in uploaders["tencent"]


def test_douyin_description_is_written_before_tags():
    source = (ROOT / "uploader/douyin_uploader/main.py").read_text(encoding="utf-8")
    start = source.index("    async def fill_title_and_description")
    end = source.index("\n    async def set_location", start)
    method = source[start:end]

    assert "await page.keyboard.type(description)" in method
    assert method.index("await page.keyboard.type(description)") < method.index("for tag in tags or []")

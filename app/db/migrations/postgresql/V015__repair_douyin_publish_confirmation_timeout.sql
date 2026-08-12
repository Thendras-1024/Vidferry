-- A previous workflow version marked uploads as failed after reaching Douyin's
-- content-management page without receiving a success banner within 180s.
-- The platform may still be processing the submission, so retain a blocking
-- unknown record until an operator verifies it instead of allowing a duplicate.
UPDATE published_youtube_materials
SET status = 'unknown',
    message = '平台已接收发布请求，但未在等待期内确认最终状态。请先到抖音作品管理页核验，系统已阻止自动重发以避免重复投稿。',
    updated_at = CURRENT_TIMESTAMP
WHERE platform_type = 3
  AND status IN ('failed', 'timeout')
  AND message LIKE 'VF-PUBLISH-CONFIRM-TIMEOUT: 已进入作品管理页%';

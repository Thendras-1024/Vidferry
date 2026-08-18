UPDATE publish_dispatch_targets AS target
SET status = CASE record.status
        WHEN 'confirmed' THEN 'confirmed'
        WHEN 'uncertain' THEN 'uncertain'
        WHEN 'failed' THEN 'failed'
        ELSE target.status
    END,
    message = COALESCE(NULLIF(record.message, ''), target.message),
    duration_ms = COALESCE(record.duration_ms, target.duration_ms),
    updated_at = CURRENT_TIMESTAMP
FROM published_youtube_materials AS record
WHERE record.publish_task_id = target.job_id
  AND record.platform_type = target.platform_type
  AND record.deleted_at IS NULL
  AND record.status IN ('confirmed', 'uncertain', 'failed');

UPDATE publish_dispatch_jobs AS job
SET status = CASE
    WHEN EXISTS (SELECT 1 FROM publish_dispatch_targets target WHERE target.job_id = job.id AND target.status = 'running') THEN 'running'
    WHEN EXISTS (SELECT 1 FROM publish_dispatch_targets target WHERE target.job_id = job.id AND target.status = 'queued') THEN 'queued'
    WHEN EXISTS (SELECT 1 FROM publish_dispatch_targets target WHERE target.job_id = job.id AND target.status = 'waiting_existing') THEN 'waiting_existing'
    WHEN EXISTS (SELECT 1 FROM publish_dispatch_targets target WHERE target.job_id = job.id AND target.status = 'uncertain') THEN 'uncertain'
    WHEN EXISTS (SELECT 1 FROM publish_dispatch_targets target WHERE target.job_id = job.id AND target.status IN ('failed', 'cancelled'))
         AND EXISTS (SELECT 1 FROM publish_dispatch_targets target WHERE target.job_id = job.id AND target.status IN ('confirmed', 'reused')) THEN 'partial'
    WHEN EXISTS (SELECT 1 FROM publish_dispatch_targets target WHERE target.job_id = job.id AND target.status IN ('failed', 'cancelled')) THEN 'failed'
    WHEN EXISTS (SELECT 1 FROM publish_dispatch_targets target WHERE target.job_id = job.id AND target.status = 'confirmed') THEN 'confirmed'
    ELSE 'reused'
END,
updated_at = CURRENT_TIMESTAMP
WHERE EXISTS (SELECT 1 FROM publish_dispatch_targets target WHERE target.job_id = job.id);

UPDATE scheduled_publish_tasks AS task
SET status = dispatch.status,
    message = COALESCE(NULLIF(dispatch.message, ''), task.message),
    updated_at = CURRENT_TIMESTAMP
FROM publish_dispatch_jobs AS dispatch
WHERE dispatch.source = 'scheduled'
  AND dispatch.source_ref_id = task.id;

UPDATE youtube_workflow_jobs AS workflow
SET status = CASE dispatch.status
        WHEN 'confirmed' THEN 'success'
        WHEN 'reused' THEN 'reused'
        WHEN 'waiting_existing' THEN 'waiting_publish'
        WHEN 'uncertain' THEN 'needs_verification'
        WHEN 'partial' THEN 'partial'
        WHEN 'failed' THEN 'failed'
        WHEN 'cancelled' THEN 'cancelled'
        ELSE workflow.status
    END,
    step = CASE WHEN dispatch.status IN ('confirmed', 'reused') THEN 'done' ELSE 'publish' END,
    message = COALESCE(NULLIF(dispatch.message, ''), workflow.message),
    updated_at = CURRENT_TIMESTAMP
FROM publish_dispatch_jobs AS dispatch
WHERE dispatch.source = 'workflow'
  AND dispatch.source_ref_id = workflow.id;

UPDATE youtube_videos AS video
SET publish_status = CASE WHEN EXISTS (
    SELECT 1
    FROM published_youtube_materials AS record
    WHERE record.video_id = video.video_id
      AND record.deleted_at IS NULL
      AND record.status = 'confirmed'
) THEN 1 ELSE 0 END;

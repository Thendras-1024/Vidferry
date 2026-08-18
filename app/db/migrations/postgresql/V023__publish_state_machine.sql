UPDATE published_youtube_materials
SET status = CASE status
    WHEN 'success' THEN 'confirmed'
    WHEN 'pending' THEN 'queued'
    WHEN 'unknown' THEN 'uncertain'
    WHEN 'canceled' THEN 'cancelled'
    WHEN 'timeout' THEN 'failed'
    ELSE status
END
WHERE status IN ('success', 'pending', 'unknown', 'canceled', 'timeout');

UPDATE publish_dispatch_targets AS target
SET status = CASE
    WHEN target.status = 'success' THEN 'confirmed'
    WHEN target.status = 'pending' THEN 'queued'
    WHEN target.status = 'unknown' THEN 'uncertain'
    WHEN target.status IN ('canceled', 'timeout') THEN CASE WHEN target.status = 'canceled' THEN 'cancelled' ELSE 'failed' END
    WHEN target.status = 'skipped' AND COALESCE(target.settings::jsonb ->> 'historyStatus', '') IN ('success', 'confirmed') THEN 'reused'
    WHEN target.status = 'skipped' AND COALESCE(target.settings::jsonb ->> 'historyStatus', '') IN ('unknown', 'uncertain') THEN 'uncertain'
    WHEN target.status = 'skipped' THEN 'waiting_existing'
    ELSE target.status
END
WHERE target.status IN ('success', 'pending', 'unknown', 'canceled', 'timeout', 'skipped');

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
END
WHERE EXISTS (SELECT 1 FROM publish_dispatch_targets target WHERE target.job_id = job.id);

UPDATE scheduled_publish_targets
SET status = CASE status
    WHEN 'success' THEN 'confirmed'
    WHEN 'pending' THEN 'queued'
    WHEN 'unknown' THEN 'uncertain'
    WHEN 'skipped' THEN 'reused'
    WHEN 'canceled' THEN 'cancelled'
    WHEN 'timeout' THEN 'failed'
    ELSE status
END
WHERE status IN ('success', 'pending', 'unknown', 'skipped', 'canceled', 'timeout');

UPDATE scheduled_publish_tasks
SET status = CASE status
    WHEN 'success' THEN 'confirmed'
    WHEN 'pending' THEN 'scheduled'
    WHEN 'unknown' THEN 'uncertain'
    WHEN 'skipped' THEN 'reused'
    WHEN 'canceled' THEN 'cancelled'
    ELSE status
END
WHERE status IN ('success', 'pending', 'unknown', 'skipped', 'canceled');

UPDATE scheduled_publish_tasks AS task
SET status = CASE dispatch.status
    WHEN 'confirmed' THEN 'confirmed'
    WHEN 'reused' THEN 'reused'
    WHEN 'waiting_existing' THEN 'waiting_existing'
    WHEN 'uncertain' THEN 'uncertain'
    WHEN 'partial' THEN 'partial'
    WHEN 'failed' THEN 'failed'
    ELSE task.status
END
FROM publish_dispatch_jobs AS dispatch
WHERE dispatch.source = 'scheduled'
  AND dispatch.source_ref_id = task.id
  AND dispatch.status IN ('confirmed', 'reused', 'waiting_existing', 'uncertain', 'partial', 'failed');

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
step = CASE WHEN dispatch.status IN ('confirmed', 'reused') THEN 'done' ELSE 'publish' END
FROM publish_dispatch_jobs AS dispatch
WHERE dispatch.source = 'workflow'
  AND dispatch.source_ref_id = workflow.id
  AND dispatch.status IN ('confirmed', 'reused', 'waiting_existing', 'uncertain', 'partial', 'failed', 'cancelled');

UPDATE youtube_videos AS video
SET publish_status = CASE WHEN EXISTS (
    SELECT 1
    FROM published_youtube_materials AS record
    WHERE record.video_id = video.video_id
      AND record.deleted_at IS NULL
      AND record.status = 'confirmed'
) THEN 1 ELSE 0 END;

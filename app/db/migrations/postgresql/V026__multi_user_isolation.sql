ALTER TABLE file_records ADD COLUMN IF NOT EXISTS owner_user_id BIGINT;
ALTER TABLE app_notifications ADD COLUMN IF NOT EXISTS owner_user_id BIGINT;
ALTER TABLE youtube_video_groups ADD COLUMN IF NOT EXISTS owner_user_id BIGINT;
ALTER TABLE youtube_videos ADD COLUMN IF NOT EXISTS owner_user_id BIGINT;
ALTER TABLE youtube_search_jobs ADD COLUMN IF NOT EXISTS owner_user_id BIGINT;
ALTER TABLE youtube_workflow_locks ADD COLUMN IF NOT EXISTS owner_user_id BIGINT;
ALTER TABLE youtube_workflow_events ADD COLUMN IF NOT EXISTS owner_user_id BIGINT;
ALTER TABLE youtube_workflow_llm_usage_events ADD COLUMN IF NOT EXISTS owner_user_id BIGINT;
ALTER TABLE youtube_subtitle_audits ADD COLUMN IF NOT EXISTS owner_user_id BIGINT;
ALTER TABLE youtube_content_safety_audits ADD COLUMN IF NOT EXISTS owner_user_id BIGINT;
ALTER TABLE published_youtube_materials ADD COLUMN IF NOT EXISTS owner_user_id BIGINT;
ALTER TABLE scheduled_publish_tasks ADD COLUMN IF NOT EXISTS owner_user_id BIGINT;
ALTER TABLE youtube_video_deletions ADD COLUMN IF NOT EXISTS owner_user_id BIGINT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM auth_users WHERE role = 'admin' AND status = 'active'
    ) AND (
        EXISTS (SELECT 1 FROM file_records WHERE owner_user_id IS NULL)
        OR EXISTS (SELECT 1 FROM app_notifications WHERE owner_user_id IS NULL)
        OR EXISTS (SELECT 1 FROM youtube_video_groups WHERE owner_user_id IS NULL)
        OR EXISTS (SELECT 1 FROM youtube_videos WHERE owner_user_id IS NULL)
        OR EXISTS (SELECT 1 FROM youtube_search_jobs WHERE owner_user_id IS NULL)
        OR EXISTS (SELECT 1 FROM youtube_workflow_jobs WHERE owner_user_id IS NULL)
        OR EXISTS (SELECT 1 FROM youtube_workflow_events WHERE owner_user_id IS NULL)
        OR EXISTS (SELECT 1 FROM youtube_workflow_llm_usage_events WHERE owner_user_id IS NULL)
        OR EXISTS (SELECT 1 FROM youtube_subtitle_audits WHERE owner_user_id IS NULL)
        OR EXISTS (SELECT 1 FROM youtube_content_safety_audits WHERE owner_user_id IS NULL)
        OR EXISTS (SELECT 1 FROM published_youtube_materials WHERE owner_user_id IS NULL)
        OR EXISTS (SELECT 1 FROM scheduled_publish_tasks WHERE owner_user_id IS NULL)
        OR EXISTS (SELECT 1 FROM youtube_video_deletions WHERE owner_user_id IS NULL)
        OR EXISTS (SELECT 1 FROM publish_dispatch_jobs WHERE owner_user_id IS NULL)
        OR EXISTS (SELECT 1 FROM user_info WHERE owner_user_id IS NULL)
        OR EXISTS (SELECT 1 FROM publish_account_groups WHERE owner_user_id IS NULL)
    ) THEN
        RAISE EXCEPTION 'V026 requires an active administrator before historical data can be assigned';
    END IF;
END $$;

UPDATE youtube_workflow_events event
SET owner_user_id = job.owner_user_id
FROM youtube_workflow_jobs job
WHERE event.job_id = job.id AND event.owner_user_id IS NULL;

UPDATE youtube_workflow_llm_usage_events usage
SET owner_user_id = job.owner_user_id
FROM youtube_workflow_jobs job
WHERE usage.job_id = job.id AND usage.owner_user_id IS NULL;

UPDATE youtube_subtitle_audits audit
SET owner_user_id = job.owner_user_id
FROM youtube_workflow_jobs job
WHERE audit.job_id = job.id AND audit.owner_user_id IS NULL;

UPDATE youtube_content_safety_audits audit
SET owner_user_id = job.owner_user_id
FROM youtube_workflow_jobs job
WHERE audit.job_id = job.id AND audit.owner_user_id IS NULL;

UPDATE file_records SET owner_user_id = (SELECT id FROM auth_users WHERE role = 'admin' AND status = 'active' ORDER BY created_at, id LIMIT 1) WHERE owner_user_id IS NULL;
UPDATE app_notifications SET owner_user_id = (SELECT id FROM auth_users WHERE role = 'admin' AND status = 'active' ORDER BY created_at, id LIMIT 1) WHERE owner_user_id IS NULL;
UPDATE youtube_video_groups SET owner_user_id = (SELECT id FROM auth_users WHERE role = 'admin' AND status = 'active' ORDER BY created_at, id LIMIT 1) WHERE owner_user_id IS NULL;
UPDATE youtube_videos SET owner_user_id = (SELECT id FROM auth_users WHERE role = 'admin' AND status = 'active' ORDER BY created_at, id LIMIT 1) WHERE owner_user_id IS NULL;
UPDATE youtube_search_jobs SET owner_user_id = (SELECT id FROM auth_users WHERE role = 'admin' AND status = 'active' ORDER BY created_at, id LIMIT 1) WHERE owner_user_id IS NULL;
UPDATE youtube_workflow_jobs SET owner_user_id = (SELECT id FROM auth_users WHERE role = 'admin' AND status = 'active' ORDER BY created_at, id LIMIT 1) WHERE owner_user_id IS NULL;
UPDATE youtube_workflow_locks SET owner_user_id = (SELECT owner_user_id FROM youtube_workflow_jobs WHERE id = youtube_workflow_locks.job_id) WHERE owner_user_id IS NULL;
UPDATE youtube_workflow_locks SET owner_user_id = (SELECT id FROM auth_users WHERE role = 'admin' AND status = 'active' ORDER BY created_at, id LIMIT 1) WHERE owner_user_id IS NULL;
UPDATE youtube_workflow_events SET owner_user_id = (SELECT id FROM auth_users WHERE role = 'admin' AND status = 'active' ORDER BY created_at, id LIMIT 1) WHERE owner_user_id IS NULL;
UPDATE youtube_workflow_llm_usage_events SET owner_user_id = (SELECT id FROM auth_users WHERE role = 'admin' AND status = 'active' ORDER BY created_at, id LIMIT 1) WHERE owner_user_id IS NULL;
UPDATE youtube_subtitle_audits SET owner_user_id = (SELECT id FROM auth_users WHERE role = 'admin' AND status = 'active' ORDER BY created_at, id LIMIT 1) WHERE owner_user_id IS NULL;
UPDATE youtube_content_safety_audits SET owner_user_id = (SELECT id FROM auth_users WHERE role = 'admin' AND status = 'active' ORDER BY created_at, id LIMIT 1) WHERE owner_user_id IS NULL;
UPDATE published_youtube_materials SET owner_user_id = (SELECT id FROM auth_users WHERE role = 'admin' AND status = 'active' ORDER BY created_at, id LIMIT 1) WHERE owner_user_id IS NULL;
UPDATE scheduled_publish_tasks SET owner_user_id = (SELECT id FROM auth_users WHERE role = 'admin' AND status = 'active' ORDER BY created_at, id LIMIT 1) WHERE owner_user_id IS NULL;
UPDATE youtube_video_deletions SET owner_user_id = (SELECT id FROM auth_users WHERE role = 'admin' AND status = 'active' ORDER BY created_at, id LIMIT 1) WHERE owner_user_id IS NULL;
UPDATE publish_dispatch_jobs SET owner_user_id = (SELECT id FROM auth_users WHERE role = 'admin' AND status = 'active' ORDER BY created_at, id LIMIT 1) WHERE owner_user_id IS NULL;
UPDATE user_info SET owner_user_id = (SELECT id FROM auth_users WHERE role = 'admin' AND status = 'active' ORDER BY created_at, id LIMIT 1) WHERE owner_user_id IS NULL;
UPDATE publish_account_groups SET owner_user_id = (SELECT id FROM auth_users WHERE role = 'admin' AND status = 'active' ORDER BY created_at, id LIMIT 1) WHERE owner_user_id IS NULL;

ALTER TABLE file_records ALTER COLUMN owner_user_id SET NOT NULL;
ALTER TABLE app_notifications ALTER COLUMN owner_user_id SET NOT NULL;
ALTER TABLE youtube_video_groups ALTER COLUMN owner_user_id SET NOT NULL;
ALTER TABLE youtube_videos ALTER COLUMN owner_user_id SET NOT NULL;
ALTER TABLE youtube_search_jobs ALTER COLUMN owner_user_id SET NOT NULL;
ALTER TABLE youtube_workflow_jobs ALTER COLUMN owner_user_id SET NOT NULL;
ALTER TABLE youtube_workflow_locks ALTER COLUMN owner_user_id SET NOT NULL;
ALTER TABLE youtube_workflow_events ALTER COLUMN owner_user_id SET NOT NULL;
ALTER TABLE youtube_workflow_llm_usage_events ALTER COLUMN owner_user_id SET NOT NULL;
ALTER TABLE youtube_subtitle_audits ALTER COLUMN owner_user_id SET NOT NULL;
ALTER TABLE youtube_content_safety_audits ALTER COLUMN owner_user_id SET NOT NULL;
ALTER TABLE published_youtube_materials ALTER COLUMN owner_user_id SET NOT NULL;
ALTER TABLE scheduled_publish_tasks ALTER COLUMN owner_user_id SET NOT NULL;
ALTER TABLE youtube_video_deletions ALTER COLUMN owner_user_id SET NOT NULL;
ALTER TABLE publish_dispatch_jobs ALTER COLUMN owner_user_id SET NOT NULL;
ALTER TABLE user_info ALTER COLUMN owner_user_id SET NOT NULL;
ALTER TABLE publish_account_groups ALTER COLUMN owner_user_id SET NOT NULL;

ALTER TABLE youtube_videos DROP CONSTRAINT IF EXISTS youtube_videos_video_id_key;
ALTER TABLE youtube_videos ADD CONSTRAINT uq_youtube_videos_owner_video UNIQUE (owner_user_id, video_id);
ALTER TABLE youtube_video_groups DROP CONSTRAINT IF EXISTS youtube_video_groups_name_key;
DROP INDEX IF EXISTS idx_youtube_video_groups_name_ci;
DROP INDEX IF EXISTS idx_youtube_video_groups_default;
CREATE UNIQUE INDEX IF NOT EXISTS idx_youtube_video_groups_owner_name ON youtube_video_groups (owner_user_id, LOWER(name));
CREATE UNIQUE INDEX IF NOT EXISTS idx_youtube_video_groups_default ON youtube_video_groups (owner_user_id) WHERE is_default = 1;

ALTER TABLE youtube_video_deletions DROP CONSTRAINT IF EXISTS youtube_video_deletions_pkey;
ALTER TABLE youtube_video_deletions ADD PRIMARY KEY (owner_user_id, video_id);
ALTER TABLE youtube_workflow_locks DROP CONSTRAINT IF EXISTS youtube_workflow_locks_pkey;
ALTER TABLE youtube_workflow_locks ADD PRIMARY KEY (owner_user_id, video_id, scope);

ALTER TABLE app_notifications DROP CONSTRAINT IF EXISTS app_notifications_aggregate_key_key;
ALTER TABLE app_notifications ADD CONSTRAINT uq_app_notifications_owner_key UNIQUE (owner_user_id, aggregate_key);

DROP INDEX IF EXISTS idx_published_youtube_materials_video_platform;
CREATE UNIQUE INDEX IF NOT EXISTS idx_published_youtube_materials_video_platform
    ON published_youtube_materials(owner_user_id, video_id, platform_type)
    WHERE video_id IS NOT NULL AND video_id != '' AND platform_type IS NOT NULL AND platform_type != 0 AND deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_file_records_owner_created ON file_records(owner_user_id, upload_time DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_youtube_videos_owner_created ON youtube_videos(owner_user_id, created_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_youtube_search_jobs_owner_created ON youtube_search_jobs(owner_user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_published_materials_owner_updated ON published_youtube_materials(owner_user_id, updated_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_scheduled_publish_tasks_owner_due ON scheduled_publish_tasks(owner_user_id, status, scheduled_at);
CREATE INDEX IF NOT EXISTS idx_app_notifications_owner_updated ON app_notifications(owner_user_id, updated_at DESC, id DESC);

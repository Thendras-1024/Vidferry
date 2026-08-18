ALTER TABLE youtube_workflow_jobs
    ADD COLUMN IF NOT EXISTS owner_user_id BIGINT;

CREATE INDEX IF NOT EXISTS idx_youtube_workflow_jobs_owner
    ON youtube_workflow_jobs (owner_user_id, updated_at DESC, created_at DESC);

DROP INDEX IF EXISTS idx_publish_account_groups_name_lower;

CREATE UNIQUE INDEX IF NOT EXISTS idx_publish_account_groups_owner_name_lower
    ON publish_account_groups (owner_user_id, LOWER(name));

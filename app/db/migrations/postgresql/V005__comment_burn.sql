ALTER TABLE youtube_workflow_jobs
    ADD COLUMN IF NOT EXISTS comment_burn_enabled INTEGER NOT NULL DEFAULT 0;

ALTER TABLE youtube_videos
    ADD COLUMN IF NOT EXISTS comment_burn_snapshot TEXT DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS comment_burn_signature TEXT DEFAULT '',
    ADD COLUMN IF NOT EXISTS comment_burn_status TEXT DEFAULT '';

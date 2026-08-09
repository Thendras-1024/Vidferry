ALTER TABLE youtube_workflow_jobs
    ADD COLUMN IF NOT EXISTS comment_burn_count INTEGER NOT NULL DEFAULT 30;

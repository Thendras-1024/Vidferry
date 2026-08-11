ALTER TABLE youtube_workflow_jobs
    ADD COLUMN IF NOT EXISTS subtitle_mask_enabled INTEGER NOT NULL DEFAULT 0;

ALTER TABLE youtube_workflow_jobs
    ADD COLUMN IF NOT EXISTS subtitle_mode TEXT NOT NULL DEFAULT 'legacy';

ALTER TABLE youtube_workflow_jobs
    ADD COLUMN IF NOT EXISTS source_subtitle_analysis TEXT DEFAULT '{}';

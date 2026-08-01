ALTER TABLE youtube_workflow_jobs
    ADD COLUMN IF NOT EXISTS translation_enabled INTEGER NOT NULL DEFAULT 1;

ALTER TABLE youtube_workflow_jobs
    ADD COLUMN IF NOT EXISTS highlight_intro_enabled INTEGER NOT NULL DEFAULT 1;

ALTER TABLE youtube_workflow_jobs
    ADD COLUMN IF NOT EXISTS cover_intro_enabled INTEGER NOT NULL DEFAULT 1;

ALTER TABLE youtube_workflow_jobs
    ADD COLUMN IF NOT EXISTS operation TEXT NOT NULL DEFAULT 'process';

ALTER TABLE youtube_workflow_jobs
    ADD COLUMN IF NOT EXISTS comment_translation_mode TEXT NOT NULL DEFAULT 'google_llm';

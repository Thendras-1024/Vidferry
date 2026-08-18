-- Repair the candidate analysis table after migration version collisions.
CREATE TABLE IF NOT EXISTS candidate_analysis_jobs (
    id TEXT PRIMARY KEY,
    session_id TEXT,
    video_id TEXT NOT NULL,
    source_url TEXT NOT NULL,
    title TEXT,
    channel TEXT,
    metadata_snapshot TEXT NOT NULL DEFAULT '{}',
    analysis_version TEXT NOT NULL DEFAULT 'candidate-v1',
    status TEXT NOT NULL,
    step TEXT NOT NULL DEFAULT 'queued',
    message TEXT,
    progress DOUBLE PRECISION NOT NULL DEFAULT 0,
    transcript_file_path TEXT,
    result TEXT NOT NULL DEFAULT '{}',
    error_reason TEXT,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP WITHOUT TIME ZONE,
    finished_at TIMESTAMP WITHOUT TIME ZONE,
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_candidate_analysis_jobs_video_status
    ON candidate_analysis_jobs (video_id, status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_candidate_analysis_jobs_session
    ON candidate_analysis_jobs (session_id, created_at DESC);

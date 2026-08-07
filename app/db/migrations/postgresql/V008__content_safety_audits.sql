CREATE TABLE IF NOT EXISTS youtube_content_safety_audits (
    job_id TEXT PRIMARY KEY,
    video_id TEXT,
    video_title TEXT,
    snapshot TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending',
    saved_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_content_safety_audits_video_saved
    ON youtube_content_safety_audits(video_id, saved_at DESC);

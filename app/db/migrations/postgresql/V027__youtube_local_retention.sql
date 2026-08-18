ALTER TABLE youtube_videos ADD COLUMN IF NOT EXISTS local_files_state TEXT NOT NULL DEFAULT 'available';
ALTER TABLE youtube_videos ADD COLUMN IF NOT EXISTS retention_anchor_at TIMESTAMPTZ;
ALTER TABLE youtube_videos ADD COLUMN IF NOT EXISTS local_files_purged_at TIMESTAMPTZ;
ALTER TABLE youtube_videos ADD COLUMN IF NOT EXISTS purge_attempted_at TIMESTAMPTZ;
ALTER TABLE youtube_videos ADD COLUMN IF NOT EXISTS purge_error TEXT;

ALTER TABLE file_records ADD COLUMN IF NOT EXISTS purged_at TIMESTAMPTZ;

ALTER TABLE published_youtube_materials ADD COLUMN IF NOT EXISTS invalidated_at TIMESTAMPTZ;
ALTER TABLE published_youtube_materials ADD COLUMN IF NOT EXISTS invalidated_by_user_id BIGINT;
ALTER TABLE published_youtube_materials ADD COLUMN IF NOT EXISTS invalidation_reason TEXT;

ALTER TABLE youtube_videos DROP CONSTRAINT IF EXISTS chk_youtube_videos_local_files_state;
ALTER TABLE youtube_videos ADD CONSTRAINT chk_youtube_videos_local_files_state
    CHECK (local_files_state IN ('available', 'purging', 'purged', 'purge_failed'));

DROP INDEX IF EXISTS idx_published_youtube_materials_video_platform;
CREATE UNIQUE INDEX IF NOT EXISTS idx_published_youtube_materials_video_platform_account
    ON published_youtube_materials(owner_user_id, video_id, platform_type, COALESCE(account_id, 0))
    WHERE video_id IS NOT NULL AND video_id != ''
      AND platform_type IS NOT NULL AND platform_type != 0
      AND deleted_at IS NULL AND invalidated_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_youtube_videos_local_retention
    ON youtube_videos(owner_user_id, local_files_state, retention_anchor_at);
CREATE INDEX IF NOT EXISTS idx_file_records_owner_video_status
    ON file_records(owner_user_id, source_video_id, status);

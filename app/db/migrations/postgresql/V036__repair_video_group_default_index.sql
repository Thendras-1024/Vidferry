-- V034 may already have created a same-named global default index.
DROP INDEX IF EXISTS idx_youtube_video_groups_default;

CREATE UNIQUE INDEX idx_youtube_video_groups_default
    ON youtube_video_groups (owner_user_id)
    WHERE is_default = 1;

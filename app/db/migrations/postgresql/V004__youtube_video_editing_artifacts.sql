ALTER TABLE youtube_videos
    ADD COLUMN IF NOT EXISTS editing_body_path TEXT DEFAULT '',
    ADD COLUMN IF NOT EXISTS editing_ass_path TEXT DEFAULT '',
    ADD COLUMN IF NOT EXISTS editing_body_signature TEXT DEFAULT '',
    ADD COLUMN IF NOT EXISTS editing_intro_signature TEXT DEFAULT '',
    ADD COLUMN IF NOT EXISTS editing_highlight_snapshot TEXT DEFAULT '[]',
    ADD COLUMN IF NOT EXISTS editing_intro_status TEXT DEFAULT '';

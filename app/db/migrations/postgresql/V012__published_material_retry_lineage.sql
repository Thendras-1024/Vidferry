ALTER TABLE published_youtube_materials
    ADD COLUMN IF NOT EXISTS retry_of_task_id TEXT DEFAULT '';

ALTER TABLE published_youtube_materials
    ADD COLUMN IF NOT EXISTS retry_of_record_id BIGINT;

ALTER TABLE published_youtube_materials
    ADD COLUMN IF NOT EXISTS retry_source TEXT DEFAULT '';

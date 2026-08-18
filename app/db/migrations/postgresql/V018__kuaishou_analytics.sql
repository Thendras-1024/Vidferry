ALTER TABLE published_youtube_materials
    ADD COLUMN IF NOT EXISTS account_id BIGINT REFERENCES user_info(id) ON DELETE SET NULL;

ALTER TABLE published_youtube_materials
    ADD COLUMN IF NOT EXISTS platform_work_id TEXT;

ALTER TABLE published_youtube_materials
    ADD COLUMN IF NOT EXISTS platform_work_url TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_published_material_platform_work
    ON published_youtube_materials(platform_type, account_id, platform_work_id)
    WHERE account_id IS NOT NULL AND platform_work_id IS NOT NULL AND deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS platform_metric_snapshots (
    id BIGSERIAL PRIMARY KEY,
    owner_user_id BIGINT NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
    platform_type INTEGER NOT NULL,
    account_id BIGINT NOT NULL REFERENCES user_info(id) ON DELETE CASCADE,
    publish_record_id BIGINT REFERENCES published_youtube_materials(id) ON DELETE SET NULL,
    platform_work_id TEXT NOT NULL,
    platform_work_url TEXT,
    title TEXT,
    published_at TIMESTAMP,
    captured_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    source TEXT NOT NULL,
    metrics JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_platform_metric_owner_account_time
    ON platform_metric_snapshots(owner_user_id, platform_type, account_id, captured_at DESC);

CREATE INDEX IF NOT EXISTS idx_platform_metric_work_time
    ON platform_metric_snapshots(owner_user_id, platform_type, account_id, platform_work_id, captured_at DESC);

CREATE TABLE IF NOT EXISTS platform_comment_samples (
    id BIGSERIAL PRIMARY KEY,
    owner_user_id BIGINT NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
    platform_type INTEGER NOT NULL,
    account_id BIGINT NOT NULL REFERENCES user_info(id) ON DELETE CASCADE,
    publish_record_id BIGINT REFERENCES published_youtube_materials(id) ON DELETE SET NULL,
    platform_work_id TEXT NOT NULL,
    platform_comment_id TEXT NOT NULL,
    body TEXT NOT NULL,
    like_count BIGINT,
    comment_published_at TIMESTAMP,
    captured_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_platform_comment_sample UNIQUE (
        owner_user_id, platform_type, account_id, platform_work_id, platform_comment_id
    )
);

CREATE INDEX IF NOT EXISTS idx_platform_comment_work_time
    ON platform_comment_samples(owner_user_id, platform_type, account_id, platform_work_id, captured_at DESC);

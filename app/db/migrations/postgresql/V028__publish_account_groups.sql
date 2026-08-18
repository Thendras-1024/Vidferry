CREATE TABLE IF NOT EXISTS publish_account_groups (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_publish_account_groups_name_lower
    ON publish_account_groups (LOWER(name));

CREATE TABLE IF NOT EXISTS publish_account_group_members (
    id BIGSERIAL PRIMARY KEY,
    group_id BIGINT NOT NULL REFERENCES publish_account_groups(id) ON DELETE CASCADE,
    account_id BIGINT NOT NULL,
    platform_type INTEGER NOT NULL,
    UNIQUE (group_id, platform_type),
    UNIQUE (group_id, account_id)
);

ALTER TABLE youtube_workflow_jobs
    ADD COLUMN IF NOT EXISTS publish_account_group_id BIGINT;

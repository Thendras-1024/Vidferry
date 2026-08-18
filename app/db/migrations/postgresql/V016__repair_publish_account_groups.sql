CREATE TABLE IF NOT EXISTS publish_account_groups (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    owner_user_id BIGINT,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS publish_account_group_members (
    id BIGSERIAL PRIMARY KEY,
    group_id BIGINT NOT NULL REFERENCES publish_account_groups(id) ON DELETE CASCADE,
    account_id BIGINT NOT NULL,
    platform_type INTEGER NOT NULL,
    UNIQUE (group_id, platform_type),
    UNIQUE (group_id, account_id)
);

CREATE INDEX IF NOT EXISTS idx_publish_account_groups_owner
    ON publish_account_groups (owner_user_id, id);

DROP INDEX IF EXISTS idx_publish_account_groups_name_lower;

CREATE UNIQUE INDEX IF NOT EXISTS idx_publish_account_groups_owner_name_lower
    ON publish_account_groups (owner_user_id, LOWER(name));

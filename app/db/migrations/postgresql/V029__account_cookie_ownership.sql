ALTER TABLE user_info
    ADD COLUMN IF NOT EXISTS owner_user_id BIGINT;

CREATE INDEX IF NOT EXISTS idx_user_info_owner_type
    ON user_info (owner_user_id, type, id);

ALTER TABLE publish_account_groups
    ADD COLUMN IF NOT EXISTS owner_user_id BIGINT;

CREATE INDEX IF NOT EXISTS idx_publish_account_groups_owner
    ON publish_account_groups (owner_user_id, id);

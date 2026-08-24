-- Repair databases that retained the pre-multi-user group index.
DROP INDEX IF EXISTS idx_youtube_video_groups_name_ci;

CREATE UNIQUE INDEX IF NOT EXISTS idx_youtube_video_groups_owner_name
    ON youtube_video_groups (owner_user_id, LOWER(name));

CREATE UNIQUE INDEX IF NOT EXISTS idx_youtube_video_groups_default
    ON youtube_video_groups (owner_user_id) WHERE is_default = 1;

DO $$
DECLARE
    administrator_id BIGINT;
BEGIN
    IF EXISTS (SELECT 1 FROM agent_sessions WHERE owner_user_id IS NULL) THEN
        SELECT id INTO administrator_id
        FROM auth_users
        WHERE role = 'admin' AND status = 'active'
        ORDER BY created_at, id
        LIMIT 1;

        IF administrator_id IS NULL THEN
            RAISE EXCEPTION 'V034 requires an active administrator before orphan Agent sessions can be assigned';
        END IF;

        UPDATE agent_sessions
        SET owner_user_id = administrator_id
        WHERE owner_user_id IS NULL;
    END IF;
END $$;

ALTER TABLE agent_sessions
    ALTER COLUMN owner_user_id SET NOT NULL;

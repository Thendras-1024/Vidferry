ALTER TABLE agent_runs
    ADD COLUMN IF NOT EXISTS owner_user_id BIGINT;

UPDATE agent_runs AS run
SET owner_user_id = session.owner_user_id
FROM agent_sessions AS session
WHERE run.owner_user_id IS NULL
  AND run.session_id IS NOT NULL
  AND run.session_id <> ''
  AND session.id = run.session_id;

UPDATE agent_runs AS run
SET owner_user_id = record.owner_user_id
FROM file_records AS record
WHERE run.owner_user_id IS NULL
  AND run.subject_type = 'material'
  AND run.subject_id <> ''
  AND record.id::TEXT = run.subject_id;

DO $$
DECLARE
    administrator_id BIGINT;
BEGIN
    IF EXISTS (SELECT 1 FROM agent_runs WHERE owner_user_id IS NULL) THEN
        SELECT id INTO administrator_id
        FROM auth_users
        WHERE role = 'admin' AND status = 'active'
        ORDER BY created_at, id
        LIMIT 1;

        IF administrator_id IS NULL THEN
            RAISE EXCEPTION 'V037 requires an active administrator before orphan Agent runs can be assigned';
        END IF;

        UPDATE agent_runs
        SET owner_user_id = administrator_id
        WHERE owner_user_id IS NULL;
    END IF;
END $$;

ALTER TABLE agent_runs
    ALTER COLUMN owner_user_id SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_agent_runs_owner_created
    ON agent_runs (owner_user_id, created_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_agent_runs_owner_session
    ON agent_runs (owner_user_id, session_id, created_at DESC);

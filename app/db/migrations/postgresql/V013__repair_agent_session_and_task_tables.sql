ALTER TABLE agent_sessions
    ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'web';

ALTER TABLE agent_sessions
    ADD COLUMN IF NOT EXISTS source_key TEXT DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_agent_sessions_source
    ON agent_sessions(deleted_at, source, updated_at DESC);

CREATE TABLE IF NOT EXISTS agent_session_bindings (
    source TEXT NOT NULL,
    source_key TEXT NOT NULL,
    session_id TEXT NOT NULL,
    owner_user_id BIGINT NOT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    PRIMARY KEY (source, source_key)
);

CREATE INDEX IF NOT EXISTS idx_agent_session_bindings_session
    ON agent_session_bindings(session_id);

CREATE TABLE IF NOT EXISTS task_acknowledgements (
    user_id BIGINT NOT NULL,
    task_key TEXT NOT NULL,
    acknowledged_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, task_key)
);

CREATE INDEX IF NOT EXISTS idx_task_acknowledgements_user_time
    ON task_acknowledgements(user_id, acknowledged_at DESC);

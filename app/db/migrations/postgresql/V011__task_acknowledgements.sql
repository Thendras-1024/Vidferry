CREATE TABLE IF NOT EXISTS task_acknowledgements (
    user_id BIGINT NOT NULL,
    task_key TEXT NOT NULL,
    acknowledged_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, task_key)
);

CREATE INDEX IF NOT EXISTS idx_task_acknowledgements_user_time
    ON task_acknowledgements(user_id, acknowledged_at DESC);

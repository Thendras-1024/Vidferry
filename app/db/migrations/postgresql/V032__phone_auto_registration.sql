ALTER TABLE auth_users
    ADD COLUMN IF NOT EXISTS avatar_url TEXT;

ALTER TABLE auth_phone_challenges
    ADD COLUMN IF NOT EXISTS idempotency_key_hash TEXT,
    ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active',
    ADD COLUMN IF NOT EXISTS activated_at TIMESTAMP WITHOUT TIME ZONE,
    ADD COLUMN IF NOT EXISTS failed_at TIMESTAMP WITHOUT TIME ZONE;

UPDATE auth_phone_challenges
SET status = 'consumed'
WHERE consumed_at IS NOT NULL AND status = 'active';

CREATE UNIQUE INDEX IF NOT EXISTS idx_auth_phone_challenges_idempotency
    ON auth_phone_challenges(idempotency_key_hash)
    WHERE idempotency_key_hash IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_auth_phone_challenges_active_phone
    ON auth_phone_challenges(phone_hash, status, expires_at);

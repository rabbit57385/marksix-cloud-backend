BEGIN;
CREATE TABLE IF NOT EXISTS marksix.draw_sync_state (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    sync_revision bigint NOT NULL DEFAULT 0 CHECK (sync_revision >= 0),
    verified_revision text,
    verified_from date,
    verified_through date,
    last_check_at timestamptz,
    last_success_at timestamptz,
    last_error text,
    retry_at timestamptz
);
INSERT INTO marksix.draw_sync_state (singleton) VALUES (true)
ON CONFLICT (singleton) DO NOTHING;
COMMIT;

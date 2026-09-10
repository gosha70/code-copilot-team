-- The human verdict on the PR an auto-build run produced (#190 §12):
-- merged_unmodified / merged_with_fixes / rejected. One row per run
-- (the driver's attempt_id); absence is "no verdict yet". The run's
-- other facts are read from its ledger on disk each time, never
-- stored — this row is the one thing the ledger cannot write, and it
-- outlives the ledger directory being archived or pruned.
CREATE TABLE IF NOT EXISTS auto_build_verdict (
    id          {PK},
    run_key     VARCHAR(80) NOT NULL UNIQUE,
    feature_id  TEXT,
    verdict     VARCHAR(30) NOT NULL,
    note        TEXT,
    set_at      TEXT
);

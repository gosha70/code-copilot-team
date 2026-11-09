-- Active time per session (#422): the gaps between consecutive turns,
-- each capped at an idle cutoff, beside the wall-clock duration_seconds
-- and never in place of it.
--
-- A NEW table and no column on any existing one, so create-if-absent is
-- the whole migration and a schema-12 store gains it in place;
-- activity.ensure_activity, called from apply_ddl, fills it from the
-- stored copilot_turn.timestamp, so nothing is re-ingested. Keyed by the
-- cutoff, so changing the configured cutoff needs no re-ingest either.
-- The gap counts say what the figure rests on: gaps measured, and gaps
-- skipped because a stamp was missing or the clock ran backwards.

CREATE TABLE IF NOT EXISTS session_activity (
    session_id          BIGINT NOT NULL REFERENCES copilot_session(id),
    idle_cutoff_seconds INTEGER NOT NULL,
    active_seconds      DOUBLE PRECISION NOT NULL,
    gaps_measured       INTEGER NOT NULL,
    gaps_unstamped      INTEGER NOT NULL,
    gaps_negative       INTEGER NOT NULL,
    PRIMARY KEY (session_id, idle_cutoff_seconds)
);

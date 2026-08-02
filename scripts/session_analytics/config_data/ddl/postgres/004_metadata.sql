-- session_analytics session metadata (FU-1).
--
-- Additive over 001_core. Adapter-neutral persistence of RawSession.metadata,
-- which upsert_session otherwise drops (Pi worker analytics, Claude git_branch,
-- Aider provisional_format). One row per (session, key); a plain string is
-- stored verbatim (value_json = FALSE, clean to query), a number/bool/list/
-- object is stored as json.dumps(...) (value_json = TRUE, consumers json.loads).
--
-- Redaction boundary: adapters neutralize/redact metadata BEFORE it reaches the
-- store; the store bounds and persists it, it is NOT a second redaction engine.
--
-- Re-ingest is a FULL REPLACEMENT of a session's metadata (delete-then-insert),
-- so a key omitted by a later ingest leaves no stale row.

CREATE TABLE IF NOT EXISTS copilot_session_metadata (
    id          {PK},
    session_id  BIGINT NOT NULL REFERENCES copilot_session(id) ON DELETE CASCADE,
    key         VARCHAR(100) NOT NULL,
    value       TEXT,
    value_json  BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE (session_id, key)
);

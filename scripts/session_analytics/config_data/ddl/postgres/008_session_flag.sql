-- Session tags a person sets by hand (favourite, to-do). One row per
-- (session, flag); absence is "not set". Anchored on copilot_session.id
-- like session_analysis and human_label: re-ingest upserts the session
-- row and keeps its id, so a person's tags survive it. "Analyzed" is
-- NOT stored here — it is derived from session_analysis rows.
CREATE TABLE IF NOT EXISTS session_flag (
    id          {PK},
    session_ref BIGINT NOT NULL REFERENCES copilot_session(id),
    flag        VARCHAR(30) NOT NULL,
    created_at  TEXT,
    UNIQUE (session_ref, flag)
);

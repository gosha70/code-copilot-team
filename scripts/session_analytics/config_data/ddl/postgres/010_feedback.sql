-- Feedback as a general record (#371 A3): a named, typed judgement on a
-- session, a turn or a tool call, from a person, a judge or a script,
-- with who said it and when. human_label (the fixed rubric per turn)
-- and session_flag are untouched; this is the shape they could not hold
-- ("this turn was wrong because X").
--
-- Target: (sequence_num, tool_sequence_num). (NULL, NULL) is the session,
-- (seq, NULL) a turn, (seq, tseq) a tool call of that turn. Anchored like
-- human_label and trace_document — sequence numbers, NOT copilot_turn.id
-- or copilot_tool_call.id — because re-ingest deletes and reinserts both
-- with fresh ids (store._delete_children), and an id FK would make
-- re-ingest of any session with feedback fail.
--
-- Exactly one value column is set; the CHECK says which shapes are
-- legal. Supersession is history, not editing: the replaced row stays,
-- the new one names it, and a row is superseded at most once (UNIQUE);
-- "current" is every row no other row names.
CREATE TABLE IF NOT EXISTS feedback (
    id                {PK},
    session_ref       BIGINT NOT NULL REFERENCES copilot_session(id),
    sequence_num      INTEGER,
    tool_sequence_num INTEGER,
    name              VARCHAR(80) NOT NULL,
    value_bool        BOOLEAN,
    value_num         DOUBLE PRECISION,
    value_text        TEXT,
    rationale         TEXT,
    source_type       VARCHAR(20) NOT NULL,
    source_id         VARCHAR(120) NOT NULL,
    supersedes        BIGINT UNIQUE REFERENCES feedback(id),
    created_at        TEXT NOT NULL,
    CHECK (
        (value_bool IS NOT NULL AND value_num IS NULL AND value_text IS NULL) OR
        (value_bool IS NULL AND value_num IS NOT NULL AND value_text IS NULL) OR
        (value_bool IS NULL AND value_num IS NULL AND value_text IS NOT NULL)
    ),
    CHECK (tool_sequence_num IS NULL OR sequence_num IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_feedback_session ON feedback (session_ref);

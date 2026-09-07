-- Human labels for judge validation (#313, Studio Phase 5). One row per
-- (turn, labeler), the same nine bool labels + sentiment + quality the
-- rubric asks the LLM for, so agreement can be computed label by label.
-- NULL means the labeler left it blank (not applicable / not sure) and
-- the pair is excluded from that label's n, exactly as a NULL judge label
-- is. Anchored like trace_document — (session_ref, sequence_num), NOT
-- copilot_turn.id — because re-ingest deletes and reinserts turn rows
-- with fresh ids, and a person's labels must survive that.
CREATE TABLE IF NOT EXISTS human_label (
    id                       {PK},
    session_ref              BIGINT NOT NULL REFERENCES copilot_session(id),
    sequence_num             INTEGER NOT NULL,
    labeler                  VARCHAR(80) NOT NULL,
    user_corrects_agent      BOOLEAN,
    user_asks_question       BOOLEAN,
    user_gives_command       BOOLEAN,
    agent_asks_clarification BOOLEAN,
    user_changes_approach    BOOLEAN,
    agent_changes_approach   BOOLEAN,
    has_misunderstanding     BOOLEAN,
    response_helpful         BOOLEAN,
    rework_detected          BOOLEAN,
    sentiment                VARCHAR(20),
    interaction_quality      INTEGER,
    created_at               TEXT,
    UNIQUE (session_ref, sequence_num, labeler)
);

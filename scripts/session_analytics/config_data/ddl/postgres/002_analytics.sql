-- session_analytics analytics schema (LLM-as-Judge + KPI rollups).
--
-- Additive over 001_core. ``heuristic_label`` is written ONLY by the judge
-- runner (M3) and never mutates turn rows. One row per (turn, rubric).

CREATE TABLE IF NOT EXISTS heuristic_label (
    id                   {PK},
    turn_id              BIGINT NOT NULL REFERENCES copilot_turn(id),
    rubric_name          VARCHAR(80) NOT NULL,
    user_corrects_agent     BOOLEAN,
    user_asks_question      BOOLEAN,
    user_gives_command      BOOLEAN,
    agent_asks_clarification BOOLEAN,
    user_changes_approach   BOOLEAN,
    agent_changes_approach  BOOLEAN,
    has_misunderstanding    BOOLEAN,
    response_helpful        BOOLEAN,
    rework_detected         BOOLEAN,
    phase_violation         BOOLEAN,
    sentiment            VARCHAR(20),
    interaction_quality  INTEGER,
    judge_id             VARCHAR(80),
    judge_model          VARCHAR(100),
    parse_status         VARCHAR(40),
    created_at           TEXT,
    UNIQUE (turn_id, rubric_name)
);

CREATE TABLE IF NOT EXISTS session_kpi (
    id                        {PK},
    session_id                BIGINT NOT NULL REFERENCES copilot_session(id),
    rubric_name               VARCHAR(80) NOT NULL,
    labeled_turn_count        INTEGER NOT NULL DEFAULT 0,
    correction_rate           DOUBLE PRECISION,
    rework_rate               DOUBLE PRECISION,
    first_attempt_success_rate DOUBLE PRECISION,
    autonomy_score            DOUBLE PRECISION,
    phase_compliance_score    DOUBLE PRECISION,
    avg_interaction_quality   DOUBLE PRECISION,
    computed_at               TEXT,
    UNIQUE (session_id, rubric_name)
);

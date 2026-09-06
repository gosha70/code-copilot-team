-- Session-level LLM analysis (#65 Phase 1): one row per (session, kind),
-- where kind is tuning | coaching | efficiency. The judge reads the whole
-- transcript and returns a JSON document the UI renders verbatim; the row
-- records WHICH judge, WHICH prompt version and WHAT it saw (archive vs
-- previews, chars, truncated) so a reader can weigh the result. Anchored on
-- copilot_session.id like trace_document: re-ingest keeps session rows and
-- replaces turns, so the analysis survives a re-ingest of its session.
-- A parse failure is stored too (parse_status + raw head) — an absent row
-- and a failed run must not look the same on the page.
CREATE TABLE IF NOT EXISTS session_analysis (
    id                {PK},
    session_ref       BIGINT NOT NULL REFERENCES copilot_session(id),
    kind              VARCHAR(30) NOT NULL,
    judge_id          VARCHAR(80),
    judge_model       VARCHAR(100),
    prompt_version    VARCHAR(40),
    transcript_source VARCHAR(20),
    transcript_chars  INTEGER,
    truncated         BOOLEAN,
    parse_status      VARCHAR(40),
    result_json       TEXT,
    error_text        TEXT,
    created_at        TEXT,
    UNIQUE (session_ref, kind)
);

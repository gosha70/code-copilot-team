-- The mode each stored session analysis was computed under (#515).
--
-- A stored analysis quotes what its judge was sent and survives a
-- re-ingest (re-ingest deletes a session's labels and kpis, not its
-- analyses). With no mode of its own, the outbound floor could judge it
-- only by its session, whose recorded mode `ingest --full` updates to the
-- current one. One row per analysis records the LOOSEST mode of the
-- session text its judge was sent; off-machine readers judge the stored
-- result and error by it against the project's current mode.
--
-- A NEW table and no column on any existing one, so create-if-absent is
-- the whole migration and a schema-13 store gains it in place: a column
-- on session_analysis would make check_schema refuse every existing store
-- until it is recreated (schema 11's note in relational/db.py). An
-- analysis with no row here was stored before schema 14 and counts as
-- `none`.
CREATE TABLE IF NOT EXISTS session_analysis_mode (
    id              {PK},
    session_ref     BIGINT NOT NULL REFERENCES copilot_session(id),
    kind            VARCHAR(30) NOT NULL,
    redaction_mode  VARCHAR(20) NOT NULL,
    recorded_at     TEXT,
    UNIQUE (session_ref, kind)
);

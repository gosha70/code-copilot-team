-- session_analytics core relational schema.
--
-- Portable across PostgreSQL (production + CI service container) and SQLite
-- (zero-infra unit tests). The ONLY dialect difference is the auto-increment
-- primary key, written as the ``{PK}`` placeholder and substituted by
-- relational/schema.py. Foreign-key columns are plain BIGINT (INTEGER
-- affinity under SQLite). Timestamps are ISO-8601 TEXT for portability —
-- duration is computed in Python, never via DB date math.

CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER NOT NULL,
    applied_at  TEXT
);

-- E1 multi-tenant developer registry.
CREATE TABLE IF NOT EXISTS developer (
    id           {PK},
    developer_id VARCHAR(100) NOT NULL UNIQUE,
    display_name VARCHAR(200)
);

CREATE TABLE IF NOT EXISTS copilot_session (
    id                {PK},
    copilot           VARCHAR(30) NOT NULL,
    session_id        VARCHAR(200) NOT NULL,
    project_path      VARCHAR(1000),
    model             VARCHAR(100),
    agent_profile     VARCHAR(100),
    phase             VARCHAR(20),
    developer_id      VARCHAR(100) NOT NULL DEFAULT 'local',  -- E1
    turn_count        INTEGER NOT NULL DEFAULT 0,
    tool_call_count   INTEGER NOT NULL DEFAULT 0,
    error_count       INTEGER NOT NULL DEFAULT 0,
    started_at        TEXT,
    ended_at          TEXT,
    duration_seconds  INTEGER,
    redaction_mode    VARCHAR(20) NOT NULL DEFAULT 'code',    -- E8
    content_redacted  BOOLEAN NOT NULL DEFAULT TRUE,          -- E8
    benchmark_run_dir VARCHAR(1000),                          -- E9
    session_embedding TEXT,                                   -- E2 (nullable)
    source            VARCHAR(20) NOT NULL DEFAULT 'local',
    UNIQUE (copilot, session_id)
);

CREATE TABLE IF NOT EXISTS copilot_turn (
    id                  {PK},
    session_id          BIGINT NOT NULL REFERENCES copilot_session(id),
    sequence_num        INTEGER NOT NULL,
    role                VARCHAR(10) NOT NULL,
    content_preview     TEXT,
    content_length      INTEGER NOT NULL DEFAULT 0,
    has_tool_use        BOOLEAN NOT NULL DEFAULT FALSE,
    uuid                VARCHAR(100),
    parent_uuid         VARCHAR(100),
    is_sidechain        BOOLEAN NOT NULL DEFAULT FALSE,
    slash_command       VARCHAR(100),
    tokens_input        INTEGER,
    tokens_output       INTEGER,
    cache_read_tokens   INTEGER,
    cache_write_tokens  INTEGER,
    model               VARCHAR(100),                          -- E5 (nullable, per-message + session fallback)
    cost_usd            DOUBLE PRECISION,                      -- E5 (nullable)
    cost_price_version  VARCHAR(50),                            -- E5 (nullable, effective_date that priced this turn)
    timestamp           TEXT
);

CREATE TABLE IF NOT EXISTS copilot_tool_call (
    id            {PK},
    turn_id       BIGINT NOT NULL REFERENCES copilot_turn(id),
    tool_use_id   VARCHAR(100),
    tool_name     VARCHAR(80) NOT NULL,
    tool_name_raw VARCHAR(100),
    input_preview TEXT,
    sequence_num  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS copilot_tool_result (
    id            {PK},
    tool_call_id  BIGINT NOT NULL REFERENCES copilot_tool_call(id),
    status        VARCHAR(20),
    is_error      BOOLEAN NOT NULL DEFAULT FALSE,
    output_length INTEGER,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS copilot_file_access (
    id           {PK},
    session_id   BIGINT NOT NULL REFERENCES copilot_session(id),
    turn_id      BIGINT REFERENCES copilot_turn(id),
    tool_call_id BIGINT REFERENCES copilot_tool_call(id),
    file_path    VARCHAR(1000) NOT NULL,
    access_type  VARCHAR(10),
    language     VARCHAR(30)
);

CREATE TABLE IF NOT EXISTS copilot_error (
    id            {PK},
    session_id    BIGINT NOT NULL REFERENCES copilot_session(id),
    turn_id       BIGINT REFERENCES copilot_turn(id),
    tool_call_id  BIGINT REFERENCES copilot_tool_call(id),
    error_type    VARCHAR(200),
    error_message TEXT,
    tool_name     VARCHAR(80),
    is_recovered  BOOLEAN NOT NULL DEFAULT FALSE
);

-- Incremental-ingest bookkeeping.
CREATE TABLE IF NOT EXISTS ingest_state (
    id               {PK},
    copilot          VARCHAR(30) NOT NULL,
    source_file      VARCHAR(1000) NOT NULL,
    last_mtime       DOUBLE PRECISION NOT NULL DEFAULT 0,
    last_byte_offset BIGINT NOT NULL DEFAULT 0,
    last_session_id  VARCHAR(200),
    ingested_at      TEXT,
    UNIQUE (copilot, source_file)
);

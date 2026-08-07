-- Slice B1 (#187): local in-flight heartbeat state — LAST-SEEN semantics,
-- never an alive/dead verdict (spec FR-4/FR-5). Dedicated table (not the
-- copilot_session_metadata KV registry) because a heartbeat can precede any
-- ingested session row and the KV registry is FK-anchored to
-- copilot_session; nothing is fabricated to satisfy an FK. Keyed by
-- (project_path, developer_id); session_id is nullable by construction (Pi
-- exposes no session id at checkpoint time). B2's central-registry schema
-- is free to replace this local shape.
CREATE TABLE IF NOT EXISTS local_heartbeat (
    project_path      VARCHAR(1024) NOT NULL,
    developer_id      VARCHAR(100)  NOT NULL,
    session_id        VARCHAR(128),
    phase             VARCHAR(64),
    feature_id        VARCHAR(128),
    checkpoint_count  BIGINT NOT NULL DEFAULT 0,
    last_heartbeat_at VARCHAR(40) NOT NULL,
    PRIMARY KEY (project_path, developer_id)
);

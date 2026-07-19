# Spec: session-analytics trace archive Slice A (E10)

Issue #98. Authoritative scope: the merged shaping doc
(`specs/session-analytics-trace-archive/shaping.md`, PR #97) — this spec
binds Slice A only, with the shaping doc's settled decisions (2026-07-18):
explicit per-project opt-in; benchmark traces deferred to A2; substring
(non-ranked) search for v1. Grounding (verified 2026-07-18): adapters parse
full transcripts at ingest (`RawTurn.text`); `ingest/redaction.py
redact_text` is the trusted redaction path; store truncates to 500-char
previews (`CONTENT_PREVIEW_CHARS`); `ProjectOverride(redaction_mode,
ingest)` is the E8 per-project config; `ingest_state`/`should_ingest` is the
incremental pattern; new tables need no migration (idempotent `apply_ddl`).

## User Scenarios

- US1: As an operator who enabled `trace_archive: true` for a project, I run
  `session-analytics archive`; later the source transcript is deleted by
  Claude Code's cleanup — the redacted TURN TEXT still exists in my store,
  per turn, and exports with everything else. (Scope honesty, settled at
  review 2026-07-19: v1 archives redacted turn text ONLY; tool inputs and
  tool results — the highest-risk redaction surface — are deliberately
  excluded and deferred to a named follow-up slice.)
- US2: As an analyst, `session-analytics search "pricing config"` (or
  `GET /api/search?q=`) finds every archived turn containing that substring,
  with session/turn references and a snippet — across sessions whose sources
  no longer exist.
- US3: As a privacy-conscious operator, projects that never opted in (and
  all opted-out projects) have ZERO rows in the archive — provably.

## Requirements

- FR-1: **`trace_document` table** (`001_core.sql`, CREATE IF NOT EXISTS —
  no migration): `id {PK}`, `session_ref BIGINT NOT NULL REFERENCES
  copilot_session(id)`, `turn_ref BIGINT REFERENCES copilot_turn(id)`
  (nullable), `source_kind VARCHAR(30)` (v1 writes only
  `copilot_transcript`; enum room for A2), `content TEXT` (**redacted full
  text — never raw**), `content_hash VARCHAR(64)`, `source_path
  VARCHAR(1000)`, `redaction_mode VARCHAR(20)`, `archived_at TEXT`;
  UNIQUE(session_ref, turn_ref, source_kind). Index on session_ref.
- FR-2: **Opt-in config** — `ProjectOverride` gains `trace_archive: bool =
  False`; parsed from the `projects.<key>.trace_archive` config field.
  Archive is OFF unless explicitly true. No global enable flag exists.
- FR-3: **`archive` CLI** — `session-analytics archive [--copilot ...]
  [--root ...] [--dsn ...] [--full]`: discovers sources via the SAME
  adapters as ingest, resolves the project key/policy via the SAME
  resolution as ingest, and for each session: opt-out or not-opted-in →
  skipped (counted, no read of turn content persisted); opted-in → parse,
  `redact_text` EVERY turn under the effective mode, store one
  `trace_document` row per turn (upsert on the UNIQUE key — idempotent).
  Incremental by default via archive-own bookkeeping (`trace_archive_state`,
  ingest_state-shaped; `--full` bypasses). Per-source failures are skipped +
  counted, never fatal (house pattern).
- FR-4: **Redaction floor** — the effective archive mode for a session is
  the STRICTER of (config-resolved mode now, the session row's recorded
  `redaction_mode`) — the archive never stores looser than what ingest
  recorded (shaping fence #3). Every row stamps the mode actually applied.
- FR-5: **Explicit counters** — the summary prints every counter via
  as_dict (house guardrail): `sessions_scanned`, `sessions_archived`,
  `sessions_skipped_not_opted_in`, `sessions_opted_out`,
  `sessions_skipped_unchanged`, `turns_archived`, `source_failures`, and a
  per-mode breakdown.
- FR-6: **Substring search** — `search <query> [--limit N] [--dsn ...]` CLI
  and `GET /api/search?q=&limit=` over `trace_document.content` via
  parameterized `LIKE` (sqlite) / `ILIKE` (postgres) with escaped
  wildcards (`%`/`_` in the query are literals). Returns session_ref,
  turn_ref, copilot/session_id, and a snippet (fixed window around the
  first match). Deterministic ordering (session_ref, turn_ref) — documented
  as **substring search, not ranked search**. Case-insensitive on both
  dialects (LOWER() on sqlite side as needed).
- FR-7: **Export** — `trace_documents` added to the E7 export tables
  (columns constant, streamed SELECT ordered by id, no bool columns).
  Redaction-safe by construction: the table only ever holds redacted text.
- FR-8: **Tests** — unit: opt-in resolution (default off, explicit on,
  opt-out beats opt-in), redaction floor (stricter-of), LIKE-escape of
  `%`/`_`, snippet windowing, counter exactness; sqlite integration:
  archive → delete source file → search still finds text; re-run
  idempotent (row count stable); opted-out and not-opted-in projects → 0
  rows; adversarial redaction spot-checks (secrets/code in fixture turns
  come out redacted under `code`/`metadata-only`); export streams; FastAPI
  search endpoint (with fastapi/httpx). Postgres path via local Docker
  (ILIKE + upsert), CI being down.
- FR-9: **Docs** — README section: enabling per project, the archive/search
  commands, the substring-not-ranked promise, size expectations, the
  redaction floor, and the A2/B/C deferrals.

## Constraints

- Stdlib only; no new dependencies; no external search engine.
- **No unredacted storage, ever** — `redact_text` before every write; no
  raw-file copying (named no-go in shaping).
- All SQL parameterized; names via shared constants; one `{PK}` DDL file
  (no dialect fork — that's Slice B's problem).
- No change to `ingest()`, existing tables, or the judge.
- One issue per PR: this bundle covers exactly #98.

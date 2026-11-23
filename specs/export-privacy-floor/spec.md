# Spec: export applies a project's current privacy settings (#487)

`session-analytics export` writes what the store holds. A project opted out
(`ingest: "off"`) or tightened to a stricter redaction mode after its
sessions were ingested keeps those rows in the store, and today `export`
writes them as stored, planted secrets included (the reproduction is in
#487). Every path that sends session text off the machine already applies
the current configuration when it reads the store (#457, `OutboundPolicy`).
This spec gives `export` the same floor by default, with a flag for the store
as it is.

## Requirements

- **FR-1: one floor per export.** `export` loads `OutboundPolicy` once per
  run, from the current configuration, and applies it to every table it
  writes. Under `--table all` every file is filtered by the same policy, so
  the files agree with each other.
- **FR-2: a project's setting is read with #478's combined check.**
  `ProjectKeyResolver.override` reads the project's entries under both of
  its keys, the matching `project_ids` id and the git root: the project is
  opted out if either entry opts out, and the stricter of their modes holds.
  `OutboundPolicy.load` already uses it, so an opt-out or a tightening filed
  under either key applies to export.
- **FR-3: an opted-out project exports nothing.** A session whose project is
  configured `ingest: "off"` now has no row in any table of session data:
  `sessions`, `turns`, `labels`, `kpis`, `trace_documents` and `feedback`.
  A `benchmark_results` row linked to such a session keeps its benchmark
  outcome, with `session_ref` empty, and in any `benchmark_results` row a
  `run_dir` that sits under an opted-out project's path is emptied (D3).
  So is a kept session's `benchmark_run_dir` that sits under one.
  The column table below gives the rule for every column.
- **FR-4: a tightened project exports markers.** For a session whose
  project's current mode is stricter than the mode it was recorded under,
  stored session text leaves as the marker `OutboundPolicy.text` returns,
  the one the off-machine paths send: `turns.content_preview` and
  `trace_documents.content`. Its `redaction_mode` reads `metadata-only` in
  `sessions`, `turns` and `trace_documents`, the mode of the text the row now
  carries (D2). Its feedback text is exported as stored, since the redaction
  mode has never governed feedback (D4). Every other column is exported as
  stored: metadata is not content (`specs/redaction-canaries/spec.md`).
  A `trace_documents` row is judged by its own `redaction_mode`, as the
  off-machine paths judge archived text (#514), so a row archived before a
  tightening exports the marker even after `ingest --full` has re-recorded
  its session.
- **FR-5: the store as it is, on request.** `--raw` writes every row as
  stored, as `export` does today (D1).
- **FR-6: the export says what it changed in the tables it wrote, in counts
  only.**
  - By default, for each written table the floor changed, one stderr line
    gives, with their reasons, the counts of:
    - rows dropped, because their session's project is opted out;
    - rows reduced to `metadata-only`, because their session's project was
      tightened since ingest: the text replaced by the marker, the
      `redaction_mode` set to `metadata-only`, or both, counting a row once;
    - rows with a link to an opted-out project emptied:
      `benchmark_results.session_ref` or `run_dir`, and
      `sessions.benchmark_run_dir`.

    Only counts above 0 are given. A table the floor did not change prints
    nothing, so `--table kpis` with a tightened project prints nothing: its
    rows carry no text and no mode.
  - `--raw` always prints one stderr line giving how many sessions of
    opted-out projects and how many of tightened projects it wrote as
    stored, zeros included. It counts only sessions with rows in the written
    tables that the default export would have dropped or changed, so
    `--raw --table kpis` with a tightened project reports no tightened
    session.
  - Neither names a project, a project path or a session: counts only.
    Stdout carries the CSV alone.
- **FR-7: nothing else changes.** A store with no opted-out or tightened
  project exports what it exports today: the same bytes in CSV, and the same
  rows in Parquet. Column orders and row orders are unchanged, CSV stays
  streamed, and in every case Parquet carries the same rows and values as
  CSV.
- **FR-8: docs, and the specs this revises.**
  - The Session Analytics README's Export section describes the default,
    `--raw` and the summary.
  - The export examples in `docs/session-analytics-cookbook.md` show the
    default and `--raw`.
  - An Unreleased CHANGELOG entry supersedes the 2.1.0 upgrade note
    "`export` still writes what the store holds".
  - The out-of-scope line in `specs/redaction-canaries/spec.md` that names
    CSV/Parquet export, and FR-6 of `specs/session-analytics-export/spec.md`
    ("A project opted out under E8 has no rows"), point to this spec.
  - The 2.1.0 visual pages (`docs/visual/cct-2.1.0-release-map.html`,
    `docs/visual/cct-field-guide.html`) are left as they are until the
    release that ships this.

## Column decisions

Every table that holds session data references its session through a
foreign key that is never empty. `benchmark_results.session_ref` is the
exception: it is empty for an attempt matched to no session. "As stored"
means the column is written as the store holds it.

**`sessions`**, linked by `id`.
- Opted out: the row is dropped.
- `benchmark_run_dir`, in any kept row: emptied when it is the path of an
  opted-out project or sits under it, as `benchmark_results.run_dir` is;
  otherwise as stored.
- Tightened: `redaction_mode` reads `metadata-only` (D2). As stored: `id`,
  `copilot`, `session_id`, `project_path`, `model`, `phase`,
  `developer_id`, `turn_count`, `tool_call_count`, `error_count`,
  `started_at`, `ended_at`, `duration_seconds`, `cost_usd` and the eight
  `kpi_*` columns. They hold identity, timing, counts and cost, and no
  session text.

**`turns`**, linked by `session_id`.
- Opted out: the rows are dropped.
- Tightened: `content_preview` becomes the marker. `redaction_mode`, the
  parent session's, reads `metadata-only`. As stored: `session_id`,
  `sequence_num`, `role`, `content_length`, `has_tool_use`, `tokens_input`,
  `tokens_output`, `cache_read_tokens`, `cache_write_tokens`, `cost_usd`,
  `model`, `cost_price_version`.

**`labels`**, which has no session column. It is linked through `turn_id`,
which is never empty and references `copilot_turn`, by an inner join to that
turn's `session_id`. The joined id is used to filter and is not written.
- Opted out: the rows are dropped.
- Tightened: all eighteen columns as stored. `id`, `turn_id`,
  `rubric_name`, the nine booleans, `sentiment` (a short label),
  `interaction_quality` (an integer), `judge_id`, `judge_model`,
  `parse_status` and `created_at` carry no session text.

**`kpis`**, linked by `session_id`.
- Opted out: the rows are dropped.
- Tightened: all ten columns as stored: numeric rollups.

**`benchmark_results`**, linked by `session_ref`, which may be empty.
- Opted out: the row is kept and `session_ref` is emptied (D3). The other
  sixteen columns, the benchmark's identity and outcome, are as stored,
  except `run_dir` (below).
- `run_dir`, in any row: emptied when it is the path of an opted-out
  project or sits under it (D3), whatever `session_ref` holds; otherwise as
  stored. The opted-out paths are the ones the off-machine paths never name
  (`OutboundPolicy.excluded_projects`), compared by whole path components.
- Tightened: all seventeen columns as stored.
- A row with no `session_ref` is otherwise as stored under every setting.

**`trace_documents`**, linked by `session_ref`.
- Opted out: the rows are dropped.
- Tightened:
  - `content` becomes the marker.
  - `redaction_mode`, the row's own, reads `metadata-only`.
  - `content_hash` is as stored. It is a digest of the stored text, and the
    marker itself carries a 12-character digest of the same text, so it
    reveals no more than the marker.
  - `source_path` is as stored: the path of the transcript file the turn was
    archived from. A path is metadata, which no mode redacts
    (`specs/redaction-canaries/spec.md`), and the session's `project_path`
    is exported as stored too.
  - `id`, `session_ref`, `sequence_num`, `source_kind` and `archived_at` are
    as stored.

**`feedback`**, linked by `session_ref`.
- Opted out: the rows are dropped.
- Tightened: all thirteen columns as stored, `value_text` and `rationale`
  included (D4).

## Constraints

- `OutboundPolicy`'s semantics do not change: the floor export applies is
  the floor the off-machine paths apply. A read-only accessor may be added
  for the summary's counts.
- No schema change, no store rewrite, no new configuration key. Removing
  stored rows still needs a new store.
- Export stays CLI-only; no API or MCP export is added.
- What each redaction mode removes does not change, and neither do the
  off-machine paths.

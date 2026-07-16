# Spec: session-analytics export slice — CSV/Parquet (E7)

Issue #87 (E7, first Tier-2 bet from the #65 prioritization). Base: the #63
pipeline + E5 cost (#85) + E8 privacy (#86). The relational store now holds
cost and per-project redaction data worth exporting. Groundwork: the CLI is
argparse subcommands (`cli.py`); optional deps are gated via `ImportError`
(graph/mcp/serve) + `importlib.util.find_spec` test skips (kuzu/fastapi);
stored content is already redacted at ingest (`content_preview`,
`content_redacted`). Scope = the CSV/Parquet export slice only.

## User Scenarios

- US1: As an operator, I run `session-analytics export --format csv` and get a
  one-row-per-session summary — including cost (E5) and per-session
  `redaction_mode` (E8) and judge KPIs — that I can open in a spreadsheet or
  pipe into another tool, without hand-writing SQL.
- US2: As an operator with pandas/DuckDB, I export to Parquet for columnar
  analysis; if `pyarrow` isn't installed I get a clear "install pyarrow"
  message, never a stack trace.
- US3: As a privacy-conscious operator, the export never contains anything the
  store didn't already hold in redacted form — it reads only from the DB, never
  re-reads raw transcripts — so it honors the ingest-time redaction and my E8
  opt-outs automatically.

## Requirements

- FR-1: `session-analytics export --format csv|parquet [--table
  sessions|turns|labels|kpis|all] [--out <path>]`. `--format` defaults to `csv`;
  `--table` defaults to `sessions`.
- FR-2: **Export shapes** (from the relational store):
  - `sessions` — denormalized one row per session: id, copilot, session_id,
    project_path, model, phase, developer_id, redaction_mode, turn_count,
    tool_call_count, error_count, started_at, ended_at, duration_seconds,
    `cost_usd` (Σ turn costs, E5), and the `session_kpi` columns (LEFT JOIN;
    NULL when unlabeled).
  - `turns` — per turn: session_id, sequence_num, role, content_length,
    has_tool_use, tokens_*, cost_usd, model, cost_price_version, redacted
    `content_preview` (as stored).
  - `labels` — `heuristic_label` rows. `kpis` — `session_kpi` rows.
  - `all` — one file per table (`<table>.<ext>`) written into the `--out`
    directory.
- FR-3: **CSV** via the stdlib `csv` module (always available), streamed
  row-by-row (no full-table load into memory); stable, documented column order;
  `ORDER BY` for reproducible output.
- FR-4: **Parquet** via `pyarrow`, gated as an OPTIONAL dependency — a clear
  "install pyarrow to export Parquet" message + usage exit code on
  `ImportError` (never a traceback). Same columns + ordering as CSV.
- FR-5: **Output**: a single table → `--out <file>`, or stdout by default for
  CSV (binary Parquet requires `--out`). `all` requires `--out <dir>`.
- FR-6: **Redaction-safe by construction** — export reads ONLY from the
  relational store (already redacted at ingest); it NEVER re-reads raw
  transcripts. A project opted out under E8 has no rows and is absent from
  exports; `redaction_mode` is an exported column so an export self-documents
  its privacy posture (a session ingested with `redaction: none` exports its
  raw preview — the operator's own ingest-time choice).
- FR-7: **Tests** — CSV shape/content/ordering per table; the `sessions`
  summary carries `cost_usd` + `redaction_mode` + KPI columns; determinism
  (stable order across runs); redaction-safety (a metadata-only session's
  exported preview is the redacted marker, not raw text); Parquet tests skipped
  when `pyarrow` is absent (run in CI when installed). SQLite + smoke parity.
- FR-8: **Docs** — a README export section (command, tables, formats, the
  redaction-safety note, pyarrow-optional).

## Constraints

- Python; CSV is stdlib (zero-dep, always); Parquet via optional `pyarrow`
  (graceful `ImportError`, no traceback).
- Export reads only the relational store — never re-reads raw transcripts
  (the redaction-safety invariant).
- CSV is streamed (no full-table memory load); output is deterministic.
- Queries are dialect-agnostic (SQLite + PostgreSQL).
- One issue per PR: this bundle covers exactly #87. Grafana, webhooks, and
  incremental/streaming export are out of scope (later E7 issues).

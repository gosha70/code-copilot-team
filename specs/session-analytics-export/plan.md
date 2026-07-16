---
spec_mode: full
feature_id: session-analytics-export
risk_category: integration
justification: |
  Adds a read-only CSV/Parquet export CLI over the existing relational store.
  Low risk — no schema change, no ingest/redaction change; exports already-
  redacted stored data (never re-reads raw transcripts). Parquet is an optional
  pyarrow dependency gated like kuzu/fastapi. Coverage via the unittest suite
  (+ smoke). Tracking #65; builds on E5 (#85) + E8 (#86).
status: approved
date: 2026-07-16
issue: 87
origin:
  issue: gosha70/code-copilot-team#87
  urls:
    - https://github.com/gosha70/code-copilot-team/issues/87
  origin_claim: |
    Issue #87 (E7 export slice): a `session-analytics export` CLI writing the
    relational store to CSV (stdlib) and Parquet (optional pyarrow). Tables:
    sessions (denormalized, with E5 cost + E8 redaction_mode + session_kpi),
    turns, labels, kpis, all. Redaction-safe by construction (reads only the
    store, already redacted; opted-out projects absent). Deterministic ordering;
    graceful ImportError for pyarrow. Grafana/webhooks/streaming deferred.
---

# Plan: session-analytics export slice (E7)

Grounded (verified 2026-07-16): CLI = argparse subcommands + a `_CMD` dispatch
dict (`cli.py`); optional deps caught via `except ImportError` (cli.py:261/362/
386) with `find_spec` test skips; the store is SQLite/Postgres via `Database`
(`relational/db.py` `query`); reusable session/cost/KPI query shapes exist in
`mcp/tools.py` + `api/dashboard.py`; stored `content_preview` is redacted at
ingest.

## Deliverables

1. **`export` module** (`scripts/session_analytics/export.py` or
   `export/`): per-table row generators (streamed) with fixed column orders +
   deterministic `ORDER BY`, reading via `Database.query`. The `sessions`
   generator LEFT JOINs the cost rollup + `session_kpi`.
2. **CSV writer** (stdlib `csv`, streamed) + **Parquet writer** (pyarrow,
   imported lazily; `ImportError` → usage error with an install hint).
3. **`export` CLI subcommand** (`cli.py`): `--format`, `--table`, `--out`;
   stdout default for a single CSV table; `all` → directory.
4. **Tests** (`tests/test_export.py`) per FR-7; **docs** (README) per FR-8.

## Design decisions to confirm at approval

- **D-out-semantics** — single table → `--out <file>` else stdout (CSV);
  Parquet always requires `--out` (binary); `--table all` requires an `--out`
  directory. *(Recommend — Unix-pipeable CSV, no binary-to-terminal.)*
- **D-turns-content** — the `turns` export includes the stored (already-
  redacted) `content_preview`; a `redaction: none` session therefore exports
  its raw preview, which was the operator's own ingest choice, and the
  `redaction_mode` column documents it per row. *(Recommend include — export =
  what's stored; consistent with the redaction-safety invariant.)*
- **D-parquet-in-memory** — v1 builds the pyarrow table in memory before
  writing (fine at local single-store scale); batched/streamed Parquet is out
  of scope. *(Recommend — flag if very large stores are expected.)*

## Out of scope

- Grafana provisioning, webhooks, incremental/streaming export, arbitrary-SQL
  export (separate later E7 issues).
- Any change to ingest, redaction, or the schema.

## Test strategy

Unittest-first (SQLite): ingest the fixture, export each table to a temp file /
captured stdout, assert column order + row content + `ORDER BY` determinism;
assert the `sessions` summary carries `cost_usd`, `redaction_mode`, and KPI
columns; assert redaction-safety (a metadata-only session's exported preview is
the redacted marker). Parquet tests `skipUnless(pyarrow)`; the smoke workflow
(pyarrow installable there) can assert a Parquet round-trip. No new DDL, so no
migration risk.

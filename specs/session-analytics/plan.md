---
spec_mode: full
feature_id: session-analytics
risk_category: integration
justification: |
  New subsystem touching scripts/ (new session_analytics package + bash
  dispatcher), a new top-level studio/ Next.js app, .github/workflows/, and
  introducing two data stores the repo does not currently run (PostgreSQL via
  docker-compose + embedded Kùzu). Multi-adapter ingestion (Claude Code primary,
  Aider secondary) of external on-disk formats; an LLM-as-Judge pass reusing the existing
  benchmark judge infrastructure; an MCP server; and a rich multi-tab UI.
  Delivered as one PR (P1–P6 as internal milestones) per user decision, with a
  CI smoke gate. Privacy is an AC: nothing leaves the machine by default.
status: draft
date: 2026-05-30
issue: 63
origin:
  issue: gosha70/code-copilot-team#63
  urls:
    - https://github.com/gosha70/code-copilot-team/issues/63
  origin_claim: |
    See spec.md `origin:` block. #63 = full session-analytics pipeline mirroring
    kiro-analyzer (unreachable; planned from issue text + real on-disk formats).
    User-confirmed: one PR for all phases; Postgres + Kùzu as specified; full
    rich Studio UI. E1–E10 are extension points only, with schema columns added
    up front to avoid later migrations.
---

# Plan: Copilot Session Analytics & Process Mining Pipeline

## Architecture

```
Claude Code JSONL ┐  (primary)
                  ├─► SessionAdapter ─► normalize ─► PostgreSQL ─► Kùzu graph
Aider md history  ┘  (secondary)          (idempotent upsert)         │
                                               │                      │
                                          LLM-as-Judge           MCP server (stdio)
                                          (claude-code / Ollama)       │
                                               │                       ▼
                                          heuristic_label ──► FastAPI ──► Next.js Studio
```

One Python domain layer, three consumers (CLI, MCP server, FastAPI) — single source
of truth for SQL/Cypher. The Next.js Studio is pure presentation; it never opens a DB
(Kùzu is embedded/Python-bound/single-writer) and calls FastAPI over `127.0.0.1`.

## Conventions mirrored from `benchmark_runner`

- Bash dispatcher `scripts/session-analytics` sets `PYTHONPATH=scripts:.`,
  `PYTHONUNBUFFERED=1`, then `exec python3 -m session_analytics "$@"`.
- `contracts.py`: frozen dataclasses + `runtime_checkable` Protocol; null-vs-zero
  discipline (`None` ≠ `0`/`False`).
- `registry.py` + `_register.py`: idempotent `register_all()` /
  `unregister_all_for_tests()`; one grep-able registration file.
- `cli.py`: argparse subparsers + `_HANDLERS` dict; stable exit codes 0/2/3/8.
- No hardcoded structured data: schema/labels/tool-maps in `config/*.yaml` + DDL files,
  loaded via `importlib.resources`.
- Tests alongside the package; CI smoke gate modeled on `benchmark-smoke.yml`.

## Build milestones (one PR)

**M1 — Ingestion + relational foundation (P1).** Package scaffold, `contracts.py`,
`constants.py`, `config.py`, `registry.py`/`_register.py`, `adapters/claude_code.py`,
`normalize/`, `relational/` (psycopg + `ddl/postgres/*.sql` + idempotent upsert),
`ingest/` (pipeline + incremental + redaction), CLI `list`/`ingest`/`doctor`, bash
dispatcher, `requirements.txt`, `docker-compose.yml`, CI smoke gate, unit tests.

**M2 — Kùzu graph (P3-graph).** `graph/schema.py`, `graph/builder.py` (MERGE-by-id),
`graph/query.py`, CLI `graph`, tests.

**M3 — LLM-as-Judge (P2).** `heuristic_label` + `session_kpi` tables; reuse
`benchmark_runner.judge` Protocol/registry + `claude_code_judge` invocation;
`judge/session_judge.py`, `judge/ollama_judge.py`, `judge/runner.py`, `judge/rubric.py`;
CLI `analyze`/`kpis`; tests.

**M4 — MCP server (P3-mcp).** `mcp/server.py`/`tools.py`/`resources.py`; CLI `mcp`; tests.

**M5 — Aider adapter (P4).** `adapters/aider.py` (the secondary multi-copilot
example; Kiro is out of scope — owned by the upstream kiro-analyzer); complete
cross-copilot normalization; fixtures + tests.

**M6 — FastAPI + Next.js Studio (P5).** `api/server.py`/`serve.py`/`routes/`; `studio/`
Next.js app (Dashboard, Session Detail w/ Insights/Agent-Tuning/Prompt-Coaching,
Knowledge-Graph explorer w/ Cytoscape, Analysis 5-step wizard, Settings, Agents);
CLI `serve`.

## CLI surface (`./scripts/session-analytics`)

`list` · `ingest` (`--copilot --root --since-days --developer-id --redact
--incremental/--full --dsn`) · `analyze` (`--judge {claude-code,ollama}:<model>
--rubric --workers --overwrite --session-id`) · `graph` (`--rebuild --session-id
--db-path`) · `kpis` · `mcp` · `serve` (`--api-port --ui-port --no-ui`) · `doctor`.
Wizard mapping: select→`ingest --since-days`, load→`ingest`, graph→`graph`,
judge→`analyze`, analyze→`kpis`.

## Idempotency / incremental / privacy

- Natural key `(copilot, native_session_id)` UNIQUE; session upsert `ON CONFLICT DO
  UPDATE RETURNING id`; children delete-then-reinsert per session in one txn. Graph
  `MERGE` by native id. `--full` re-parses safely.
- `ingest_state` gates re-ingest by file mtime / byte offset; `discover()` is cheap.
- `--redact {none,code,metadata-only}` (default `code`) applied before any DB write or
  judge prompt; API binds `127.0.0.1`; default judge is local Ollama (cloud judge is
  explicit opt-in).

## Schema columns added up front (avoid later migrations)

`developer_id` (E1), token+`cost_usd` columns (E5), `redaction_mode`/`content_redacted`
(E8), `session_embedding` + Kùzu `SIMILAR_TO` (E2), `benchmark_run_dir` (E9).

## Dependencies

- Python (`scripts/session_analytics/requirements.txt`): `psycopg[binary]`, `kuzu`,
  `fastapi`, `uvicorn[standard]`, `pyyaml`, `httpx`, `mcp`. Embeddings (E2) kept out of
  the default install behind `requirements-embeddings.txt`.
- Node (`studio/package.json`): `next`, `react`, `tailwindcss`, `cytoscape`,
  `cytoscape-fcose`.

## Test strategy

- Per-adapter unit tests with tiny committed fixtures (Claude Code JSONL incl.
  unknown-type skip + sidechain; Aider markdown).
- Registry-reset `conftest.py`; idempotency test (ingest twice → identical rows/ids;
  ingest grown session → converges); normalization table-driven; graph rebuild
  idempotency; MCP tool JSON contracts.
- CI smoke (`session-analytics-smoke.yml`, <90s, no LLM): unittest suite → `list` →
  `ingest` tiny fixture into a `postgres:16` service container → `graph --rebuild` →
  assert row/node counts.

## Verification

1. `PYTHONPATH=scripts:. python3 -m unittest discover -s scripts/session_analytics/tests`.
2. End-to-end on real local data: `ingest --copilot claude-code` → `graph --rebuild` →
   `kpis`; spot-check `doctor` counts.
3. `analyze --judge ollama:<model>`; confirm `heuristic_label` rows, turns unmutated.
4. MCP: call `search_sessions`/`get_session_details`; assert contracts.
5. Studio: `serve` → dashboard, session detail, graph explorer, settings test-connection.
6. CI smoke green.
7. `scripts/check-origin-alignment.sh session-analytics` before declaring done.

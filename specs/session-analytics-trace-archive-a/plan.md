---
spec_mode: full
feature_id: session-analytics-trace-archive-a
risk_category: privacy
justification: |
  Highest-privacy-surface slice in the analytics series: full (redacted)
  trace text vs 500-char previews. Risk is contained by reusing the exact
  ingest-trusted parse→redact path, explicit per-project opt-in (OFF by
  default), a redaction floor (never looser than ingest recorded), zero
  rows for opted-out/not-opted-in projects, and adversarial redaction
  tests. New tables only (no migration); stdlib only; portable LIKE search
  (no dialect fork). Scope bound by the merged shaping doc (PR #97).
status: approved
date: 2026-07-18
issue: 98
origin:
  issue: gosha70/code-copilot-team#98
  urls:
    - https://github.com/gosha70/code-copilot-team/issues/98
    - https://github.com/gosha70/code-copilot-team/pull/97
  origin_claim: |
    Issue #98 (E10 Slice A, scoped by the merged shaping doc): a
    trace_document table (redacted full text per turn, UNIQUE(session_ref,
    turn_ref, source_kind), no migration); an `archive` CLI behind the SAME
    E8 opt-out/redaction gate as ingest, explicit per-project opt-in only
    (trace_archive: true, OFF by default), incremental with explicit
    counters and a redaction floor (never looser than the session's
    recorded mode); portable substring search (CLI + GET /api/search,
    LIKE/ILIKE, escaped wildcards, documented non-ranked); a
    trace_documents export table. v1 excludes benchmark traces (A2), FTS
    (B), correlation/Studio UI (C), embeddings (E2), unredacted storage
    (never), external search engines, retention policies.
---

# Plan: session-analytics trace archive Slice A (E10, #98)

Grounded (verified 2026-07-18): `RawTurn.text` carries full turn text;
`ingest/redaction.py redact_text` is the single trusted redaction path
(store.py:183 uses it before truncating to preview); `ProjectOverride
(redaction_mode, ingest)` + pipeline's project-key resolution is the E8
gate; `ingest_state`/`should_ingest` is the incremental idiom; idempotent
`apply_ddl` lands new tables with no migration (E9 precedent); E7 export
and the api/server endpoint patterns are the surfacing points.

## Deliverables

1. **DDL** (`001_core.sql` + `003_indexes.sql`): `trace_document` per FR-1
   + `trace_archive_state` (ingest_state-shaped bookkeeping for the
   archive walk).
2. **Config** (`config.py`): `ProjectOverride.trace_archive: bool = False`
   + parsing (`projects.<key>.trace_archive`); constants for the key.
3. **`archive` module** (`scripts/session_analytics/archive.py` new): a
   pure, injectable core (`archive_sessions(refs, policy_fn, store_fn,
   ...) -> ArchiveStats` with as_dict) + the source walk reusing adapters;
   per-source resilient; redaction floor per FR-4.
4. **Store** (`relational/store.py`): `upsert_trace_document` (parameterized,
   ON CONFLICT on the UNIQUE key, caller-owned commit per the #92
   convention) + search query helper with LIKE-escaping.
5. **CLI** (`cli.py`): `archive` + `search` subcommands (house dispatch,
   exit codes, stderr partials on failure per the #92 pattern).
6. **API** (`api/server.py`): `GET /api/search?q=&limit=` (bounded limit,
   400 on empty q).
7. **Export** (`export.py` + constants): `trace_documents` table.
8. **Tests** (`tests/test_trace_archive.py`) per FR-8; **README** per FR-9.

## Design decisions to confirm at approval

- **D-granularity** — one `trace_document` row per TURN (`turn_ref` set),
  not per session: search hits resolve to turns, the UNIQUE key is natural,
  and re-archiving updates per-turn rows idempotently. A session-level
  concatenated row is cut. *(Recommend per-turn.)*
- **D-bookkeeping** — a separate `trace_archive_state` table mirroring
  `ingest_state` (mtime-gated, `--full` bypass) rather than piggybacking on
  ingest's rows: the two walks run independently (a source can be ingested
  but not archived, and vice versa). *(Recommend separate table.)*
- **D-search-limit** — API/CLI default limit 50, hard cap 500; snippet =
  ±120 chars around the first match, whitespace-trimmed. *(Recommend.)*
- **D-not-opted-in-visibility** — sessions skipped because their project
  never opted in are COUNTED (`sessions_skipped_not_opted_in`) but their
  content is never parsed into memory beyond what discovery requires.
  *(Recommend — the counter keeps coverage honest without touching
  content.)*
- **D-transactions** — caller-owned: one commit per archive run, stderr
  PROCESSED-only partials on failure (the settled #92 convention).
  *(Recommend.)*

## Out of scope

Everything the shaping doc defers: A2 (benchmark traces), B (FTS/dialect
fork), C (correlation + Studio UI), embeddings (E2), retention/TTL,
external search engines, any `ingest()`/schema-of-existing-tables change.

## Test strategy

Unit (stdlib, injected fakes): opt-in resolution truth table (default off /
explicit on / opt-out beats opt-in), redaction floor stricter-of cases,
LIKE-escape (`%`, `_`, mixed), snippet windowing edges, ArchiveStats
counter exactness, per-source failure resilience. sqlite integration:
archive fixture project (opted-in) → delete source → search finds text;
idempotent re-run; not-opted-in + opted-out → zero rows; adversarial
redaction fixtures (API keys, code blocks) provably redacted under
code/metadata-only; export streams; `apply_ddl` retrofit (drop + re-apply).
FastAPI: /api/search endpoint (fastapi/httpx venv). Postgres 16 via local
Docker: ILIKE search, ON CONFLICT upsert, end-to-end archive+search (CI
down — local battery per the standing protocol). Studio untouched →
`next build` stays green.

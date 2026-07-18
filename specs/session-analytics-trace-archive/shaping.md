# Shaping: E10 — agent trace archive (session-analytics)

Status: shaping only — no build authorized. Tracking #65 (E10 row: "Agent
trace archive integration — no groundwork — trace indexing, full-text
search, label correlation"). Shaped 2026-07-18 after the E-series arc
completed (E5/E7/E8/E9 shipped; Phase 4b harness gates passed).

## Problem

The analytics store deliberately keeps only **500-char redacted previews**
(`copilot_turn.content_preview`, `CONTENT_PREVIEW_CHARS`) of what agents
actually said and did. The full traces live in two places, both volatile:

1. **Copilot transcripts** — `~/.claude/projects/<hash>/<uuid>.jsonl`: raw,
   unredacted, and deleted by Claude Code's own transcript cleanup
   (`cleanupPeriodDays`, default ~30 days). A session older than the cleanup
   window is *permanently unrecoverable* — the store's preview is all that
   remains.
2. **Benchmark attempt traces** — `transcript.json` in runs trees: never
   committed (deliberately, per the #95 evidence-hygiene review) and pruned
   with the runs tree.

Consequences today: no way to search what happened across sessions ("which
sessions touched the pricing config?", "where did the agent propose X?");
no durable record once sources age out; the judge/labels/KPIs point at turns
whose underlying content may no longer exist anywhere.

E10's product gap: **durable, redaction-safe, searchable trace retention** —
not another analytics view.

## Current surfaces it builds on (verified)

- Adapters already parse full transcripts at ingest (`adapters/claude_code.py`)
  — the parse→redact machinery exists; only the *truncation to preview* loses
  content. The archive can reuse the exact pipeline path.
- E8 invariants (opt-out FIRST, `none/code/metadata-only` redaction before
  any DB write, CLI > project > global precedence) — the archive MUST sit
  behind the same gate; it raises the stakes of redaction correctness because
  full text >> preview.
- `ingest_state` (mtime/offset bookkeeping) — the incremental pattern for
  "archive only new/changed sources".
- New-table-no-migration pattern (`apply_ddl` re-runs `CREATE TABLE IF NOT
  EXISTS`; proven in E9's `benchmark_result`).
- E7 export contract (fixed columns, streamed, redaction-safe by
  construction) — an archived trace table exports the same way.
- E9 linkage — benchmark attempt dirs ↔ sessions via `benchmark_run_dir` /
  `benchmark_result`; an archived benchmark trace can carry the same key.

## Appetite

Two increments of the established E-slice size (each ≈ E7/E9-outcomes:
one issue → one PR → ~1 session including review). Anything that doesn't
fit is cut, not stretched.

## Candidate slices

### Slice A — archive + index + search (RECOMMENDED FIRST BET)

Make traces durable, discoverable, exportable. Nothing else.

- `trace_document` table (new — no migration): `session_ref`,
  `turn_ref` (nullable), `source_kind` (`copilot_transcript` in v1; the
  enum leaves room for `benchmark_attempt` in A2), **redacted full text**,
  `content_hash`, `source_path`, `archived_at`, `redaction_mode`. UNIQUE on
  (session_ref, turn_ref, source_kind).
- `archive` CLI: walks the same sources ingest reads, re-parses via the
  existing adapters, applies the SAME redaction/opt-out gate, stores full
  redacted text incrementally (ingest_state-style bookkeeping). Explicit
  counters (archived / skipped / opted_out / redacted_mode breakdown) per the
  house guardrail.
- **Search v0: portable substring search** (`LIKE`/`ILIKE`) over
  `trace_document` — one DDL, both dialects, honest about scale
  (single-operator local stores; the E7/E9 precedent says thousands of
  sessions, not millions). `search` CLI + `GET /api/search?q=` returning
  session/turn refs + highlighted snippets. Documented as **substring
  search, not ranked search** — no relevance ordering is promised or
  implied (results order by session/turn, deterministically).
- Export: `trace_documents` joins the E7 table set (redaction-safe by
  construction — it only ever holds redacted text).
- Acceptance sketch: archive a store's sessions; delete a source transcript;
  the archived text survives and is findable by search; opt-out projects
  produce ZERO trace_document rows; every row's text provably passed
  redaction (spot-check + tests); export streams it.

### Slice A2 — benchmark attempt traces (follow-up, not in A)

Settled 2026-07-18: benchmark `transcript.json` archiving stays OUT of
slice A. The condition was "include only if the same redaction/opt-out
contract applies cleanly" — it does not: benchmark attempts run in
throwaway worktrees with no stable E8 project identity (the project-key
resolver would key on a temp path or the fixture repo, neither of which is
the operator's opt-in surface), so "which project's policy governs this
trace?" has no clean answer today. A2 must first define that contract
(likely: archive-benchmark-traces is its own top-level opt-in, keyed by
benchmark rather than project, reusing the E9 `benchmark_result` link for
identity) before any implementation.

### Slice B — real FTS (sqlite FTS5 + postgres tsvector)

Upgrade search once the archive contract is proven. First genuine
per-dialect DDL fork in the package (today one `{PK}`-parameterized file
serves both) — needs its own design decision (per-dialect DDL files vs
conditional statements) and is exactly the rabbit hole to keep OUT of
slice A. Ship only if LIKE-search demonstrably hurts.

### Slice C — label correlation + Studio UI

"Sessions where the judge flagged rework AND the trace mentions X";
a Studio search page. Defer until A proves the archive contract — same
data-first-UI-second discipline that worked for E9 (#92 → #96).

## Rabbit holes (named so they stay fenced)

1. **Dialect FTS fork** (→ slice B, deliberately). LIKE v0 dodges it.
2. **Archive size growth** — full text ≈ MBs/session vs KBs of previews.
   Fence: archive is **opt-in per project** (reuse the E8 `projects` config
   block — a `trace_archive: true` flag), plus a documented size expectation.
   No compression/tiering engineering in v1.
3. **Re-redaction drift** — a session ingested under `code` redaction later
   archived under `none` (or config changed between runs) creates
   mixed-redaction storage. Fence: the archive stamps `redaction_mode` per
   row and NEVER stores looser than the session row's recorded mode;
   "effective redaction = mixed" surfacing already exists (E8 settings view).
4. **Raw-file copying temptation** — copying JSONL files verbatim would be
   simpler and WRONG (bypasses redaction entirely). The archive stores
   parsed, redacted text only. This is a no-go, not a trade-off.

## No-gos (v1)

- **No unredacted storage, ever** — the E8 gate applies before any write;
  a redaction bug in the archive is a privacy incident, not a data bug.
- No embeddings/semantic search (that's E2's lane).
- No external search dependency (no Elasticsearch/Meilisearch — stdlib +
  existing DB only, per the package's zero-infra philosophy).
- No Studio UI, no label correlation (slice C).
- No retention/TTL policies for the archive itself (archive = durable;
  deletion stays a manual/`forget`-style follow-up).
- No archiving of sources for opted-out projects — not even metadata.

## Risks

- **Privacy surface expansion** (highest): full-text redacted content is a
  bigger blast radius than previews if redaction has a gap. Mitigation:
  archive reuses the identical `redaction.redact_text` path ingest already
  trusts; tests must include adversarial redaction cases; opt-in default
  (archive OFF unless a project enables it) keeps the surface deliberate.
- **Source formats drift** (Claude Code JSONL is an external contract) —
  already true for ingest; the archive adds no new parser, so no new risk
  class, but archive failures must be per-source resilient (E6/E9 pattern:
  skip + count, never abort).
- **Store bloat on Postgres CI** — the smoke job's service container is
  ephemeral; only local stores grow. Documented, not engineered around.
- **LIKE-search disappointment** — if operators expect Google, v0 will feel
  thin. Mitigation: scope the promise ("substring search over redacted
  traces"); slice B exists.

## Recommended first bet

**Slice A as one issue/PR** (`session-analytics-trace-archive`), appetite
one increment: table + `archive` CLI (opt-in per project, explicit
counters) + substring search (CLI + API) + export + docs/tests. Slice B
ships only on demonstrated search pain; slice C only after A's contract
survives real use. This matches the maintainer's 2026-07-18 direction:
*make traces discoverable and exportable first; defer correlation/UI until
the archive contract is proven.*

## Settled at shaping review (maintainer, 2026-07-18)

The three betting-table questions were resolved before this doc entered
repo history:

1. **Opt-in default: explicit opt-in only.** The archive is OFF for every
   project until its config enables it (`trace_archive: true` in the E8
   `projects` block). No implicit enablement, no global default-on.
2. **Benchmark traces: OUT of slice A → A2**, because the E8
   redaction/opt-out contract does not apply cleanly to benchmark worktrees
   (no stable project identity). A2 defines its own opt-in contract first —
   see the Slice A2 section.
3. **Substring search accepted for v1** on the condition it is documented
   as *portable substring search, not ranked search* — no relevance
   ordering promised. FTS remains slice B, gated on demonstrated pain.

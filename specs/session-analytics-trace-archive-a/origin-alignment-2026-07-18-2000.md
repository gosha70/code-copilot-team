# Origin alignment check — session-analytics-trace-archive-a

Origin: https://github.com/gosha70/code-copilot-team/issues/98
(scope authority: specs/session-analytics-trace-archive/shaping.md, PR #97)

Origin claim:
> Issue #98 (E10 Slice A, scoped by the merged shaping doc): a
> trace_document table (redacted full text per turn, UNIQUE(session_ref,
> turn_ref, source_kind), no migration); an `archive` CLI behind the SAME
> E8 opt-out/redaction gate as ingest, explicit per-project opt-in only
> (trace_archive: true, OFF by default), incremental with explicit counters
> and a redaction floor (never looser than the session's recorded mode);
> portable substring search (CLI + GET /api/search, LIKE/ILIKE, escaped
> wildcards, documented non-ranked); a trace_documents export table. v1
> excludes benchmark traces (A2), FTS (B), correlation/Studio UI (C),
> embeddings (E2), unredacted storage (never), external search engines,
> retention policies.

Working claim:
> specs/session-analytics-trace-archive-a/{spec.md,plan.md,tasks.md} bind
> exactly that scope (FR-1..FR-9), approved by the user 2026-07-18 with all
> five defaults confirmed: D-granularity = one row per turn; D-bookkeeping =
> separate trace_archive_state; D-search-limit = default 50 / cap 500 /
> snippet ±120; D-not-opted-in-visibility = counted, no content persisted;
> D-transactions = caller-owned single commit + PROCESSED-only failure
> partials. Both hardenings confirmed BINDING: FR-4 redaction floor
> (stricter of current config and stored ingest mode) and FR-8 adversarial
> tests (secrets/code provably redacted; opt-out/not-opt-in provably zero
> rows). User re-emphasized: backend/API tight — no Studio, no benchmark
> traces, no FTS, no embeddings. No implementation exists yet on branch
> feat/session-analytics-trace-archive-a-98.

Verdict: aligned
Confidence: high

Checked 2026-07-18 by re-reading issue #98, the merged shaping doc's
"Settled at shaping review" section, and the grounded surfaces (RawTurn.text,
ingest/redaction.py redact_text, ProjectOverride, ingest_state idiom,
idempotent apply_ddl, E7 export + api/server patterns). Plan flipped to
status: approved with explicit user approval.

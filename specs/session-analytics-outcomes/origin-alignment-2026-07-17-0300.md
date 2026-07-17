# Origin alignment check — session-analytics-outcomes

Origin: https://github.com/gosha70/code-copilot-team/issues/92

Origin claim:
> Issue #92 (E9 outcomes slice): a new benchmark_result table (stable identity
> benchmark_id/task_id/backend_id/run_id/attempt + result/scores/diff stats,
> UNIQUE(run_dir), nullable session_ref) populated by correlate from each
> attempt dir's score.json (missing/malformed counted, never fatal;
> out-of-scope backends stored without session_ref); explicit counters
> extended (scores_ingested/scores_missing); caller-owned single commit with a
> failure-time partial summary (closing the #91 follow-up); a by-result
> dashboard aggregate on GET /api/dashboard/benchmark; the benchmark_results
> export table. No Studio UI, no fuzzy fallback.

Working claim:
> specs/session-analytics-outcomes/{spec.md,plan.md,tasks.md} bind exactly
> that scope (FR-1..FR-8), with the slice approved by the user (2026-07-17)
> and five decisions confirmed at plan approval: D-store-outcomes-for-foreign-
> backends = yes (link stays claude-code-scoped); D-upsert-key =
> UNIQUE(run_dir); D-partial-summary-format = same JSON shape to stderr;
> D-aggregate-cost-source = linked sessions' turn costs only; and the user's
> D-parse-strictness guardrail: tolerant of missing/partial fields, strict
> about malformed types that would corrupt aggregates (bad result enum /
> non-numeric / non-bool → scores_missing, never coerced). No implementation
> exists yet on branch feat/session-analytics-outcomes-92.

Verdict: aligned
Confidence: high

Checked 2026-07-17 by re-reading issue #92, the #91 shipped pipeline
(correlate.py / store.py / cli.py in 4f9c9c5), score.json's writer + schema
(run.py, score.schema.json: result enum pass/fail/error/timeout, scores +
derived blocks), and the apply_ddl CREATE-IF-NOT-EXISTS idempotency that makes
a new table migration-free. Plan flipped to status: approved with explicit
user approval; the four defaults + the parse-strictness guardrail confirmed.

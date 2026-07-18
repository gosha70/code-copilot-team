# Origin alignment check — session-analytics-benchmark-ui

Origin: https://github.com/gosha70/code-copilot-team/issues/96

Origin claim:
> Issue #96 (E9 Studio slice, backend-free first pass): a Benchmark
> comparison view over the EXISTING GET /api/dashboard/benchmark payload —
> typed api.benchmark() fetcher; coverage stats (linked/unlinked sessions,
> distinct attempts); per-result table/cards with exactly attempts,
> linked_sessions, total_cost_usd, avg_duration_seconds; honest empty state
> pointing at correlate; no API/schema/store change unless the payload proves
> insufficient (then stop and re-scope). Reuses Card/Stat/useApi/formatCost;
> one-shot fetch; next build is the gate.

Working claim:
> specs/session-analytics-benchmark-ui/{spec.md,plan.md,tasks.md} bind exactly
> that scope (FR-1..FR-6), approved by the user 2026-07-18 with all four
> defaults confirmed: D-placement = new /benchmark page + nav tab;
> D-presentation = coverage Stat row above a per-result comparison table;
> D-duration-format = humanized, em-dash for unavailable; D-refresh =
> one-shot only. The user re-emphasized the FR-4 circuit breaker as STRICT:
> if the payload cannot support the UI cleanly, stop and rescope — never
> expand the backend inside #96. No implementation exists yet on branch
> feat/session-analytics-benchmark-ui-96.

Verdict: aligned
Confidence: high

Checked 2026-07-18 by re-reading issue #96, the shipped payload (dashboard.py
benchmark_correlation + benchmark_outcomes merged at /api/dashboard/benchmark,
endpoint-tested), and the studio surfaces (api.ts get<T> fetcher pattern,
TABS nav, Card/Stat/Loading/ErrorNote/useApi/formatCost components). Plan
flipped to status: approved with explicit user approval.

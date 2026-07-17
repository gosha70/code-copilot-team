# Origin alignment check — session-analytics-correlate

Origin: https://github.com/gosha70/code-copilot-team/issues/91

Origin claim:
> Issue #91 (E9 link + export + summary slice): a `session-analytics correlate
> --runs-root <dir>` command that scans benchmark run-record.json files and sets
> copilot_session.benchmark_run_dir on the matching (copilot='claude-code',
> session_id) row via a session_id EXACT-join only (null-session-id / unmatched
> runs reported, not fuzzy-matched); a testable correlate core with an injected
> link_fn; benchmark_run_dir added to the sessions export; a backend dashboard
> aggregate of linked vs unlinked sessions. No schema change (column already
> ships), no benchmark-outcome ingestion, no Studio UI, no project_path/
> time-window fallback (deferred).

Working claim:
> specs/session-analytics-correlate/{spec.md,plan.md,tasks.md} bind exactly that
> scope (FR-1..FR-8), with the E9 scope chosen by the user (2026-07-16) as the
> link + export + summary slice (session_id exact-join only), and four defaults
> confirmed at plan approval: D-run-dir-granularity = per-attempt dir;
> D-collision = last-writer-wins + warning; D-summary-wiring = backend dashboard
> payload; D-copilot-scope = claude-code only. Plus the user's guardrail: the
> command summary must make unlinked/null-session records explicitly visible so
> coverage gaps are not hidden. No implementation exists yet on branch
> feat/session-analytics-correlate-91.

Verdict: aligned
Confidence: high

Checked 2026-07-16 by re-reading issue #91, the #65 prioritization + Tier-2
scoping, and the grounded surfaces (the already-shipped inert benchmark_run_dir
column; session_id captured on both sides — benchmark run-record.json
backend.metadata.session_id and copilot_session.session_id; CREATE-only
apply_ddl so no migration is needed; store/export/dashboard surfacing points).
Plan flipped to status: approved with explicit user approval; the exact-join
slice + the four defaults + the visible-coverage-gap guardrail confirmed.

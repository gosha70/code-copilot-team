# Origin alignment check — session-analytics-benchmark-step

Origin: specs/session-analytics-benchmark-step/origin/2026-09-08-owner-directive.md
(owner messages of 2026-09-08; no GitHub issue by the owner's standing rule)

Origin claim:
> The Benchmark page must explain what it shows and offer the action
> that fills it, instead of four zero tiles and a CLI command. That
> means: a runs-folder setting, "Link benchmark runs" as a pipeline
> step (skipped, not failed, when unset), the page in truthful states
> from the store, and no new GitHub issue.

Working claim:
> specs/session-analytics-benchmark-step/{spec.md,plan.md,tasks.md} bind
> that scope (FR-1..FR-10) and supersede the 2026-07-18 backend-free
> Benchmark UI spec's FR-3/FR-4/FR-5 and Studio-only constraint, which
> the owner's ask cannot be met inside. The reviewer's five P1s at
> a7f01d7 (polling race, inferred cause, "organic", the Claude-Code-only
> linking boundary, the stale spec) are folded into FR-5, FR-7, FR-8 and
> this bundle. Implementation is on branch feat/benchmark-step (PR #321).

Verdict: aligned
Confidence: high

Checked 2026-09-08 by re-reading the owner's messages, the proposal
(§3 of doc_internal/plans/studio-graph-search-benchmark-2026-09-08.md,
gitignored), the shipped correlate contract (#91: Claude Code-only exact
join; outcomes for every backend, #92), and the reviewer's findings on
PR #321 at a7f01d7.

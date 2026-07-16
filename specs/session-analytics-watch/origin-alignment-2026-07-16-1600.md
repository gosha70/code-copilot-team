# Origin alignment check — session-analytics-watch

Origin: https://github.com/gosha70/code-copilot-team/issues/89

Origin claim:
> Issue #89 (E6 polling slice): a `session-analytics watch` command that loops
> incremental ingest() every --interval seconds until SIGINT/SIGTERM (clean
> exit), resilient to per-cycle errors, logging IngestStats each cycle; a
> testable run_watch(ingest_fn, interval, iterations, sleep_fn, should_stop)
> core; studio useApi gains an optional refresh interval + a live indicator,
> opted into by the dashboard + sessions list. No WebSocket, no native watcher,
> no new server protocol (deferred to a later E6 issue). Grounded in cheap
> incremental ingest + one-shot useApi.

Working claim:
> specs/session-analytics-watch/{spec.md,plan.md,tasks.md} bind exactly that
> scope (FR-1..FR-8), with the E6 scope chosen by the user (2026-07-16) as the
> polling slice (no WS/native-watcher/new-protocol), and four low-stakes
> defaults confirmed at plan approval: D-interval-default = 15s (watch + studio,
> both configurable); D-refresh-scope = dashboard + sessions list only;
> D-signal-handling = SIGINT + SIGTERM stop cleanly (EXIT_OK, no traceback);
> D-cadence = ingest first then sleep. No implementation exists yet on branch
> feat/session-analytics-watch-89.

Verdict: aligned
Confidence: high

Checked 2026-07-16 by re-reading issue #89, the #65 prioritization + Tier-2
scoping, and the grounded surfaces (cheap incremental ingest via should_ingest,
reusable ingest(), argparse CLI dispatch, one-shot useApi in the studio). Plan
flipped to status: approved with explicit user approval; the polling-slice
scope + the four defaults confirmed.

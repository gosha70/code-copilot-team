---
spec_mode: full
feature_id: session-analytics-watch
risk_category: integration
justification: |
  Adds a `watch` CLI (incremental-ingest polling loop) + an opt-in studio
  auto-refresh. Low risk — reuses the existing ingest() unchanged, stdlib-only
  (time/signal), no schema/redaction change, no new server protocol. The loop
  core is injectable for deterministic tests (no real sleep/DB). Studio change
  is a backward-compatible useApi option. Tracking #65; builds on E5/E8/E7.
status: approved
date: 2026-07-16
issue: 89
origin:
  issue: gosha70/code-copilot-team#89
  urls:
    - https://github.com/gosha70/code-copilot-team/issues/89
  origin_claim: |
    Issue #89 (E6 polling slice): a `session-analytics watch` command that
    loops incremental ingest() every --interval seconds until SIGINT/SIGTERM
    (clean exit), resilient to per-cycle errors, logging IngestStats each cycle;
    a testable run_watch(ingest_fn, interval, iterations, sleep_fn, should_stop)
    core; studio useApi gains an optional refresh interval + a live indicator,
    opted into by the dashboard + sessions list. No WebSocket, no native
    watcher, no new server protocol (deferred). Grounded in cheap incremental
    ingest + one-shot useApi.
---

# Plan: session-analytics watch (E6 polling slice)

Grounded (verified 2026-07-16): `ingest/incremental.py should_ingest`
mtime-gates re-ingest (cheap re-scan); `ingest()` (pipeline.py) is the reusable
entry; the CLI is argparse subcommands + a `_CMD` dispatch (`cli.py`); the
studio fetches once via `useApi` (`components/ui.tsx`), no polling/WS/SSE.

## Deliverables

1. **`watch` core** (`scripts/session_analytics/watch.py` new): `run_watch(
   ingest_fn, interval, *, iterations=None, sleep_fn=time.sleep,
   should_stop=None)` — ingest-then-sleep loop, per-cycle exception caught +
   logged, stops on `iterations` exhaustion or `should_stop()`.
2. **`watch` CLI** (`cli.py`): new subcommand wiring the real `ingest()` (config
   redaction/projects/pricing, like `_cmd_ingest`) + `time.sleep` +
   `iterations=None`; a SIGINT/SIGTERM handler flips a stop flag → clean
   `EXIT_OK`; per-cycle IngestStats logged.
3. **Studio** (`components/ui.tsx` + `app/page.tsx` + `app/sessions/page.tsx`):
   `useApi` optional refresh interval (`setInterval`, cleared on cleanup);
   dashboard + sessions opt in; a small "auto-refreshing (every Ns)" indicator.
4. **Tests** (`tests/test_watch.py`) per FR-7; **docs** (README) per FR-8.

## Design decisions to confirm at approval

- **D-interval-default** — default `--interval` = 15s; studio auto-refresh
  interval = 15s to match. *(Recommend — responsive without hammering; both
  configurable.)*
- **D-refresh-scope** — the dashboard and the sessions list auto-refresh; other
  pages stay one-shot. *(Recommend — those are the "live" views.)*
- **D-signal-handling** — SIGINT (Ctrl+C) and SIGTERM both stop the loop
  cleanly between cycles (finish/skip the current sleep, exit EXIT_OK, no
  traceback). *(Recommend.)*
- **D-cadence** — ingest FIRST, then sleep, so the first cycle runs immediately
  and Ctrl+C during a sleep exits promptly. *(Recommend.)*

## Out of scope

- Native fswatch/inotify watcher; SSE/WebSocket push; per-event streaming
  (a later E6 issue).
- Any change to `ingest()`, the schema, redaction, or the judge.

## Test strategy

Unittest (stdlib): `run_watch` with an injected `ingest_fn` (call counter) +
`sleep_fn` (records intervals, never sleeps) + `iterations` / `should_stop` —
assert exact cycle count, that a raising cycle doesn't stop the loop, that
`sleep_fn` gets the interval, and clean stop. No real time, DB, or signals in
the unit tests (signal wiring is thin CLI glue, exercised via a `should_stop`
callback). Studio: `next build` (the studio CI job) validates the useApi
change; no JS test runner exists.

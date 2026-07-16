# Spec: session-analytics watch (E6 live/polling slice)

Issue #89 (E6, Tier-2 from the #65 prioritization). Base: the #63 pipeline +
E5/E8/E7. Groundwork: incremental ingest is cheap (`ingest/incremental.py`
`should_ingest` mtime-gates re-ingest), the studio fetches once via `useApi`
(no polling/WS/SSE), and there is no watcher/push infra. Scope = the **polling
slice** (2026-07-16 decision): near-real-time via a re-ingest loop + studio
interval-refresh — no WebSocket, no native watcher dep, no new server protocol.

## User Scenarios

- US1: As an operator, I run `session-analytics watch` and it keeps the store
  fresh — re-ingesting new/changed sessions every few seconds — until I press
  Ctrl+C, which stops it cleanly. A transient error in one cycle is logged and
  the watch keeps going.
- US2: As a studio user, with `watch` running the dashboard reflects new data
  without a manual reload (it auto-refreshes on an interval), and I can see it
  is auto-refreshing.

## Requirements

- FR-1: **`watch` CLI** — `session-analytics watch [--interval <sec>] [--dsn
  <dsn>] [--copilots <c> ...]`. Loop: run incremental `ingest()` (with the same
  config-resolved redaction/projects/pricing as `ingest`) → sleep `--interval`
  → repeat, until SIGINT/SIGTERM → clean exit `EXIT_OK`. Default interval
  documented (recommend 15s). Ingest is incremental (not `--full`).
- FR-2: **Testable core** — `run_watch(ingest_fn, interval, *, iterations=None,
  sleep_fn=time.sleep, should_stop=…)` runs `iterations` cycles (`None` =
  until stopped): each cycle calls `ingest_fn()` then `sleep_fn(interval)`
  (ingest first, so the first cycle is immediate). The CLI wires the real
  ingest + `time.sleep` + `iterations=None`; tests inject fakes.
- FR-3: **Resilient + interruptible** — an exception from a single `ingest_fn`
  cycle is caught, logged, and the loop CONTINUES (never fatal). SIGINT/SIGTERM
  (or a `should_stop` signal) ends the loop between cycles and exits cleanly
  (no traceback on Ctrl+C).
- FR-4: **Per-cycle reporting** — each cycle logs the `IngestStats` summary
  (ingested / skipped / opted-out counts) so the operator sees progress.
- FR-5: **Studio auto-refresh** — `useApi` gains an OPTIONAL refresh interval;
  when set it re-invokes the loader every interval (`setInterval`, cleared on
  unmount / deps change). Backward-compatible (absent = one-shot as today).
  The dashboard and the sessions list opt in.
- FR-6: **Live indicator** — an auto-refreshing page shows a subtle
  "auto-refreshing (every Ns)" indicator so the behavior is visible.
- FR-7: **Tests** — `run_watch`: bounded `iterations` runs exactly that many
  ingest cycles; a cycle raising does not stop the loop (next cycle still
  runs); `sleep_fn` is called with the interval each cycle; a `should_stop`
  ends the loop cleanly. Injected `ingest_fn`/`sleep_fn` — no real sleep, no
  real DB, no real time. Studio validated by `next build`.
- FR-8: **Docs** — a README `watch` section (command, interval, Ctrl+C, the
  studio auto-refresh).

## Constraints

- Python stdlib only (`time`, `signal`); no new dependencies.
- `watch` REUSES `ingest()` unchanged — no ingest-logic duplication.
- The loop is resilient (per-cycle error non-fatal) and interruptible
  (SIGINT/SIGTERM → clean, non-error exit).
- Studio auto-refresh is opt-in per page; `useApi` stays backward-compatible
  (interval optional).
- No new server protocol, no WebSocket, no native file watcher (deferred to a
  later E6 issue).
- One issue per PR: this bundle covers exactly #89.

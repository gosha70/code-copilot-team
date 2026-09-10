---
feature_id: auto-build-cap-alerts
spec_mode: lightweight
status: approved
date: 2026-09-10
issue: none
origin:
  transcripts:
    - specs/auto-build-cap-alerts/origin/2026-09-10-second-unattended-run.md
  user_messages:
    - "2026-09-10: 'Then run the next real feature and reconsider D against the additional evidence'"
  origin_claim: |
    An auto-build run that is burning its cost or wall-clock cap, or has
    passed it, should appear among the Team tab's alerts, derived from
    its ledger on every read like every other alert, so a person sees
    it without opening the Runs tab. Chosen as the small feature for
    the second real unattended auto-build run (2026-09-10).
---

# Spec: cap alerts for auto-build runs

## Problem

Run 1 of 2026-09-09 overran its wall-clock cap by three minutes inside
one long step; run 4 ended at 73% of its cost cap. The Runs tab shows
both after the fact. The Team tab's Alerts card (`api/alerts.py`,
`GET /api/team/alerts`, `session-analytics team alerts`) knows budgets
and runaway sessions but nothing about auto-build runs, so a run that
is about to hit a cap, or has passed one, is invisible where alerts are
looked at.

## User scenarios

- US1: As the operator, while an unattended run is in progress and its
  spend reaches 80% of its cost cap, or its clock reaches 80% of its
  wall-clock cap, I see a warning on the Team tab's Alerts card and in
  `team alerts`, naming the run, the figure and the cap. At 100% the
  alert is a breach.
- US2: As the operator, `team alerts --fail-on warning` in a cron job
  exits 1 when a live run is at 80% of a cap, the same way it does for a
  budget.

## Requirements

- FR-1: `api.alerts.auto_build_alerts(runs, *, now=None)` takes the
  `runs` list of `api.auto_build.list_runs()` and returns one alert per
  run per cap that is at or above `BUDGET_WARNING_SHARE` (0.8) of the
  cap, for runs that have not `concluded`. Cost share is
  `(cost.metered_usd + cost.estimated_usd) / caps.cost_usd`; wall-clock
  share is `elapsed_sec / caps.wall_clock_sec`. A cap that is null or
  not positive yields no alert. Level is `warning` at or above the share
  and below the cap, `breach` at or above the cap.
- FR-2: Each alert is a dict with `kind` in {`auto-build-cost`,
  `auto-build-wall-clock`}, `level`, `scope: "run"`, `subject: {key,
  feature_id, ledger, pr_number}`, `window: null`, `figures` carrying
  the spent/elapsed value, the cap and the share (rounded to two
  decimals), and a `message` that names the feature id, the run key,
  the value against the cap as a percentage, and for cost the estimated
  portion when it is non-zero (e.g. "auto-build run team-developer-aliases
  (47908-474720888) has spent $7.30 of its $10.00 cap (73%, $2.00
  estimated) and is still running").
- FR-3: `all_alerts()` includes the auto-build alerts whenever a
  `runs` list is passed (new keyword argument `runs`, default `None`
  meaning "not evaluated"), sorted with the others by level, and the
  report gains `auto_build: {evaluated: bool, live_runs: int}`.
  `render_alerts()` prints the auto-build line like the others and, in
  the configuration lines, says whether auto-build runs were evaluated
  and how many were live.
- FR-4: `GET /api/team/status`, `GET /api/team/alerts` and
  `session-analytics team status|alerts` evaluate auto-build alerts by
  reading the ledgers through `api.auto_build.list_runs()` with the
  loaded `auto_build` config; a ledger root that is not a directory
  yields `evaluated: true` with zero runs and no alert; the existing
  exit-code behaviour of `team alerts --fail-on` applies to them.

## Constraints

- Python stdlib only; no new table, no new config key; alerts stay
  derived; the Runs tab and the ledger format are unchanged.
- Existing alert kinds, messages and tests are unchanged.
- The Studio's Alerts card renders the new kinds without change (it
  renders `level` and `message` generically); no Studio change is in
  scope.

## Out of scope

Alerts for concluded runs; a Studio link from an alert to the Runs tab;
notifications.

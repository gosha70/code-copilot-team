---
feature_id: pi-team-plane-d
spec_mode: lightweight
status: approved
date: 2026-09-08
issue: 174
origin:
  issue: gosha70/code-copilot-team#174
  transcripts:
    - specs/pi-team-plane-d/origin/2026-09-08-owner-decisions.md
  origin_claim: |
    "Runaway recursive agent loops can be audited, alerted, or flagged
    if they breach budget bounds" (issue #174 acceptance), on the
    shared Postgres team store with trusted-LAN access the owner chose
    on 2026-09-08; owner on the same day: proceed with #174 after the
    team store (PR #324) merged.
---

# Spec: budgets, runaway detection and alerts over the team store (#174 Slice D)

## Why this shape

The plane is one shared store every developer writes to (PR #324).
Everything an alert needs is already in it: priced turns with
timestamps, errors per turn, heartbeats. So Slice D is a read-only
evaluation over the store — reproducible from the rows, which is what
"audited" means here — plus the thresholds as configuration and two
surfaces: the Team tab and a CLI command whose exit code can drive a
cron job or a CI gate. No daemon, no notification service, no schema
change; nothing is fabricated for a source that lacks prices (E5 rule).

## User scenarios

- US1 (infrastructure engineer): I set a daily and a monthly team
  budget, and per-developer and per-project daily budgets. The Team
  tab shows a banner when spend passes 80% of any of them and a red
  one past 100%, naming who or what and by how much, and saying when
  unpriced turns mean the true spend is higher.
- US2 (engineering manager): a session that keeps producing turns at
  a high rate, or whose recent turns are mostly errors, or that is
  spending fast, is flagged on the Team tab with the developer, the
  project, the session and the figures, so I can look at it.
- US3 (operator): `session-analytics team alerts` prints the alerts
  and exits non-zero on a breach, so a cron job or a pipeline step can
  page or stop.

## Requirements

- FR-1 **Budgets are configuration**, not schema: `team.budgets`
  in `defaults.json` with `team_daily_usd`, `team_monthly_usd`,
  `developer_daily_usd`, `project_daily_usd`, each `null` (no budget)
  by default; env `CCT_SA_BUDGET_TEAM_DAILY_USD`,
  `CCT_SA_BUDGET_TEAM_MONTHLY_USD`, `CCT_SA_BUDGET_DEVELOPER_DAILY_USD`,
  `CCT_SA_BUDGET_PROJECT_DAILY_USD`; Settings → Team group with those
  four plus the active window. A non-numeric or negative value refuses
  loudly at config load, naming the key.
- FR-2 **Runaway thresholds are configuration**: `team.runaway` with
  `recent_minutes` (60), `max_turns_recent` (300), `max_error_share`
  (0.5, over the last `recent_turns` = 50 turns of a session),
  `max_cost_recent_usd` (20), `min_turns_for_error_share` (20); env
  `CCT_SA_RUNAWAY_*`. A session is *recent* when its newest turn is
  within `recent_minutes` of now.
- FR-3 **Evaluation** (`api/alerts.py`, pure over the store):
  `budget_alerts(status, budgets)` from the team status windows —
  `warning` at ≥ 80%, `breach` at ≥ 100% of a budget, per scope
  (team/day, team/month = 30 days, developer/day, project/day); each
  alert carries scope, subject, spent, budget, share, and
  `unpriced_turns` for that window (so the message can say "true spend
  is higher"). `runaway_alerts(db, thresholds, now)` over recent
  sessions: `turns` (turns in the last `recent_minutes` >
  `max_turns_recent`), `errors` (error share over the last
  `recent_turns` > `max_error_share`, only when at least
  `min_turns_for_error_share` recent turns exist), `cost` (priced cost
  in the last `recent_minutes` > `max_cost_recent_usd`); each carries
  developer, project, session id, the figures and the threshold.
  Every alert has `kind`, `level` (`warning` | `breach`), `subject`,
  `message` (one sentence, in words), `figures`.
- FR-4 **Surfaces.** `GET /api/team/alerts` (and `alerts` embedded in
  `/api/team/status`); the Team tab shows a banner list above the
  tables — red for breach, amber for warning — each with its figures
  and a link to the session where there is one; empty state says which
  budgets are set and which are not. CLI `session-analytics team
  alerts [--json] [--fail-on warning|breach]` prints them and exits 1
  when an alert at or above the chosen level exists (default `breach`),
  else 0 — the flag for cron and CI.
- FR-5 **Honesty.** A window with no priced turn never breaches;
  unpriced priceable turns are counted and named on every budget
  alert; a runaway alert names the exact figures and the threshold;
  no alert is stored — they are re-derived on every read (the audit is
  the rows). Liveness is not used as a runaway signal (last-seen only).
- FR-6 **Noise policy** is the pages': probe/temp sessions never alert.
- FR-7 **Docs.** Cookbook §8.5 "Budgets and runaway alerts": what to
  set, what a warning and a breach mean, the cron/CI recipe with the
  exit code, and that alerts are derived, not stored.
- FR-8 **Verification.** Unit tests: budgets at 79/80/100%, no priced
  turn never breaches, unpriced turns named, each runaway kind on a
  seeded store including the min-turns guard and the noise exclusion;
  the route; the CLI exit codes; states-check for the banner states;
  the smoke job's Postgres step extended with a breach.

## Constraints

- No new GitHub issue; the PR references #174 and does not close it
  unless the owner says the epic is complete.
- No daemon or push channel; the CLI exit code is the alarm.
- No schema change; no alert storage.
- The pi runtime is unchanged.

## Out of scope

Automatic termination of a runaway session (the #190 unattended-core
circuit breaker is the place for that, and it already stops its own
runs); per-turn Pi tokens; email/Slack delivery.

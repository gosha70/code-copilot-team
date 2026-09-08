---
feature_id: pi-team-plane-b2c
spec_mode: lightweight
status: approved
date: 2026-09-08
issue: 174
origin:
  issue: gosha70/code-copilot-team#174
  transcripts:
    - specs/pi-team-plane-b2c/origin/2026-09-08-owner-decisions.md
  origin_claim: |
    Cross-team visibility into active autonomous runs, global token
    spend and aggregated metrics for a team of Pi/Claude Code
    developers: sessions report progress to a central interface,
    `pi-team status` shows precise tracking for all current team
    tasks. Decided 2026-09-08: the central plane is one shared
    Postgres store every developer writes to, identity is the derived
    developer_id with access by database credentials on a trusted LAN.
---

# Spec: the team store — live registry, cross-developer rollups, Team tab (#174 Slices B2 + C + E)

## Why now

Slice A (local `/cct:team` wiring, #185) and B1 (derived developer
identity + local heartbeat, #187) are merged. The shaping doc left
B2–E blocked on two decisions; the owner made them on 2026-09-08
(origin). With them made, the pieces already in the repo compose into
the plane with little new machinery: the store is dual-dialect with a
Postgres DSN and a compose file; `developer_id` is populated; the
`local_heartbeat` table holds last-seen state per (project, developer);
the cost engine prices turns; the Studio auto-refreshes.

## User scenarios

- US1 (engineering manager): I open the Studio's **Team** tab against
  the team store and see every developer, whether they are active
  right now, what they are working on (project, phase, feature), and
  what their sessions cost today, this week and this month.
- US2 (infrastructure engineer): I see cost by developer, by
  repository and by time window across the whole team, with unpriced
  work shown as unpriced, never as free.
- US3 (developer): I point my `CCT_SA_DB` at the team DSN, keep
  `session-analytics watch` running, and my sessions and heartbeats
  appear in the team view within the watch interval; nothing else
  changes in how I work.
- US4 (anyone at a terminal): `session-analytics team status` prints
  the same table the tab shows.

## Requirements

- FR-1 **Team status payload.** `GET /api/team/status` returns
  `{store: {dialect, shared}, now, active_window_seconds, developers[],
  projects[], totals}`. Per developer: id, display name, `liveness`
  (`active` = a heartbeat within the window, `idle` = a heartbeat
  outside it, `unknown` = no heartbeat ever), the latest heartbeat's
  project, phase, feature id, checkpoint count and time, and sessions
  / turns / cost for today, 7 days, 30 days. Per project: developers,
  sessions and cost per window. Totals: developers, active now, cost
  per window, priced vs priceable turns.
- FR-2 **Liveness is last-seen, never alive/dead.** The window
  (default 300 s) is a named constant in `defaults.json`
  (`team.active_window_seconds`) and returned in the payload; the
  page says "active in the last N minutes", not "online".
- FR-3 **Windows are by turn timestamp** (`copilot_turn.timestamp`),
  UTC, bucketed in Python after one 30-day scan on either dialect
  (timestamps are ISO text in more than one shape, so a string compare
  at a boundary would misplace a turn); a turn without a timestamp
  counts in no window and is reported in `totals.unstamped_turns`.
- FR-4 **Cost honesty (E5 rule).** Cost sums priced turns only;
  `priced_turns` / `priceable_turns` accompany every cost figure; the
  page shows an em dash for a window with no priced turn.
- FR-5 **Noise policy** is the pages': lists and aggregates exclude
  probe/temp sessions; a heartbeat is never noise.
- FR-6 **Store awareness.** `store.shared` is true when the DSN's
  dialect is Postgres; the Team tab on a SQLite store says it is a
  local, single-developer store and links to the cookbook's team
  setup. Nothing else differs between dialects.
- FR-7 **Team tab** (`/team`, nav after Sessions): a developers table
  (liveness dot, current work, windows), a projects table, totals,
  auto-refreshing on the watch interval; all states pure and asserted
  in `states-check.mjs` (`lib/teamView.ts`).
- FR-8 **CLI.** `session-analytics team status [--window N]` prints
  the developers table from the same function; exit 0. The pi
  adapter's `pi-code team status` is unchanged (it reads the local
  ledger, a different concern — see plane-shaping "link, don't fuse").
- FR-9 **Setup path documented** (cookbook §"A team store"): compose
  up Postgres, share the DSN, every developer sets `CCT_SA_DB` and
  runs `watch`; what the trusted-LAN decision means; that heartbeats
  arrive at the watch interval.
- FR-10 **Verification.** Unit tests for the payload on a seeded
  SQLite store with three developers, heartbeats inside and outside
  the window and none, turns in and out of windows, unpriced turns;
  the API route; the CLI; states-check for the tab; the Postgres
  dialect asserted in CI by the smoke job's `postgres:16` service (a
  heartbeat 30 s old is active, one 3 h old is idle, the store reports
  itself shared).

## Constraints

- No new GitHub issue; PR references #174 and does not close it (D
  remains).
- No daemon beyond Postgres; no non-loopback session-analytics API.
- No app-level auth (owner's decision); the cookbook says so plainly.
- The team ledger (Slice A) and the analytics store stay separate.
- Pi per-turn tokens are not fabricated; Pi cost stays pass-through.

## Out of scope (Slice D, next PR)

Budgets, breach detection, runaway-loop detection and alerting.

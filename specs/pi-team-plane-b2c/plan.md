---
spec_mode: lightweight
feature_id: pi-team-plane-b2c
risk_category: ui
justification: |
  Composes shipped pieces (dual-dialect store, developer_id, the
  local_heartbeat table, the cost engine, dashboard rollups, the
  Studio) into one read-only payload, a tab and a CLI command. No
  schema change, no new service. FR-1..FR-10 in spec.md state it.
status: approved
date: 2026-09-08
issue: 174
origin:
  issue: gosha70/code-copilot-team#174
  transcripts:
    - specs/pi-team-plane-b2c/origin/2026-09-08-owner-decisions.md
  origin_claim: |
    Cross-team visibility into active runs, global token spend and
    aggregated metrics; `pi-team status`-style tracking for all
    current team tasks. Topology: one shared Postgres store; identity:
    derived developer_id, access by database credentials on a trusted
    LAN (owner, 2026-09-08).
---

# Plan: the team store (#174 B2 + C + E)

## Deliverables

1. `api/team.py`: `team_status(db, *, noise, now, active_window_seconds)`
   — pure over the store; `liveness()` pure helper.
2. `config_data/defaults.json`: `team.active_window_seconds: 300`;
   `config.py` `TeamConfig`.
3. `api/server.py`: `GET /api/team/status?window=`.
4. `cli.py`: `team status [--window N]` printing the developers table.
5. Studio: `app/team/page.tsx`, `lib/teamView.ts` (pure rows, dot
   state, window formatting), nav entry, `lib/api.ts` types.
6. Cookbook: "A team store" section; README section.
7. `plane-shaping.md`: decisions 1–2 recorded as decided.

## Test strategy

`tests/test_team.py` (seeded three-developer store), `test_api.py`
route, `test_cli.py` command, states-check block; Postgres check via
the compose container.

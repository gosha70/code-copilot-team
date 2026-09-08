---
spec_mode: lightweight
feature_id: pi-team-plane-d
risk_category: ui
justification: |
  A read-only evaluation over rows the store already holds, thresholds
  as configuration, a banner and a CLI exit code. No schema, no daemon,
  no change to the pi runtime. FR-1..FR-8 in spec.md state it.
status: approved
date: 2026-09-08
issue: 174
origin:
  issue: gosha70/code-copilot-team#174
  transcripts:
    - specs/pi-team-plane-d/origin/2026-09-08-owner-decisions.md
  origin_claim: |
    "Runaway recursive agent loops can be audited, alerted, or flagged
    if they breach budget bounds" over the shared Postgres team store
    with trusted-LAN access (owner, 2026-09-08).
---

# Plan: budgets, runaway detection and alerts (#174 Slice D)

## Deliverables

1. `config_data/defaults.json` `team.budgets` and `team.runaway`;
   `config.py` `BudgetsConfig`, `RunawayConfig` on `TeamConfig`; env
   keys; `constants.py` names.
2. `api/alerts.py`: `budget_alerts()`, `runaway_alerts()`,
   `all_alerts()`; alert dict shape.
3. `api/server.py`: `GET /api/team/alerts`; `alerts` in
   `/api/team/status`.
4. `cli.py`: `team alerts [--json] [--fail-on warning|breach]`.
5. Studio: `lib/teamView.ts` alert helpers (pure), Team tab banner
   list and empty state; Settings → Team group; `lib/api.ts` types.
6. Cookbook §8.5; README; smoke step breach.

## Test strategy

`tests/test_alerts.py` seeded store; `test_api.py`; `test_cli.py`;
states-check; smoke Postgres step.

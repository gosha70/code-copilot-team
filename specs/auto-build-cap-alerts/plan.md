---
spec_mode: lightweight
feature_id: auto-build-cap-alerts
risk_category: infra
justification: |
  One derived alert family added to an existing derived-alerts module,
  fed by an existing ledger reader, exposed through routes and a CLI
  that already exist. FR-1..FR-4 in spec.md state the behaviour; a full
  bundle would restate them. Chosen small on purpose: it is the feature
  for the second real unattended auto-build run.
status: approved
date: 2026-09-10
issue: none
origin:
  transcripts:
    - specs/auto-build-cap-alerts/origin/2026-09-10-second-unattended-run.md
  user_messages:
    - "2026-09-10: 'Then run the next real feature and reconsider D against the additional evidence'"
  origin_claim: |
    An auto-build run burning or past its cost or wall-clock cap should
    show among the Team tab's alerts, derived from its ledger on every
    read, so a person sees it without opening the Runs tab.
---

# Plan: cap alerts for auto-build runs

## Deliverables

1. `scripts/session_analytics/api/alerts.py`: `KIND_AUTO_BUILD_COST`,
   `KIND_AUTO_BUILD_WALL_CLOCK`; `auto_build_alerts(runs, *, now=None)`
   (FR-1, FR-2); `all_alerts(..., runs=None)` merging them and adding
   the `auto_build` block; `render_alerts()` line (FR-3).
2. `scripts/session_analytics/api/server.py` (`/api/team/status`,
   `/api/team/alerts`) and `cli.py` (`_cmd_team`): read the runs with
   `auto_build.list_runs(conn, cfg.auto_build)` and pass them (FR-4).
3. Tests in `scripts/session_analytics/tests/test_alerts.py` (or the
   existing alerts test module): every test function's name carries
   `cap_fr<N>` for the requirement it verifies, because
   `verification.yaml` selects verifiers with `-k cap_fr<N>`. Runs are
   built as dicts in the shape `api.auto_build.read_run` returns (see
   `tests/test_auto_build_runs.py` for the shape); the route and CLI
   tests point `CCT_SA_AUTO_BUILD_ROOT` at a temporary ledger root.
4. `docs/session-analytics-cookbook.md` §8.5: one paragraph on the
   auto-build alerts.

## Interfaces

- `auto_build_alerts(runs: list[dict], *, now=None) -> list[dict]`.
- `all_alerts(db, status, *, budgets, runaway, noise, now=None,
  runs=None) -> dict` — report gains `auto_build: {evaluated, live_runs}`.

## Test strategy

Unit tests only (deterministic): alert derivation over run dicts at the
boundaries (79%, 80%, 100%, null cap, concluded run); the report block
and the rendered line; the route and CLI over a temporary ledger root
with one live run at 90% of its cost cap and a root that is not a
directory. The suite command is the session-analytics pytest run with
the host-`.env` cases deselected.

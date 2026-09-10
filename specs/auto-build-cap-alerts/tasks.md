# Tasks: cap alerts for auto-build runs

<!-- One phase: the feature is small by design (the second real unattended run). -->

## US1: a run burning its cap shows among the Team alerts

| # | Task | File(s) | Done |
|---|------|---------|------|
| 1 | `auto_build_alerts(runs, *, now=None)`: one alert per unconcluded run per cap at or above `BUDGET_WARNING_SHARE`, warning below the cap, breach at or above it; null or non-positive cap → no alert; `kind`, `scope: "run"`, `subject`, `figures`, `message` per FR-2 (FR-1, FR-2) | `scripts/session_analytics/api/alerts.py`, `constants.py` | [ ] |
| 2 | `all_alerts(..., runs=None)` merges and sorts them; report gains `auto_build: {evaluated, live_runs}`; `render_alerts()` prints them and says whether runs were evaluated (FR-3) | `scripts/session_analytics/api/alerts.py` | [ ] |
| 3 | `/api/team/status`, `/api/team/alerts`, `team status|alerts` read the ledgers via `auto_build.list_runs(conn, cfg.auto_build)` and pass `runs=`; a missing root evaluates to zero runs (FR-4) | `scripts/session_analytics/api/server.py`, `cli.py` | [ ] |
| 4 | Tests for FR-1..FR-4, each function named `test_cap_fr<N>_…` for the FR it verifies (verification.yaml selects them with `-k cap_fr<N>`): derivation at the boundaries and for concluded runs, the report block and rendered line, the route and CLI over a temporary ledger root | `scripts/session_analytics/tests/test_alerts.py` | [ ] |
| 5 | Cookbook §8.5 paragraph on auto-build alerts | `docs/session-analytics-cookbook.md` | [ ] |

**Checkpoint US1**:
- [ ] `PYTHONPATH=scripts:. python3 -m pytest scripts/session_analytics/tests -q` green (host `.env` cases deselected in the automation test command)
- [ ] `./scripts/session-analytics team alerts` on this repository prints the auto-build evaluation line

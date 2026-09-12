# Tasks: the Runs tab shows a run's probe, fallback and earlier terminations

<!-- One phase: the feature is small by design (the sixth real unattended run). -->

## US1: a run's probe, fallback and earlier terminations are visible

| # | Task | File(s) | Done |
|---|------|---------|------|
| 1 | `probe`, `earlier_terminations`, `fallbacks` on the run record; file-pattern constants (FR-1, FR-2, FR-3) | `scripts/session_analytics/api/auto_build.py`, `scripts/session_analytics/constants.py` | [ ] |
| 2 | `render_run` probe/termination/fallback lines; `render_list` "resumed after N termination(s)" (FR-4) | `scripts/session_analytics/api/auto_build.py` | [ ] |
| 3 | Types, three pure helpers, card rendering, states-check assertions (FR-5) | `studio/lib/api.ts`, `studio/lib/runsView.ts`, `studio/app/runs/page.tsx`, `studio/scripts/states-check.mjs` | [ ] |
| 4 | Tests for FR-1..FR-5 (FR-5: the record carries `probe`, `earlier_terminations`, `fallbacks`), each function named `test_hist_fr<N>_…` (verification.yaml selects them with `-k hist_fr<N>`); cookbook sentence (FR-6) | `scripts/session_analytics/tests/test_auto_build_runs.py`, `docs/session-analytics-cookbook.md` | [ ] |

**Checkpoint US1**:
- [ ] `env PYTHONPATH=scripts:. python3 -m pytest scripts/session_analytics/tests -q` green (host `.env` cases deselected in the automation test command)
- [ ] `npm --prefix studio run states-check` green (run locally; not a verifier — see spec FR-6)

# Tasks: budgets, runaway detection and alerts (#174 Slice D)

| # | Task | File(s) | Done |
|---|------|---------|------|
| 1 | Budgets and runaway thresholds as config + env + Settings (FR-1, FR-2) | `config_data/defaults.json`, `config.py`, `constants.py`, `studio/app/settings/page.tsx` | [x] |
| 2 | Evaluation: budget and runaway alerts (FR-3, FR-5, FR-6) | `api/alerts.py` | [x] |
| 3 | Route + alerts in status (FR-4) | `api/server.py` | [x] |
| 4 | CLI `team alerts` with exit code (FR-4) | `cli.py` | [x] |
| 5 | Team tab banners + empty state; pure helpers (FR-4) | `studio/app/team/page.tsx`, `studio/lib/teamView.ts`, `studio/lib/api.ts` | [x] |
| 6 | Tests, states-check, smoke breach (FR-8) | `tests/test_alerts.py`, `tests/test_api.py`, `tests/test_cli.py`, `studio/scripts/states-check.mjs`, `.github/workflows/session-analytics-smoke.yml` | [x] |
| 7 | Cookbook §8.5 + README (FR-7) | `docs/`, `scripts/session_analytics/README.md` | [x] |

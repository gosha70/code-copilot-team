# Tasks: developer aliases for the team store

<!-- One phase: the feature is small by design (the first real unattended run). -->

## US1: aliases fold developer rows at read time

| # | Task | File(s) | Done |
|---|------|---------|------|
| 1 | `team.aliases` in defaults.json (`{}`), `CFG_TEAM_ALIASES`, `ENV_TEAM_ALIASES`, `TeamConfig.aliases` with `id=Name,id2=Name` env parsing and a refusal that names `team.aliases` (FR-1) | `scripts/session_analytics/constants.py`, `config.py`, `config_data/defaults.json` | [ ] |
| 2 | `team_status(..., aliases=)`: fold rows sharing a display name; `merged_ids` on every row; sums, null cost when none priced, newest heartbeat wins (FR-2, FR-3) | `scripts/session_analytics/api/team.py` | [ ] |
| 3 | API route and CLI pass `cfg.team.aliases`; alias name beats the `developer` table's display_name (FR-4) | `scripts/session_analytics/api/server.py`, `cli.py` | [ ] |
| 4 | Tests for FR-1..FR-4, each function named `test_alias_fr<N>_…` for the FR it verifies (verification.yaml selects them with `-k alias_fr<N>`): FR-1 in `test_identity.py`, FR-2/FR-3 in `test_team.py`, FR-4 in `test_cli.py` (CLI) and `test_team.py`; update the `TeamConfig(...)` construction in `test_identity.py` | `scripts/session_analytics/tests/test_team.py`, `tests/test_identity.py`, `tests/test_cli.py` | [ ] |
| 5 | Cookbook §8.4 paragraph on aliases | `docs/session-analytics-cookbook.md` | [ ] |

**Checkpoint US1**:
- [ ] `PYTHONPATH=scripts:. python3 -m pytest scripts/session_analytics/tests -q` green (host `.env` cases deselected in the automation test command)
- [ ] `./scripts/session-analytics team status` on a store with aliases set shows one folded row

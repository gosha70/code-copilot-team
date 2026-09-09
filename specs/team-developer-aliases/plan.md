---
spec_mode: lightweight
feature_id: team-developer-aliases
risk_category: config
justification: |
  A read-time fold driven by one config mapping, in the team status
  function and the config loader, with tests. No schema, no UI, no new
  dependency. Chosen deliberately small as the first real unattended
  auto-build run (#190).
status: approved
date: 2026-09-08
issue: 174
origin:
  issue: gosha70/code-copilot-team#174
  transcripts:
    - specs/team-developer-aliases/origin/2026-09-08-first-unattended-run.md
  origin_claim: |
    One person's sessions appear under several developer ids on the
    Team tab; fold them into one row under one configured name at read
    time, without rewriting the store. The first real unattended
    auto-build run (owner, 2026-09-08).
---

# Plan: developer aliases for the team store

## Deliverables

1. `scripts/session_analytics/config.py`: `TeamConfig.aliases`
   (`dict[str, str]`), loaded from `team.aliases` in
   `config_data/defaults.json` (add the key, default `{}`) with
   `CCT_SA_TEAM_ALIASES` (`id=Name,id2=Name`) on top; constants
   `CFG_TEAM_ALIASES` in `constants.py` and `ENV_TEAM_ALIASES` in
   `config.py`; malformed entries refuse with `team.aliases` named.
2. `scripts/session_analytics/api/team.py`: `team_status(...,
   aliases: Mapping[str, str] | None = None)` folds developer rows per
   FR-2/FR-3 and adds `merged_ids` to every row; `render_status()`
   unchanged in shape (the folded row prints like any other).
3. `scripts/session_analytics/api/server.py` and `cli.py`: pass
   `cfg.team.aliases` into `team_status()`.
4. Tests: `scripts/session_analytics/tests/test_identity.py` for FR-1
   (env parsing, malformed entry refused with the key named);
   `test_team.py` for FR-2 (fold, `merged_ids` on every row) and FR-3
   (sums, null cost when none priced, newest heartbeat wins);
   `test_cli.py` and `test_team.py` for FR-4 (the CLI table and the
   route apply the config aliases; alias name beats the developer
   table). Every test function's name carries `alias_fr<N>` for the
   requirement it verifies (`test_alias_fr2_fold_shares_display_name`),
   because `verification.yaml` selects verifiers with `-k alias_fr<N>`.
5. `docs/session-analytics-cookbook.md` §8.4: one paragraph on
   `team.aliases` / `CCT_SA_TEAM_ALIASES`.

## Interfaces

- `TeamConfig(active_window_seconds, budgets, runaway, aliases)`.
- `team_status(db, *, noise, active_window_seconds, now=None,
  aliases=None)`; developer rows gain `merged_ids: list[str]`.

## Test strategy

Unit tests only (deterministic): the team status fold on a seeded
SQLite store, the config loader's env parsing and refusal. The suite
command is the session-analytics pytest run, with the two host-`.env`
cases deselected.

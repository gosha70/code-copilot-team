---
spec_mode: lightweight
feature_id: auto-build-run-surface
risk_category: ui
justification: |
  A read-only reader over an existing, tested ledger format, one new
  table holding one hand-set label, one API family, one CLI subcommand
  and one Studio page in the shape of /team. FR-1..FR-10 in spec.md state
  the behaviour; a full bundle would restate them.
status: approved
date: 2026-09-09
issue: "#190 §12"
origin:
  transcripts:
    - specs/auto-build-run-surface/origin/2026-09-08-owner-ordering.md
  user_messages:
    - "2026-09-08: 'one real run, then option 3 over its data, then D scoped by that data'"
  origin_claim: |
    Build the §12 run surface and the human verdict label over the data
    of the real unattended runs: one page showing each run's outcome in
    the driver's own words, why it stopped, rounds, cost against cap
    with the estimated part distinguished, verifier state and policy
    decisions; and a way to record what the human did with the PR that
    survives the ledger. Not increment D.
---

# Plan: the auto-build run surface and the human verdict

## Deliverables

1. `constants.py` / `config.py` / `defaults.json`: `auto_build` block
   (`ledger_root`, `active_window_seconds`), `AutoBuildConfig`,
   `CCT_SA_AUTO_BUILD_ROOT`, the two fixed subdirectory names, the
   `POLICY_EVENTS` set, the verdict vocabulary, `TBL_AUTO_BUILD_VERDICT`.
2. `api/auto_build.py` (pure, no FastAPI): `scan_runs(root, *, now,
   active_window_seconds)` → records + skipped + duplicates;
   `list_runs(db, cfg, now)` joining verdicts; `run_detail(db, cfg,
   key)`; `set_verdict(db, cfg, key, verdict, note, now)`;
   `clear_verdict`; `render_list` / `render_run` for the CLI.
3. `config_data/ddl/postgres/009_auto_build_verdict.sql` + `_DDL_FILES`.
4. `api/server.py`: `GET /api/runs`, `GET /api/runs/{key}`,
   `PUT|DELETE /api/runs/{key}/verdict` (body model `VerdictUpdate`).
5. `cli.py`: `runs` parser (`list|show|label|unlabel`), `_cmd_runs`.
6. Studio: `lib/api.ts` types + calls; `lib/runsView.ts` (state,
   intro, outcome/verdict wording, cost and verifier lines, polling);
   `app/runs/page.tsx`; nav tab in `app/layout.tsx`.
7. Tests: `tests/test_auto_build_runs.py`; `states-check.mjs` block.
8. Docs: cookbook, session-analytics README, this bundle.

## Interfaces

- `scan_runs(root: Path, *, now: datetime, active_window_seconds: int)
  -> ScanResult(runs: list[dict], skipped: list[dict], duplicates: int)`.
- `list_runs(db, cfg, *, now=None) -> dict` (the FR-5 list payload).
- `run_detail(db, cfg, key, *, now=None) -> dict | None`.
- `set_verdict(db, cfg, key, verdict, note, *, now=None) -> dict`
  raises `LookupError` (unknown key) / `ValueError` (bad verdict).
- `clear_verdict(db, cfg, key, *, now=None) -> dict` (same errors).

## Test strategy

Ledgers are written to a temporary root by the tests from the four real
runs' shapes; the reader is exercised through the public functions and
the FastAPI client; sqlite for the store leg, the Postgres smoke job for
the DDL. Studio logic is asserted by the states script.

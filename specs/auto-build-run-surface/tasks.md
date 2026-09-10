# Tasks: the auto-build run surface and the human verdict

| # | Task | File(s) | Done |
|---|------|---------|------|
| 1 | `auto_build` config block, constants, env key, vocabularies (FR-1, FR-2, FR-4) | `constants.py`, `config.py`, `config_data/defaults.json` | [x] |
| 2 | Ledger reader: records, skipped, duplicates, live rule, policy decisions (FR-2, FR-3) | `api/auto_build.py` | [x] |
| 3 | Verdict table + store functions (FR-4) | `config_data/ddl/postgres/009_auto_build_verdict.sql`, `relational/db.py`, `api/auto_build.py` | [x] |
| 4 | API routes (FR-5) | `api/server.py` | [x] |
| 5 | CLI `runs list/show/label/unlabel` (FR-6) | `cli.py` | [x] |
| 6 | Pure view module: states, wording, cost/verifier lines, polling (FR-7, FR-8) | `studio/lib/runsView.ts`, `studio/lib/api.ts` | [x] |
| 7 | Runs page + nav tab (FR-7) | `studio/app/runs/page.tsx`, `studio/app/layout.tsx` | [x] |
| 8 | Tests: reader, store, API; states script (FR-9) | `tests/test_auto_build_runs.py`, `studio/scripts/states-check.mjs` | [x] |
| 9 | Docs (FR-10) | `docs/session-analytics-cookbook.md`, `scripts/session_analytics/README.md` | [x] |
| 10 | Real-data walk over the four ledgers; run 4 labelled `merged_with_fixes` (FR-9) | — | [x] |

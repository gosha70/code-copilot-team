# Tasks: Benchmark explains itself; linking runs is a pipeline step

| # | Task | File(s) | Done |
|---|------|---------|------|
| 1 | Runs-root setting in config, constants, defaults, ENV_KEYS (FR-1) | `config.py`, `constants.py`, `config_data/defaults.json` | [x] |
| 2 | `correlate.run` shared by CLI and step, with live progress (FR-4) | `correlate.py`, `cli.py` | [x] |
| 3 | `correlate` step after ingest; skipped vs failed; runs-root reader; counts (FR-2, FR-3) | `pipeline_jobs.py` | [x] |
| 4 | API runner + payload `runs_root`/`link_job` (FR-6) | `api/server.py` | [x] |
| 5 | Settings → Benchmarks; boundary wording (FR-1, FR-5) | `studio/app/settings/page.tsx` | [x] |
| 6 | Pure intro: five states, cause only from counters, polling rules (FR-7, FR-8) | `studio/lib/benchmarkIntro.ts` | [x] |
| 7 | Benchmark page rewrite; polling per FR-8 | `studio/app/benchmark/page.tsx` | [x] |
| 8 | Analysis by-id lookup, skipped badge, correlate counters (FR-9) | `studio/app/analysis/page.tsx` | [x] |
| 9 | Tests: pipeline, correlate, API; states script incl. counterexample and polling (FR-10) | `tests/*`, `studio/scripts/states-check.mjs` | [x] |
| 10 | Cookbook + this bundle; old spec marked superseded | `docs/`, `specs/` | [x] |

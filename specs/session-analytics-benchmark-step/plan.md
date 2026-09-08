---
spec_mode: lightweight
feature_id: session-analytics-benchmark-step
risk_category: ui
justification: |
  A pipeline step over an already-shipped, tested scan (correlate, #91/#92),
  one setting, one payload extension and a page rewrite. The behaviour is
  fully stated by FR-1..FR-10 in spec.md; a full bundle would restate them.
status: approved
date: 2026-09-08
issue: none
origin:
  transcripts:
    - specs/session-analytics-benchmark-step/origin/2026-09-08-owner-directive.md
  user_messages:
    - "2026-09-08: '[P2] The Benchmark section is lacking explanation and actions'"
    - "2026-09-08: 'Graph first … Then Ask, then Benchmark.'"
  origin_claim: |
    The Benchmark page must explain what it shows and offer the action
    that fills it, instead of four zero tiles and a CLI command. That
    means: a runs-folder setting, "Link benchmark runs" as a pipeline
    step (skipped, not failed, when unset), the page in truthful states
    from the store, and no new GitHub issue (standing rule).
---

# Plan: Benchmark explains itself; linking runs is a pipeline step

## Deliverables

1. `config.py` / `constants.py` / `defaults.json`: the runs-root setting
   (`CCT_SA_BENCHMARK_RUNS_ROOT`, `benchmark_runs_root`), in ENV_KEYS.
2. `correlate.run(db, runs_root, stats, progress)`: the one scan; the
   CLI `correlate` command and the pipeline step both call it.
3. `pipeline_jobs.py`: `STEP_CORRELATE` after `ingest`; `StepSkipped`
   ends a step done with the reason; `benchmark_runs_root()` reader;
   counts `benchmark_linked` / `benchmark_results`; done rule.
4. `api/server.py`: `_correlate` runner publishing live counters;
   `/api/dashboard/benchmark` gains `runs_root` and `link_job`.
5. Studio: Settings → Benchmarks group; `lib/benchmarkIntro.ts` (pure:
   state, headline, cause from counters, polling rules);
   `app/benchmark/page.tsx` rewrite of the opening card and button;
   Analysis by-id step lookup, skipped badge, correlate counters.
6. Docs: cookbook §1 row, §8.3, §9; this bundle; the 2026-07-18 spec
   marked superseded.

## Interfaces

- `correlate.run(db, runs_root: Path, *, stats=None, ingested_at=None,
  progress=None) -> CorrelationStats`; raises `RunsRootError` for a
  non-directory.
- `pipeline_jobs.StepSkipped(reason)`; job dict gains `skipped: true`.
- Payload: `runs_root {path, configured, is_dir}`, `link_job {state,
  message?, skipped?, seconds?, progress?}`.
- `benchmarkIntro(summary) -> {state, headline, cause, canLink,
  rootLine}`; `shouldPoll(pending, data)`, `settleWatch(pending, data)`.

## Test strategy

Unit (Python): step placement and skip; runs-root states; `run` links,
stores, commits once, refuses a file, reports live counters; API
payload and the step run through the API with a fixture runs dir.
States script: every page state, the counterexample for the inferred
cause, the polling transitions. Build + doc-accuracy. Real-data walk on
the owner's runs folder.

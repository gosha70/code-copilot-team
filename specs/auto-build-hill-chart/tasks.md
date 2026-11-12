# Tasks: auto-build moves the pitch's hill-chart scopes

| # | Task | Requirement(s) | File(s) | Done |
|---|---|---|---|---|
| 0 | Owner rules D1–D5 (done 2026-11-11: D1 explicit tokens with preflight refusal, D2–D3 and D5 as recommended, D4 retry once then journal); markers removed; statuses approved; fresh alignment record | all | `spec.md`, `plan.md`, alignment record | [x] |
| 1 | Pitch resolution: `specs/<id>` else `specs/pitches/<id>`; bare id everywhere else; the review runner resolves the same way and the driver passes it the collaboration dir; test that a pitch id resolves and a missing id still errors | FR-1 | `scripts/auto-build-loop.sh`, `scripts/review-round-runner.sh`, `tests/test-auto-build-loop.sh` | [x] |
| 2 | `setup_pitch` fixture and the no-hill assertions on a feature fixture | FR-2 | `tests/test-auto-build-loop.sh` | [x] |
| 3 | `hill_map` from phase titles, `hill_preflight` lines and refusal (exit 1 on a phase without a token or with an unknown scope id, before the ledger), the frozen map in the ledger and a drift refusal on resume; tests for tokens, multiple tokens, no token, unknown scope, scope named by no phase | FR-3, FR-4 | driver, suite | [x] |
| 4 | `hill_set` (atomic, forward-only, idempotent; a write failure parks as `hill_chart_error`), `hill_phase_start`, `hill_phase_landed` with the last-phase rule and the scoped commit retried once then journaled, `hill_final`; call sites | FR-5, FR-6, FR-7, FR-8 | driver, suite | [x] |
| 5 | Scenario tests: full run, shared scope, park at coverage gate then resume, pre-set done, hill-commit retry and persistent failure, feature run unchanged; pins in `tests/test-counts.env` and `docs/repo-structure.md` in the same commit | all | suite, pins | [x] |
| 6 | Docs: `docs/auto-build.md` § Hill chart; one sentence in `hill.md`, `cooldown.md`, `scope-executor.md`; `scripts/generate.sh`; `test-generate`; CHANGELOG | FR-9 | docs, commands, agent, generated copies | [x] |
| 7 | Gates: validate-spec, origin alignment, suites, generators `--check`, doc accuracy, `git diff --check`, `pre-pr-check.sh --closes 405`, peer review, PR closing #405 | all | repository gates | [ ] |

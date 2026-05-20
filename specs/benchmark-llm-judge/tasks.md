# Tasks — Calibrated LLM-Judge + Rich Reports (#34)

Each task is bounded and independently verifiable. AC map: spec.md
§ Success Criteria ←→ tasks below. Under the recommended D1 Option B,
each Phase B step corresponds to its own sub-issue and its own PR;
under Option A, the same step list collapses into a single PR's
commit chain (see plan.md § Option-A delta).

Pre-existing-failure note (memories
`project_benchmark_preexisting_env_test_failures`,
`project_polyglot_dogfood_subset_stale`): run suites **per-module**;
`test_polyglot_adapter`×4, `test_cli_skeleton` hang, the stale
`test_polyglot_dogfood_subset` `*/leap` list, and pytest
auto-collecting `fixtures/**/leap_test.py` are known host noise, NOT
regressions.

## Phase A — SDD bundle (gated; STOP after)

### TA.1 — Bundle + alignment record
- **Output:** `specs/benchmark-llm-judge/{spec,plan,tasks}.md` +
  `origin-alignment-2026-05-20-0238.md`, mirroring the
  `specs/benchmark-aider-backend/` / `specs/benchmark-bench-driver/`
  format. Captures: D1 PR-structure analysis (A/B/C with
  recommendation), corpus-inventory finding (1171 attempts on
  disk, 44 passing), human-labeling dependency, research-question
  failure path (D6 zero-dimensions terminal state).
- **Done when:** `validate-spec.sh --feature-id benchmark-llm-judge`
  and `check-origin-alignment.sh benchmark-llm-judge` both exit ≤ 1;
  reported to user; **explicit "go" + D1 (A/B/C) choice received
  before any Phase-B task.**

## Phase B0 — Preflight (no code yet)

### TB0.1 — Confirm corpus inventory holds on the maintainer machine
- **Output:** re-run the corpus-inventory script (spec.md §
  Calibration-corpus reality check) on the maintainer machine; the
  numbers (1171 / 44 passing / 5 (backend, model) tuples) must
  hold or the plan adapts. If new runs landed since 2026-05-20,
  update the table in spec.md.
- **Done when:** numbers reconciled; spec.md updated if necessary.

### TB0.2 — Ratify rubric v1 dimensions with user
- **Output:** confirm the four dimensions —
  **idiomaticity / error_handling / test_thoughtfulness /
  security_hygiene** — and the 1–5 anchor descriptions with the
  user. Draft `benchmarks/calibration/rubric-default-v1.md` (the
  prompt template + dimension list + 1–5 anchor sentences) ready
  for the sub-issue A PR to land.
- **Done when:** user has explicitly approved the rubric dimensions
  and 1–5 anchors; rubric-default-v1.md drafted.

### TB0.3 — Ratify judge backend default with user
- **Output:** confirm `claude-code:sonnet` as the default judge,
  or accept a user override (e.g. opus, or a local-gateway model
  for self-hosting). Record the choice in spec.md if it changes
  from the recorded default.
- **Done when:** explicit user confirmation.

### TB0.4 — File sub-issues + capture numeric IDs (Option B only)
- **Output:** five real GitHub issues filed under
  gosha70/code-copilot-team via `gh issue create`, each
  referencing this spec/plan with the per-AC mapping from plan.md
  § D1 (labels A–E). For each created issue, capture the assigned
  numeric ID into a new file
  `specs/benchmark-llm-judge/sub-issue-numbers.md` with a small
  table:

  ```
  | Label | Numeric ID | Title |
  |-------|------------|-------|
  | A     | #<NN>      | feat(benchmark): Judge protocol + …  |
  | B     | #<NN>      | feat(benchmark): calibration validation … |
  | C     | #<NN>      | feat(benchmark): HTML + CSV + static-SVG … |
  | D     | #<NN>      | feat(benchmark): calibrated-judge winner-extension … |
  | E     | #<NN>      | chore(benchmark): land first labeled calibration set … |
  ```

  Post a comment on #34 listing the five numeric IDs as its
  closing-link block ("This epic closes when #<E's id> merges").
  Every subsequent PR title / body uses the captured numeric ID
  in its `Closes #NN` keyword — the placeholder label `A`/`B`/…
  never appears in a PR description (memory
  `feedback_github_close_keyword_per_issue`: one `Closes #NN` per
  real issue; the E PR also writes a separate `Closes #34`
  keyword so the epic closes automatically).
- **Done when:** five issues open; `sub-issue-numbers.md` committed
  alongside Phase B1's first commit; #34 epic-comment posted.

## Phase B1 — sub-issue A — Judge protocol + claude_code judge + corpus-selection CLI

### TB1.1 — `judge/contracts.py`
- **Output:** `Judge` protocol + `JudgeInput`/`JudgeResult` frozen
  dataclasses; mirrors `Backend`/`BackendResult` shape. Module
  docstring explicitly names the additivity invariant (this
  artifact never overwrites `score.json`).
- **Done when:** protocol-shape unit test green;
  `isinstance(claude_code_judge, Judge)` holds.

### TB1.2 — `judge/claude_code_judge.py`
- **Output:** Judge using the `claude-code` backend headless
  invocation + provider-routing env vars. Reads
  `rubric-default-v1.md`, formats with attempt evidence
  (diff + prompt + verify output), invokes the model, parses
  output into a `JudgeResult` with per-dimension rating +
  explanation. Records the corrected `judge_invocation` block
  (peer review 2026-05-20): `model` set; `temperature: null`;
  `seed: null`; `temperature_control: "unsupported"`;
  `seed_control: "unsupported"`; `provider_endpoint_present`
  boolean. The local `claude` CLI exposes only `--model` /
  `--fallback-model` — no `--temperature`, no `--seed`. **The
  judge MUST NOT claim T=0 it cannot enforce.** Re-run stability
  is empirical, surfaced by the calibration step's Spearman.
- **Done when:** recorded-transcript fake-judge suite green
  (including an explicit assertion that `judge_invocation`
  contains the corrected null/`"unsupported"` fields, not a
  silent `0.0`); no live LLM in tests.

### TB1.3 — `judge/runner.py` + `cli.py` `judge` subcommand
- **Output:** `run_judge(run_dir, judge_id, rubric_name)` walks
  `run_dir`, invokes the judge per attempt, writes `judge.json`
  adjacent to `score.json`. CLI wires it as
  `./scripts/benchmark judge --run-dir <d> --judge claude-code:sonnet
  [--rubric default-v1]`.
- **Done when:** end-to-end against the fake-judge shim writes one
  `judge.json` per attempt; `score.json` byte-identical pre/post
  (asserted).

### TB1.4 — `calibration/corpus_select.py` + `calibration-corpus` CLI
- **Output:** axis-agnostic corpus selector. Reads
  `runs/**/run-record.json` + `score.json`; applies the requested
  axes filter (`--axes model,repeated-runs[,adapter,backend]`)
  and target-N (`--target-n 50`); writes
  `<name>.corpus.jsonl` (selected task-runs, one per line) and
  `<name>.meta.json` (selection command + axes + per-axis
  counts). Deterministic ordering (sorted by `run_path`) so the
  selection is reproducible.
- **Done when:** unit test on a fixture `runs/` tree picks the
  expected task-runs; `--target-n 50 --axes model,repeated-runs`
  against the live `runs/` produces a corpus that satisfies (a)
  N ≥ 50, (b) ≥ 2 axes represented.

### TB1.5 — Registry + `_register.py`
- **Output:** `judge/registry.py` parallel to the backend
  registry; one-line registration block in `_register.py` after
  the backend registrations.
- **Done when:** `python3 -m benchmark_runner list-judges` (or the
  chosen surface) shows `claude-code-judge`.

### TB1.6 — sub-issue A closeout
- **Output:** spec → AC2 (partial: protocol + judge.json),
  corpus-selection capability, fake-judge suite green; PR opened.
- **Done when:** per-module suite green;
  `check-origin-alignment.sh benchmark-llm-judge` ≤ 1; diff shown
  + explicit approval per commit; PR `feat(benchmark): Judge
  protocol + claude_code judge + corpus-selection CLI
  (Closes #<sub-issue A's real id, from sub-issue-numbers.md>)`.

## Phase B2 — sub-issue B — Calibration validation + Spearman gate

### TB2.1 — `calibration/spearman.py`
- **Output:** Spearman ρ implementation in stdlib (`statistics` +
  rank-by-sort). No new external dependency.
- **Done when:** golden-numbers test against published vectors
  green; tied-rank handling tested.

### TB2.2 — `calibration/validate.py` + `calibrate` CLI
- **Output:** reads a labeled `<name>.jsonl` + a `judge.json`
  directory tree, joins on (run_path, dimension), computes
  per-dimension Spearman + exact-match-rate, writes:
    - `<name>.calibration-report.md` (numbers + per-dimension
      scatter SVG + threshold + per-dimension pass/fail),
    - `<name>.calibrated-dimensions.json` (machine-readable list
      of calibrated dimensions + threshold used).
  Default threshold 0.6, overridable via `--threshold`.
- **Done when:** synthetic-labels test produces the expected
  calibration-report against a fixed judge fixture; threshold
  boundary tested at 0.59, 0.6, 0.7.

### TB2.3 — sub-issue B closeout
- **Output:** spec → AC3, AC4 (the per-dimension threshold
  enforced + uncalibrated flagged).
- **Done when:** per-module suite green; PR
  `feat(benchmark): calibration validation + Spearman gate
  (Closes #<sub-issue B's real id>)`.

## Phase B3 — sub-issue C — HTML + CSV + static-SVG reports (additive)

### TB3.1 — Additivity snapshot regression test
- **Output:** **WRITTEN FIRST.**
  `test_report_no_judge_regression.py` — a fixture run-dir with
  no `judge.json` files; emit Markdown + JSON; compare to a
  snapshot baseline (committed under tests/fixtures); modulo
  timestamp lines, byte-identical.
- **Done when:** the test passes before any HTML/CSV/SVG emitter
  code is added; this is the safety net for the rest of B3.

### TB3.2 — `report.py` `_emit_html`
- **Output:** stdlib-only HTML renderer; deterministic-first /
  judge-second / verdicts-third layout; explicit visual separator
  element. `report --html` flag in `cli.py`.
- **Done when:** `test_report_html.py` asserts structural markers
  + layout ordering; the byte-stream contains no JS.

### TB3.3 — `report.py` `_emit_csv`
- **Output:** `report.csv` (per-task) + `report-by-model.csv`
  (per-(backend, model)). `report --csv` flag.
- **Done when:** fixed fixture → byte-identical CSV
  (`test_report_csv.py`).

### TB3.4 — `report.py` `_emit_svg_*`
- **Output:** pure-string SVG bar / histogram / forest plot.
  Embedded into HTML; also written as standalone `*.svg` files
  alongside the HTML.
- **Done when:** `test_report_svg.py` asserts expected
  `<rect>` / `<path>` / `<text>` elements; opens in a browser
  with JS disabled (manual spot-check, recorded in PR
  description).

### TB3.5 — sub-issue C closeout
- **Output:** spec → AC5, AC6, AC7. AC9 (no dollar-cost) and
  AC10 (docs) partial: the HTML/CSV emitters surface no cost
  figures; docs land alongside in benchmarks/README.md.
- **Done when:** per-module suite green; PR
  `feat(benchmark): HTML + CSV + static-SVG reports
  (Closes #<sub-issue C's real id>)`.

## Phase B4 — sub-issue D — Winner-extension on calibrated dimensions

### TB4.1 — `report.py` calibrated-judge caller
- **Output:** additive caller logic that, given a
  `calibrated-dimensions.json`, builds samples per (backend, model)
  × dimension from `judge.json` ratings on
  **passing-on-both-sides** attempts and calls
  `report_winner.declare_winner(MetricSpec(name=f"judge:{dim}",
  kind="continuous", higher_is_better=True,
  continuous_threshold_relative=0.10), …)` unchanged.
- **Done when:** test injects a fixture with two (backend, model)
  groups, varied ratings, mixed pass/fail; asserts:
  (a) calibrated dimensions emit verdicts; uncalibrated do not.
  (b) Non-passing-on-both-sides samples are filtered out — a
      non-passing sample that would swing the verdict if included
      is asserted to NOT swing the verdict.
  (c) `declare_winner` is called (verified via spy / mock), and
      `report_winner.py` source is unchanged (git diff gate
      below).

### TB4.2 — `report_winner.py` not-modified CI gate
- **Output:** a per-PR check (`git diff --quiet
  scripts/benchmark_runner/report_winner.py` against the merge
  base) blocking merge of sub-issue D if `report_winner.py` was
  touched.
- **Done when:** the CI gate runs and passes; documented in
  benchmarks/README.md.

### TB4.3 — sub-issue D closeout
- **Output:** spec → AC4 (winner math excludes uncalibrated) +
  AC8 (deterministic-first ordering enforced in code).
- **Done when:** per-module suite green; PR
  `feat(benchmark): calibrated-judge winner-extension
  (Closes #<sub-issue D's real id>)`.

## Phase B5 — sub-issue E — First labeled calibration set + activate

### TB5.1 — Select the corpus
- **Output:** `./scripts/benchmark calibration-corpus --target-n 50
  --axes model,repeated-runs --name cct-instance-v1` writes
  `benchmarks/calibration/cct-instance-v1.corpus.jsonl` +
  `.meta.json`.
- **Done when:** corpus N ≥ 50; ≥ 2 axes represented; reviewer
  agrees the selection is representative (no all-failures, no
  all-sonnet, etc.).

### TB5.2 — Label the corpus (the human-labeling step)
- **Output:** `benchmarks/calibration/cct-instance-v1.jsonl` —
  one record per (run_path, dimension); ≥50 × 4 = ≥200 records;
  notes per record where the rating was borderline.
- **Done when:** human reviewer (the maintainer, or a documented
  multi-reviewer effort) has labeled every (run_path, dimension)
  pair. Calendar time, not agent time — gates merge of sub-issue E but
  does NOT block sub-issues A–D.

### TB5.3 — Run calibration + commit reports
- **Output:**
  `./scripts/benchmark calibrate --judge claude-code:sonnet
  --labels benchmarks/calibration/cct-instance-v1.jsonl` ;
  resulting `calibration-report.md` +
  `calibrated-dimensions.json` committed under
  `benchmarks/calibration/`.
- **Done when:** the artifacts are on disk; if any dimensions
  cleared 0.6, a follow-up `./scripts/benchmark report --html
  --calibrated-dimensions benchmarks/calibration/cct-instance-v1.calibrated-dimensions.json
  --run-dir <a representative run-dir>` is rendered and
  spot-checked against AC5/AC8; if zero dimensions cleared 0.6
  (D6 terminal state), the calibration-report.md spells out the
  negative outcome and the maintainer decides whether to file a
  rubric-v2 follow-up.

### TB5.4 — sub-issue E closeout (which closes #34)
- **Output:** spec → AC1 (labeled set) + AC4 (calibrated
  dimensions activated in reports) + AC10 (docs land alongside).
- **Done when:** per-module suite green; PR
  `chore(benchmark): land first labeled calibration set + first
  calibration-report (Closes #<sub-issue E's real id>, Closes #34)`
  (memory
  `feedback_github_close_keyword_per_issue`: each Closes keyword
  on its own).

## Cross-cutting tasks (apply to every PR)

### TC.1 — Diff-shown-and-approved gate
- Every commit: `git status` + `git diff` shown to the user;
  explicit "yes" / "go" / "commit" before staging; commit message
  via heredoc; per memory `feedback_review_before_commit` +
  `feedback_commit_messages_with_backticks_use_F_file` (use
  `git commit -F <file>` for messages containing backticks).

### TC.2 — Never push to master
- All work on feature branches (`feat/benchmark-llm-judge-{a,b,c,d,e}`
  under Option B; `feat/benchmark-llm-judge` under Option A);
  per memory `feedback_never_push_to_master` +
  `feedback_no_push_without_review`.

### TC.3 — Origin-alignment record refreshed before PR
- Fresh `origin-alignment-<date>-<time>.md` per sub-issue at
  PR-open time; `check-origin-alignment.sh benchmark-llm-judge`
  exits ≤ 1 before merge.

### TC.4 — Run.py / report_winner.py / contracts.py untouched
- Pre-PR `git diff --quiet
  scripts/benchmark_runner/{run,report_winner,contracts}.py`
  against the merge base; if any of those files were touched,
  STOP and escalate to user before proceeding.

### TC.5 — No live LLM in tests
- All judge tests use the recorded-transcript fake-judge fixture
  pattern (mirror codex/aider). Live judge invocations are a
  maintainer / Phase-B5 step, not a CI step.

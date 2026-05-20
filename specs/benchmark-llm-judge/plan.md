---
spec_mode: full
feature_id: benchmark-llm-judge
risk_category: integration
justification: "Adds a parallel `Judge` protocol + scorer (mirrors the existing Backend contract from #32) + a calibration validation pipeline + additive HTML/CSV/SVG reports + a winner-declaration extension on calibrated-judge dimensions. Touches a new `scripts/benchmark_runner/judge/` package, extends `report.py` additively, and reuses `report_winner.declare_winner` unchanged. The deterministic harness — `run.py`, `score.json`, `BackendResult`, `report_winner.declare_winner` — is NOT modified. External integration: the judge invokes an LLM via the existing `claude-code` backend headless path + provider-routing env vars. Empirical research-question component: per-dimension Spearman ≥ 0.6 is an empirical outcome, not a guarantee; the plan defines a path for zero-dimensions-calibrated. Human-labeling dependency: ≥50 task-runs hand-labeled on a multi-dimensional rubric — reviewer hours, not an agent task. D1 PR-structure is open; the team-lead recommendation is Option B (split #34 into sub-issues)."
status: draft
date: 2026-05-20
issue: 34
origin:
  issue: gosha70/code-copilot-team#34
  urls:
    - https://github.com/gosha70/code-copilot-team/issues/34
    - https://github.com/gosha70/code-copilot-team/issues/32
    - https://github.com/gosha70/code-copilot-team/issues/33
    - https://github.com/Aider-AI/polyglot-benchmark
    - https://www.swebench.com/verified.html
  origin_claim: |
    See spec.md `origin:` block. Issue #34 v3 adds calibrated
    LLM-judge scoring + rich reports (HTML/CSV/static charts) on top
    of the deterministic harness from #32/#33. Five subsystems
    "deliverable in order"; deterministic-first ordering an explicit
    AC; ≥50 task-runs spanning ≥2 axes for the calibration set;
    Spearman ≥ 0.6 per dimension; dollar-cost permanently out of
    scope. Two structural properties (human-labeling dependency +
    empirical research question) distinguish #34 from #36/#41.
    Corpus inventory (2026-05-20, recorded in spec.md): 1171
    attempt-records exist; calibration corpus needs no new
    benchmark spend. D1 PR-structure is OPEN — team lead recommends
    Option B (split into sub-issues) to honor the one-PR-per-issue
    rule (memory `feedback-pr-must-fully-address-issue`).
---

# Implementation Plan — Calibrated LLM-Judge + Rich Reports (#34)

> **D1 is the gating decision.** This plan describes the engineering
> work that is invariant across the three D1 options. The per-PR /
> per-sub-issue partition depends on D1; the **Option-B mapping** is
> spelled out below as the recommended path, with the Option-A and
> Option-C deltas listed at the end.

## Approach

The deterministic harness from #32/#33 is **frozen** by this feature:
`run.py`, `score.json`, `BackendResult`, and `declare_winner` are
unchanged. The judge subsystem is a parallel package
(`scripts/benchmark_runner/judge/`) that READS what `run.py` already
wrote (diff + prompt + verify output per attempt) and WRITES a
strictly-additive `judge.json` adjacent to `score.json`. The reports
gain HTML + CSV + SVG-chart emitters additively; the existing
Markdown + JSON paths are byte-identical (modulo timestamps) when
no `judge.json` is present.

The plan is staged across two gated phases (this Phase A and Phase
B implementation) and — under the recommended D1 Option B — across
five sub-issues, each fully closable by one PR per the
one-PR-per-issue rule.

## D1 (PR structure) — recommended path: Option B

Five sub-issues, each fully closable by one PR.

> **Labels `A`–`E` below are PLACEHOLDERS, not GitHub close-keyword
> targets.** GitHub `Closes sub-issue A` does NOT auto-close anything —
> close keywords require real numeric issue IDs. Phase B0 (TB0.4)
> files five real issues against `gosha70/code-copilot-team` and
> captures their assigned numbers into a small table
> (`specs/benchmark-llm-judge/sub-issue-numbers.md` — committed
> alongside Phase B1's first commit). Every later PR title /
> body / branch name MUST use the real numeric ID; `Closes sub-issue A`
> is a planning shorthand and never appears in a PR description.
> Memory `feedback_github_close_keyword_per_issue` applies — one
> `Closes #NN` keyword per real issue, no shared keyword.

The order below is the buildable-dependency order — subsequent
sub-issues import artifacts from earlier ones but each PR fully
closes its own issue without partial PRs against the umbrella #34.

| Label | Suggested sub-issue title | Closes when | Depends on |
|---|---|---|---|
| **A** | `feat(benchmark): Judge protocol + claude_code judge + corpus-selection CLI` | `Judge` protocol + `claude_code_judge` produce a real `judge.json` per attempt; `./scripts/benchmark calibration-corpus` selects N≥50 from `runs/` across user-specified axes; fake-judge recorded-transcript test green. | — |
| **B** | `feat(benchmark): calibration validation + per-dimension Spearman gate` | `./scripts/benchmark calibrate` runs the judge against a labeled corpus and emits `calibration-report.md` + `calibrated-dimensions.json`; tested against synthetic labels (no human-labeling required to merge). | A |
| **C** | `feat(benchmark): HTML + CSV + static-SVG reports (additive)` | `./scripts/benchmark report --html --csv` emits the additive artifacts with the deterministic-block-first / judge-block-second / verdicts-third layout; existing Markdown+JSON byte-identical when no judge.json present (regression-protected by snapshot test). | — (can ship in parallel with A) |
| **D** | `feat(benchmark): calibrated-judge winner-extension (deterministic-first enforced)` | Calibrated dimensions trigger `declare_winner` calls (reusing `report_winner.py` unchanged) with samples restricted to passing-on-both-sides attempts; uncalibrated dimensions never declare a winner; non-passing ratings appear in the report but never in the verdict. | A, B, C |
| **E** | `chore(benchmark): land first labeled calibration set + first calibration-report.md` | A real human-labeled `<name>.jsonl` ≥50 records ≥2 axes lands under `benchmarks/calibration/`; `calibrate` is run against it; the resulting `calibration-report.md` + `calibrated-dimensions.json` land in the same PR; reports on this CCT instance now show calibrated verdicts wherever dimensions cleared Spearman 0.6. | A, B, C, D. **All upstream code is already merged before the human-labeling work commits to a final rubric.** |

Each PR's title / body uses the real numeric ID captured in TB0.4,
e.g. `feat(benchmark): Judge protocol + claude_code judge +
corpus-selection CLI (Closes #<A's real id>)`. The PR that lands
the labeled set ALSO writes `Closes #34` in its body (separate
keyword per the memory above), so #34 the epic closes
automatically when E's PR merges. If a sub-issue spawns mid-PR
divergence that demands its own issue, the same numeric-ID
discipline applies — never refer to a non-existent `#34X` in a
PR body.

If calibration on the first rubric fails entirely (D6
zero-dimensions terminal state), E ships the negative calibration
report; the maintainer files a follow-up issue for rubric v2 if
they want to try again — that's a new bet, not a re-open of #34.

The full Phase B0–B5 task layout below assumes Option B; deltas for
Options A and C are at the end of this plan.

## Phase boundaries (Option B)

| Step | Sub-issue | Working slice | Gate |
|---|---|---|---|
| Phase A | (this bundle) | spec/plan/tasks + origin-alignment | `validate-spec.sh` + `check-origin-alignment.sh` exit 0; user picks D1 (A/B/C); user "go" |
| Phase B0 | (pre-sub-issue A) | preflight: corpus inventory locked, rubric v1 dimensions ratified with user, judge backend default ratified, sub-issues filed | spec.md § Calibration-corpus reality check confirmed against current `runs/`; rubric v1 written to `benchmarks/calibration/rubric-default-v1.md`; sub-issues sub-issue A–sub-issue E filed |
| Phase B1 | sub-issue A | Judge protocol + claude_code judge + corpus-selection CLI | fake-judge suite green; `judge.json` shape stable; `calibration-corpus --target-n 50 --axes model,repeated-runs` produces a valid corpus from existing `runs/` |
| Phase B2 | sub-issue B | calibration validation + Spearman gate | tested with synthetic labels: spearmanr from `scipy.stats` (or stdlib equivalent — see § Tooling), threshold 0.6, deterministic — synthetic-labels-against-fixed-judge-fixture produces a fixed `calibration-report.md` |
| Phase B3 | sub-issue C | HTML + CSV + static-SVG reports (additive) | snapshot test: a run with no judge.json produces a Markdown+JSON report byte-identical (modulo timestamps) to the #32/#33 baseline; HTML renders the deterministic-first / judge-second / verdicts-third layout; SVG charts render without JS |
| Phase B4 | sub-issue D | winner-extension on calibrated dimensions | calibrated-dimensions.json with N dimensions triggers N `declare_winner` calls on `judge:<dim>`; passing-on-both-sides enforced (asserted in a test that injects non-passing samples and asserts they are excluded); uncalibrated dimensions skipped |
| Phase B5 | sub-issue E | first real labeled calibration set + activated calibration | ≥50 task-runs labeled by a human reviewer; `calibrate` run; report renders calibrated verdicts where dimensions cleared 0.6 (or zero-dimensions-terminal-state per D6) |

Per the one-PR-per-issue rule, each B-step closes its own
sub-issue with its own PR; #34 closes when sub-issue E (B5) closes.

## Phase B0 — Preflight (no code yet)

1. **Confirm corpus inventory holds** on the maintainer machine:
   re-run the inventory script in spec.md § Calibration-corpus
   reality check; numbers in the spec must still match (or the
   plan adapts).
2. **Lock rubric v1 dimensions with the user.** The spec names
   four (idiomaticity / error_handling / test_thoughtfulness /
   security_hygiene); confirm the names + per-dimension
   prompt-fragment phrasing before sub-issue A's judge prompt template
   becomes the API surface a calibration set will be labeled
   against. Land `benchmarks/calibration/rubric-default-v1.md` in
   the sub-issue A PR (it is the prompt template + the dimension list +
   the 1–5 rating anchor descriptions).
3. **Confirm judge backend default with the user.** `claude-code:sonnet`
   is the spec's default; if the user prefers a different judge
   model (e.g. opus, or a local-gateway model so the judge is
   self-hostable), it lands in sub-issue A.
4. **File sub-issues sub-issue A–sub-issue E** referencing this spec/plan and
   their per-AC mapping.

## Phase B1 — sub-issue A — Judge protocol + claude_code judge + corpus-selection CLI

### Files to create

- `scripts/benchmark_runner/judge/__init__.py`
- `scripts/benchmark_runner/judge/contracts.py` — `Judge` protocol +
  `JudgeInput`/`JudgeResult` frozen dataclasses (mirror
  `Backend`/`BackendResult`).
- `scripts/benchmark_runner/judge/claude_code_judge.py` — initial
  judge using the `claude-code` backend headless invocation +
  provider-routing env vars; reads the rubric prompt template,
  formats with attempt evidence (diff + prompt + verify output),
  parses model output into a `JudgeResult`.
- `scripts/benchmark_runner/judge/registry.py` — light registry
  parallel to `benchmark_runner.registry` for judges.
- `scripts/benchmark_runner/judge/runner.py` — `run_judge(run_dir,
  judge_id, rubric_name)`: walks `run_dir`, invokes the judge per
  attempt directory, writes `judge.json`.
- `scripts/benchmark_runner/calibration/__init__.py`
- `scripts/benchmark_runner/calibration/corpus_select.py` —
  axis-agnostic selector; reads `runs/`'s `run-record.json` +
  `score.json`, applies the axes filter + target-N, writes
  `<name>.corpus.jsonl` (selected task-runs) + `<name>.meta.json`
  (the selection command + axes + per-axis counts).
- `scripts/benchmark_runner/cli.py` extensions: `judge` subcommand
  (`./scripts/benchmark judge --run-dir <d> --judge claude-code:sonnet
  [--rubric default-v1]`) and `calibration-corpus` subcommand.
- `benchmarks/calibration/rubric-default-v1.md` — the prompt
  template + dimension list + 1–5 rating anchors.
- `scripts/benchmark_runner/tests/test_judge_protocol.py` — protocol
  shape + JudgeInput/JudgeResult immutability.
- `scripts/benchmark_runner/tests/test_claude_code_judge.py` —
  recorded-transcript fake-judge shim (mirror codex/aider fake-CLI
  pattern); no live LLM in tests.
- `scripts/benchmark_runner/tests/test_corpus_select.py` — fixture
  `runs/` tree; selection axes; deterministic output.
- `scripts/benchmark_runner/tests/fixtures/judge/` — recorded
  judge-output fixtures (success / partial / parse-failure).

### Files to modify

- `scripts/benchmark_runner/_register.py` — judge registration block
  parallel to backends.

### Files NOT to modify

- `scripts/benchmark_runner/run.py` (D9 invariant)
- `scripts/benchmark_runner/contracts.py` (Judge contracts live in
  the new `judge/contracts.py` package, parallel not entangled)
- `scripts/benchmark_runner/report_winner.py` (D2 invariant)

### Done when (per sub-issue A)

- `Judge` protocol exists; `claude_code_judge` registers; the
  fake-CLI recorded-transcript suite is green per-module.
- `./scripts/benchmark calibration-corpus --target-n 50
  --axes model,repeated-runs` produces a corpus from the live
  `runs/` archive that satisfies (a) N ≥ 50, (b) ≥ 2 axes
  represented, (c) `<name>.meta.json` records reproducibly.
- `./scripts/benchmark judge --run-dir <d>` writes `judge.json`
  per attempt (live LLM, run by the maintainer; not in CI).

## Phase B2 — sub-issue B — Calibration validation + Spearman gate

### Files to create

- `scripts/benchmark_runner/calibration/validate.py` — reads a
  labeled `<name>.jsonl` + a run-dir of `judge.json` files,
  joins on (run_path, dimension), computes per-dimension Spearman
  ρ + exact-match rate, writes the artifacts.
- `scripts/benchmark_runner/calibration/spearman.py` — Spearman
  implementation (see § Tooling: NO new external dependency added
  — stdlib + the existing `statistics` module are sufficient
  given small N).
- `scripts/benchmark_runner/cli.py` extension: `calibrate`
  subcommand.
- `scripts/benchmark_runner/tests/test_calibration_validate.py` —
  fixed-judge fixture × fixed-label fixture → fixed expected
  Spearman matrix; threshold gating tested at 0.6, 0.7, and 0.59
  (boundary).
- `scripts/benchmark_runner/tests/test_spearman.py` — golden
  numbers for the Spearman implementation against published test
  vectors.

### Done when (per sub-issue B)

- `./scripts/benchmark calibrate --judge claude-code:sonnet
  --labels benchmarks/calibration/<name>.jsonl` produces
  `<name>.calibration-report.md` + `<name>.calibrated-dimensions.json`.
- The validate suite passes per-module against synthetic labels;
  no human labeling required to merge this PR.

## Phase B3 — sub-issue C — HTML + CSV + static-SVG reports (additive)

### Files to create / modify

- Extend `scripts/benchmark_runner/report.py` additively with:
  - `_emit_html(report_data, out_path)` — Jinja-less stdlib HTML
    rendering (avoid new dependency); deterministic-first /
    judge-second / verdicts-third layout; explicit visual separator
    HTML element.
  - `_emit_csv(report_data, out_dir)` — `report.csv` (per-task)
    + `report-by-model.csv` (per-(backend, model)).
  - `_emit_svg_bar(pass_rates, out_path)`, `_emit_svg_hist(...)`,
    `_emit_svg_forest(...)` — pure-string SVG (no matplotlib
    dependency unless the user blesses one in B0 preflight).
- `scripts/benchmark_runner/cli.py` extension: `report --html
  --csv` flags.
- `scripts/benchmark_runner/tests/test_report_html.py` — render
  HTML for a fixture run-dir; assert structure + layout markers
  + that the deterministic block precedes the judge block.
- `scripts/benchmark_runner/tests/test_report_csv.py` — fixed
  fixture → byte-identical CSV.
- `scripts/benchmark_runner/tests/test_report_svg.py` — fixed
  fixture → SVG with expected `<rect>` / `<path>` / `<text>`
  elements.
- `scripts/benchmark_runner/tests/test_report_no_judge_regression.py`
  — **THE REGRESSION GUARD**: a fixture run-dir with no
  `judge.json` files; emit Markdown + JSON; compare to a
  snapshot baseline; modulo timestamp lines, byte-identical.

### Files NOT to modify

- `scripts/benchmark_runner/report_winner.py`
- The existing Markdown/JSON emission paths beyond what's needed
  to surface judge-block content WHEN PRESENT.

### Done when (per sub-issue C)

- HTML + CSV + SVG emit per the flags; snapshot regression test
  green; static SVGs render without JS (verified by opening in a
  browser with JS disabled, or equivalent CI gate).

## Phase B4 — sub-issue D — Winner-extension on calibrated dimensions

### Files to create / modify

- `scripts/benchmark_runner/report.py` — additive caller logic that,
  given a `calibrated-dimensions.json`, builds samples per
  (backend, model) × dimension from `judge.json` ratings on
  passing-on-both-sides attempts, calls
  `declare_winner(MetricSpec(name=f"judge:{dim}", ...), …)`
  unchanged.
- `scripts/benchmark_runner/tests/test_report_winner_judge.py` —
  inject a fixture with two (backend, model) groups, varied judge
  ratings, mixed pass/fail; assert that:
  1. Calibrated dimensions emit verdicts; uncalibrated do not.
  2. Non-passing-on-both-sides samples are filtered out (the
     deterministic-first gate). Inject a non-passing sample that
     would swing the verdict if included; assert the verdict does
     not swing.
  3. `report_winner.py` is called with `declare_winner` — verified
     via spy / mock — but not modified (`git diff` clean).

### Files NOT to modify

- `scripts/benchmark_runner/report_winner.py` (D2 invariant —
  asserted by the spy/mock above + a git diff check in CI).

### Done when (per sub-issue D)

- Calibrated-dimensions winner-extension shipped; deterministic-first
  gate test green; `report_winner.declare_winner` is reused
  unchanged.

## Phase B5 — sub-issue E — First labeled calibration set + activate

### Files to create

- `benchmarks/calibration/cct-instance-v1.jsonl` — ≥50 task-runs
  × 4 dimensions = ≥200 JSONL records (one per (run_path,
  dimension)); spans ≥2 axes (default: `model` ×
  `repeated-runs`); labels by a single human reviewer (the
  maintainer) with notes per record where the rating is
  borderline.
- `benchmarks/calibration/cct-instance-v1.meta.json` —
  reviewer (or reviewers), labeling-session timestamps, the
  corpus-selection command used (so the selection step is
  reproducible).
- `benchmarks/calibration/cct-instance-v1.calibration-report.md`
  — output of `./scripts/benchmark calibrate
  --judge claude-code:sonnet --labels …`.
- `benchmarks/calibration/cct-instance-v1.calibrated-dimensions.json`
  — output of the same run; consumed by `report.py` at report
  time.
- (Optional) `doc_internal/2026-MM-DD-calibration-session.md` —
  internal notes from the labeling session, NOT committed if the
  notes contain reviewer fatigue / private commentary.

### Done when (per sub-issue E)

- The labeled set is on disk + the calibrate script has run + the
  resulting calibration-report is committed.
- If any dimensions cleared Spearman 0.6: subsequent reports show
  calibrated verdicts on those dimensions; the AC8
  deterministic-first invariant holds (asserted by a spot-check
  against one PR-attached comparison report).
- If zero dimensions cleared 0.6 (D6 terminal state): the
  calibration-report.md spells out the negative outcome; the
  judge-block of subsequent reports renders raw ratings with all
  dimensions flagged `uncalibrated`; the maintainer files (or
  declines to file) a rubric-v2 follow-up. #34 still closes;
  AC1–AC10 are still satisfied, AC4 vacuously (no calibrated
  dimensions to declare a verdict on).

## Reuse map

Defers to spec.md § Reuse map. Headline:

- `Backend` / `BackendResult` shape → cloned as `Judge` /
  `JudgeResult` in a parallel `judge/` package; not entangled.
- `claude_code` backend headless invocation → reused by
  `claude_code_judge`.
- `declare_winner` from `report_winner.py` → reused unchanged on
  the new `judge:<dim>` metric names.
- `run.py`'s `attempt_dir` / `score.json` write path → READ-ONLY;
  the judge writes the additive `judge.json` adjacent.
- `runs/` corpus (1171 attempt-records) → seeds the calibration
  set.

## Tooling decisions

- **No new external Python dependency.** Spearman ρ on N ≤ 200
  is trivially implementable in stdlib (`statistics` + rank-by-sort).
  Avoiding `scipy` keeps the harness's runtime footprint small
  and matches the existing report's stdlib-only posture.
- **SVG = pure-string emission.** Bar / histogram / forest plot
  are small enough that hand-written SVG is more legible and more
  testable than a matplotlib invocation. Confirms decision D8
  (additivity) — no plotting-library dependency creeps in.
- **HTML = stdlib-only.** No Jinja, no Pydantic, no
  templating-engine dependency.

## Test strategy

Stdlib `unittest`/pytest under
`scripts/benchmark_runner/tests/` (consistent with #32/#33/#36/#41
practice). New test modules per Phase B section. Run **per-module**
— the documented host failures
(`test_polyglot_adapter`×4, `test_cli_skeleton` hang, stale
`test_polyglot_dogfood_subset`, `fixtures/**/leap_test.py`
autocollection) are pre-existing, not regressions
(memory `project_benchmark_preexisting_env_test_failures`).

Mandatory guard tests:
- **Additivity regression** (Phase B3): a run with no `judge.json`
  emits a Markdown+JSON report byte-identical (modulo timestamps)
  to a snapshot baseline.
- **Deterministic-first enforcement** (Phase B4): a fixture with a
  non-passing sample that would swing the verdict if included
  asserts the verdict does not swing.
- **`report_winner.py` not-modified** (Phase B4): a CI gate
  (`git diff --quiet -- scripts/benchmark_runner/report_winner.py`
  against the merge base) before merging sub-issue D.

No live LLM in tests. Judge tests use recorded-transcript fake-CLI
fixtures, mirroring the codex/aider pattern.

## Delegation strategy

Single build agent, phase-scoped per sub-issue (under Option B);
reads spec/plan/tasks before each sub-issue's work; one sub-issue
per scoped invocation; runs that sub-issue's tests; does not
advance until green; does not commit (team lead commits with per-step
user diff approval). No parallel sub-agents — sub-issues sub-issue A and
sub-issue C CAN proceed in parallel structurally, but a single
serial pass is preferred to keep the diff-review surface bounded
(memory `team-lead-efficiency`).

Per-sub-issue agent prompts MUST include:
- The relevant spec.md § + the sub-issue's task list.
- The "do not touch" list (D-invariants: `run.py`,
  `report_winner.py`, etc.).
- The "verify every code path, not one sampled path" memory
  (memory `feedback_verify_delegated_build_trace_all_paths`).
- A reminder that `judge.json` is additive; running `judge` MUST
  NOT mutate `score.json`.

## Files to create (total, under Option B)

- `scripts/benchmark_runner/judge/{__init__,contracts,claude_code_judge,registry,runner}.py`
- `scripts/benchmark_runner/calibration/{__init__,corpus_select,validate,spearman}.py`
- `scripts/benchmark_runner/tests/test_judge_protocol.py`
- `scripts/benchmark_runner/tests/test_claude_code_judge.py`
- `scripts/benchmark_runner/tests/test_corpus_select.py`
- `scripts/benchmark_runner/tests/test_calibration_validate.py`
- `scripts/benchmark_runner/tests/test_spearman.py`
- `scripts/benchmark_runner/tests/test_report_html.py`
- `scripts/benchmark_runner/tests/test_report_csv.py`
- `scripts/benchmark_runner/tests/test_report_svg.py`
- `scripts/benchmark_runner/tests/test_report_no_judge_regression.py`
- `scripts/benchmark_runner/tests/test_report_winner_judge.py`
- `scripts/benchmark_runner/tests/fixtures/judge/transcript-*.txt`
- `benchmarks/calibration/rubric-default-v1.md`
- `benchmarks/calibration/cct-instance-v1.{jsonl,meta.json,calibration-report.md,calibrated-dimensions.json}`
- `specs/benchmark-llm-judge/{spec,plan,tasks}.md` +
  `origin-alignment-2026-05-20-0238.md` (this bundle)

## Files to modify

- `scripts/benchmark_runner/cli.py` — `judge`,
  `calibration-corpus`, `calibrate` subcommands; `report` gains
  `--html --csv --judge --calibrated-dimensions` flags.
- `scripts/benchmark_runner/_register.py` — judge registration.
- `scripts/benchmark_runner/report.py` — additive HTML/CSV/SVG
  emitters; calibrated-dimensions-aware aggregation; calls into
  the unchanged `declare_winner` on `judge:<dim>` metrics.
- `benchmarks/README.md` — judge usage, calibration usage,
  rubric-extension instructions.

## Files NOT to modify (D-invariants)

- `scripts/benchmark_runner/run.py` (D9)
- `scripts/benchmark_runner/contracts.py` (D2 — `Backend`,
  `BackendResult` shape stable)
- `scripts/benchmark_runner/report_winner.py` (D2 — `declare_winner`
  shape stable)

## Rollout (Option B)

1. Phase A bundle reviewed; user picks D1.
2. Phase B0: sub-issues sub-issue A–sub-issue E filed referencing this bundle;
   rubric v1 + judge default ratified.
3. Branches `feat/benchmark-llm-judge-a` … `e`, each with its own
   PR titled `feat(benchmark): … (Closes #<sub-issue real id>)`,
   using the numeric ID captured in TB0.4 — never the placeholder
   label.
4. Per-PR commits: diff shown + explicit user approval before
   every commit; never push to master.
5. PRs open only after per-module suites green,
   `check-origin-alignment.sh benchmark-llm-judge` ≤ 1, and any
   executable artifacts actually run (fake-judge suite; judge CLI;
   `report --html` rendered).
6. The first labeled calibration set (sub-issue E) is the last PR; it
   merges only after the human-labeling work is complete and the
   live `calibrate` run has produced its report.

## Option-A delta (if user picks Option A instead)

- Single branch `feat/benchmark-llm-judge`, single PR
  `Closes #34`.
- Phase B1–B4 happen in one commit chain; Phase B5 is the
  PR-merge gate (mirror #41's `_VERIFIED_VERSION` placeholder
  pattern at scale): a loud constant
  `CALIBRATION_SET_REQUIRED__DO_NOT_MERGE` in the report's
  calibrated-dimensions resolver, plus a self-enforcing test
  `test_calibration_set_present_for_merge`, both lifted only when
  the real labeled set lands in the same branch before merge.
- Trade-off: PR sits open for days/weeks while a human labels
  ≥50 records; large diff to review; merge gates on a single
  reviewer's calendar.
- Plan/tasks rewriting required if the user picks A.

## Option-C delta (NOT recommended — violates AC)

- Single PR ships sub-issue A–sub-issue D; sub-issue E becomes a documented maintainer
  procedure.
- Violates explicit #34 v3 AC ("Calibration set checked in:
  ≥50 task-runs spanning ≥2 axes of variation, full per-dimension
  human ratings"). #41 could ship the leaderboard as a maintainer
  procedure because the leaderboard run is NOT an AC of #41; the
  calibration set IS an AC of #34. Option C is therefore a scope
  regression against an explicit AC — recorded here for
  completeness, not as a recommended path.

## Risks

1. **Calibration fails on all dimensions (D6 terminal state).**
   Mitigation: spec.md treats this as a valid terminal outcome,
   not a build failure. The harness still ships correctly.
2. **Human labeling is slow / inconsistent.** Mitigation:
   sub-issue E is its own PR; the upstream code (sub-issue A–d) merges
   independently and is exercised by synthetic-label tests. The
   maintainer can iterate on labels without re-running upstream
   PRs.
3. **A reviewer-vs-reviewer baseline isn't established before
   thresholding.** Mitigation: rubric v1 ships with the 0.6
   threshold; rubric-v2 follow-up could add a small
   second-reviewer overlap to bound reviewer noise (out of scope
   for #34).
4. **The judge's free-text explanations include PII or copilot
   internals.** Mitigation: explanations are recorded as-is in
   `judge.json` but the recorded prompt + judge model are also
   stored, so a reviewer can audit and a future scrubber can
   re-process if needed. Judge default is `claude-code:sonnet` —
   the same content the backend already routes through.
5. **`report_winner.py` ends up needing a change after all.**
   Mitigation: the spec explicitly forbids it (D2), the plan
   tests for it (a CI gate against the merge base). If a change
   is truly required, that's a Phase B4 escalation back to the
   user — not a unilateral edit.

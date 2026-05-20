# Origin-Alignment Record — benchmark-llm-judge

Date: 2026-05-20 02:38 UTC
Gate: plan-approval (Phase A, pre-build)
Origin: gosha70/code-copilot-team#34 (v3 body, 2026-05-08)

Verdict: aligned (high)
Confidence: high

Revision 2026-05-20 (post peer review): two P1 review findings
addressed in-place (sub-issue close-keyword discipline; corrected
claude-code-judge determinism contract). User confirmed D1=Option B
(with real numeric sub-issue IDs captured in TB0.4), D4=approved
four v1 dimensions, D7=`claude-code:sonnet` with the corrected
determinism contract (temperature/seed recorded as
null/"unsupported", never silently 0.0). Bundle is now go-gated on
explicit user "go" only.

## What the user asked for (#34 v3)

Calibrated LLM-judge scoring + rich reports on top of the
deterministic harness from #32/#33. Five subsystems "deliverable in
order":

1. Calibration set: ≥50 task-runs spanning ≥2 axes of variation
   (adapters / backends / models / repeated-runs); per-dimension
   1–5 human ratings; `benchmarks/calibration/<name>.jsonl` schema
   (`{run_path, dimension, rating, notes}`).
2. Judge protocol mirroring the Backend contract from #32; initial
   `claude-code --model sonnet` judge; per-run `judge.json`.
3. Calibration validation: per-dimension Spearman correlation;
   threshold ≥ 0.6 (revisable); uncalibrated dimensions flagged in
   the report and excluded from winner math.
4. Rich reports (HTML + static-SVG charts + CSV) — ADDITIVE to
   the existing Markdown + JSON reports.
5. Winner-declaration extension on calibrated-judge dimensions
   using the same `Δ > 2σ AND ≥ threshold` rule with per-dimension
   threshold.

Explicit ACs (verbatim, abridged): calibration set checked in;
deterministic across re-runs; calibration script measures Spearman
+ outputs `calibration-report.md`; per-dimension ≥0.6 enforced;
HTML separates deterministic + calibrated-judge; static
SVG/PNG charts; CSV exports; deterministic-first ordering (a run
that fails deterministic tests cannot win on judge-only); no
dollar-cost figures anywhere; docs for adding a judge / extending
the rubric / re-running calibration.

Permanently OUT: dollar-cost reporting; replacing deterministic
scoring with judge scoring; new benchmark adapters (#33); new
copilot backends (#33); cross-CCT-instance shared calibration sets.

## What the spec/plan commit to

A parallel `scripts/benchmark_runner/judge/` package implementing
the `Judge` protocol (mirrors `Backend`); a `claude_code_judge`
that reuses the existing claude-code backend's headless invocation;
a strictly-additive `judge.json` per-attempt artifact (never
overwrites `score.json`); a corpus-selection CLI sourcing ≥50
task-runs from the existing `runs/` archive (1171 attempts on
disk, NO new benchmark spend required); a calibration-validation
script computing per-dimension Spearman + emitting
`calibration-report.md` + `calibrated-dimensions.json`; additive
HTML + CSV + static-SVG report emitters; a winner-extension that
reuses `report_winner.declare_winner` unchanged on `judge:<dim>`
metric names; deterministic-first ordering enforced at the
winner-extension step (only passing-on-both-sides attempts
contribute to a calibrated-judge verdict).

The deterministic harness (`run.py`, `score.json`,
`BackendResult`, `report_winner.py`, `contracts.py`) is **NOT
modified**. Markdown + JSON reports keep their existing shape (a
snapshot regression test guards byte-identity modulo timestamps
when no `judge.json` is present).

## Divergences (recorded; user confirmation pending)

1. **PR-structure: split #34 into sub-issues (Option B,
   APPROVED 2026-05-20).** The one-PR-per-issue rule (memory
   `feedback-pr-must-fully-address-issue`, 2026-05-19, derived
   from PR #38 revert) forbids partial PRs against one issue.
   #34 has 5 subsystems + a human-labeling dependency (≥50
   hand-labels) + an empirical research question
   (per-dimension Spearman ≥ 0.6). A single PR (Option A) would
   sit open for days/weeks while a human labels the corpus; a
   maintainer-procedure split (Option C) violates the explicit
   AC "Calibration set checked in: ≥50 task-runs…". Option B
   files **five real GitHub issues** in TB0.4 (placeholder
   labels A–E used in this bundle; real numeric IDs captured
   into `specs/benchmark-llm-judge/sub-issue-numbers.md` before
   any PR is opened). #34 closes automatically when sub-issue
   E's PR merges (its body carries a separate `Closes #34`
   keyword in addition to `Closes #<E's real id>`, per memory
   `feedback_github_close_keyword_per_issue` — one keyword per
   real issue, no shared keyword). Placeholder labels NEVER
   appear in PR descriptions. This is a STRUCTURAL change to
   how #34 is closed (the epic closes by linkage to its
   sub-issues), NOT a scope change — engineering work and ACs
   are identical to Option A.

2. **Calibration corpus from existing `runs/` archive.** Issue
   v3 leaves the corpus source open. Inventory (2026-05-20):
   1171 attempt-records across 50 run-dirs, 5 (backend, model)
   tuples (claude-code × phi-3 / qwen2.5-coder:7b / qwen3.6:27b
   / RedHatAI/Qwen3-Coder-Next-NVFP4 / sonnet plus a stub
   swe-bench-verified), 44 passing total (3.8%), 568 non-passing
   attempts with file changes. ≥50 task-runs spanning ≥2 axes
   (model × repeated-runs) are immediately sourcable; NO new
   benchmark spend is required. This is methodology-honest (the
   calibration corpus reflects the actual CCT-instance workload)
   and schedule-honest (no new run campaign before
   human-labeling).

3. **Judge rates non-passing code too.** Issue v3 framing
   ("quality differences inside a passing run") implies
   passing-only rating. The corpus reality (44 passing total,
   mostly `sonnet`) makes passing-only infeasible at N=50 and
   collapses the model variation axis. The rubric dimensions
   (idiomaticity / error_handling / test_thoughtfulness /
   security_hygiene) are defined for any code the model
   produced; non-passing attempts get rated. Deterministic-first
   ordering is enforced separately at the winner-extension step
   (only passing-on-both-sides samples enter `declare_winner`),
   which keeps the explicit AC ("a run that fails deterministic
   tests cannot win on judge-only criteria") satisfied.

4. **Default rubric dimensions.** Issue v3 names four candidates
   and defers "final dimensions chosen at implementation time."
   The spec adopts the four named dimensions as v1, pending
   Phase B0.2 ratification with the user.

5. **No new external Python dependency.** Spearman ρ + SVG
   emission stay stdlib-only (no scipy, no matplotlib, no
   templating engine). Matches the existing harness's stdlib-only
   posture. Recorded as a tooling decision, not a deviation
   from origin.

## Open questions for the user (gate the plan)

Resolved in peer-review round 2026-05-20:

- **D1 (PR structure):** **APPROVED** — Option B, with real
  numeric sub-issue IDs filed in TB0.4 and captured in
  `sub-issue-numbers.md`. Placeholder labels A–E never appear in
  PR descriptions (close keywords require real numeric IDs).
- **D4 (rubric v1 dimensions):** **APPROVED** —
  `idiomaticity`, `error_handling`, `test_thoughtfulness`,
  `security_hygiene`. 1–5 anchor descriptions to land in
  `benchmarks/calibration/rubric-default-v1.md` in #34-sub-issue-A.
- **D7 (judge backend default):** **APPROVED with corrected
  contract** — `claude-code:sonnet` with `temperature: null` /
  `seed: null` / `temperature_control: "unsupported"` /
  `seed_control: "unsupported"`. The local `claude` CLI exposes
  only `--model`/`--fallback-model`; the judge MUST NOT claim
  T=0 it cannot enforce. Re-run stability is empirical and
  surfaced by the calibration Spearman.

## Verification

- `./scripts/validate-spec.sh --feature-id benchmark-llm-judge`:
  **PASS** (2/2), exit 0 — confirmed on the team-lead session
  host 2026-05-20, re-confirmed after the peer-review fixes.
- `./scripts/check-origin-alignment.sh benchmark-llm-judge`:
  **PASS** (aligned, high), exit 0 — confirmed on the
  team-lead session host 2026-05-20 after the peer-review
  fixes (was aligned/medium with the original draft; the two
  P1 fixes promoted the verdict to high).
- The corpus-inventory numbers in spec.md were computed by
  walking `runs/**/run-record.json` + `runs/**/score.json` on
  the team-lead session host on 2026-05-20. Re-confirmation on
  the maintainer machine is gated as TB0.1 before any code is
  written.

## Peer-review revision history

- **Round 1 (2026-05-20).** Original draft; verdict aligned
  (medium); D1/D4/D7 pending user choice.
- **Round 2 (2026-05-20).** Two P1 review findings addressed
  in-place:
  - **Sub-issue close-keyword discipline.** Plan + tasks
    rewritten to use placeholder labels A–E in the planning
    bundle; TB0.4 files five real GitHub issues and captures
    their numeric IDs into `sub-issue-numbers.md` before any
    PR is opened. Every PR title uses the captured numeric ID
    in its `Closes #NN` keyword; placeholder labels never
    appear in PR descriptions.
  - **Claude-code judge determinism contract.** Local
    `claude --help` exposes only `--model` /
    `--fallback-model` — no `--temperature`, no `--seed`. The
    judge therefore records `temperature: null` / `seed: null`
    / `temperature_control: "unsupported"` /
    `seed_control: "unsupported"`. Re-run stability is
    empirical and surfaced by the calibration step's Spearman,
    not silently claimed as T=0. Fixed in spec.md
    (Interface § Initial judge implementation, the schema
    example, D7, AC2) and tasks.md (TB1.2).
- **Round 3 (2026-05-20).** Two P2 review findings addressed:
  spec.md § D1 table now uses placeholder labels A–E (was
  `#34a`–`#34e`) with the same B0 numeric-ID note; this
  alignment record refreshed to reflect resolved D1/D4/D7
  decisions and actual validation results.

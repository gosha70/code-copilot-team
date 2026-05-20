---
feature_id: benchmark-llm-judge
spec_mode: full
status: draft
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
    Issue #34 (v3, 2026-05-08) adds calibrated LLM-judge scoring on top
    of the deterministic harness from #32/#33, plus rich reports
    (HTML/CSV/static charts). Five subsystems "deliverable in order":
    (1) calibration set ≥50 task-runs spanning ≥2 axes of variation
    (adapters/backends/models/repeated-runs), human 1–5 ratings per
    rubric dimension; (2) Judge protocol mirroring the Backend contract,
    `judge.json` per run; (3) calibration validation — per-dimension
    Spearman ≥ 0.6, uncalibrated dimensions excluded from winner math;
    (4) rich reports — HTML/static-SVG-charts/CSV, ADDITIVE to the
    existing Markdown+JSON reports; (5) winner-declaration extension —
    same `Δ > 2σ AND ≥ threshold` rule on calibrated-judge dimensions
    with per-dimension threshold; deterministic-first ordering enforced
    (a run that fails deterministic tests cannot win on judge-only).
    Permanently out of scope: dollar-cost reporting; replacing
    deterministic scoring with judge scoring.

    Two properties make #34 structurally unlike #36/#41: (a) a HUMAN
    LABELING dependency on the calibration set (hours of reviewer
    work, not an agent task); (b) a RESEARCH QUESTION — the judge is
    only useful if Spearman ≥ 0.6 on ≥1 dimension, which is an
    empirical outcome, not a guarantee. The plan treats "the judge
    fails calibration on some/all dimensions" as a defined-outcome
    path, not an edge case.

    Corpus inventory finding (2026-05-20, 5 axes inspected): 1171
    attempt-records exist across 50 run-dirs, 5 (backend, model) tuples
    (claude-code × {phi-3, qwen2.5-coder:7b, qwen3.6:27b,
    RedHatAI/Qwen3-Coder-Next-NVFP4, sonnet} + one stub
    swe-bench-verified). Pass rate is 3.8% (44 passing task-runs); 568
    non-passing attempts have file changes (judge-ratable). The
    calibration corpus can be sourced from existing runs (≥2 axes:
    models × repeated-runs, optionally also benchmarks×backends if
    #33 Track B lands first); NO additional benchmark spend is
    required to assemble it. Human labeling time, however, is.
---

# Calibrated LLM-Judge Scoring + Rich Reports (#34)

> **Judge is secondary; deterministic-first non-negotiable.** A run
> that fails deterministic tests cannot win on judge-only criteria
> (issue v3 explicit AC). The judge augments comparison *inside*
> passing runs (or, in the report layer, surfaces advisory ratings
> alongside non-passing runs) — it never overrides the deterministic
> verdict.

## Problem

#32/#33 deliver a benchmark-agnostic harness that compares
copilots/models on pass/fail, elapsed time, and token usage with a
calibrated winner-declaration rule (`Δ > 2σ AND ≥ threshold`). What
that harness cannot tell apart: two passing runs on the same task that
produce visibly different code (idiomaticity, error handling, test
thoughtfulness, security hygiene). These are the dimensions human
reviewers actually disagree about and the dimensions a leaderboard
score-row never surfaces.

#34 adds an LLM-judge that rates those dimensions — but only after a
human-labeled calibration set proves the judge's verdict correlates
with reviewer judgment on this CCT instance's corpus. Without
calibration, an LLM judge is just another opinion; the winner rule
must not be widened on uncalibrated signal.

Two structural properties distinguish #34 from #36 (bench driver) and
#41 (aider backend):

1. **Human-labeling dependency.** ≥50 task-runs must be hand-labeled
   on a multi-dimensional rubric. This is reviewer time, not an agent
   task — the analog of #41's recorded-capture gate, but ~50× larger.
2. **Empirical research question.** The judge is only useful if
   Spearman ≥ 0.6 on ≥1 rubric dimension. That correlation is an
   empirical outcome. "All dimensions fail calibration" is a real
   possible outcome and must have a defined handling path.

## Strategic framing

The deterministic score from #32 is the **primary** signal — what
merges, what wins. The LLM-judge score is a **secondary** signal that
augments comparison; it never overrides the deterministic verdict.

This ordering is enforced in three places:
- **Report layout** — deterministic block first, judge block second,
  with explicit visual separation (issue v3 AC).
- **Winner declaration** — calibrated-judge dimensions can declare a
  winner only when both compared sides pass deterministically (issue
  v3 AC).
- **Uncalibrated dimensions** — never declare a winner; raw ratings
  still appear in the report for reviewer use.

Permanently out of scope (issue v3): dollar-cost reporting; replacing
deterministic scoring with judge scoring; authoring new adapters
(#33); adding new backends (#33); cross-CCT-instance shared
calibration sets (deferred follow-up).

## Calibration-corpus reality check (2026-05-20)

A direct inventory of `runs/` produced numbers that **shape the whole
plan** and are recorded here so the spec can be re-derived without
re-running the inventory:

| Backend | Model | Benchmark | Attempts | Passing |
|---|---|---|---:|---:|
| claude-code | qwen2.5-coder:7b | aider-polyglot | 567 | 3 |
| claude-code | phi-3 | aider-polyglot | 513 | 3 |
| claude-code | RedHatAI/Qwen3-Coder-Next-NVFP4 | aider-polyglot | 39 | 10 |
| claude-code | sonnet | aider-polyglot | 34 | 27 |
| claude-code | qwen3.6:27b | aider-polyglot | 14 | 0 |
| stub | (none) | swe-bench-verified | 3 | 1 |
| claude-code | sonnet | swe-bench-verified | 1 | 0 |
| **Total** | | | **1171** | **44** |

Three load-bearing consequences:

1. **The calibration corpus does NOT need new benchmark spend.** ≥50
   task-runs spanning ≥2 axes of variation (models × repeated-runs;
   adapters once #33 Track B lands) are already on disk. The corpus
   build step is a *selection + labeling* exercise, not a *generation*
   exercise.
2. **A passing-runs-only calibration corpus is infeasible at N=50.**
   Only 44 passing runs exist, almost all on `sonnet`. A
   passing-only set would (a) miss the 50 floor and (b) collapse the
   "model" variation axis to a single model. The corpus must mix
   passing and non-passing runs — the rubric dimensions
   (idiomaticity, error handling, etc.) are *defined for any code
   the model produced*, not only passing code. 568 non-passing
   attempts with file changes are available.
3. **The "deterministic-first cannot win on judge" rule still
   protects the report.** Even though non-passing attempts are
   *rated* by the judge, the winner-declaration extension only
   activates a calibrated-judge verdict when both sides
   deterministically pass on the same task (interface § Winner
   extension).

## User Scenarios

1. **Maintainer adds the judge to a fresh comparison run.** A
   maintainer who already ran
   `./scripts/benchmark compare --config <cfg>` runs
   `./scripts/benchmark judge --run-dir runs/<ts>/ [--judge claude-code:sonnet]`.
   The harness walks every `attempt-NN-run-NN/` under the run-dir,
   invokes the configured judge against each attempt's diff + prompt
   + verify output, and writes `judge.json` adjacent to `score.json`
   in every attempt directory. No existing artifact is overwritten.
   `score.json` is the authoritative deterministic verdict; the
   judge can be re-run any number of times without invalidating it.

2. **Reviewer opens the rich HTML report.** Same maintainer runs
   `./scripts/benchmark report --run-dir runs/<ts>/ --html`. The
   produced `report.html` (static; no JS required) shows: §
   Deterministic results (existing table contents, unchanged) →
   visual separator → § Judge ratings (per-dimension table with
   calibration-status badge per dimension: `calibrated`/`uncalibrated`)
   → § Verdicts (deterministic verdicts first; calibrated-judge
   verdicts appear only for dimensions that passed Spearman ≥ 0.6).
   Charts (bar/histogram/forest plot) render as embedded static
   SVG/PNG. The same data also exports to `report.csv` (per-task
   table) and `report-by-model.csv` (per-(backend, model) table).

3. **Calibration validation succeeds on some dimensions, fails on
   others.** A maintainer runs
   `./scripts/benchmark calibrate --judge claude-code:sonnet
   --labels benchmarks/calibration/<name>.jsonl`. The script invokes
   the judge against each labeled run, computes per-dimension
   Spearman + exact-match-rate, writes
   `benchmarks/calibration/<name>.calibration-report.md`, and updates
   `benchmarks/calibration/<name>.calibrated-dimensions.json` (the
   list of dimensions ≥ 0.6 Spearman, consumed by `report.py` and
   `report_winner.py` at report time). A dimension that scored 0.42
   appears in the report as `uncalibrated (Spearman 0.42 < 0.6)` and
   is excluded from winner math.

4. **All dimensions fail calibration.** Same flow as scenario 3,
   `calibrated-dimensions.json` ends up empty. The HTML report
   renders the judge block in full (raw ratings still visible for
   reviewer use) but no calibrated-judge verdict is declared on any
   dimension. `report.md` / `report.json` carry the same posture.
   The harness, the judge integration, the reports, and the
   winner-declaration extension are still correctly built; the only
   loss is that the empirical research question came back negative
   on this rubric × this judge × this corpus, and the maintainer
   either (a) revises the rubric, (b) tries a different judge model,
   or (c) raises the threshold debate (see § Failure mode below).

5. **CI re-runs the stub-backend smoke without the judge.** A
   contributor's PR re-runs the stub × stub end-to-end smoke from
   #32 + #36. The judge subsystem MUST be opt-in — `./scripts/benchmark
   report` without `--html`/`--judge` produces the existing
   Markdown+JSON report unchanged. No CI cost change, no new
   external dependency in the smoke path.

6. **Reviewer audits the judge's verdict.** A reviewer opens
   `attempt-01-run-001/judge.json` and sees: per-dimension rating
   (1–5), the judge's full free-text explanation, and the exact
   prompt + judge model + judge backend used. `judge.json` is
   reproducible: re-running the judge against the same attempt with
   the same judge config produces a byte-identical (or
   semantically-identical, modulo LLM nondeterminism the spec
   acknowledges and the judge records) verdict.

## Interface

### Judge protocol (mirrors the Backend protocol)

A new `Judge` protocol in
`scripts/benchmark_runner/judge/contracts.py` (parallel to the
existing `Backend` protocol in `contracts.py`):

```python
@runtime_checkable
class Judge(Protocol):
    judge_id: str

    def rate(self, attempt: JudgeInput) -> JudgeResult: ...
```

`JudgeInput` (frozen dataclass) carries: `attempt_dir: Path` (the
already-written attempt directory), `task_id: str`, `benchmark_id:
str`, the per-attempt `diff_path` / `prompt_path` / `verify_output`
that the judge needs as evidence, and a `rubric: RubricSpec`
(dimensions + per-dimension prompt fragment). The judge does NOT
re-execute the model — it reads what `run.py` already wrote.

`JudgeResult` (frozen dataclass) carries: per-dimension `rating: int
∈ {1..5}`, per-dimension `explanation: str`, `judge_model: str`,
`judge_backend_id: str`, `prompt_sha256: str`, optional
`tokens_input/output`, optional `seed`. None means "judge did not
provide"; do not coerce.

### Initial judge implementation

`scripts/benchmark_runner/judge/claude_code_judge.py` — a Judge that
runs `claude-code` headlessly with a fixed rubric prompt template.
Reuses the existing `claude_code` backend's headless invocation
pattern + the same provider-routing env vars (so the judge can route
to vLLM/Ollama through `ANTHROPIC_BASE_URL`).

**Determinism contract (corrected 2026-05-20 per peer review).** The
local `claude` CLI surface exposes `--model` / `--fallback-model`
only — no `--temperature`, no `--seed` flag. The judge therefore
**cannot pin temperature or seed**. Re-run stability is an empirical
property, not a guaranteed one. `judge.json` records what the judge
actually controlled:

- `judge_invocation.model` — the model alias passed via `--model`.
- `judge_invocation.temperature` — `null` (CLI does not expose the
  knob; the judge does not assume the model defaults to 0).
- `judge_invocation.seed` — `null` (same reason).
- `judge_invocation.provider_endpoint_present` — boolean only.
- `prompt_sha256` per (dimension, attempt) — what the judge sent,
  byte-identifiable for audit.

Re-run agreement is a property the calibration step measures (a
re-run of the judge against the same attempts should produce
similar ratings; large variance shows up as low Spearman against
the human labels). The harness does NOT silently claim
`temperature: 0.0` when the CLI cannot enforce it.

If a future judge backend (or future CLI release) exposes
temperature / seed, that judge implementation MAY set those fields
to non-null values; the schema is forward-compatible.

Default judge: `claude-code:sonnet` (model string identical to the
backend convention). User-overridable via
`./scripts/benchmark judge --judge claude-code:<model>` and via
config-file consumers. A maintainer who wants pinnable temperature
+ seed today files a follow-up to add a non-claude-code judge
backend; that is out of scope for #34.

### `judge.json` schema (additive; never overwrites `score.json`)

Written per attempt at `<attempt_dir>/judge.json`:

```json
{
  "schema_version": "1.0",
  "judge_id": "claude-code-judge",
  "judge_model": "sonnet",
  "judge_backend_id": "claude-code",
  "rubric_name": "default-v1",
  "rubric_dimensions": ["idiomaticity", "error_handling",
                        "test_thoughtfulness", "security_hygiene"],
  "ratings": {
    "idiomaticity": { "rating": 4, "explanation": "...",
                      "prompt_sha256": "..." },
    "error_handling": { "rating": 3, "explanation": "...",
                        "prompt_sha256": "..." },
    ...
  },
  "judge_invocation": {
    "model": "sonnet",
    "temperature": null,
    "seed": null,
    "temperature_control": "unsupported",
    "seed_control": "unsupported",
    "provider_endpoint_present": true
  }
}
```

Multiple judges can write side-by-side files
(`judge-<judge_id>.json`); the default file name (`judge.json`)
points at whichever judge was nominated for winner-extension math.

### Calibration-set schema

`benchmarks/calibration/<name>.jsonl` — one JSONL record per
(task-run × dimension) pair (issue v3 verbatim):

```json
{"run_path": "runs/<ts>-…/<task-slug>/attempt-01-run-001",
 "dimension": "idiomaticity",
 "rating": 4,
 "notes": "naming + iteration style idiomatic for Python;
           one block could use a comprehension"}
```

A companion `<name>.meta.json` records the human reviewer(s),
labeling-session timestamps, and the corpus-selection commands so the
labeled set is reproducible.

### Calibration validation

`./scripts/benchmark calibrate --judge <id> --labels
benchmarks/calibration/<name>.jsonl [--threshold 0.6]` runs the judge
against every distinct `run_path` in the labels file, joins judge
ratings with human ratings on `(run_path, dimension)`, and computes
per-dimension Spearman ρ + exact-match rate. Writes:

- `benchmarks/calibration/<name>.calibration-report.md` — per-dimension
  numbers + a scatter-plot SVG per dimension + the threshold +
  pass/fail per dimension.
- `benchmarks/calibration/<name>.calibrated-dimensions.json` — the
  machine-readable list of calibrated dimensions and per-dimension
  threshold used. THIS is the file that `report.py` and
  `report_winner.py` consume at report time.

The default threshold is `0.6` (issue v3 verbatim, "starting bar,
revisable based on observed reviewer-vs-reviewer agreement on the
calibration set itself"). The threshold lives in the
`calibrated-dimensions.json` so reports are self-describing: a
reader can see what threshold gated this verdict without re-running
calibration.

### Rich-reports surface (ADDITIVE)

`./scripts/benchmark report --run-dir <d> [--html] [--csv]
[--judge <id>] [--calibrated-dimensions <path>]`:

- Without flags: existing Markdown + JSON only (no regression).
- `--html`: emit `report.html` with deterministic block first,
  judge block second, calibrated verdicts third. Charts embedded as
  static SVG (no JS).
- `--csv`: emit `report.csv` (per-task table) and
  `report-by-model.csv` (per-(backend, model) table).
- `--judge` / `--calibrated-dimensions`: locate the judge.json
  files (default: `judge.json` per attempt) and the calibrated-dim
  list (default: nearest `*.calibrated-dimensions.json` under
  `benchmarks/calibration/`, or none if absent).

Charts:
- pass-rate bar chart per (backend, model)
- per-dimension rating histogram per (backend, model)
- A/B forest plot for winner-declaration verdicts (deterministic +
  calibrated-judge verdicts in a single plot, with deterministic
  rows above a visual separator)

### Winner-declaration extension

`report_winner.declare_winner` is reused unchanged for calibrated-judge
dimensions. New caller logic in `report.py`:

- For each calibrated dimension `d` (Spearman ≥ threshold), build
  samples-per-(backend, model) from passing-attempt `judge.json`
  ratings for `d`, then call
  `declare_winner(MetricSpec(name=f"judge:{d}", kind="continuous",
                  higher_is_better=True,
                  continuous_threshold_relative=0.10), …)`.
  Only passing attempts contribute to the samples — this is the
  code-level enforcement of issue v3 AC "a run that fails
  deterministic tests cannot win on judge-only criteria".
- Uncalibrated dimensions: skipped (no `declare_winner` call); they
  surface in the report as `uncalibrated (Spearman <observed> <
  <threshold>)`.

The deterministic verdicts (pass-rate, elapsed-seconds, etc.) keep
their existing rule and threshold unchanged — `report_winner.py` is
not modified beyond what's required to make the metric name visible
in the verdict output.

## Reuse map

- `scripts/benchmark_runner/contracts.py` — `Backend`/`BackendResult`
  shape that the new `Judge`/`JudgeResult` mirrors.
- `scripts/benchmark_runner/backends/claude_code.py` — headless
  invocation + provider-routing env-var pattern reused by the
  `claude_code_judge`.
- `scripts/benchmark_runner/run.py` — `attempt_dir` layout +
  `score.json` write path; `judge.json` lands adjacent and is never
  overwritten by `run.py`. NO change to `run.py` is required.
- `scripts/benchmark_runner/report_winner.py` — `declare_winner` is
  reused unchanged on calibrated-judge dimensions. NO change to
  `report_winner.py` is required (the verdict ID `"judge:<dim>"` is
  encoded by the caller).
- `scripts/benchmark_runner/report.py` — extended with HTML/CSV
  emitters + judge-aware aggregation; the existing Markdown+JSON
  paths are NOT changed.
- `runs/` corpus — 1171 attempt-records seed the calibration set; no
  new benchmark spend required.

## Design Decisions

> **D1 is open and gates the bundle structure.** Sections below
> describe the chosen subsystems and decisions that hold across all
> three D1 options. The Phase B implementation order and the per-PR
> AC mapping depend on which D1 option the user picks.

### D1 — PR structure (open; team-lead recommends Option B)

#34 has 5 subsystems, an empirical research question, and a
human-labeling dependency on the calibration set. The
one-PR-per-issue rule (memory `feedback-pr-must-fully-address-issue`,
2026-05-19, derived from PR #38 revert) forbids partial PRs against
one issue. Three options were evaluated; the team lead recommends
**Option B**.

> **Sub-issue labels A–E are PLACEHOLDERS, not GitHub
> close-keyword targets.** `Closes #34a` does NOT auto-close
> anything — close keywords require real numeric issue IDs.
> Phase B0 (TB0.4) files five real GitHub issues, captures their
> numeric IDs into `specs/benchmark-llm-judge/sub-issue-numbers.md`,
> and every later PR uses those numeric IDs in its `Closes #NN`
> keyword (placeholder labels never appear in a PR description).
> Memory `feedback_github_close_keyword_per_issue`: one keyword
> per real issue.

| Option | Shape | Pros | Cons |
|---|---|---|---|
| **A — one PR, labeling gate** | All 5 subsystems land in one branch; merge blocked on the labeled calibration set landing (mirror #41's `_VERIFIED_VERSION` placeholder pattern at much larger scale). | Closes #34 in one shot; matches the issue's "deliverable in order" framing literally. | PR sits open for days/weeks while a human labels ≥50 task-runs; large PR is hard to review; the human-labeling step is irreversibly serial with merge. |
| **B — split #34 into sub-issues (RECOMMENDED)** | File five real GitHub issues, each fully closable in one PR. Suggested split (labels are placeholders until TB0.4 captures numeric IDs): **A** Judge protocol + scorer + corpus-selection CLI (no labels); **B** Calibration validation harness + Spearman gate (no labels yet, tested against synthetic labels); **C** Rich reports — HTML/CSV/SVG (no judge dependency, additive); **D** Winner-extension on calibrated dimensions (depends on A+B); **E** Land the actual labeled calibration set + first `calibration-report.md` + activate calibrated dimensions in CCT's reports. | Each PR fully closes its own issue (rule compliant). Buildable code (A/B/C/D) ships in parallel with the human-labeling work (E). The empirical research question is isolated to E — code can still merge if calibration fails. | Requires filing 5 sub-issues + capturing their numeric IDs before any PRs reference them; mildly contradicts #34's "deliverable in order" framing (the original five subsystems remain the order; they just become separate issues). #34 becomes the epic, closed automatically when the E PR merges (its body carries a separate `Closes #34` keyword in addition to `Closes #<E's real id>`). |
| **C — one PR for buildable code, calibration as maintainer procedure** | Ship judge + reports + validation harness + winner-ext in one PR; calibration set ≥50 + the actual calibration-report.md are a documented maintainer procedure (mirror #41's leaderboard decision). | One PR; no labeling-gate wait. | Directly violates an explicit #34 AC ("Calibration set checked in: ≥50 task-runs spanning ≥2 axes of variation, full per-dimension human ratings"). #41 could ship the leaderboard as a maintainer procedure because the leaderboard run is NOT an AC of #41; the calibration set IS an AC of #34. Option C is therefore a scope regression against an explicit AC, not a parallel of the #41 pattern. |

**Recommendation: Option B.** Rationale: the one-PR-per-issue rule is
binding; the calibration set is an explicit AC of #34 (rules out
Option C); a single-PR gate at the scale of ≥50 hand-labels is the
exact "schema-phase-ships-with-spec-bundle" anti-pattern the rule
was written against (rules out Option A). The sub-issue split lines
up cleanly with the issue's own enumeration of subsystems.

### D2 — Calibration corpus source

Existing `runs/` corpus (1171 attempt-records, 5 (backend, model)
tuples, mostly aider-polyglot). **No new benchmark spend is required
to source ≥50 task-runs spanning ≥2 axes.** Variation axes selected
by default: `model` (5 distinct) × `repeated-runs` (many same-tuple
re-runs). Additional axes (`adapter`, `backend`) light up if/when
#33 Track B lands; the corpus-selection CLI MUST be axis-agnostic
so re-sourcing is a config change, not a code change.

### D3 — Judge rates non-passing code too

The rubric dimensions (idiomaticity, error handling, test
thoughtfulness, security hygiene) are *defined for any code the
model produced* — a failing run can still have idiomatic Python with
a logic bug, or non-idiomatic Python that happens to pass. Rating
the full corpus (not just passing runs) is necessary because the
passing-run-only set (44 total, almost all `sonnet`) can't hit N=50
or span multiple model variation axes.

Deterministic-first ordering is enforced separately, **at the
winner-extension step**: only passing-on-both-sides attempts
contribute samples to a calibrated-judge winner verdict (interface
§ Winner extension). Non-passing-attempt ratings still appear in
the report's judge block for reviewer use, never in the verdict.

### D4 — Default rubric dimensions

Issue v3 enumerates four candidate dimensions with "final dimensions
chosen at implementation time":
**idiomaticity**, **error_handling**, **test_thoughtfulness**,
**security_hygiene**. The spec adopts these as the v1 default and
records them in `rubric-default-v1.md`. The rubric is data, not
code — extending or replacing the rubric requires a new
`rubric-default-vN.md` + a new calibration-report; no scorer or
report code change.

### D5 — Spearman threshold default

`0.6` per dimension (issue v3 verbatim). The threshold is stored in
the calibrated-dimensions JSON the report consumes, so reports are
self-describing without re-running calibration. Tightening the
threshold (e.g. raising to 0.7) is a maintainer-side flag at
calibration time, not a code change.

### D6 — Calibration failure handling (the research-question path)

If a dimension scores Spearman < threshold, `calibrated-dimensions.json`
omits it. The report still renders raw ratings for that dimension
(advisory only) and labels it `uncalibrated (Spearman X.XX < 0.6)`.
**Zero dimensions calibrated is a valid terminal state** — the
harness is still correctly built; only the calibrated-judge winner
verdict is empty. The maintainer's recovery options are (a) revise
the rubric (new `rubric-default-vN.md`), (b) try a different judge
model, (c) acknowledge the negative result and treat the judge as
advisory-only on this CCT instance. Choice (c) is a legitimate
outcome of the empirical research question, NOT a build failure.

### D7 — Judge backend default

`claude-code:sonnet` via the harness `Backend` protocol — same
headless invocation, same provider-routing env vars
(`ANTHROPIC_BASE_URL`, etc.), same provider-presence boolean
recording (never set, never logged values). This means the judge can
route to vLLM/Ollama through the same gateway the backend uses; no
new provider-config surface is introduced.

**Determinism caveat (peer-reviewed 2026-05-20).** The local
`claude` CLI surface exposes `--model` / `--fallback-model` only —
no `--temperature`, no `--seed`. The claude-code judge therefore
records `temperature: null` / `seed: null` /
`temperature_control: "unsupported"` and treats re-run stability as
an empirical property measured by the calibration step, not a
guarantee. A maintainer who needs pinned T=0 / seed today must add
a non-claude-code judge backend (e.g. a direct vLLM HTTP judge);
that's a follow-up, out of scope for #34. Interface § Initial
judge implementation and AC2 spell out the corrected contract.

### D8 — Additivity discipline

HTML / CSV / SVG charts are ADDITIVE outputs. Markdown + JSON
reports from #32/#33 are NOT removed and NOT changed beyond what's
required to surface judge-block content when present. A run that
has no `judge.json` files MUST produce a report identical (modulo
timestamp lines) to the #32 baseline — this is the no-regression
invariant the contributor smoke test in scenario 5 protects.

### D9 — `score.json` immutability

`judge.json` is a SEPARATE file. `run.py` is NOT modified.
Calibration / re-running the judge / changing the rubric MUST NOT
require re-running the underlying benchmark. This is the
contract that makes the corpus-as-calibration-source plan
(decision D2) viable: the existing 1171 attempt-records can be
labeled and judged without any re-execution.

## Requirements

1. **R1 — Judge protocol.** New `scripts/benchmark_runner/judge/`
   package with `Judge` protocol mirroring `Backend`. `claude_code`
   judge implementation. `judge.json` written per attempt, additive
   to `score.json`.
2. **R2 — Corpus-selection CLI.** `./scripts/benchmark
   calibration-corpus --axes <axes> --target-n <n>` selects task-runs
   from the existing `runs/` archive, writes a
   `<name>.corpus.jsonl` (the unlabeled selection) and a
   `<name>.meta.json` (the selection command, axes, counts).
   Axis-agnostic — works for adapter/backend/model/repeated-runs.
3. **R3 — Calibration set + human-labeling format.**
   `benchmarks/calibration/<name>.jsonl` schema (issue v3 verbatim),
   per-(run_path, dimension) records. Companion
   `<name>.meta.json` records reviewers + corpus-selection
   reproducibility data.
4. **R4 — Calibration validation script.** `./scripts/benchmark
   calibrate` runs the judge against the labeled corpus, computes
   per-dimension Spearman, writes `<name>.calibration-report.md` +
   `<name>.calibrated-dimensions.json`. Default threshold 0.6.
5. **R5 — Rich reports (additive).** `./scripts/benchmark report
   --html --csv [--judge <id>] [--calibrated-dimensions <p>]`
   emits HTML + CSV. Static SVG charts (bar, histogram, forest
   plot). Existing Markdown/JSON unchanged.
6. **R6 — Deterministic-first ordering enforced.** In the
   winner-extension caller, calibrated-judge samples include
   only passing-on-both-sides attempts. Non-passing ratings appear
   in the report but never in the verdict.
7. **R7 — Documentation.** "How to add a new judge", "How to
   extend the rubric", "How to re-run calibration" — three
   procedure docs landing alongside the code that implements
   them.

## Constraints / What NOT to Build

1. **No change to `run.py` or `score.json`.** `judge.json` is
   strictly additive. Calibration / rubric changes must not
   require re-running the underlying benchmark.
2. **No change to `report_winner.declare_winner`.** The same
   function is called on new metric names; no rule, threshold, or
   significance-gate code is touched.
3. **No dollar-cost reporting anywhere** (permanently out of scope
   per #34 v3).
4. **No removal of Markdown / JSON reports.** HTML / CSV are
   additive.
5. **No replacement of deterministic scoring with judge scoring.**
   Judge is always secondary; uncalibrated dimensions never declare
   a winner; passing-on-both-sides is required for calibrated-judge
   verdicts.
6. **No cross-CCT-instance shared calibration sets** (deferred
   follow-up per #34 v3 OUT list).
7. **No new benchmark adapters or copilot backends** (#33's
   territory; #34 reuses what exists).
8. **No live LLM in tests.** Judge tests use a recorded-transcript
   fake-judge shim (mirror the codex/aider fake-CLI pattern); no
   live judge invocation in CI.

## Key Entities

- **Judge protocol** — the contract every judge implementation
  satisfies (analog of `Backend`).
- **`judge.json`** — the additive per-attempt rating artifact.
- **Rubric (`rubric-default-v1.md`)** — the prompt-template + the
  list of rated dimensions; data, not code.
- **Calibration set (`<name>.jsonl` + `<name>.meta.json`)** — the
  human-labeled corpus the judge is validated against.
- **`<name>.calibration-report.md` + `<name>.calibrated-dimensions.json`** —
  the validation artifacts; the JSON is consumed by reports and
  the winner extension.
- **Static-SVG charts** — bar / histogram / forest plot rendered
  without JS, suitable for archived reports and email attachment.
- **Deterministic-first gate** — the report-side rule that strips
  non-passing attempts from calibrated-judge verdict samples.

## Success Criteria (mapped to issue v3 AC)

- [ ] **AC1** Calibration set checked in: ≥50 task-runs spanning
      ≥2 axes of variation; full per-dimension human ratings.
      *(Phase-B5 deliverable; the labeling work happens after the
      buildable code lands.)*
- [ ] **AC2** Judge scorer implemented; `judge.json` per attempt.
      Determinism contract (peer-reviewed 2026-05-20): the local
      `claude` CLI does not expose `--temperature` or `--seed`, so
      the claude-code judge records both as `null` /
      `temperature_control: "unsupported"` / `seed_control:
      "unsupported"`. Re-run stability is an empirical property
      surfaced by the calibration step (Spearman against human
      labels), not a guarantee from a fixed T=0. Any future judge
      implementation that can pin temperature/seed populates those
      fields to non-null.
- [ ] **AC3** `calibrate` script measures Spearman; emits
      `calibration-report.md`.
- [ ] **AC4** Per-dimension calibration threshold (≥0.6 default)
      enforced; uncalibrated dimensions flagged in report, excluded
      from winner math.
- [ ] **AC5** HTML report renders deterministic + calibrated-judge
      scores with explicit visual separation.
- [ ] **AC6** Charts (bar / histogram / forest plot) render as
      static SVG/PNG (no JS).
- [ ] **AC7** CSV exports for per-task and per-(backend, model)
      tables.
- [ ] **AC8** Deterministic-first ordering enforced in code: a run
      that fails deterministic tests cannot win on judge-only
      criteria (= no non-passing-attempt sample enters a
      calibrated-judge `declare_winner` call).
- [ ] **AC9** No dollar-cost estimate in any report.
- [ ] **AC10** Documentation: how to add a judge / extend rubric /
      re-run calibration.
- [ ] **Origin gate** `check-origin-alignment.sh benchmark-llm-judge`
      exits ≤ 1; `validate-spec.sh --feature-id benchmark-llm-judge`
      exits 0.
- [ ] **Additivity invariant** A run with no `judge.json` files
      produces a Markdown+JSON report byte-identical (modulo
      timestamps) to the #32/#33 baseline. Regression-protected by
      a snapshot test in `report.py`'s test module.

## Deviation from origin

1. **#34 split into sub-issues (Option B recommendation; PENDING
   user approval).** The issue body frames 5 subsystems "deliverable
   in order" as a single deliverable. The team-lead recommendation
   is to file 5 sub-issues so each PR fully closes its own issue
   per the one-PR-per-issue rule. This is a structural change to
   how #34 is closed (the epic closes by linkage to its
   sub-issues), not a scope change. Spec / plan / tasks below
   describe the same engineering work whichever D1 option the user
   picks; only the per-PR AC partitioning differs.
2. **Calibration corpus from existing `runs/` archive.** Issue v3
   leaves the corpus source open. The corpus-inventory finding
   above (1171 attempt-records on disk) means no new benchmark
   spend is needed. This is methodology-honest (the calibration
   corpus reflects the actual CCT-instance workload) and
   schedule-honest (no new run campaign before the human-labeling
   step). Recorded explicitly so a future reader doesn't assume a
   freshly-generated corpus is required.
3. **Judge rates non-passing code too.** Issue v3 implies the
   judge runs on passing runs only ("quality differences inside a
   passing run"). The corpus-inventory finding (only 44 passing
   runs total, almost all on `sonnet`) makes a passing-only
   calibration set infeasible at N=50 and collapses the model
   variation axis. The spec extends the judge to rate every
   attempt with file changes, with the deterministic-first
   ordering enforced separately at the winner-extension step. This
   is consistent with issue v3 AC ("Deterministic-first ordering
   enforced: a run that fails deterministic tests cannot win on
   judge-only criteria") — the AC governs the verdict, not the
   rating.

## Sources

- `issue: gosha70/code-copilot-team#34` — v3 body (calibration
  arithmetic copilot-count-agnostic; deterministic-first explicit;
  per-(backend, model) reporting; variation axes broadened).
- `path: scripts/benchmark_runner/contracts.py` — `Backend` /
  `BackendResult` shape the `Judge` mirrors.
- `path: scripts/benchmark_runner/run.py` — `attempt_dir` +
  `score.json` layout; the `judge.json` adjacent write path.
- `path: scripts/benchmark_runner/report_winner.py` —
  `declare_winner` reused unchanged on calibrated-judge metric
  names.
- `path: scripts/benchmark_runner/report.py` — additive HTML/CSV
  emitters; baseline that the no-regression invariant protects.
- `path: runs/` — 1171 attempt-records on disk (corpus inventory
  2026-05-20).
- `specs/benchmark-harness/spec.md` — backend-vs-provider
  distinction; per-(backend, model) verdict shape.
- `specs/benchmark-aider-backend/spec.md` — the "verification
  artifact must really exist before merge" pattern that the
  labeling gate mirrors at larger scale.
- `memory: feedback-pr-must-fully-address-issue` (2026-05-19) —
  the one-PR-per-issue rule driving the Option-B recommendation.

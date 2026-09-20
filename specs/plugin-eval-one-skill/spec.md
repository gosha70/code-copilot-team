---
feature_id: plugin-eval-one-skill
spec_mode: lightweight
status: approved
date: 2026-09-19
issue: "#363 (P3, plugin adoption step 3; the last open item)"
origin:
  issue: "#363"
  transcripts:
    - specs/plugin-eval-one-skill/origin/2026-09-19-owner-direction-step-3.md
  user_messages:
    - "2026-09-19: 'Evaluate one skill afterwards—not as a prerequisite for adoption. ... 18 agent runs, plus applicable graders. ... Use concurrency 1 and --no-publish, and describe the budget honestly before approval.'"
    - "2026-09-19: 'Finish #363 issue'"
---

# Spec: one bounded `claude plugin eval` run on a single skill

## Why

P3 is the last open item of #363. Its question: does `claude plugin eval`
tell us something `benchmarks/` cannot? One experiment, one skill, a
stated budget, then a written answer. Nothing is built on top of it.

## Verified facts (2026-09-19, CLI 2.1.278)

Sources: `code.claude.com/docs/en/plugin-evals`, `claude plugin eval
--help`, a blank case written by `claude plugin eval init --bare`, and a
read of `benchmarks/`.

| Fact | Source |
|---|---|
| A case is `evals/<name>/prompt.md` (frontmatter: `max_turns`, `allowed_tools`, `model`, `runs`, …; an unknown key is an error) plus `graders/*.md` | docs, local template |
| Free graders, computed from the transcript: `regex`, `tool_used`, `tool_order`, `file_exists`. Paid: `llm`, `baseline` (three judge votes each) | docs |
| A plugin under test runs in two arms by default, with and without the plugin, same number of runs. Δ is the with score minus the without score | docs |
| A `tool_used` grader on `Skill` is reported but excluded from the score in both arms: a "plugin fired" indicator | docs |
| **Runs are isolated**: throwaway home and working directory; user settings, hooks, `CLAUDE.md`, installed plugins, memory and skills are absent. The owner's `setup.sh` install cannot leak into the without arm | docs |
| Each run starts in an empty directory. `Write`, `Edit` and `Bash` are gated behind `--allow-tools`; read-only tools are granted when a case lists them | docs |
| The eval directory must be inside the plugin folder (relative path, no `..`) | docs |
| `--max-cost-usd` is checked before each run launches, so the overrun is bounded to the runs in flight; reported cost is a list-price estimate | `--help`, docs |
| No variance or confidence interval is reported across runs | docs (absent) |
| The report publishes to claude.ai by default; `--no-publish` keeps it local. Non-interactive first runs need `--trust-plugin` | `--help`, docs |
| `benchmarks/` tests a candidate = (backend, model, env) on coding task sets, scored by deterministic verification plus a calibrated judge. It has **no** with-plugin/without-plugin arm (nor a per-skill one) and its candidate schema cannot express one | `benchmarks/README.md`, `benchmarks/schema/compare-config.schema.json`, `scripts/benchmark_runner/backends/claude_code.py` |

## Requirements

- **FR-1** The skill under test is `copyright-headers`. Reasons: its
  behaviour is project-defined (an exact two-line header built from the
  project's `## Copyright & Licensing` section), so a model without the
  skill cannot guess it; it is one of the six skills that #366 turned
  from always-loaded into on-demand for plugin users, so whether it
  fires is a live question; and it can be graded with free `regex`
  graders only.
- **FR-2** Three cases under `specs/plugin-eval-one-skill/eval/`, each a
  request a user would type, never naming the skill: a new Python file
  (header expected), a new shell script with a shebang (header on
  line 2), and a new JSON file (no header allowed). Each case also
  carries a `tool_used: Skill` indicator.
- **FR-3** Graders are `regex` and `tool_used` only. No `llm` or
  `baseline` grader, so there is no judge cost and no judge noise.
- **FR-4** The run targets a **copy** of the generated plugin in the
  session scratchpad, with the three cases copied into its `evals/`.
  Nothing is added to `adapters/claude-code/plugin/`, which
  `tests/test-generate.sh` pins to two authored and five generated
  directories.
- **FR-5** One invocation, as the owner set it: 3 cases × 3 runs ×
  2 arms = 18 agent runs, `--max-cost-usd 5`, `--concurrency 1`,
  `--no-publish`, plus `--trust-plugin` (our own plugin, scratchpad
  copy), `--threshold 0` (the exit code reports errors, not scores) and
  a fixed `--model`.
- **FR-6** `findings.md` in this bundle records: the command, the
  actual cost, per-case and per-arm scores, Δ, how often the skill
  fired, what went wrong, and a plain answer to P3's question with its
  limits. It proposes a disposition for #363; closing the issue is the
  owner's act.

## Constraints

- Paid. Nothing runs without the owner's authorization of this exact
  invocation. No second invocation, no retries, no reruns with other
  models or flags; a failed or inconclusive run is reported as such.
- The budget is described honestly: $5 stops later runs from launching;
  the one run in flight can exceed it.
- Nothing is installed into `~/.claude`. Nothing is published to
  claude.ai. The report and JSON stay in the scratchpad; the numbers
  that matter are copied into `findings.md`.
- No new repo surface: no `evals/` in the shipped plugin, no CI step, no
  generator change. If the answer is "worth doing again", that is a
  follow-up proposal, not part of this.
- Three runs per arm with no variance reported is a smoke signal, not a
  measurement. `findings.md` says so.
- Separate PR. It references #363; whether it closes it is the owner's
  call, so the PR text carries no close marker.

## Out of scope

More skills, more cases, `llm` graders, a permanent eval suite, CI
gating on eval scores, changes to `benchmarks/`, fixing the
`copyright-headers` description if the run shows it does not fire
(reported, then the owner decides).

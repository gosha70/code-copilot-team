# Findings: one bounded `claude plugin eval` run (#363 P3)

Run once on 2026-09-20 04:04:55Z–04:06:40Z, authorized by the owner, on
Sonnet. No retry, no second run.

## The question

P3 asked: does plugin eval tell us something `benchmarks/` cannot?

**Yes.** It tests one behaviour, here copyright headers, with the
plugin versus without it, against a clean no-plugin baseline.
`benchmarks/` cannot express that: its unit under test is a candidate
(backend, model, env), its schema has no field for plugin or skill
presence, and in its default mode the operator's own hooks, skills and
CLAUDE.md take part in every candidate alike. It was also cheap and
quick: $0.91 and under two minutes for 18 runs.

What it does **not** replace: `benchmarks/` answers "which model or
provider solves real coding tasks", verified by test suites. Plugin eval
answers "does the plugin change the answer for this behaviour".
Different questions; the two do not overlap.

## What was run

```
claude plugin eval <scratchpad>/evalrun-1/plugin \
  --model sonnet --runs 3 \
  --max-cost-usd 5 --concurrency 1 --no-publish \
  --trust-plugin --threshold 0 \
  --json result.json --report report.html
```

Target: a scratchpad copy of `adapters/claude-code/plugin` (version
1.1.0, from 6d17c21) with `specs/plugin-eval-one-skill/eval/` copied in
as `evals/`. CLI 2.1.278. Exit 0.

## Results

| | |
|---|---|
| Agent runs | 18 of 18 completed (3 cases × 3 runs × 2 arms) |
| Cost | **$0.9149** (list-price estimate, as the tool reports it). Judge cost $0: free graders only. The $5 launch budget was never approached |
| Wall time | 104 s |

| Case | With plugin | Without | Δ | Skill fired (with arm) |
|---|---|---|---|---|
| `new-python-file` | 1.00 (3/3 runs, all three graders) | 0.00 (0/3) | **+1.00** | 3 of 3 |
| `new-shell-script` | 1.00 (3/3, incl. header directly after the shebang) | 0.00 (0/3) | **+1.00** | 3 of 3 |
| `no-header-for-json` | 1.00 (3/3) | 1.00 (3/3) | 0.00 | 0 of 3 |
| Mean | 1.00 | 0.33 | +0.67 | |

Per run, the with arm took 3–4 turns and about $0.066; the without arm
took 1 turn and about $0.041. That difference, roughly 60% more per
request and two extra turns, is **whole-plugin overhead**: the with arm
loaded the entire plugin (24 skills, 14 agents, 14 commands, seven
hooks), not this skill alone. It cannot be read as the cost of the
`copyright-headers` skill.

## What this shows

1. **The on-demand skill fires on a natural request.** In all six runs
   that asked for a new source file, Sonnet invoked
   `copyright-headers` without being told to, and produced the exact
   two-line header, in the right place, including after a shebang. This
   was the live question left by #366's D1, where the six always-loaded
   rules became ordinary skills for plugin users. For this skill, on
   this model, that change did not lose the behaviour.
2. **It does not over-apply.** For the JSON file the skill was not even
   invoked, and no header was added. Correct, and it means the skill's
   description is not triggering on every "create a file" request.
3. **The tool works end to end** on a generated plugin: two arms, free
   graders, a configured launch budget (a run already in flight can
   overrun it), a local report, nothing published.

## Limits — read these before quoting the numbers

- **The treatment is the whole plugin, not one skill.** The two arms
  differ by all 24 skills, the agents, the commands and the hooks. That
  the header came from `copyright-headers` rests on the skill-fired
  indicator (6 of 6), which is good evidence but not isolation.
- **The raw result files are not in this bundle.** `result.json` and
  `report.html` stayed in the session scratchpad, as the spec required,
  so the scores and the spend here are reported by the builder, not
  independently verifiable from the repository.
- **Δ = +1.00 is close to guaranteed by construction.** The header
  format is project-defined; a model without the skill cannot produce
  it. The informative part is the skill-fired count and the placement,
  not the size of Δ.
- **The without arm's replies were not kept.** The tool deletes each
  run's directory unless `--keep-temp` is passed, and neither the JSON
  nor the HTML report embeds the replies. So it is unknown whether the
  baseline wrote no header or a header in another format (a standard
  Apache notice, say). Both score 0 here. Not rerun: one invocation was
  authorized.
- **Nine runs per arm, and the tool reports no variance or confidence
  interval.** Every run agreeing is a clean smoke signal, not a
  measurement.
- **One model.** Sonnet only. A smaller model may not invoke the skill
  on its own; nothing here speaks to that.
- **The prompt quotes the licensing section inline.** A real project
  has it in `CLAUDE.md`. A run starts in an empty directory and `Write`
  is gated, so the case tests "follows the rule when it can see the
  section", not "finds the section in the project".
- **Pattern graders see only what a pattern can see.** Whether the
  generated code is any good was not graded.

## Practical notes for a next time

- Pass `--keep-temp` if the replies matter.
- The eval directory must sit inside the plugin folder, and
  `tests/test-generate.sh` pins the shipped plugin's contents, so a
  permanent suite would need either a declared `evals/` directory there
  or the copy step used here.
- Runs are fully isolated from the operator's `~/.claude`, so a machine
  with the `setup.sh` install gives a clean baseline.
- Free graders kept the whole run under a dollar. An `llm` grader adds
  three judge calls per grader per run.

## Proposed disposition for #363

Every item in the issue is now dealt with:

| Item | Outcome |
|---|---|
| P1 `effort` in agent frontmatter | done, PR #365 |
| P2 CLI facts in the features skill | done, PR #365; the rename was declined by the owner for now |
| Plugin: load repair, then generated from sources | done, PRs #364 and #366 |
| P3 one bounded plugin eval | done, this bundle: the answer is yes, with the limits above |
| `omitClaudeMd` | declined on purpose, recorded in the issue |
| Environmental notes | no work implied |

Nothing is left open under it. Closing #363 is the owner's act. A
permanent eval suite for the six formerly always-loaded skills would be
new work with its own issue; it is not proposed here.

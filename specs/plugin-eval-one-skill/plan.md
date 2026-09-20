---
spec_mode: lightweight
feature_id: plugin-eval-one-skill
risk_category: infra
justification: |
  One paid command, run once, against a scratchpad copy of the plugin,
  plus three small case folders and a findings note. No product code, no
  generator change, no CI change. FR-1..FR-6 in spec.md state the whole
  behaviour; a full bundle would restate them.
status: approved
date: 2026-09-19
issue: "#363"
origin:
  issue: "#363"
  transcripts:
    - specs/plugin-eval-one-skill/origin/2026-09-19-owner-direction-step-3.md
  user_messages:
    - "2026-09-19: 'Evaluate one skill afterwards—not as a prerequisite for adoption. ... 18 agent runs, plus applicable graders. ... Use concurrency 1 and --no-publish, and describe the budget honestly before approval.'"
    - "2026-09-19: 'Finish #363 issue'"
  origin_claim: |
    One bounded experiment on a single skill, with a stated budget, to
    answer whether plugin eval tells us something benchmarks/ cannot.
    Three cases, three runs, two arms: 18 agent runs plus graders.
    --max-cost-usd 5, concurrency 1, --no-publish, the budget described
    honestly before approval. Paid evaluation is separately authorized.
---

# Plan: one bounded plugin eval run on `copyright-headers`

## The shape of it

```
specs/plugin-eval-one-skill/
  eval/<3 cases>/prompt.md + graders/*.md    authored here, reviewed in the PR
  findings.md                                written after the run

<scratchpad>/evalrun/plugin/                 copy of adapters/claude-code/plugin
<scratchpad>/evalrun/plugin/evals/           copy of eval/   (the tool needs evals inside the plugin)
<scratchpad>/evalrun/{result.json,report.html}
```

The shipped plugin gains nothing. The copy exists because the eval
directory must sit inside the plugin folder, and the plugin folder is
pinned by `tests/test-generate.sh`.

## The three cases

Each prompt pastes a `## Copyright & Licensing` section (Company "Acme
Robotics Ltd", License "Apache-2.0") the way a user would quote their
own CLAUDE.md, asks for one new file, and asks for the contents in the
reply, because `Write` is a gated tool and a run starts in an empty
directory. No prompt names the skill.

| Case | Expectation | Scored graders (all `regex`, free) |
|---|---|---|
| `new-python-file` | two-line hash-comment header opens the file | line 1 text; line 2 text; header is the first thing in the code block |
| `new-shell-script` | shebang, then the header on line 2 | line 1 text; line 2 text; header directly follows the shebang |
| `no-header-for-json` | no header: JSON has no comment syntax | reply has no "Copyright"; reply still contains the JSON |

Each case also has a `tool_used: Skill` grader matching
`copyright-headers`. The tool excludes it from the score in both arms
and reports it as "did the plugin fire".

The patterns were checked locally against a correct and an incorrect
sample reply for each case before any paid run.

What each outcome would mean:

- **With arm high, without arm low, skill fired.** The skill works as an
  on-demand plugin skill, and plugin eval shows it. This is the result
  `benchmarks/` cannot produce: it has no with/without-plugin arm.
- **With arm low, skill did not fire.** The skill's description does not
  trigger on a "create a new file" request. A real finding about #366's
  D1 (always-on rules became on-demand for plugin users). Reported; any
  description change is a separate decision.
- **Both arms similar.** Either the model already does this unprompted,
  or the cases are too easy. Says little; reported as such.
- **JSON case.** Both arms should pass. A with-arm failure means the
  skill over-applies.

## The one invocation — authorized

**Authorized by the owner on 2026-09-19 (local time), on Sonnet, exactly as
written below: run once, no retries.**

```
claude plugin eval <scratchpad>/evalrun/plugin \
  --model sonnet --runs 3 \
  --max-cost-usd 5 --concurrency 1 --no-publish \
  --trust-plugin --threshold 0 \
  --json <scratchpad>/evalrun/result.json \
  --report <scratchpad>/evalrun/report.html
```

- 3 cases × 3 runs × 2 arms = **18 agent runs. No judge calls**, because
  no grader is `llm` or `baseline`.
- **Budget, honestly:** `--max-cost-usd 5` stops further runs from
  launching once $5 is reached. With concurrency 1 the overrun is
  bounded to the single run in flight: $5 is a launch budget, and spend
  can reach $5 plus that one run. Expected spend is well under that: the #366 probes cost
  $0.01–$0.11 per haiku session in a full, non-isolated environment;
  these runs are isolated (smaller context) and at most 8 turns, on
  Sonnet. My estimate is $1–$3 in total. It is an estimate, not a bound.
- `--model sonnet`: the model a plugin user is most likely to be on. The
  result says nothing about other models, and `findings.md` will say so.
- `--trust-plugin`: required off a terminal. The directory is our own
  generated plugin, copied to the scratchpad, outside any git
  repository, so the trust does not extend to the repo.
- `--threshold 0`: the default of 1.0 would turn any imperfect score
  into exit 1; here a non-zero exit should mean the run broke.
- Run once. No retry, no second model, no rerun with different flags.

## Deliverables

1. `eval/` — the three cases (this bundle).
2. `findings.md` — command, actual cost, per-case per-arm scores, Δ,
   skill-fired counts, anything that went wrong, the answer to P3 with
   its limits (three runs per arm, no variance reported, one model), and
   a proposed disposition for #363.
3. A PR with the bundle. No close marker; closing #363 is the owner's
   act.

## Gates

`scripts/validate-spec.sh --all`, `scripts/check-origin-alignment.sh`,
`scripts/check-doc-accuracy.sh`, `git diff --check`. No test suite is
touched. No `/review-submit`: there is no code to review, and the PR
is the review surface for the cases and the findings.

## Risks

- **The command may be unavailable.** The docs describe an early-access
  gate and a server-side off switch. If it refuses to start, nothing is
  spent, and that refusal is the finding.
- **A case file may be rejected** (unknown key, bad pattern). The
  formats come from the docs and a generated template, and the patterns
  were tested, but the first real parse is the paid invocation. A parse
  failure should stop before any run launches; if it does not, the
  partial result is reported, not rerun.
- **The plugin's own hooks run inside the eval.** They are the seven
  shipped hooks; none needs the network, and the isolated environment
  withholds the owner's shell variables.
- **Small sample.** Nine runs per arm in total. A smoke signal.

# Tasks: one bounded plugin eval run

| # | Task | File(s) | Done |
|---|------|---------|------|
| 0 | Owner approves the plan and authorizes the one invocation with its budget (approved 2026-09-19, Sonnet) | `plan.md` | [x] |
| 1 | Three cases with free graders; patterns checked against good and bad sample replies (FR-1..FR-3) | `eval/**` | [x] |
| 2 | Assemble the scratchpad copy: generated plugin plus `evals/` (FR-4) | scratchpad only | [x] |
| 3 | The one invocation: 18 runs, `--max-cost-usd 5`, `--concurrency 1`, `--no-publish` (FR-5). Run once: 18/18 runs, $0.9149, exit 0 | scratchpad only | [x] |
| 4 | Findings: cost, scores, Δ, skill-fired, limits, the answer to P3, proposed disposition for #363 (FR-6) | `findings.md` | [x] |
| 5 | Gates, origin alignment re-check, commit, PR (no close marker), CI green | — | [ ] |

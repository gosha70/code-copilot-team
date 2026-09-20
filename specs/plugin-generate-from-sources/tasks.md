# Tasks: generate the plugin from its sources

| # | Task | File(s) | Done |
|---|------|---------|------|
| 0 | Owner decisions D1–D4; plan approval (2026-09-19). Authorization for the bounded runtime runs: asked again after task 4 | `plan.md` | [x] |
| 1 | Plugin section in the generator: scoped clean of the five generated subdirectories, then skills, agents, commands, hook scripts, templates, helper; four-directory path rewrite (FR-1..FR-3) | `scripts/generate.sh` | [x] |
| 2 | D2 guard in the five non-safety hook sources (FR-4) | `adapters/claude-code/.claude/hooks/{auto-format,verify-after-edit,verify-on-stop,notify,reinject-context}.sh` | [x] |
| 3 | Run the generator; commit the generated plugin contents; second run is a no-op | `adapters/claude-code/plugin/**` | [x] |
| 4 | Generator assertions incl. the reverse (no plugin file without a source) and authored files surviving a run; guard cases; count pins (FR-8) | `tests/test-generate.sh`, `tests/test-hooks.sh`, `tests/test-counts.env`, `docs/repo-structure.md` | [x] |
| 5 | Runtime proof: four bounded runs, combined configured budget $1.00 (an in-flight request may overrun a cap), and the four build-time verifications (FR-5, FR-9). Done: $0.2973 actual; results in `plan.md` | scratchpad only | [x] |
| 6 | Version 1.1.0, descriptions, install docs written from what task 5 showed (FR-5..FR-7) | `plugin.json`, `marketplace.json`, `docs/install.md` | [x] |
| 7 | Gates, incl. `validate-spec.sh --all` and `claude plugin validate` (all green under CI conditions, 2026-09-19) | — | [x] |
| 8 | Origin alignment re-check, `/review-submit` (DeepSeek), PR, CI green | — | [ ] |

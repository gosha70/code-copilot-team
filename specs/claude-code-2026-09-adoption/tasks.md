# Tasks: agent `effort` frontmatter + CLI facts refresh

| # | Task | File(s) | Done |
|---|------|---------|------|
| 0 | Owner decisions D1 (effort table) and D2 (manifest sentence); plan approval | `plan.md` | [x] |
| 1 | `effort:` in the 12 adapter-authored agents (FR-1, FR-2) | `adapters/claude-code/.claude/agents/*.md` | [x] |
| 2 | `effort:` in the 2 `claude_code/`-authored agents (FR-1, FR-2) | `claude_code/.claude/agents/{verify-app,visual-reviewer}.md` | [x] |
| 3 | "CLI Facts (September 2026)" section incl. subagent frontmatter gates and the `omitClaudeMd` decline (FR-3, FR-4) | `shared/skills/opus-4-7-features/SKILL.md` | [x] |
| 4 | Per-agent `effort` assertion; count pin 812 → 826 (FR-6) | `tests/test-shared-structure.sh`, `tests/test-counts.env`, `docs/repo-structure.md` | [x] |
| 5 | D2 sentence (FR-5) | `adapters/claude-code/setup.sh` | [x] |
| 6 | Regenerate; no hand-edited derived file in the diff | `scripts/generate.sh` | [x] |
| 7 | Gates: test-generate, test-shared-structure, check-doc-accuracy, `git diff --check` | — | [x] |
| 8 | Origin alignment re-check, then `/review-submit` | — | [ ] |
| 9 | Live check: real session, one `low` and one `high` agent | scratchpad only | [x] |

## Results (2026-09-19, CLI 2.1.278)

**Generated surfaces.** `scripts/generate.sh` wrote the two synced
agents into the adapter directory and the skill into the cursor,
github-copilot and pi adapters. Nothing else moved.

**Gates.**

- `tests/test-generate.sh`: 304 passed, 0 failed.
- `tests/test-shared-structure.sh`: 821 passed, 5 failed + count line.
  Four are "installed hooks/… matches adapter/", identical on untouched
  master. The fifth, "installed skills/opus-4-7-features/SKILL.md
  matches shared/", compares `~/.claude/skills` on this machine with the
  skill this branch edits; it clears when the owner syncs after merge.
  CI has no installed copy. 821 + 5 = 826.
- The FR-6 assertion exits 1 on master's `build.md` and on a file with
  `effort:` only in the body.
- `scripts/check-doc-accuracy.sh`: clean. `git diff --check`: clean.

**Live check.** Scratch project with this branch's `phase-recap.md`
(`effort: low`) and `security-review.md` (`effort: high`) under
`.claude/agents/`; main session on haiku, `--max-budget-usd 0.50`; each
agent asked to reply OK. The subagent transcripts record
`claude-sonnet-5` with `effort: low` for phase-recap and `effort: high`
for security-review. `setup.sh --sync` was not run.

**Limitations, unchanged.** The unknown-key probe covers 2.1.278 only.
Before 2.1.267 `effort` is ignored on pinned-default models. Forwarding
of frontmatter effort to a local-model gateway is unverified.

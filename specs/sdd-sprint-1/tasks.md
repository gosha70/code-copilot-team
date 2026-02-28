# Tasks: SDD Sprint 1 — Specification Layer

<!-- Generated retrospectively. [US#] = traceability tag linking back to spec.md user stories. -->

## [US1] Create SDD templates

| # | Task | File(s) | Owner | Done |
|---|------|---------|-------|------|
| 1 | Create spec template with frontmatter and all required sections | `shared/templates/sdd/spec-template.md` | Templates agent | [x] |
| 2 | Create plan template with spec_mode frontmatter | `shared/templates/sdd/plan-template.md` | Templates agent | [x] |
| 3 | Create tasks template with [US#] traceability | `shared/templates/sdd/tasks-template.md` | Templates agent | [x] |

## [US5] Propagate spec-workflow to all adapters

| # | Task | File(s) | Owner | Done |
|---|------|---------|-------|------|
| 4 | Create spec-workflow on-demand rule | `shared/rules/on-demand/spec-workflow.md` | Rules agent | [x] |
| 5 | Update generation pipeline for spec-workflow | `scripts/generate.sh` | Pipeline agent | [x] |

## [US4] Agent-level enforcement (Claude Code)

| # | Task | File(s) | Owner | Done |
|---|------|---------|-------|------|
| 6 | Update Plan agent to emit spec artifacts | `adapters/claude-code/.claude/agents/plan.md` | Agent-manifest agent | [x] |
| 7 | Update Build agent to gate on spec_mode | `adapters/claude-code/.claude/agents/build.md` | Agent-manifest agent | [x] |

## Final Verification

- [x] All 834+ existing tests pass
- [x] generate.sh exits cleanly
- [x] Codex AGENTS.md under 32 KiB

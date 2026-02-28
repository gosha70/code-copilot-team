# Claude Code Session Kickoff — SDD Sprint 1

## How to Use This

Start Claude Code in the `code-copilot-team` repo root, then paste the
appropriate prompt below for each phase. Run one phase per session.

---

## Phase 1: Plan (ALREADY DONE)

The spec and plan are pre-written in `specs/sdd-sprint-1/`. Skip straight to
Build.

---

## Phase 2: Build

Start a new Claude Code session (`claude` from repo root), then paste this
prompt directly — the Build agent activates automatically based on context
(there is no `/chat build` slash command):

```
Implement SDD Sprint 1 per the approved spec and plan in specs/sdd-sprint-1/.

Read these files first:
1. specs/sdd-sprint-1/plan.md — full implementation plan with tasks and file ownership
2. specs/sdd-sprint-1/spec.md — requirements with acceptance criteria
(All v2.2 errata corrections are already incorporated in these two files.)

Key constraints:
- All rule/template changes go through shared/ → generate.sh → adapters/
- Agent manifests (plan.md, build.md) are Claude Code adapter-specific — edit directly
- Do NOT create files listed under "What NOT to Build" in the spec
- Run the full test suite (834+ tests) after all changes
- Show the delegation plan before executing

The plan has 6 tasks with non-overlapping file ownership. Delegate accordingly.
```

---

## Phase 3: Review

Start a new Claude Code session (`claude` from repo root), then paste this
prompt directly — the Review agent activates automatically based on context:

```
Review all changes from the SDD Sprint 1 build.

Check against:
1. specs/sdd-sprint-1/spec.md — verify all FR-001 through FR-010 are implemented
2. specs/sdd-sprint-1/plan.md — verify all acceptance criteria checkboxes are satisfiable

Specific things to verify:
- plan.md frontmatter supports all 3 spec_modes (full, lightweight, none)
- Build agent reads plan.md frontmatter (not conversation state) to determine gating
- generate.sh produces spec-workflow content in all 6 adapters
- Codex AGENTS.md stays under 32 KiB
- All 834+ existing tests pass
- No files outside Sprint 1 scope were modified
```

---

## Phase 4: Commit

After review passes:

```
Commit all Sprint 1 changes with message:

feat(sdd): add specification layer — templates, spec-workflow rule, conditional Build gate

Sprint 1 of SDD adoption:
- Add shared/templates/sdd/ with spec, tasks, and plan templates
- Add shared/rules/on-demand/spec-workflow.md with risk-based spec_mode classification
- Update agent-team-protocol.md and phase-workflow.md with Plan Approval Gate
- Update Plan agent to emit spec_mode in plan.md frontmatter
- Update Build agent to gate conditionally on spec_mode (full|lightweight|none)
- Update generate.sh to propagate SDD artifacts to all 6 adapters

Refs: SDD-Implementation-Plan-v2.1-Final.docx, SDD-Plan-v2.2-Errata.md
```

---

## Notes

- The repo's own workflow (Research → Plan → Build → Review) is being used to
  implement SDD into that same workflow. This is intentional dogfooding.
- Session boundaries matter: one phase per session to avoid context exhaustion.
- The Build agent will delegate to 2–4 sub-agents based on the file ownership
  table in plan.md.
- Non-Claude adapters receive advisory content only (enforced gating is Sprint 3).

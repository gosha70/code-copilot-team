---
spec_mode: full
feature_id: sdd-sprint-1-specification-layer
risk_category: integration
justification: "Framework-level change affecting shared rules, templates, agent manifests, and generation pipeline across 6 adapters."
status: approved
date: 2026-02-28
---

# Implementation Plan: SDD Sprint 1 — Specification Layer

**Branch**: `sdd-sprint-1-spec-layer`
**Input**: doc_internal/SDD-Implementation-Plan-v2.1-Final.docx + doc_internal/SDD-Plan-v2.2-Errata.md (reference only — all corrections are incorporated below)

## Summary

Add spec-driven development templates, a spec-workflow rule, a Plan Approval Gate,
and conditional Build gating (spec_mode: full | lightweight | none) to the
code-copilot-team framework. Claude Code adapter gets agent-level enforcement;
other adapters get advisory content via generate.sh.

## Technical Context

**Language/Version**: Bash (scripts), Markdown (rules/templates/agents)
**Primary Dependencies**: scripts/generate.sh, shared/rules/, shared/templates/
**Testing**: bash tests (test-shared-structure.sh, test-generate.sh, test-hooks.sh)
**Constraints**: All changes must flow through shared/ → generate.sh → adapters/. No direct adapter edits except Claude Code agent manifests (which are adapter-specific by design).

## Scope

### Task 1: Create SDD Templates (3 files)

**Files to create:**

- `shared/templates/sdd/spec-template.md`
  - YAML frontmatter: spec_mode, feature, risk_category, date
  - Sections: User Scenarios (prioritized, BDD Given/When/Then), Requirements (FR-xxx with [NEEDS CLARIFICATION] markers), Constraints / What NOT to Build, Key Entities, Success Criteria
  - Adapted from GitHub Spec Kit spec-template.md (MIT licensed, github/spec-kit repo)

- `shared/templates/sdd/tasks-template.md`
  - Tasks grouped by user story [US#]
  - [P] markers for parallelizable tasks
  - Checkpoint validation after each story group
  - File ownership per task
  - Adapted from GitHub Spec Kit tasks-template.md

- `shared/templates/sdd/plan-template.md`
  - YAML frontmatter: spec_mode (full | lightweight | none), feature, risk_category, justification, date
  - Sections: Summary, Technical Context, Constitution Check (referencing shared/rules/always/), Architecture Decisions (ADR format), Project Structure
  - For spec_mode: none → only frontmatter + Summary paragraph required
  - Adapted from GitHub Spec Kit plan-template.md

**Acceptance criteria:**
- [ ] All 3 files exist in shared/templates/sdd/
- [ ] spec-template.md has all required sections with placeholder guidance
- [ ] plan-template.md frontmatter supports all 3 spec_mode values
- [ ] Templates reference shared/rules/always/ as the project constitution

### Task 2: Create spec-workflow Rule (1 file)

**File to create:**

- `shared/rules/on-demand/spec-workflow.md`

**Content:**
- Risk-based spec_mode classification:
  - full: security, schema, integration, features >2 files
  - lightweight: features 1–2 files, non-critical
  - none: bug fixes (non-security), docs, trivial changes
- Required spec sections and validation criteria
- Plan Approval Gate protocol: user must approve spec.md before Build
- [NEEDS CLARIFICATION] resolution rules: all markers resolved before Build
- Plan always emits plan.md with spec_mode frontmatter (even for none)

**Acceptance criteria:**
- [ ] File exists in shared/rules/on-demand/
- [ ] Defines all 3 spec_mode values with clear classification criteria
- [ ] Describes Plan Approval Gate protocol
- [ ] Describes [NEEDS CLARIFICATION] resolution requirement

### Task 3: Modify Existing On-Demand Rules (2 files)

**Files to modify:**

- `shared/rules/on-demand/agent-team-protocol.md`
  - Add: Plan Approval Gate between Phase 1 (Plan) and Phase 2 (Build)
  - Add: specs/<feature-id>/ directory convention
  - Add: Plan always emits plan.md; Build reads plan.md frontmatter

- `shared/rules/on-demand/phase-workflow.md`
  - Add to post-Plan verification: plan.md present in specs/<id>/ with spec_mode frontmatter
  - Add to pre-Build check: if spec_mode is full/lightweight, spec.md present with no unresolved [NEEDS CLARIFICATION]

**Acceptance criteria:**
- [ ] agent-team-protocol.md includes Plan Approval Gate description
- [ ] phase-workflow.md includes spec artifact verification steps
- [ ] Both files reference specs/ directory convention

### Task 4: Modify Agent Manifests (2 files, Claude Code only)

**Files to modify:**

- `adapters/claude-code/.claude/agents/plan.md`
  - Add: load spec-workflow.md rule at session start
  - Add: determine spec_mode based on risk classification
  - Add: always emit plan.md with spec_mode frontmatter to specs/<feature-id>/
  - Add: emit spec.md only when spec_mode is full or lightweight
  - Add: resolve all [NEEDS CLARIFICATION] via AskUserQuestion before completing

- `adapters/claude-code/.claude/agents/build.md`
  - Add: Step 0 — read specs/<id>/plan.md frontmatter to determine spec_mode
  - Add: gate behavior conditional on spec_mode (full → require spec.md + emit tasks.md; lightweight → require spec.md; none → proceed)
  - Add: show tasks.md to user for approval before delegation (full mode)

**Acceptance criteria:**
- [ ] plan.md agent loads spec-workflow.md
- [ ] plan.md agent emits plan.md for all spec_modes
- [ ] build.md agent reads plan.md frontmatter and gates conditionally
- [ ] build.md agent emits tasks.md before delegation in full mode

### Task 5: Update Generation Pipeline (1 file)

**File to modify:**

- `scripts/generate.sh`
  - Add: copy shared/templates/sdd/ into relevant adapter output locations
  - Add: include spec-workflow.md in on-demand rule generation for all adapters
  - Verify: Codex (AGENTS.md), Cursor (.mdc), GitHub Copilot (instructions/), Windsurf (rules.md), Aider (CONVENTIONS.md) all receive spec-workflow content

**Acceptance criteria:**
- [ ] generate.sh runs without errors
- [ ] git diff adapters/ shows spec-workflow content in all 6 adapter outputs
- [ ] Non-Claude adapters contain spec-workflow as advisory guidance
- [ ] Codex output stays under 32 KiB limit

### Task 6: Verify (CI + Tests)

- [ ] Run: bash scripts/generate.sh — clean exit
- [ ] Run: git diff --exit-code adapters/ — shows expected changes only
- [ ] Run: bash tests/test-shared-structure.sh — all existing tests pass
- [ ] Run: bash tests/test-generate.sh — all existing tests pass
- [ ] Run: bash tests/test-hooks.sh — all existing tests pass
- [ ] Total: 834+ existing tests green

## Constraints / What NOT to Build

- Do NOT create checklist-template.md (removed per v2.2 errata — conformance is inline Review output)
- Do NOT create lessons-learned-template.md (that is Sprint 2)
- Do NOT modify review.md agent (that is Sprint 3)
- Do NOT modify CI workflow sync-check.yml (that is Sprint 3)
- Do NOT add new tests yet (that is Sprint 3)
- Do NOT modify shared/rules/always/* files (that is Sprint 2)
- Do NOT modify shared/docs/* files (that is Sprint 2)
- Do NOT modify any PROJECT.md template files (that is Sprint 2)

## File Ownership (Non-Overlapping)

| Agent / Owner | Files |
|---------------|-------|
| Templates agent | shared/templates/sdd/spec-template.md, tasks-template.md, plan-template.md |
| Rules agent | shared/rules/on-demand/spec-workflow.md, agent-team-protocol.md, phase-workflow.md |
| Agent-manifest agent | adapters/claude-code/.claude/agents/plan.md, build.md |
| Pipeline agent | scripts/generate.sh |

## Risk

- generate.sh modification could break existing adapter generation → mitigate by running full test suite after
- Codex AGENTS.md has 32 KiB limit → verify size after adding spec-workflow content
- Agent manifest changes are Claude Code–specific; other adapters get advisory content only

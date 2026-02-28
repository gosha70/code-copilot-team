---
spec_mode: full
feature_id: sdd-sprint-1-specification-layer
risk_category: integration
status: approved
date: 2026-02-28
---

# Spec: SDD Sprint 1 — Specification Layer

## User Scenarios

### US1: Developer starts a new feature with full spec (Priority: HIGH)

**Given** a developer starts a Plan phase for a feature touching auth logic
**When** the Plan agent evaluates risk classification
**Then** it assigns spec_mode: full, emits spec.md + plan.md to specs/<feature-id>/, and requires user approval before Build can start

### US2: Developer starts a small feature with lightweight spec (Priority: MEDIUM)

**Given** a developer starts a Plan phase for a 1-file config change
**When** the Plan agent evaluates risk classification
**Then** it assigns spec_mode: lightweight, emits plan.md + minimal spec.md (Requirements + Constraints only)

### US3: Developer fixes a non-security bug with no spec (Priority: MEDIUM)

**Given** a developer starts a Plan phase for a CSS bug fix
**When** the Plan agent evaluates risk classification
**Then** it assigns spec_mode: none, emits only plan.md with justification in frontmatter, and Build proceeds without spec gate

### US4: Build agent gates on spec_mode (Priority: HIGH)

**Given** a Build phase starts and reads specs/<id>/plan.md frontmatter
**When** spec_mode is full and spec.md has unresolved [NEEDS CLARIFICATION] markers
**Then** the Build agent refuses to proceed and instructs the user to resolve markers in a Plan session

### US5: Non-Claude adapter receives advisory content (Priority: LOW)

**Given** a developer uses Cursor or GitHub Copilot
**When** scripts/generate.sh runs
**Then** the spec-workflow rule appears in the adapter's config as advisory guidance (no agent-level gate)

## Requirements

- **FR-001**: Plan agent MUST always emit specs/<feature-id>/plan.md with spec_mode in YAML frontmatter
- **FR-002**: Plan agent MUST emit specs/<feature-id>/spec.md when spec_mode is full or lightweight
- **FR-003**: Plan agent MUST NOT emit spec.md when spec_mode is none
- **FR-004**: Build agent MUST read specs/<id>/plan.md frontmatter to determine gating behavior
- **FR-005**: Build agent MUST refuse to proceed when spec_mode is full and spec.md is missing or has unresolved [NEEDS CLARIFICATION]
- **FR-006**: Build agent MUST emit tasks.md to specs/<id>/ before delegation when spec_mode is full
- **FR-007**: spec-workflow.md MUST define risk-based classification for all 3 spec_modes
- **FR-008**: generate.sh MUST propagate spec-workflow.md to all 6 adapters
- **FR-009**: All 834+ existing tests MUST continue to pass after changes
- **FR-010**: Codex AGENTS.md output MUST stay under 32 KiB

## Constraints / What NOT to Build

- No checklist-template.md (removed per v2.2 errata)
- No lessons-learned-template.md (Sprint 2)
- No review.md agent changes (Sprint 3)
- No CI workflow changes (Sprint 3)
- No new test additions (Sprint 3)
- No changes to shared/rules/always/* (Sprint 2)
- No changes to shared/docs/* (Sprint 2)
- No changes to PROJECT.md templates (Sprint 2)

## Key Entities

- **spec_mode**: enum (full | lightweight | none) — stored in plan.md YAML frontmatter
- **specs/<feature-id>/**: directory per feature containing SDD artifacts
- **plan.md**: always-emitted artifact with spec_mode, risk_category, justification
- **spec.md**: requirements artifact, emitted for full/lightweight modes
- **tasks.md**: task decomposition artifact, emitted for full mode
- **[NEEDS CLARIFICATION]**: inline marker in spec.md indicating unresolved ambiguity
- **[US#]**: traceability tag linking tasks to user stories
- **[P]**: parallelism marker on tasks that can be executed concurrently

## Success Criteria

1. Plan agent correctly classifies spec_mode for security (full), small feature (lightweight), and bug fix (none)
2. Build agent gates conditionally — blocks on missing spec for full, proceeds freely for none
3. generate.sh produces spec-workflow content in all 6 adapter outputs
4. All 834+ existing tests pass
5. One pilot feature completed end-to-end using full SDD workflow

---
spec_mode: full
feature_id: [feature-id]
risk_category: [security | integration | schema | feature | bug | docs]
status: draft
date: [YYYY-MM-DD]
---

# Spec: [Feature Name]

<!-- Project constitution: shared/rules/always/ — copilot-conventions.md, coding-standards.md, safety.md -->

## User Scenarios

<!-- Prioritize: HIGH / MEDIUM / LOW. One scenario per user story. BDD format. -->

### US1: [Short scenario name] (Priority: HIGH)

**Given** [starting context]
**When** [action or trigger]
**Then** [expected outcome]

### US2: [Short scenario name] (Priority: MEDIUM)

**Given** [starting context]
**When** [action or trigger]
**Then** [expected outcome]

<!-- Add US3, US4 ... as needed. -->

## Requirements

<!-- FR-xxx: numbered, imperative, testable. Mark gaps with [NEEDS CLARIFICATION]. -->
<!-- Build agent will refuse to start if any [NEEDS CLARIFICATION] remain unresolved. -->

- **FR-001**: [System] MUST [behaviour]
- **FR-002**: [System] MUST [behaviour]
- **FR-003**: [System] MUST NOT [prohibited behaviour]
- **FR-004**: [Description] — [NEEDS CLARIFICATION: what exactly should happen when X?]

## Constraints / What NOT to Build

<!-- Explicit out-of-scope prevents scope creep. -->

- No [thing] — [reason or sprint deferral]
- No [thing] — [reason or sprint deferral]

## Key Entities

<!-- Named concepts that appear in requirements and code. Define once here. -->

- **[EntityName]**: [one-line definition]
- **[EntityName]**: [one-line definition]

## Success Criteria

<!-- Measurable, verifiable. Tie back to user scenarios where possible. -->

1. [US1 outcome is demonstrable via ...]
2. [FR-001 is verified by ...]
3. [No regressions: existing test suite passes]

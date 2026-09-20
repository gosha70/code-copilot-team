---
spec_mode: full
feature_id: [feature-id]
risk_category: [security | integration | schema | feature | bug | docs]
justification: "[Why this spec_mode? One sentence.]"
status: draft
date: [YYYY-MM-DD]
collaboration_mode: single
---

<!-- spec_mode: none → stop here. Only frontmatter + Summary paragraph required. -->
<!-- spec_mode: lightweight → fill Summary, Technical Context, Scope. Skip ADRs if none needed. -->
<!-- spec_mode: full → fill all sections. -->

# Implementation Plan: [Feature Name]

**Branch**: `[feature|fix|chore]/[feature-id]`
**Input**: specs/[feature-id]/spec.md

## Summary

[2–4 sentences. What is being built, why, and what the outcome is. No implementation detail here.]

## Technical Context

**Language/Version**: [e.g. TypeScript 5.4, Python 3.12, Bash]
**Primary Dependencies**: [list files, modules, or libraries this change touches]
**Testing**: [test runner + relevant test files]
**Constraints**: [hard limits — size caps, backward compat, API contracts]

## Constitution Check

<!-- Confirm the plan satisfies shared/skills/ (coding-standards, safety, etc.) before Build starts. -->

| Rule file | Concern | Status |
|-----------|---------|--------|
| `coding-standards.md` | No magic strings, no secrets, lint-clean | [OK / NOTE: ...] |
| `safety.md` | No credentials in source, inputs validated | [OK / NOTE: ...] |
| `copilot-conventions.md` | One logical change per commit, repo is source of truth | [OK / NOTE: ...] |

## Architecture Decisions

<!-- One ADR block per significant decision. Omit section if no decisions needed. -->

### ADR-1: [Decision title]

**Context**: [What situation forced a decision?]
**Decision**: [What was chosen?]
**Consequences**: [Trade-offs, follow-up work, risks accepted.]

<!-- Add ADR-2, ADR-3 ... as needed. -->

## Project Structure

<!-- List only files that are created or modified. -->

```
[path/to/new-file.ext]          — [one-line description]
[path/to/modified-file.ext]     — [what changes]
```

## Scope

<!-- Task breakdown. Reference spec.md FRs and US# tags. -->

### Task [N]: [Task name]

**Files**: [file list]
**Acceptance criteria**:
- [ ] [Verifiable check tied to a FR or US]
- [ ] [Verifiable check]

<!-- Add Task N+1 ... as needed. -->

## Constraints / What NOT to Build

- No [thing] — [reason]
- No [thing] — deferred to [Sprint / phase]

## File Ownership (Non-Overlapping)

| Owner | Files |
|-------|-------|
| [agent/role] | [file list] |
| [agent/role] | [file list] |

## Collaboration (Dual Mode)

<!-- Only fill this section if collaboration_mode is set to dual. -->
<!-- Delete this section if collaboration_mode: single. -->

| Field | Value |
|-------|-------|
| Subject provider | [e.g., claude] |
| Peer provider | [e.g., codex] |
| Review scope | [code \| design \| both] |

Required artifacts (created by peer-review runner):
- `specs/[feature-id]/collaboration/plan-consult.md`
- `specs/[feature-id]/collaboration/build-review.md`

See `provider-collaboration-protocol.md` for the full protocol.

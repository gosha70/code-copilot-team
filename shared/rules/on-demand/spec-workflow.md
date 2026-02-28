# Spec Workflow — SDD Specification Protocol

Rules governing when a Software Design Document (SDD) spec is required, what sections it must contain, and how it gates the transition from Plan to Build.

## Risk-Based spec_mode Classification

Every planned feature is assigned a `spec_mode` based on change risk. The Plan agent determines this value and records it in `specs/<feature-id>/plan.md` YAML frontmatter.

| spec_mode     | When to use |
|---------------|-------------|
| `full`        | Security changes, schema changes, integration work, features touching more than 2 files |
| `lightweight` | Features touching 1–2 files, non-critical changes |
| `none`        | Bug fixes (non-security), docs-only changes, trivial or cosmetic changes |

When in doubt, escalate to the next higher mode. Under-speccing a risky change costs more than over-speccing a safe one.

## Required Spec Sections per Mode

### full

All sections from `spec-template.md` are required, plus a `tasks.md` task breakdown:

- Overview
- Requirements
- Constraints
- Architecture / Design
- Data Model (if applicable)
- API Contract (if applicable)
- Security Considerations
- Test Strategy
- Open Questions
- `tasks.md` — discrete, bounded build tasks derived from the spec

### lightweight

Only two sections are required in `spec.md`:

- Requirements
- Constraints

### none

No `spec.md` is required. The Plan agent emits only `plan.md`.

## Plan Approval Gate Protocol

### What the Plan Agent Emits

The Plan agent always emits `specs/<feature-id>/plan.md` regardless of `spec_mode`. The file must include YAML frontmatter with at minimum:

```yaml
---
feature_id: <feature-id>
spec_mode: full | lightweight | none
status: draft | approved
---
```

### Approval Flow by spec_mode

**full or lightweight:**
1. Plan agent emits `plan.md` and `spec.md` (with required sections populated).
2. All `[NEEDS CLARIFICATION]` markers in `spec.md` are resolved via user questions before emitting.
3. User reviews and approves both `plan.md` and `spec.md`.
4. Build may not start until both are approved.

**none:**
1. Plan agent emits `plan.md` only.
2. User reviews and approves `plan.md` directly.
3. Build proceeds without a spec gate.

### Build Agent Behavior

- The Build agent reads `specs/<id>/plan.md` frontmatter to determine `spec_mode`.
- For `full` or `lightweight`: Build agent checks that `spec.md` exists and contains no unresolved `[NEEDS CLARIFICATION]` markers before proceeding.
- If unresolved markers are found, Build agent stops and surfaces them to the user. It does not proceed.

## [NEEDS CLARIFICATION] Resolution Rules

- All `[NEEDS CLARIFICATION]` markers in `spec.md` must be resolved before Build starts.
- The Plan agent is responsible for resolving these via clarifying questions with the user during the Plan phase.
- Markers may not be carried forward into Build as "TBD" items — they represent missing information that will block implementation.
- The Build agent refuses to proceed if any `[NEEDS CLARIFICATION]` markers remain in `spec.md`.

Example marker (must not appear in an approved spec):

```
[NEEDS CLARIFICATION]: Should this endpoint require authentication?
```

## Spec Artifacts Directory Convention

All SDD artifacts for a feature live under `specs/<feature-id>/`.

| Artifact    | Emitted for            | Description |
|-------------|------------------------|-------------|
| `plan.md`   | all modes              | Plan with `spec_mode` frontmatter and high-level approach |
| `spec.md`   | `full` and `lightweight` | Software design document with required sections |
| `tasks.md`  | `full` only            | Discrete, bounded build tasks for delegation |

The `specs/` directory should be committed to the repository so the Plan and Build phases can operate across session boundaries.

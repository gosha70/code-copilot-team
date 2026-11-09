---
spec_mode: full
feature_id: simplest-complete-change
risk_category: integration
justification: "Framework-level instruction architecture update affecting shared conventions, coding standards, review guidelines, and memory skills across all supported adapters and reviewer setup."
status: draft
date: 2026-11-10
collaboration_mode: single
issue: 389
origin:
  issue: gosha70/code-copilot-team#389
  urls:
    - https://github.com/gosha70/code-copilot-team/issues/389
    - https://github.com/DietrichGebert/ponytail
  origin_claim: |
    Add a Simplest Complete Change policy to Code Copilot Team (CCT): seek the least complex existing solution that completely meets the approved requirements, while retaining the project's verification, security, clarification, and approval gates. Make reuse-first reasoning effective before implementation and make later review findings evidence-based. Inspired by Ponytail, but implemented natively in CCT's instruction architecture rather than by unconditionally stacking a second plugin and its SessionStart rules.
---

# Implementation Plan: Simplest Complete Change (#389)

**Branch**: `feat/simplest-complete-change`
**Input**: `specs/simplest-complete-change/spec.md`

## Summary

Incorporate a native Simplest Complete Change (reuse-first) policy into Code Copilot Team (CCT). The policy embeds an ordered decision ladder into `copilot-conventions` (under Target Alignment and Complexity Control), resolves the boundary between externalized configuration defaults and non-configurable named constants in `coding-standards`, integrates selective high-value decision memory into `memkernel-memory`, requires code review removal findings in `CODE_REVIEW.md` to cite viable replacements, and verifies delivery across all 7 adapters (**Aider**, **Claude Code**, **Codex**, **Cursor**, **GitHub Copilot**, **Pi**, and **Windsurf**) plus the reviewer setup path.

## Technical Context

**Language/Version**: Markdown (skills, review guidelines, conventions), Bash (sync, setup & test scripts)
**Primary Dependencies**:
- `shared/skills/copilot-conventions/SKILL.md`
- `shared/skills/coding-standards/SKILL.md`
- `shared/skills/memkernel-memory/SKILL.md`
- `shared/review/CODE_REVIEW.md`
- `scripts/generate.sh`
- `scripts/setup-reviewer.sh`
**Testing**:
- `bash tests/test-shared-structure.sh`
- `bash tests/test-generate.sh`
- `bash tests/test-setup-reviewer.sh`
**Constraints**:
- CCT owns this policy natively and remains 100% functional without Ponytail as an installation, runtime, or release dependency (users may install Ponytail independently).
- No duplication of the reuse ladder across multiple always-loaded skills (`copilot-conventions` owns the ladder; `coding-standards` owns the configuration/constant boundary).
- Tool-neutral clarification references via `shared/skills/clarification-protocol/SKILL.md`.

## Artifact-to-Delivery-Path Matrix

| Canonical Source | Role / Content | Delivery Mechanism | Target Adapters / Consumers | Verification Suite |
|---|---|---|---|---|
| `shared/skills/copilot-conventions/SKILL.md` | Ordered reuse-first decision ladder & completeness invariants (§ Target Alignment and Complexity Control) | `scripts/generate.sh` | Aider, Claude Code, Codex, Cursor, GitHub Copilot, Pi, Windsurf | `tests/test-generate.sh`, `tests/test-shared-structure.sh` |
| `shared/skills/coding-standards/SKILL.md` | Boundary between externalized schema/fallback/operator defaults and non-configurable named constants | `scripts/generate.sh` | Aider, Claude Code, Codex, Cursor, GitHub Copilot, Pi, Windsurf | `tests/test-generate.sh`, `tests/test-shared-structure.sh` |
| `shared/skills/memkernel-memory/SKILL.md` | Selective, high-value decision memory retention format with revisit triggers (when MemKernel is configured) | `scripts/generate.sh` | Claude Code, Cursor, GitHub Copilot, Windsurf, Pi, Codex (on-demand skill) | `tests/test-generate.sh`, `tests/test-shared-structure.sh` |
| `shared/review/CODE_REVIEW.md` | Evidence-backed review rule (cite replacement + non-weakened requirement) | `scripts/setup-reviewer.sh` (and direct repo reference) | Reviewer assistant / `.github/copilot-review-instructions.md` & target repos | `tests/test-setup-reviewer.sh`, `tests/test-shared-structure.sh` |

## Constitution Check

| Rule file | Concern | Status |
|-----------|---------|--------|
| `coding-standards.md` | Schema/fallback/operator defaults remain externalized; named constants only for genuinely non-configurable invariants | OK: Explicit boundary rule in FR-004 |
| `safety.md` | Non-negotiable security and validation boundaries | OK: Explicit invariant in FR-002 |
| `copilot-conventions.md` | Natural home for the ordered reuse ladder without duplicating into `coding-standards` | OK: Consolidated in § Target Alignment and Complexity Control |

## Architecture Decisions

### ADR-1: Native CCT Ownership vs Ponytail Dependency
- **Context**: Upstream Ponytail provides simplicity guidance via a standalone plugin and SessionStart hooks. Making Ponytail an installation or runtime dependency would couple CCT to external plugin lifecycles and conflicting persona rules.
- **Decision**: CCT owns the Simplest Complete Change policy natively within its instruction architecture. Users remain free to install Ponytail independently, but CCT has zero installation, runtime, or release dependency on Ponytail.
- **Consequences**: Full autonomy across all 7 adapters (`Aider`, `Claude Code`, `Codex`, `Cursor`, `GitHub Copilot`, `Pi`, `Windsurf`), deterministic parity testing, and zero external plugin drift.

### ADR-2: Single Home for the Reuse Ladder (`copilot-conventions`) vs Config Boundary (`coding-standards`)
- **Context**: Both `copilot-conventions` and `coding-standards` are always-loaded rules. Putting the reuse ladder in both would bloat prompt context and create maintenance drift.
- **Decision**: Place the ordered reuse ladder in `shared/skills/copilot-conventions/SKILL.md` under `Target Alignment and Complexity Control`. Keep `shared/skills/coding-standards/SKILL.md` focused strictly on clarifying the boundary between externalized configuration defaults (schema, fallback, and operator defaults) and genuinely non-configurable named constants.
- **Consequences**: Zero duplication between always-loaded skills; clear separation of concerns.

### ADR-3: Selective Decision Memory via Existing MemKernel Interfaces
- **Context**: Recording every trivial implementation choice creates noise, whereas losing high-impact architectural reuse decisions causes future sessions to re-litigate rejected designs.
- **Decision**: Qualify `shared/skills/memkernel-memory/SKILL.md` so that when MemKernel is configured, agents selectively retain high-value implementation decisions (requirement, selected option, rejected alternatives with evidence, verification, and revisit triggers) using existing MemKernel interfaces.
- **Consequences**: High signal-to-noise ratio in memory without any MemKernel schema or API changes.

## Project Structure

```
specs/simplest-complete-change/plan.md          — Implementation plan with SDD frontmatter & delivery matrix
specs/simplest-complete-change/spec.md          — Functional requirements and user scenarios
specs/simplest-complete-change/tasks.md         — Task breakdown and concrete verification checkpoints
specs/simplest-complete-change/origin-alignment-2026-11-10-0100.md — Origin alignment record with resolved triage history
```

*(Implementation phase will touch: `shared/skills/copilot-conventions/SKILL.md`, `shared/skills/coding-standards/SKILL.md`, `shared/skills/memkernel-memory/SKILL.md`, `shared/review/CODE_REVIEW.md`, generated adapter files, and test suites).*

## Scope

### Task 1: Spec Approval Gate
**Files**: `specs/simplest-complete-change/{plan.md,spec.md,tasks.md,origin-alignment-2026-11-10-0100.md}`
**Acceptance criteria**:
- [ ] Conforms to `spec_mode: full` with all required sections.
- [ ] Validated via `scripts/validate-spec.sh --feature-id simplest-complete-change`.
- [ ] Verified via `scripts/check-origin-alignment.sh simplest-complete-change`.
- [ ] Approved by maintainers before implementation.

### Task 2: Canonical Skill & Review Updates (Implementation Phase)
**Files**: `shared/skills/copilot-conventions/SKILL.md`, `shared/skills/coding-standards/SKILL.md`, `shared/skills/memkernel-memory/SKILL.md`, `shared/review/CODE_REVIEW.md`
**Acceptance criteria**:
- [ ] Ordered reuse ladder placed in `copilot-conventions` (§ Target Alignment and Complexity Control) with completeness and caller-tracing invariants.
- [ ] Configuration vs non-configurable named constant boundary defined in `coding-standards` without creating an escape hatch from externalized schema/fallback/operator defaults.
- [ ] Tool-neutral clarification protocol referenced (`shared/skills/clarification-protocol/SKILL.md`).
- [ ] Selective high-value decision memory format documented in `memkernel-memory` for when MemKernel is configured.
- [ ] Evidence-backed removal/replacement citation added to `CODE_REVIEW.md`.

### Task 3: Multi-Adapter Delivery & Concrete Collision Tests (Implementation Phase)
**Files**: `adapters/**`, `tests/test-shared-structure.sh`, `tests/test-generate.sh`, `tests/test-setup-reviewer.sh`
**Acceptance criteria**:
- [ ] `scripts/generate.sh` propagates skill updates across Aider, Claude Code, Codex, Cursor, GitHub Copilot, Pi, and Windsurf.
- [ ] `tests/test-shared-structure.sh` explicitly asserts the two collision cases ("tiny default vs configuration policy" and "small local fix misses another caller") so tests fail if precedence or completeness rules are removed.
- [ ] `tests/test-setup-reviewer.sh` verifies that `setup-reviewer.sh` delivers the updated `CODE_REVIEW.md` guidance.

## Constraints / What NOT to Build

- No installation, runtime, or release dependency on Ponytail.
- No duplication of the reuse ladder across both `copilot-conventions` and `coding-standards`.
- No harness-specific tool names (such as `ask_question`) in shared canonical contracts.
- No new MCP tools, database tables, or runtime decision engines.
- No changes to the benchmark harness (tracked separately).

## File Ownership (Non-Overlapping)

| Owner | Files |
|-------|-------|
| Spec Author | `specs/simplest-complete-change/*` |
| Build Agent | `shared/skills/*`, `shared/review/*`, `adapters/*`, `tests/*` |

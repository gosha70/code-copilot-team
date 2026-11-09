---
spec_mode: full
feature_id: simplest-complete-change
risk_category: integration
status: draft
date: 2026-11-10
---

# Spec: Simplest Complete Change — reuse-first implementation and evidence-backed review (#389)

Code Copilot Team (CCT) emphasizes root-cause analysis, tracing callers, thorough verification, proportionality, and explicit clarification protocols. While `shared/skills/copilot-conventions/SKILL.md` (§ Target Alignment and Complexity Control) already directs agents to prefer minimal solutions that fit the architecture, it does not yet spell out the explicit reuse-first evaluation order before new code is written. Furthermore, `shared/skills/coding-standards/SKILL.md` mandates externalized configuration loaders and defaults files, requiring a clear boundary so that genuinely non-configurable internal constants do not trigger unnecessary scaffolding while real schema, fallback, and operator defaults remain externalized.

This specification introduces a native Simplest Complete Change policy owned directly by CCT without any installation, runtime, or release dependency on Ponytail.

## User Scenarios

### US1: Agent Evaluates Implementation Options via Reuse Ladder (Priority: HIGH)

**Given** an approved task with clear requirements and identified constraints  
**When** the agent begins designing the implementation under `copilot-conventions`  
**Then** the agent systematically evaluates the ordered reuse ladder in `shared/skills/copilot-conventions/SKILL.md` (§ Target Alignment and Complexity Control):
1. Does the requested change actually require new code or behavior?
2. Can an existing project implementation, helper, component, configuration, or workflow meet the requirement?
3. Can the language's standard library or a native platform capability satisfy it?
4. Can an already-approved/installed dependency meet it without introducing a new abstraction?
5. Only when 1–4 cannot satisfy the requirement, implement the simplest complete custom design.

### US2: Agent Preserves Externalized Configuration Rules While Avoiding Scaffolding for Non-Configurable Constants (Priority: HIGH)

**Given** a change that introduces or touches a value in code  
**When** applying `shared/skills/coding-standards/SKILL.md` alongside the reuse-first ladder  
**Then** real schema defaults, fallback defaults, and operator-tunable settings MUST remain externalized in configuration files per `coding-standards`, whereas named constants in code are used only for fixed internal invariants that genuinely cannot be configured at runtime (preventing this policy from acting as an escape hatch from configuration externalization).

### US3: Agent Selectively Records High-Value Decisions in MemKernel (Priority: MEDIUM)

**Given** an environment where MemKernel is configured and an agent makes a non-trivial reuse or architectural choice among competing alternatives  
**When** persisting context via `shared/skills/memkernel-memory/SKILL.md`  
**Then** the agent selectively records high-value decisions (rather than logging every minor implementation choice) using a consistent shape: Requirement & Constraints, Selected Option & Rationale, Rejected Alternatives with Concrete Evidence, Verification/Tests, and Revisit Triggers.

### US4: Reviewer Flags Redundant Abstractions with Replacement Evidence (Priority: HIGH)

**Given** a pull request undergoing code review under `shared/review/CODE_REVIEW.md`  
**When** the reviewer flags an unnecessary abstraction, dependency, duplicated implementation, or removable code  
**Then** the reviewer MUST identify the viable replacement and cite the requirement(s) it will not weaken, accounting for all callers, compatibility, safety, and tests.

### US5: Multi-Adapter and Reviewer Setup Delivery Parity (Priority: HIGH)

**Given** updates to canonical skills in `shared/skills/` and review rules in `shared/review/CODE_REVIEW.md`  
**When** running `scripts/generate.sh` and `scripts/setup-reviewer.sh`  
**Then** shared skill updates propagate cleanly to all 7 supported adapters (**Aider**, **Claude Code**, **Codex**, **Cursor**, **GitHub Copilot**, **Pi**, and **Windsurf**) via `scripts/generate.sh`, `CODE_REVIEW.md` reaches reviewer installations via `scripts/setup-reviewer.sh`, and the test suites (`test-shared-structure.sh`, `test-generate.sh`, `test-setup-reviewer.sh`) pass with zero drift.

## Requirements

- **FR-001**: **Ordered Reuse Ladder in `copilot-conventions`.** `shared/skills/copilot-conventions/SKILL.md` (§ Target Alignment and Complexity Control) MUST define the 5-step reuse evaluation order (No new code -> Existing project code/config -> Standard library/platform -> Approved dependency -> Simplest complete new code) and require tracing callers so a "small local fix" never leaves other callers broken.
- **FR-002**: **Safety and Integrity Invariants.** Security, authentication, privacy, data integrity, error handling, accessibility, and trust boundaries are non-negotiable. Simplicity MUST NOT be achieved by weakening safety or omitting required safeguards.
- **FR-003**: **Tool-Neutral Clarification Precedence.** If a material requirement is ambiguous, agents MUST follow CCT's existing clarification protocol (`shared/skills/clarification-protocol/SKILL.md`) to decide whether to ask, escalate, or proceed. Canonical instructions MUST remain tool-neutral and MUST NOT hardcode harness-specific tool names.
- **FR-004**: **Configuration vs Non-Configurable Constant Boundary in `coding-standards`.** `shared/skills/coding-standards/SKILL.md` MUST clarify that real schema, fallback, and operator defaults remain externalized, while in-code named constants apply strictly to values that genuinely cannot be configured—ensuring the reuse ladder lives only in `copilot-conventions` and does not weaken configuration rules.
- **FR-005**: **Selective Decision Memory Retention.** `shared/skills/memkernel-memory/SKILL.md` MUST instruct agents—when MemKernel is configured—to selectively retain high-value implementation decisions (Requirement, Chosen Option, Rejected Alternatives with Evidence, Verification, Revisit Conditions) using existing MemKernel interfaces without logging trivial choices.
- **FR-006**: **Evidence-Backed Code Review.** `shared/review/CODE_REVIEW.md` MUST mandate that any review finding recommending removal or replacement of code/abstractions identify the viable replacement and cite the requirement(s) that remain satisfied.
- **FR-007**: **Precision Delivery Across Adapters and Reviewer Setup.** Canonical skill changes in `shared/skills/` MUST propagate to **Aider**, **Claude Code**, **Codex**, **Cursor**, **GitHub Copilot**, **Pi**, and **Windsurf** via `scripts/generate.sh`, while `shared/review/CODE_REVIEW.md` delivery MUST be verified through `scripts/setup-reviewer.sh`.
- **FR-008**: **Concrete Collision and Parity Assertions.** `tests/test-shared-structure.sh`, `tests/test-generate.sh`, and `tests/test-setup-reviewer.sh` MUST include regression checks that fail if the precedence rule ("tiny default vs configuration policy"), completeness rule ("small local fix misses another caller"), adapter sync, or reviewer setup delivery are broken.

## Constraints

- **C-001**: CCT owns this policy natively; Ponytail is neither an installation, runtime, nor release dependency of CCT (users may install Ponytail independently).
- **C-002**: No duplication of the reuse ladder across both `copilot-conventions` and `coding-standards`.
- **C-003**: No harness-specific question tool names in shared skill contracts; reference `shared/skills/clarification-protocol/SKILL.md` directly.
- **C-004**: No new MCP tools, database schemas, or runtime services.
- **C-005**: Benchmark harness changes are out of scope.
- **C-006**: No arbitrary lines-of-code (LOC) or token reduction targets.

## Key Entities

- **Reuse Ladder**: The 5-step prioritized decision framework in `copilot-conventions` (§ Target Alignment and Complexity Control).
- **Completeness Invariant**: The requirement that a simpler change is valid only if all callers, workflows, migrations, and regression cases remain intact.
- **Configuration Boundary**: The rule in `coding-standards` keeping schema, fallback, and operator defaults externalized while reserving named constants for genuinely non-configurable values.
- **Selective Decision Memory Record**: A high-value MemKernel memory entry capturing requirement, chosen option, rejected alternatives, evidence, and revisit triggers when MemKernel is configured.
- **Evidence-Backed Review Finding**: A review comment under `CODE_REVIEW.md` that pairs a simplification/removal request with a concrete replacement and preserved requirement citation.

## Success Criteria

1. US1 is codified in `shared/skills/copilot-conventions/SKILL.md` (§ Target Alignment and Complexity Control) without duplicating into `coding-standards`.
2. US2 is codified in `shared/skills/coding-standards/SKILL.md`, preserving externalized schema/fallback/operator defaults.
3. US3 is codified in `shared/skills/memkernel-memory/SKILL.md` with selective high-value qualification.
4. US4 is codified in `shared/review/CODE_REVIEW.md` and verified via `tests/test-setup-reviewer.sh`.
5. US5 is verified across Aider, Claude Code, Codex, Cursor, GitHub Copilot, Pi, and Windsurf via `scripts/generate.sh` and `tests/test-generate.sh`.
6. `tests/test-shared-structure.sh` explicitly tests both collision cases ("tiny default vs configuration policy" and "small local fix misses another caller").
7. `bash scripts/validate-spec.sh --feature-id simplest-complete-change` and `bash scripts/check-origin-alignment.sh simplest-complete-change` exit 0.

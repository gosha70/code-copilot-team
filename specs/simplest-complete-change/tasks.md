---
spec_mode: full
feature_id: simplest-complete-change
risk_category: integration
status: approved
date: 2026-11-10
---

# Tasks: Simplest Complete Change (#389)

<!-- [P] = can run in parallel within the story group. [US#] traces to spec.md. -->

## US1 & US2: Ordered Reuse Ladder (`copilot-conventions`) & Configuration Boundary (`coding-standards`)

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 1 | | Add ordered 5-step reuse-first ladder, caller-tracing completeness invariant, and tool-neutral `clarification-protocol` reference to § Target Alignment and Complexity Control (FR-001, FR-002, FR-003) | `shared/skills/copilot-conventions/SKILL.md` | build | [x] |
| 2 | [P] | Clarify configuration/default boundary: schema, fallback, and operator defaults remain externalized; named constants are strictly for genuinely non-configurable internal values (FR-004) | `shared/skills/coding-standards/SKILL.md` | build | [x] |

**Checkpoint US1 & US2** — verify before continuing:
- [x] Reuse ladder lives solely in `copilot-conventions` (§ Target Alignment and Complexity Control) and is not duplicated in `coding-standards`
- [x] Clarification reference points to `shared/skills/clarification-protocol/SKILL.md` without harness-specific tool names
- [x] `coding-standards` preserves externalization for schema, fallback, and operator defaults while allowing named constants only for genuinely non-configurable values

---

## US3: Selective Decision Memory Retention

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 3 | | Verify the existing Decision Records section (#445) against FR-005 and add only the "selective, high-value decisions when MemKernel is configured" qualification; no new fields (FR-005) | `shared/skills/memkernel-memory/SKILL.md` | build | [x] |

**Checkpoint US3** — verify before continuing:
- [x] Explicitly qualifies retention as selective, high-value decisions when MemKernel is configured (not logging every small choice)
- [x] Uses existing MemKernel interfaces without schema or API modifications

---

## US4: Evidence-Backed Code Review

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 4 | | Require removal/simplification review findings to identify the viable replacement and cite the non-weakened requirement(s) (FR-006) | `shared/review/CODE_REVIEW.md` | build | [x] |

**Checkpoint US4** — verify before continuing:
- [x] Reviewers must name concrete replacements and verify callers, compatibility, safety, and tests before flagging removable code
- [x] `bash tests/test-setup-reviewer.sh` passes and confirms `scripts/setup-reviewer.sh` delivers the updated `CODE_REVIEW.md`

---

## US5: Multi-Adapter Delivery & Concrete Collision Tests

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 5 | | Regenerate adapters with `scripts/generate.sh` and confirm `adapters/claude-code/setup.sh` installs the updated always-loaded rules; delivery follows the plan's matrix, with no catalog support-level changes (FR-007) | `adapters/**` | build | [x] |
| 6 | [P] | Add concrete assertions for the two collision cases ("tiny default vs configuration policy" and "small local fix misses another caller") that fail if the precedence or completeness rule is removed (FR-008) | `tests/test-shared-structure.sh` | build | [x] |
| 7 | [P] | Verify adapter generation parity and reviewer installation path coverage (FR-007, FR-008) | `tests/test-generate.sh`, `tests/test-setup-reviewer.sh` | build | [x] |

**Checkpoint US5** — verify before continuing:
- [x] `scripts/generate.sh` leaves zero uncommitted diff, and each artifact appears in exactly the adapters the delivery matrix lists (always-loaded skills in all seven; `memkernel-memory` in Claude Code, Cursor, GitHub Copilot, Pi, and as a reference row in Codex)
- [x] `tests/test-shared-structure.sh` explicitly tests the "tiny default vs configuration policy" precedence rule and fails if removed
- [x] `tests/test-shared-structure.sh` explicitly tests the "small local fix misses another caller" completeness rule and fails if removed
- [x] `tests/test-generate.sh` and `tests/test-setup-reviewer.sh` pass 100%

---

## Final Verification

- [x] `bash scripts/validate-spec.sh --feature-id simplest-complete-change` passes
- [x] `bash scripts/check-origin-alignment.sh simplest-complete-change` passes
- [x] `bash tests/test-shared-structure.sh` passes
- [x] `bash tests/test-generate.sh` passes
- [x] `bash tests/test-setup-reviewer.sh` passes
- [x] No `[NEEDS CLARIFICATION]` markers remain in `spec.md`
- [x] Maintainer review and approval completed (`status: approved`) before implementation PR

---
spec_mode: full
feature_id: simplest-complete-change
risk_category: integration
status: draft
date: 2026-11-10
---

# Tasks: Simplest Complete Change (#389)

<!-- [P] = can run in parallel within the story group. [US#] traces to spec.md. -->

## US1 & US2: Ordered Reuse Ladder (`copilot-conventions`) & Configuration Boundary (`coding-standards`)

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 1 | | Add ordered 5-step reuse-first ladder, caller-tracing completeness invariant, and tool-neutral `clarification-protocol` reference to § Target Alignment and Complexity Control (FR-001, FR-002, FR-003) | `shared/skills/copilot-conventions/SKILL.md` | build | [ ] |
| 2 | [P] | Clarify configuration/default boundary: schema, fallback, and operator defaults remain externalized; named constants are strictly for genuinely non-configurable internal values (FR-004) | `shared/skills/coding-standards/SKILL.md` | build | [ ] |

**Checkpoint US1 & US2** — verify before continuing:
- [ ] Reuse ladder lives solely in `copilot-conventions` (§ Target Alignment and Complexity Control) and is not duplicated in `coding-standards`
- [ ] Clarification reference points to `shared/skills/clarification-protocol/SKILL.md` without harness-specific tool names
- [ ] `coding-standards` preserves externalization for schema, fallback, and operator defaults while allowing named constants only for genuinely non-configurable values

---

## US3: Selective Decision Memory Retention

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 3 | | Add selective high-value decision template (when MemKernel is configured) covering Requirement, Selected Option, Rejected Alternatives with Evidence, Verification, and Revisit Triggers (FR-005) | `shared/skills/memkernel-memory/SKILL.md` | build | [ ] |

**Checkpoint US3** — verify before continuing:
- [ ] Explicitly qualifies retention as selective, high-value decisions when MemKernel is configured (not logging every small choice)
- [ ] Uses existing MemKernel interfaces without schema or API modifications

---

## US4: Evidence-Backed Code Review

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 4 | | Require removal/simplification review findings to identify the viable replacement and cite the non-weakened requirement(s) (FR-006) | `shared/review/CODE_REVIEW.md` | build | [ ] |

**Checkpoint US4** — verify before continuing:
- [ ] Reviewers must name concrete replacements and verify callers, compatibility, safety, and tests before flagging removable code
- [ ] `bash tests/test-setup-reviewer.sh` passes and confirms `scripts/setup-reviewer.sh` delivers the updated `CODE_REVIEW.md`

---

## US5: Multi-Adapter Delivery & Concrete Collision Tests

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 5 | | Run `scripts/generate.sh` to propagate canonical shared skills across Aider, Claude Code, Codex, Cursor, GitHub Copilot, Pi, and Windsurf (FR-007) | `scripts/generate.sh`, `adapters/**` | build | [ ] |
| 6 | [P] | Add concrete assertions for the two collision cases ("tiny default vs configuration policy" and "small local fix misses another caller") that fail if the precedence or completeness rule is removed (FR-008) | `tests/test-shared-structure.sh` | build | [ ] |
| 7 | [P] | Verify adapter generation parity and reviewer installation path coverage (FR-007, FR-008) | `tests/test-generate.sh`, `tests/test-setup-reviewer.sh` | build | [ ] |

**Checkpoint US5** — verify before continuing:
- [ ] `scripts/generate.sh` produces zero uncommitted diff across all 7 adapters (`Aider`, `Claude Code`, `Codex`, `Cursor`, `GitHub Copilot`, `Pi`, `Windsurf`)
- [ ] `tests/test-shared-structure.sh` explicitly tests the "tiny default vs configuration policy" precedence rule and fails if removed
- [ ] `tests/test-shared-structure.sh` explicitly tests the "small local fix misses another caller" completeness rule and fails if removed
- [ ] `tests/test-generate.sh` and `tests/test-setup-reviewer.sh` pass 100%

---

## Final Verification

- [ ] `bash scripts/validate-spec.sh --feature-id simplest-complete-change` passes
- [ ] `bash scripts/check-origin-alignment.sh simplest-complete-change` passes
- [ ] `bash tests/test-shared-structure.sh` passes
- [ ] `bash tests/test-generate.sh` passes
- [ ] `bash tests/test-setup-reviewer.sh` passes
- [ ] No `[NEEDS CLARIFICATION]` markers remain in `spec.md`
- [ ] Maintainer review and approval completed (`status: approved`) before implementation PR

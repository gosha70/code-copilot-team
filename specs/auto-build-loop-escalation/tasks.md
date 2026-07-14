# Tasks: auto-build-loop escalation, notification, resume (increment C)

<!-- [P] = can run in parallel within the story group. [US#] traces to spec.md. -->

## US1: Notification + record enrichment

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 1 | | notify() with placeholder rendering, bash -c execution, journal-on-failure; fire on park/milestone/done (FR-1, FR-2) | `scripts/auto-build-loop.sh` | build | [ ] |
| 2 | | Escalation record enrichment: per-reason history refs, resolved/resolved_at, notified flag (FR-3) | `scripts/auto-build-loop.sh` | build | [ ] |
| 3 | [P] | Notify-stub tests: placeholders rendered on park/milestone/done; failing notify command leaves exit codes unchanged (FR-9) | `tests/test-auto-build-loop.sh` | build | [ ] |

**Checkpoint US1** — verify before continuing:
- [ ] `bash -n` clean; notify assertions green
- [ ] Park/milestone/done all journal + notify exactly once

---

## US2: Parked-resume resolution detection

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 4 | | Resume dispatcher on newest unresolved escalation reason (FR-4); unresolved refusal messages per reason (FR-6) | `scripts/auto-build-loop.sh` | build | [ ] |
| 5 | | review_breaker paths: approve (human-approved bypass accepted by PASS hard gate, FR-5), reject → aborted, retry → re-enter review | `scripts/auto-build-loop.sh` | build | [ ] |
| 6 | | origin_gate / provider_unavailable / test-family / cap_exceeded resolution probes (FR-4); resolved bookkeeping + notify on resume (FR-7) | `scripts/auto-build-loop.sh` | build | [ ] |
| 7 | [P] | Resume tests: approve/reject/retry, origin restore, test-fix, cap raise, unresolved refusal names the action (FR-9) | `tests/test-auto-build-loop.sh` | build | [ ] |
| 7a | [P] | Bypass-scope test: an approve bypass recorded for phase N is accepted ONLY for phase N's parked escalation — a later phase with `bypass: true` (or a stale approval) still parks (FR-5) | `tests/test-auto-build-loop.sh` | build | [ ] |

**Checkpoint US2** — verify before continuing:
- [ ] Every reason has a resolve path test AND an unresolved-refusal test where applicable
- [ ] No duplicate commits / re-reviews on any resume path

---

## US3: Docs + counts + Linux parity

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 8 | | Skill resume playbook per-reason table; remove "increment C pending" notes; regenerate adapters | `shared/skills/auto-build-loop/SKILL.md`, `adapters/` (generated) | build | [ ] |
| 9 | [P] | Count sync: tests/test-counts.env + README suite line | `tests/test-counts.env`, `README.md`, `tests/test-shared-structure.sh` (only if count text assertions change) | build | [ ] |
| 10 | | Linux container run of test-auto-build-loop.sh (ubuntu + git + jq) | — (verification) | build | [ ] |

**Checkpoint US3** — verify before continuing:
- [ ] `bash scripts/generate.sh` zero drift
- [ ] Full local gate green; container suite green

---

## Final Verification

- [ ] `bash -n` on driver + tests, 0 errors
- [ ] All suites pass with updated counts
- [ ] No [NEEDS CLARIFICATION] markers remain in spec.md
- [ ] Origin alignment re-checked (Gate 3) before presenting

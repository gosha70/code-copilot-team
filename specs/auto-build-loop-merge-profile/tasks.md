# Tasks: auto-build-loop `merge` profile (increment F)

<!-- [P] = can run in parallel within the story group. [US#] traces to spec.md. -->

## US1: Ladder + gated auto-merge

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 1 | | Unlock `merge` in the ladder (can_push/can_open_pr/can_merge=true); read merge.enabled / require_branch_protection / method / require_green_ci (FR-1) | `scripts/auto-build-loop.sh` | build | [ ] |
| 2 | | `arm_auto_merge`: branch-protection probe (`gh api`) → park `merge_blocked` if required+absent; `gh pr merge <n> --auto --<method>`; record `auto_merge_armed`/`merge_method`; failure parks (FR-3, FR-4) | `scripts/auto-build-loop.sh` | build | [ ] |
| 3 | | Finalize wiring: after open_or_update_pr call arm_auto_merge for merge; enabled:false behaves as pr; profile-aware summary/notify (FR-2) | `scripts/auto-build-loop.sh` | build | [ ] |

**Checkpoint US1** — verify before continuing:
- [ ] `bash -n` clean; advisory/pr paths byte-for-byte unchanged (no `pr merge`)
- [ ] enabled:false opens the PR and arms nothing

---

## US2: Idempotent resume + safety

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 4 | | Idempotency: skip re-arm when the PR already has auto-merge (ledger or `gh pr view --json autoMergeRequest`); `merge_blocked` parked-resume re-probes/re-arms (FR-5) | `scripts/auto-build-loop.sh` | build | [ ] |
| 5 | | Confirm no local-merge/force path; base/master commit+push refusals intact (FR-6) | `scripts/auto-build-loop.sh` | build | [ ] |

**Checkpoint US2** — verify before continuing:
- [ ] `pr merge` runs at most once across a create→arm→resume cycle
- [ ] grep shows no `--force`/local-merge/`gh pr merge` outside `arm_auto_merge`

---

## US3: Config + tests + docs + parity

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 6 | [P] | Add `merge.method` to the config template; document the `merge` block (template + settings.json) | `shared/templates/sdd/automation-template.json`, `adapters/claude-code/.claude/settings.json` | build | [ ] |
| 7 | | Tests: gh argv + api stub — arm-once (enabled+protected), enabled:false→pr, unprotected→park, resume idempotent, advisory/pr never merge (FR-7) | `tests/test-auto-build-loop.sh` | build | [ ] |
| 8 | [P] | Skill `merge` row live + config docs; regenerate adapters (zero drift) (FR-8) | `shared/skills/auto-build-loop/SKILL.md`, `adapters/` (generated) | build | [ ] |
| 9 | [P] | Count sync: `tests/test-counts.env` + README suite line | `tests/test-counts.env`, `README.md` | build | [ ] |
| 10 | | Linux container run of test-auto-build-loop.sh (ubuntu + git + jq) | — (verification) | build | [ ] |

**Checkpoint US3** — verify before continuing:
- [ ] `bash scripts/generate.sh` zero drift
- [ ] Full local gate green with updated counts; container suite green

---

## Final Verification

- [ ] `bash -n` on driver + tests, 0 errors
- [ ] All suites pass with updated counts
- [ ] No [NEEDS CLARIFICATION] markers remain in spec.md
- [ ] Origin alignment re-checked (Gate 3) before presenting

# Tasks: unattended cross-harness execution

<!-- [P] = can run in parallel within the story group. -->

## US1: Unattended Permission Posture

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 1 | [P] | Add or update the named unattended posture so it imports the relaxed profile and sets `headless.ask_resolution = "allow"` without changing deny/floor/sandbox behavior (FR-1, FR-2, FR-3) | `adapters/pi/runtime/config/profiles.ts` | build | [ ] |
| 2 | | Add profile-resolution tests proving the posture resolves relaxed imports, sandbox requirements, and headless ask allow; keep `ci` fail-fast and conservative profiles unchanged (FR-4) | `tests/pi-runtime/` | build | [ ] |
| 3 | | Add permission-engine regression tests: ask-gated operations allow only under the unattended headless posture; denied commands/protected paths/sandbox rejection still deny (FR-2) | `tests/pi-runtime/` | build | [ ] |

**Checkpoint US1** - verify before continuing:
- [ ] Pi runtime profile tests green
- [ ] Permission decision invariants prove ask-only relaxation

---

## US2: Shared Claude Settings Generation

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 4 | | Implement a Claude settings generator/switch path from the shared permission profile JSON; preserve unrelated settings, emit no `bypassPermissions`, and set the Claude-side non-interactive default equivalent to Pi's ask-resolution allow (FR-5, FR-6) | `adapters/claude-code/`, `scripts/` as needed | build | [ ] |
| 5 | | Add idempotency tests for generated `settings.json`, managed-key update/removal, non-interactive default preservation/removal, and unrelated-key preservation (FR-5, FR-6, FR-7) | `tests/` | build | [ ] |
| 6 | [P] | Add a drift guard proving the shared permission profile, Pi imported layer, and Claude generated settings agree on the managed allow/ask/deny posture and residual-ask semantics (FR-8) | `tests/`, maybe `scripts/` | build | [ ] |

**Checkpoint US2** - verify before continuing:
- [ ] Claude settings generation is idempotent and no-bypass
- [ ] Cross-harness permission drift guard covers allow/deny lists and ask-resolution semantics

---

## US3: Continuity Reporting

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 7 | | Add a continuity report over `tasks.md`, `.cct/pi-session.json`, and `.cct/auto-build/<feature-id>/state.json`; report missing/corrupt/untrusted honestly (FR-9, FR-13) | `adapters/pi/runtime/`, `scripts/` as appropriate | build | [ ] |
| 8 | | Add tests for trusted checkpoint recovery, untrusted withheld recovery, corrupt checkpoint handling, and no native Pi compaction overclaim (FR-10, FR-11, FR-12) | `tests/pi-runtime/`, `tests/` | build | [ ] |
| 9 | | Surface unattended posture and cooldown-resume support in `doctor`, `features`, or the equivalent diagnostics, including enabled/degraded/unavailable status by adapter (FR-22) | `adapters/pi/runtime/`, `adapters/claude-code/`, tests as appropriate | build | [ ] |
| 10 | [P] | Document the durable-state-first contract and mapatlas-style `tasks.md` workflow (FR-23) | `adapters/pi/docs/`, shared docs as appropriate | docs | [ ] |

**Checkpoint US3** - verify before continuing:
- [ ] Continuity diagnostics distinguish present, missing, corrupt, and untrusted state
- [ ] Docs state Pi compaction recovery is degraded, not native

---

## US4: Cooldown Resume Supervisor

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 11 | | Add the supervisor ledger schema under `.cct/` with feature id, harness, worktree, attempts, cooldowns, exit classification, evidence, and timestamps (FR-15, FR-16) | `scripts/`, tests fixtures | build | [ ] |
| 12 | | Implement harness-neutral launch/resume around `scripts/auto-build-loop.sh --resume`, `pi-code`, and the Claude Code wrapper; preserve project/worktree and posture (FR-14, FR-18) | `scripts/` | build | [ ] |
| 13 | | Implement explicit usage-limit classification with stored evidence and unknown-error parking/failure (FR-16, FR-19) | `scripts/` | build | [ ] |
| 14 | | Implement incomplete-task detection after clean exit and retry/cooldown caps with injectable sleep/test clock (FR-17, FR-18, FR-19) | `scripts/`, tests fixtures | build | [ ] |
| 15 | | Prove no destructive git operations are issued by the supervisor; git ownership remains with the auto-build driver or user action (FR-20) | `tests/` | build | [ ] |
| 16 | | Wire non-blocking notifications for cooldown/park/done using the existing notification contract (FR-21) | `scripts/`, tests | build | [ ] |

**Checkpoint US4** - verify before continuing:
- [ ] Mock harness usage-limit run cools down and relaunches
- [ ] Clean exit with unchecked tasks is not treated as success
- [ ] Retry caps and unknown errors park/fail deterministically
- [ ] Supervisor never commits, pushes, merges, deletes branches, or removes worktrees

---

## Final Verification

- [ ] Pi runtime suite green
- [ ] Claude launcher/setup tests green
- [ ] Auto-build-loop/supervisor tests green
- [ ] Shared-structure/count drift guards updated
- [ ] Docs links checked
- [ ] No `bypassPermissions` emitted by generated settings
- [ ] No stale `[NEEDS CLARIFICATION]` markers in this spec package

# Tasks: Wire the T8.1/T8.2 team controller into Pi (issue #174)

Wiring only — the T8.1 `agents/team.ts` and T8.2 `agents/team-status.ts`
libraries and their coordination/safety model are built + tested and MUST NOT be
re-implemented. Keep the gates green (`test-pi-runtime.sh`,
`test-typecheck-gate.sh`, `test-pi-launcher.sh`), gate on `agents.teams_enabled`,
audit every action, serialize ledger mutations, and preserve the `degraded`
boundary (no live execution/transport). `AC` = acceptance.

## US1 — Feature-gated command surface + serialized mutations

| # | [P] | Task | File(s) | AC |
|---|-----|------|---------|----|
| 1 | | Extract `withLedgerLock` → `agents/ledger-lock.ts`, parameterized `{ lockName }` (default `worktrees`), keeping the pid/token ownership; update `worktree-lifecycle.ts` to import it (no behavior change). (FR-3) | `agents/ledger-lock.ts`, `agents/worktree-lifecycle.ts` | worktree suite still green; team uses `.cct/team.lock` |
| 2 | | `teamsEnabled(cfg)` gate + audit helper; the mutating-op wrapper `load → op → save` under `withLedgerLock(repoRoot, fn, {lockName:"team"})`, surfacing the op's `error`. (FR-1/FR-2/FR-3/FR-5) | `agents/team-commands.ts` | disabled ⇒ opt-in reply + zero side effects |
| 3 | | `/cct:team` handlers for `create | join | task | assign | approve | activate | claim | complete | fail | message | leave | recover | shutdown | close` → the matching team.ts op (claim uses `autonomy.max_concurrency`). (FR-1/FR-2) | `agents/team-commands.ts` | each op routed + audited; usage on unknown sub |
| 4 | | `registerCommand("cct:team", …)` in `index.ts`, routing subcommands via `emit`. (FR-1) | `index.ts` | `/cct:team …` dispatches; usage shown |
| 5 | | Tests: gated (disabled ⇒ refuse, no write); full lifecycle create→…→close green; **each refusal branch** — double-claim, cross-assignment claim, over-cap claim, pre-approval claim, close-while-claimed. (AC-1, AC-2) | `tests/pi-runtime/team-commands.test.mjs` | all branches asserted; ledger reflects only successful ops |
| 6 | | Tests: **concurrency** — two real processes claim one task (barrier-released, reuse the #172 fixture pattern) → exactly one wins; distinct tasks both survive. (AC-3) | `tests/pi-runtime/team-commands.test.mjs` (+ fixture) | one-claimant guarantee proven cross-process |

**Checkpoint US1** — the full team lifecycle is drivable via `/cct:team`, gated,
audited, and lock-serialized; every coordination refusal is enforced through the
wiring.

---

## US2 — Status, synthesis, recovery + CLI

| # | [P] | Task | File(s) | AC |
|---|-----|------|---------|----|
| 7 | | `/cct:team status [--json]` → `teamStatus` + `renderTeamStatus`; `synthesize [--json]` → `synthesizeTeam` (read-only). (FR-1) | `agents/team-commands.ts`, `index.ts` | correct counts + `complete\|partial\|failed\|empty` verdict |
| 8 | | `pi-code team status\|synthesize [--json]` read-only CLI; route `team` through the launcher diagnostic dispatch + recursion-guard allow-list + help. (FR-4) | `cli.ts`, `bin/pi-code` | `pi-code team status --json` returns the snapshot; launcher test green |
| 9 | | Tests: status counts; synthesis verdicts incl. fail-closed edges (`complete` only when all `done`); `leave`/`recover` reopen orphaned claims (never auto-complete). (AC-4) | `tests/pi-runtime/team-commands.test.mjs` | recovery reopens, verdict fail-closed |

**Checkpoint US2** — status + fail-closed synthesis + reopen-only recovery are
exposed in-session and via the CLI.

---

## US3 — Session advisory, docs, honesty

| # | [P] | Task | File(s) | AC |
|---|-----|------|---------|----|
| 10 | | Session-start advisory: when teams enabled and `.cct/team.json` exists, push a one-line `teamStatus` summary to `state.warnings` + audit `team.status`; read-only, no recovery. (FR-6) | `index.ts` | worker/task counts surfaced on start; no mutation |
| 11 | | Assert wiring subscribes ONLY to `session_start` + registers the command (no invented event); worktree lock behavior unchanged post-extraction. (AC-6) | `tests/pi-runtime/team-commands.test.mjs` | no-invented-event + no worktree regression asserted |
| 12 | [P] | Docs + honesty: `adapters/pi/docs/team-coordination.md` (the `/cct:team` + CLI surface, the `agents.teams_enabled` gate, the two-file ledger, the `degraded` boundary — no live execution/transport, snapshot status); README link + launcher help/test. (FR-7) | `adapters/pi/docs/*`, `bin/pi-code`, `tests/test-pi-launcher.sh` | doc states the degraded boundary; help lists the commands; launcher test green |

**Checkpoint US3** — teams are honestly documented (opt-in, coordination-state,
degraded), surfaced at session start, and the command/CLI surface is discoverable.

---

## Global definition of done (every task)

`build` + `typecheck` (strict) + Pi runtime suite + launcher suite green ·
team libraries & safety model unchanged (wiring only; the lock extraction is
additive + behavior-preserving) · every action audited · mutations gated on
`agents.teams_enabled` and lock-serialized · single-claimant / approval /
bounded-concurrency / close-while-claimed all fail-closed through the wiring ·
synthesis fail-closed + recovery reopen-only · team ledger separate from the
worktree ledger · `agents.teams` capability unchanged · no new Pi event invented.

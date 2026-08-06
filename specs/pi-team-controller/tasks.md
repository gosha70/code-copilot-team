# Tasks: Wire the T8.1/T8.2 local team ledger into Pi — Slice A of #174

Wiring only — `agents/team.ts` (T8.1) + `agents/team-status.ts` (T8.2) are built +
tested and MUST NOT be re-implemented. This targets **issue #185** (Slice A of the
#174 epic); do **not** close #174. Keep the gates green (`test-pi-runtime.sh`,
`test-typecheck-gate.sh`, `test-pi-launcher.sh`), resolve every PR #184 review
finding (both rounds), and preserve the `degraded` boundary. Identity is
**declared attribution, not authentication** (documented). `AC` = acceptance.

## US1 — Canonical, declared-identity, gated command surface

| # | [P] | Task | File(s) | AC |
|---|-----|------|---------|----|
| 1 | | Extract `withLedgerLock` → `agents/ledger-lock.ts`, `withLedgerLock(repoRoot, fn, { lockName })` with `type LedgerLockName = "worktrees" \| "team"`; update `worktree-lifecycle.ts` to import it (no behavior change). (review lock decision) | `agents/ledger-lock.ts`, `agents/worktree-lifecycle.ts` | worktree concurrency + stale-owner tests green unchanged; team uses `.cct/team.lock` |
| 2 | | `resolveTeamRoot(cwd) → {ok,root}\|{ok:false,reason}` (via `primaryRepoRoot`, **NO `?? cwd`**) fronts EVERY team op; unresolved ⇒ mutation refuses + audit `team.root-unresolved` + writes nothing; reads report "no canonical repository root". (round-2 #2, FR-2) | `agents/team-commands.ts` | linked-worktree op targets the PRIMARY ledger; git-fail creates nothing |
| 3 | | `TeamIdentity { teamId, memberId }` — **both `CCT_TEAM_ID` + `CCT_TEAM_MEMBER_ID` mandatory**; `attachTeamIdentity(env)` stores ONLY these (no cached role/status); actor for actor-scoped/membership subs comes from it, never args; missing either ⇒ refuse + `team.identity-invalid`. Honest: attribution, NOT authentication. (round-2 #1/#3, FR-3) | `agents/team-commands.ts`, `index.ts` | actor from env; missing/unknown declared id refused |
| 4 | | Authz re-validated **inside the lock per mutation**: load → require `identity.teamId===ledger.teamId` (**team binding**, else `team.identity-invalid`) → `actor=members.find(memberId)` → require `active`. Tiers: `create`=bootstrap (`<teamId>===identity.teamId`, no pre-membership); `join`/`task`=**any active member** (not lead); `assign`/`approve`/`activate`/`recover`/`close`=**active lead** as of the loaded ledger (never cached). **Sole-active-lead `leave` on a non-closed team refused** (no lead-transfer). (round-2 #1/#3, FR-4) | `agents/team-commands.ts` | wrong-team + stale-lead + non-lead admin + unidentified join/task refused |
| 5 | | Safe create + bootstrap: `create <teamId> [--no-plan-approval]` (approval default-on = library) — refuse over existing-valid AND corrupt `team.json` (never overwrite); lead = **declared** member; no restart after create. Other mutations load→null⇒refuse→authz→op→save-on-ok; reads/advisory missing⇒"no team", corrupt⇒fail-closed (never `null`→`teamStatus`). (review #4 + round-2 #5, FR-5) | `agents/team-commands.ts` | duplicate/corrupt create leaves file byte-for-byte unchanged; declared lead usable immediately |
| 6 | | `/cct:team` handlers, correct signatures: `complete/fail(ledger, taskId, actor)`; `message <to\|all> <body…>` → **load ledger under lock, validate team-open + sender-active + recipient**, then `postMessage(root, actor, to, body, now)` (`false`⇒failure, no `team.json` rewrite); claim uses `autonomy.max_concurrency`. Gate mutations on `agents.teams_enabled`. (review #5, FR-1/FR-6) | `agents/team-commands.ts` | signatures correct; message validates before append; disabled ⇒ refuse + no write |
| 7 | | `registerCommand("cct:team", …)` in `index.ts`, routing subcommands via `emit`. (FR-1) | `index.ts` | `/cct:team …` dispatches; usage on unknown sub |
| 8 | | Tests: gated; full lifecycle; **each refusal** (double/cross/over-cap/pre-approval claim, close-while-claimed); **team binding** (`CCT_TEAM_ID=A` + `create B` ⇒ refused/no ledger; `teamId=A` vs ledger `B` ⇒ all mutations refused); **join/task authz** (missing/unknown/inactive identity refused; active non-lead allowed); **live authz** — a teammate that becomes `left` is refused next actor-cmd (not cached); the **lead** stale-cache case via an externally-modified ledger fixture; **sole-active-lead `leave` refused**; same-team existing-member impersonation NOT prevented (documented); create-over-existing/corrupt byte-for-byte; `--no-plan-approval` vs default. (AC-3,4,5,6) | `tests/pi-runtime/team-commands.test.mjs` | all branches + binding + live-authz asserted |
| 9 | | Tests: **canonical ledger across two REAL linked worktrees** (claim in A → visible in B; concurrent claim → exactly one wins in the primary ledger); **fail-closed root** — force `gitCommonDir` to fail from a worktree ⇒ mutation refuses + `team.root-unresolved`, **nothing created** in that worktree. (AC-1,2) | `tests/pi-runtime/team-commands.test.mjs` (+ fixture) | split-ledger impossible; one-claimant proven; git-fail creates nothing |

**Checkpoint US1** — team lifecycle drivable via `/cct:team`, on ONE canonical
primary ledger (fail-closed), actor from declared identity with per-mutation
authz, lead-only admin, safe create, gated + lock-serialized, every refusal
enforced.

---

## US2 — Status, synthesis, recovery + CLI (honest gate)

| # | [P] | Task | File(s) | AC |
|---|-----|------|---------|----|
| 10 | | `/cct:team status\|synthesize [--json]` (read-only) → `teamStatus`+`renderTeamStatus` / `synthesizeTeam`; `leave`/`recover` reopen orphaned claims (never auto-complete). (FR-1) | `agents/team-commands.ts`, `index.ts` | counts + `complete\|partial\|failed\|empty` verdict; reopen-only |
| 11 | | `pi-code team status\|synthesize [--json]` read-only CLI at `teamRoot` — renders whenever a valid ledger exists regardless of the untrusted-project `agents.teams_enabled`; JSON adds `enabled: true\|false\|unknown` + trust note. Route `team` through the launcher dispatch + recursion-guard allow-list + help. (review #6, FR-8) | `cli.ts`, `bin/pi-code` | CLI renders under project-only opt-in; JSON reports enabled/trust; launcher test green |
| 12 | | Tests: status/synthesis edges (fail-closed verdict); recovery reopens; CLI renders when `agents.teams_enabled=true` only in trusted project config; JSON `enabled`/trust asserted. (AC-5,6) | `tests/pi-runtime/team-commands.test.mjs` | gate semantics + recovery asserted |

**Checkpoint US2** — status + fail-closed synthesis + reopen-only recovery exposed
in-session and via a CLI whose gate semantics don't misreport project-only opt-in.

---

## US3 — Session advisory, docs, honesty

| # | [P] | Task | File(s) | AC |
|---|-----|------|---------|----|
| 13 | | Session-start advisory: teams enabled + valid `.cct/team.json` at `teamRoot` ⇒ one-line `teamStatus` summary → `state.warnings` + audit `team.status`; read-only, no recovery, never `null`→`teamStatus`. (FR-9) | `index.ts` | counts surfaced on start; no mutation; corrupt ⇒ fail-closed warn |
| 14 | | Assert wiring subscribes ONLY to `session_start` + registers the command (no invented event); worktree lock behavior unchanged post-extraction. (AC-7) | `tests/pi-runtime/team-commands.test.mjs` | no-invented-event + no worktree regression |
| 15 | [P] | Docs + honesty: `adapters/pi/docs/team-coordination.md` (`/cct:team` + CLI, the `CCT_TEAM_*` identity contract + per-subcommand authz table, the gate, the two-file ledger at the PRIMARY root, the `degraded` boundary, pointer to `plane-shaping.md`); README link + launcher help/test. (FR-10) | `adapters/pi/docs/*`, `bin/pi-code`, `tests/test-pi-launcher.sh` | doc states identity/authz + degraded boundary; help lists commands; launcher test green |

**Checkpoint US3** — teams honestly documented (local slice, declared-identity /
attribution-aware, degraded), surfaced at session start, and discoverable.

---

## Global definition of done (every task)

`build` + `typecheck` (strict) + Pi runtime suite + launcher suite green ·
team libraries & safety model unchanged (wiring only; lock extraction additive +
behavior-preserving) · ONE canonical ledger via `resolveTeamRoot` **fail-closed**
(no `?? cwd`) · actor from **declared** `CCT_TEAM_*` (both ids mandatory;
attribution, honestly NOT authentication) · declared `teamId` validated against
`ledger.teamId` (team binding) · authz re-validated **inside the lock per
mutation** (active actor; lead-only set; join/task any-active-member; never
cached) · sole active lead can't strand the team · create never
overwrites existing/corrupt (bootstrap lead = declared member) · single-claimant /
approval / bounded / close-while-claimed fail-closed + lock-serialized · every
action audited · CLI gate never misreports project-only opt-in · team ledger
separate from the worktree ledger · `agents.teams` capability unchanged · no new
Pi event · targets **#185**, does NOT close epic **#174**.

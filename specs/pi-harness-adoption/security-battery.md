# Security Battery — coverage manifest (T11.5, spec DoD §18.5 / items 10–12)

Audit map: every security category, DoD-11 vector, and DoD-12 cross-adapter item
→ the concrete test(s) that prove it. The battery is **consolidation**: the
executable tripwire (`tests/pi-runtime/security-battery.test.mjs`) asserts one
canonical fail-closed invariant per category over the SAME real functions the
deep suites exercise; this manifest points at where the depth lives.

## The eight categories → tripwire + depth

| Category | Battery tripwire | Deep coverage |
|---|---|---|
| trust gating (FR-004a) | `security-battery` #1 | `config.test.mjs` (trust gating), `session-recovery.test.mjs` |
| protected paths | `security-battery` #2 | `enforcement.test.mjs` (traversal/symlink), `fuzz.test.mjs` |
| command denial | `security-battery` #3 | `protected-ops.test.mjs`, `fuzz.test.mjs` (chaining/priv-prefix) |
| sandbox fail-closed | `security-battery` #4 | `sandbox.test.mjs` |
| secret redaction | `security-battery` #5 | `memory.test.mjs`, `worker-analytics.test.mjs`, `team.test.mjs` |
| lifecycle hook honesty | `security-battery` #6 | `hooks.test.mjs`, `fuzz.test.mjs` |
| tamper-safe ledgers | `security-battery` #7 | `team.test.mjs` (reconcile), `worktree-planners.test.mjs` |
| fail-closed team/worktree | `security-battery` #8 | `team.test.mjs`, `worktree-git.test.mjs` |
| (honesty boundary) | `security-battery` #9 | the capability registry + its drift guard |
| env scrubbing at spawn boundaries (#173) | `security-battery` #10 | `env-scrub.test.mjs` (policy + trust asymmetry), `child-session.test.mjs` (real spawn), `tests/test-pi-launcher.sh` (worktree-run handoff, opt-out scopes) |

## DoD item 11 — security vectors → tests

| Vector | Covered by |
|---|---|
| path traversal | `enforcement.test.mjs` "traversal and symlinks cannot bypass"; `security-battery` #2 |
| symlinks | `enforcement.test.mjs` (symlink canonicalization); `worktree-git.test.mjs` (symlink-escape) |
| shell-wrapper bypass | `fuzz.test.mjs` (priv/env prefixes, chaining); `protected-ops.test.mjs` (`stripPrivilegePrefix`); `security-battery` #3 |
| injection via docs/tool output | `checkpoint.test.mjs` "a tampered checkpoint is sanitized before it can reach context"; memory/message redaction (`memory.test.mjs`, `team.test.mjs`) |
| package substitution | `protected-ops.test.mjs` (package-install classification); `fuzz.test.mjs` |
| **fork bombs** | **degraded, not parity** — see below |
| worktree cross-contamination | `worktree-git.test.mjs` (ownership conflict refusal, isolation, foreign-worktree protection) |
| analytics secret leakage | `worker-analytics.test.mjs` (redacted correlation), `team.test.mjs` (redacted messages) |
| host credentials leaking into sub-sessions | `security-battery` #10; `child-session.test.mjs` (scrubbed spawn); `test-pi-launcher.sh` (scrubbed handoff; repo-local opt-out ignored) |

## DoD item 12 — cross-adapter contract → tests (shared semantics only)

| Contract item | Covered by |
|---|---|
| capability SET agreement (Pi ≡ Claude ≡ catalog) | `cross-adapter-contract.test.mjs` #3; `validate-capabilities.sh` (every catalog id classified by every adapter) |
| phase order | `cross-adapter-contract.test.mjs` #1 (`PHASE_ORDER`) |
| gate/permission decision semantics | `cross-adapter-contract.test.mjs` #2 (deny precedence); `enforcement.test.mjs` |
| SDD classification / artifacts | `test-pi-adapter.sh` (`sdd-cross-adapter/` + `sdd-parity/` fixtures) |
| verification outcomes | `verify.test.mjs` (supported/degraded/unsupported gate) |
| analytics semantics (neutral format) | `session_analytics/tests/test_adapter_pi.py` (T11.1 neutral `RawSession`) |
| review artifact formats / provider dispatch | `peer-reviewer-enforcement.test.mjs`, `review.test.mjs` |

**Native features are NOT forced to parity.** Where the registry marks a
divergence (e.g. `agents.subagents` = Claude `native/enabled`, Pi `degraded`),
`cross-adapter-contract.test.mjs` #4 asserts that divergence is intentional and
honest, not a contract violation.

## DoD item 10 — bounded/isolated agents

| Requirement | Covered by |
|---|---|
| worktree isolation + ownership + caps | `worktree-git.test.mjs`, `agent-caps.test.mjs` |
| team single-claimant + bounded concurrency | `team.test.mjs` |
| autonomous/CI require an isolation policy | `sandbox.test.mjs` (autonomous + host-unrestricted blocked) |

## Degraded, not parity (intentional — asserted via the registry, never faked)

These surfaces Pi deliberately does NOT implement. The battery does not test a
behavior that does not exist; instead `security-battery` #9 asserts each is
reported honestly (never `enabled`) in the capability registry.

| Surface | Why degraded | Honest registry status |
|---|---|---|
| **fork-bomb / resource-exhaustion containment** | Pi cannot itself create a sandbox — containment is an OS/sandbox concern | `security.sandbox` = `degraded` |
| live UI / status transport | no Pi UI event stream — snapshot only | `agents.teams` = `degraded` |
| live peer execution / message transport | runners spawn separately; messaging is a polled append-log | `agents.teams` = `degraded` |
| Stop / compaction lifecycle events | none observable in Pi | `verification.enforcement`, `memory.session-state` = `degraded` |

## What this task did NOT change

T11.5 added **tests + this manifest only** — no new enforcement, no changed
semantics. Every battery assertion imports an existing function; every "gap"
closed was a missing test, not a missing behavior.

## #173 closure mapping (pi-sandbox-hardening)

Issue #173's three asks → delivery, honestly bounded:

| #173 ask | Delivered by |
|---|---|
| 1. Backend integration (evaluate/choose isolation wrapper) | T10.1 `policy/sandbox.ts` (SandboxProvider, docker + env-declaration backends, fail-closed `sandboxGate`) + T10.4 `sandbox-backends-eval.md` (explicit-declaration recommendation; no blind detectors) |
| 2. Env-var scrubbing before exposing the shell to the subagent | `policy/env-scrub.ts` + the scrubbed `runChildSession` spawn + the scrubbed `worktree run` handoff (`pi-code env scrub-list`, fail-closed), `security.env-scrub` capability (Pi degraded), battery #10 |
| 3. Execution battery runs cleanly in CI | this battery + `cross-adapter-contract.test.mjs`, executed by `pi-tests.yml` behind an anti-skip guard |

Containment (#173 AC-1) remains **degraded by construction**: the operator's
sandbox contains; Pi detects, gates fail-closed, and never fabricates a
sandbox (`security.sandbox` degraded). The primary interactive session's env
is not scrubbed (it is the user's own shell) — `security.env-scrub` is
reported degraded for exactly that boundary.

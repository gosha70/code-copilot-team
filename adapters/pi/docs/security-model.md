# Pi Security Model

What the Pi harness enforces, how it fails closed, and — just as important —
what it **deliberately does not** do. This page is a reader's guide; the
authoritative sources are:

- the **security battery** — [`../../../specs/pi-harness-adoption/security-battery.md`](../../../specs/pi-harness-adoption/security-battery.md)
  (maps every guarantee to a concrete test),
- the **capability registry / matrix** — [`../../../shared/capabilities/COMPATIBILITY.md`](../../../shared/capabilities/COMPATIBILITY.md)
  (per-capability honest status),
- the **lessons learned** — [`../../../specs/pi-harness-adoption/lessons-learned.md`](../../../specs/pi-harness-adoption/lessons-learned.md).

## Principles

- **Fail closed.** When a security-relevant decision is ambiguous or a required
  precondition is absent, the harness refuses. Unknown trust → untrusted; an
  unresolved required gate → block; a required sandbox that is absent → block.
- **Honest, not faked.** A capability that Pi cannot fully deliver is reported
  `degraded`/`unsupported`, never a fake pass. The battery asserts the degraded
  surfaces are **never** reported `enabled`.
- **Monotonic floor (P7).** Project config may strengthen the security floor,
  never weaken it; relaxations are rejected and recorded.

## What is enforced

| Guarantee | Mechanism | Battery |
|---|---|---|
| **Trust gating** (FR-004a) | project + project-local config read only when positively trusted | #1 |
| **Protected paths** | canonicalized path matching — traversal + symlinks cannot bypass | #2 |
| **Command denial** | classifier survives shell wrappers / privilege prefixes / chaining | #3 |
| **Sandbox fail-closed** | `autonomous`/`ci` reject unrestricted-host execution absent an override | #4 |
| **Secret redaction** | secret-value detection refuses/`[REDACTED]`s memory, analytics, messages | #5 |
| **Lifecycle-hook honesty** | events Pi can't observe report `unsupported`, never a fake pass | #6 |
| **Tamper-safe ledgers** | `.cct/*.json` reconciled to the live invariants on load, not just sanitized | #7 |
| **Fail-closed team/worktree** | single-claimant claiming, ownership-overlap refusal, foreign-worktree protection | #8 |
| **Env scrubbing at spawn boundaries** (#173) | credential-shaped names removed before a subagent spawn and the `worktree run` handoff (names matched, values never read); fail-closed if the scrub list cannot be computed; in-repo config can tighten but never loosen | #10 |

The **permission engine** is allow/ask/deny with `deny` precedence and a
deterministic headless `ask` resolution (no TTY → configured resolution, default
deny). Protected paths and denied commands compose on top.

## What is intentionally degraded (not faked)

Pi lacks some primitives; the harness is explicit about it rather than
pretending. Each is reported honestly in the registry (`#9` asserts they are
never `enabled`):

| Surface | Why | Registry status |
|---|---|---|
| **fork-bomb / resource-exhaustion containment** | Pi cannot itself create a sandbox — this is an OS/sandbox concern | `security.sandbox` degraded |
| **live UI / status transport** | no Pi UI event stream — status is an on-demand snapshot | `agents.teams` degraded |
| **live peer execution / message transport** | teammates run via separate runners; messaging is a polled append-log | `agents.teams` degraded |
| **Stop / compaction lifecycle events** | none observable in Pi — gates fire at explicit CCT actions | `verification.enforcement`, `memory.session-state` degraded |
| **primary-session env scrubbing** | the interactive session's env is the user's own shell; only CCT-controlled spawn boundaries are scrubbed | `security.env-scrub` degraded |

The sandbox capability **detects and rejects**; it does not create a sandbox. To
actually contain untrusted execution, run under a container / micro-VM / remote
sandbox and declare it (`CCT_SANDBOX=...`), or set an explicit, audited override.

### Environment scrubbing (#173)

CCT-controlled spawns do not inherit the raw host environment. A NAME-based
policy (`policy/env-scrub.ts`) removes credential-shaped variables (`AWS_*`,
`GITHUB_TOKEN`, `*_TOKEN`, `*_SECRET`, `*_KEY`, `*_PAT`, `PGPASSWORD`,
`SSH_AUTH_SOCK`, ...) while keeping OS baselines, the `CCT_*` contract, and
the LLM provider credentials a child pi needs (`ANTHROPIC_API_KEY`,
`ANTHROPIC_AUTH_TOKEN`, `OPENAI_API_KEY`, `PI_API_KEY`, AWS region/profile
selectors). Values are never read, logged, or persisted — removed NAMES are
reported (`ChildResult.scrubbedEnv`; the `env.scrub` audit at a worker's
session start).

Two boundaries are scrubbed; one is deliberately not:

- **Subagent child sessions** — `runChildSession` scrubs by default
  (fail-safe ON even if a caller passes no config).
- **`pi-code worktree run` handoff** — the launcher resolves the list via
  `pi-code env scrub-list` (single TS pattern source) BEFORE provisioning
  and refuses the handoff if it cannot (never a silent unscrubbed launch, no
  git side effects on refusal). Removal happens by exec'ing through
  `/usr/bin/env -u <name> ...`, which also covers names bash `unset` cannot
  touch (e.g. `my-app_TOKEN`). The removed names ride in `CCT_ENV_SCRUBBED`
  — or, when a user-controlled scope disabled scrubbing, the disabling layer
  rides in `CCT_ENV_SCRUB_OFF` — and the worker's session start audits an
  `env.scrub` record either way (`scrubbed` with count+names, or `disabled`
  with the layer). An unscrubbed handoff is never silent.
- **The primary interactive session is NOT scrubbed** — that env is the
  user's own shell, not a CCT spawn; reported `degraded`, not hidden.

The `CCT_*` runtime contract survives scrubbing — with one deliberate
exception: the **`CCT_CONFIG__*` env-config carrier namespace is scrubbed
wholesale** at spawn boundaries. That layer is sanctioned to carry arbitrary
config values, including secrets (`CCT_CONFIG__providers__api_key=...`), and
a name-shape rule cannot recognize every secret-bearing config key — so none
of them cross the boundary. Children resolve their own configuration from
files; a specific carrier var can be restored only by naming it EXACTLY in
`security.env_scrub_keep` from a trusted scope (prefix keeps never apply to
the namespace).

Configuration is trust-asymmetric (`security.env_scrub`,
`security.env_scrub_keep`, `security.env_scrub_extra`): **both** in-repo
layers (`config.toml`, `config.local.toml`) may only tighten; turning
scrubbing off or adding keeps requires a user-controlled scope (global
config, `CCT_CONFIG__*` env, `--set`), and a later user-controlled setting
always beats an earlier repo one. A repo you cloned can therefore never
silently re-expose your credentials to its sub-sessions. A custom
`providers.*.api_key_env` credential name is not auto-kept — add it via
`security.env_scrub_keep` in your global config.

## Data handling

- **Redaction before persistence** — memory promotion refuses secret-bearing
  facts; worker-analytics and team messages are redacted at emit; the analytics
  pipeline re-redacts before the store. No new pattern set is introduced per
  surface — a single shared redaction path is reused.
- **Provenance is a hard boundary** — a worktree the harness did not create
  (`origin:"cct"`) is never removed; a tampered ledger cannot flip that.

## Verifying the posture yourself

```sh
bash tests/test-pi-runtime.sh        # includes the security battery
node --test tests/pi-runtime/security-battery.test.mjs
node --test tests/pi-runtime/cross-adapter-contract.test.mjs
pi-code features                     # the live capability report
```

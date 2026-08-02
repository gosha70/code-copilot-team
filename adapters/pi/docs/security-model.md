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

The sandbox capability **detects and rejects**; it does not create a sandbox. To
actually contain untrusted execution, run under a container / micro-VM / remote
sandbox and declare it (`CCT_SANDBOX=...`), or set an explicit, audited override.

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

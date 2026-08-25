# Origin Alignment Check — routing-recovery

Date: 2026-08-24 09:00 (record opened)
Last revised: 2026-08-25 — follow-up implementation review completed
the explain, wake handoff, child capability, parser, and cap-scheduling
boundaries described in the build audit below; scope remains increment D
Trigger: rev-1 SDD bundle authored for increment D of #109 at the
owner's direction ("The strongest next increment is D … my
recommended order is: 1. D — probes/recovery/failback"), immediately
after increment C (#254) merged via PR #256. The child issue is filed
on plan-review GO; until then the origin anchors on the umbrella.

## Origin sources read

- #109 §Delivery Plan Increment D (probe execution; failback at task
  boundaries; scheduled recovery; recovery-aware selection), §8 (the
  seven-state vocabulary, the persisted schedule shape, the
  four-source timing precedence, the real-canary contract —
  "/v1/models, --version, or a TCP connection alone is insufficient"
  — and the six-point failback policy), §9 (the idempotent
  cron-compatible tick contract, its seven steps, and the
  generators-optional note), Scenario 7, Acceptance §Recovery (all
  seven checkboxes).
- The owner's sequencing directive (2026-08-24): D before the codex
  adapter before E — D closes operational-control gaps in the
  runtime that now exists; E then evaluates a complete runtime.
- specs/routing-tier1-failover/ — B's frozen store/actions/selector/
  supervisor contracts; B's decay journal line was explicitly left as
  D's hook, and B's plan reserved operator probes for D.
- specs/routing-tier2-delegation/ — C's reconciliation flow (FR-D7
  consumes it unchanged) and the promotion discipline
  (refused→implemented→behaviorally-tested) the recovery/policy keys
  follow; C's deferred-scope record names reconcile-on-recovery as
  D's.
- scripts/lib/routing-state.sh, routing-select.sh,
  cooldown-supervisor.sh, routing-cli.sh — the seams D extends;
  increment A's RC_POLICY_FUTURE_KEYS (the three keys promoting, the
  one staying refused).

## Working claim

Increment D = the umbrella's recovery bullets on A+B+C's frozen
contracts: probe-verified health (real inference + tool canaries,
honest unverifiability), four-source recovery timing with named
backoff defaults, hysteresis-guarded boundary-only failback enforcing
the promoted preferred_profile and policy keys, the idempotent
`routing tick --due --once` with explicit lock-guarded wake, the sole
operator exit from auth-disabled, reconciliation-on-recovery, and the
`recovery` repo restriction — completing Scenario 7 and the
Acceptance §Recovery checklist.

## Mismatches / deviations from the origin sketch

- **launchd/systemd generators deferred** (§9 calls them optional):
  the cron-compatible `--once` command is the portable contract;
  generators can follow without contract changes.
- **`degraded` is round-tripped but not yet emitted**: §8's state
  list includes it; D freezes it in the closed vocabulary and the
  store, but no D path grades a partial canary as degraded (failing
  the tool canary is a FAILED probe). Emitting it is a visible
  follow-on, never a silent semantic.
- **`max_switches_per_task` stays refused** — the umbrella's
  policy sketch lists it, but no increment owns its behavior yet;
  the a-key-nothing-enforces rule keeps it refused.
- **Wake resumes only unattended `routing_no_eligible_profile`
  parks** with ledger-recorded relaunch arguments; attended parks
  and other terminal states need an operator (narrower than "safely
  wake runs parked", deliberately — wake never reinterprets a
  disposition).
- **Probe reality in tests**: probes execute through a test seam
  (`CCT_ROUTING_PROBE_CMD`) like B's harness seam; the real
  claude-code/pi canary paths are exercised for executability, not
  against live providers. The real-canary CONTRACT (inference + tool
  call; connectivity checks insufficient) is what the suite pins.

## Plan review round 1 (owner) — HOLD, three amendments, then GO

Judgment calls: hysteresis-at-consumption APPROVED (with the dwell
pin: it gates the CURRENT ACTIVE profile's tenure as well as the
preferred profile's health age); crash-visible `probing` AMENDED;
narrow wake APPROVED with the replay amendment; both-layer
promotions APPROVED (explicit-null boolean reads a standing
constraint — no third `// true` incident). Amendments applied to
plan/spec/tasks, all execution-contract:

1. **Abandoned probing is absence of evidence, never provider
   evidence**: an overdue `probing` marker reads as `unknown` +
   `routing_probe_abandoned`, reschedules via backoff, touches no
   failure/success counter, and can never produce `healthy` — a
   supervisor crash is never attributed to the provider (`probe_fail`
   now means actual negative canary evidence only). The seven-state
   transition matrix is closed and executable, with
   verified-canary-success as the sole edge into `healthy`.
2. **Probes join the spend/taint boundaries**: the frozen invocation
   ordering (existing accounting debit/estimate — launched probes
   are accounted even on malformed/timeout/crash results → bounded
   launch with pre-launch caps yielding `probe_deferred_caps`, never
   a bypass → B's secret-taint scrub before persistence →
   classification → transition); no cost-file capability in the
   probe child; credential values child-env only; the
   credential-echo and malformed-evidence-still-costed cases pinned.
3. **Wake is an idempotent CLOSED RECONSTRUCTION** (amended during
   T3 — see below): the supervisor records run IDENTITY, never a
   command; wake rebuilds the invocation from a fixed flag list with
   the executable from its own installation, re-validating every
   ledger value; it revalidates disposition/mode/restriction/locks/
   root, requires a probe-qualified candidate, and claims a per-park
   wake GENERATION atomically before launch — replays of a claimed
   generation are journaled no-ops; an unacknowledged launch releases
   the claim retryably; a live run lock always refuses.

## Amendment during build (T3 review round 2)

The owner's T3 review established that the originally approved
"verbatim argv replay" stores an execution capability in a file the
supervisor itself treats as untrusted, and reproduced arbitrary
command execution from a forged ledger. Plan **Amendment A1** replaces
it with closed reconstruction, and the spec/tasks were amended to
match before any T3 code was committed.

This does not change what the ORIGIN asked for. The origin (issue #257
and the user's sequencing message) asks for probe-verified recovery
with bounded, operator-controlled relaunch — "Tier-2 is delegated
bounded work, not another unrestricted failover target", and D
"closes the remaining operational-control gaps". Verbatim replay was
a MECHANISM chosen to serve that intent; closed reconstruction serves
the same intent strictly more tightly (it can launch everything the
replay could launch legitimately, and nothing it could be tricked
into). The amendment narrows mechanism, not scope.

Rounds 5–6 corrected the wake boundary under plan Amendment A4.
`routing.recovery` remains restriction-only and contains only the two
vetoes `wake_enabled` and `auto_failback_enabled`; the abandoned
repository-owned `wake_caps` mechanism was not aligned with FR-D8 and
is removed. Explicit `--wake` reconstructs only this installation's
code-owned default invocation; non-default grants are refused for
manual resume because the mutable ledger is evidence, not authority.
The same amendment tightens probe
boundaries: atomic cap+reservation using current spend plus the pending
estimate, infrastructure/accounting failures kept distinct from cap
deferrals, no accounting capability in the child, mechanism validated
before spend, interrupted ticks reaped, and acknowledgement after full
routing admission.

Round 4 added four more, under plan Amendment A3: the declared probe
time bound is now ENFORCED through the repo's proven bounded runner (a
hanging provider could otherwise hang `tick`, which would stop every
profile from ever recovering); the wake acknowledgement
moved after every fail-closed startup check, so a run that refuses for
a corrupt ledger or a terminated policy stays retryable; and probe
accounting is serialised, because T3 releases the state lock before
probing and an unserialised debit dropped rows. All four narrow what
an automatic wake or probe may do.

Round 3 added five further narrowings under plan Amendment A2. Its
initial exact-cap-replay rule is superseded by A3/A4's code-owned-
defaults-only rule; the remaining current decisions are:
bounded-work modes (`--delegate`/`--reconcile`) are refused by name
rather than auto-woken; persisted caps are closed and type-checked as
evidence before the default-only authority check; the launch
acknowledgement is a durable
`acked` generation released only through a locked CAS; fallback
marking requires a live run lock; and wake/failback outcomes are
persisted as closed named events. All five reduce what an automatic
wake may do — none widen scope.

Also recorded, both narrowings rather than additions:
`routing.recovery.wake_enabled` is promoted in T3 rather than T5
(behaviour and key must ship together), and a routed supervisor now
refuses a second run over one ledger, taking its run lock before the
ledger is read or created.

## Build completion audit (2026-08-24)

The 2026-08-25 direct implementation review closed ten concrete
runtime and observability gaps without widening increment D. Probe
health now requires a run-specific value in the parsed backend result;
prompt/transcript/stderr echoes are not evidence. A live supervisor
drives due probes through the same globally locked tick path when a
recovery marker is its only selection blocker, so optional timer
generators are no longer an undeclared runtime prerequisite. Tick
discovers registered-worktree ledgers by default and documents an
explicit shared ledger root. The remaining fixes preserve profile
tenure in all launch modes, isolate reconcile-on-recovery artifacts,
advance unverifiable scheduling backoff without inventing provider
failure, remove private probe directories, keep malformed cost text on
the estimate path, render effective state, and update the promoted-key
template caption. These are corrections to the existing D contract,
not new routing authority or origin scope.

The follow-up review closed nine regressions introduced by that audit:
`explain` again loads and renders effective circuit state; a wake passes
the exact validated registry and ledger root to its child; probe routing
paths are rebound to a private tree instead of unset into production
`$HOME` defaults; credentials are delivered only through child env and
stay out of argv; structured result and measured-cost records survive
non-JSON notices; surrounding response whitespace is normalized; and
cap deferrals advance scheduling backoff without inventing provider
failure. These are implementation corrections to the same D decisions,
not new authority or scope.

The final direct implementation review removed the last inferred
authority path: automatic wake reconstructs only this installation's
code-owned default supervisor invocation. The ledger supplies bounded
identity and evidence; repository configuration supplies only the two
vetoes. Non-default caps or `on-incomplete` remain operator-resumed.

The same audit made every new unattended lock path fail closed on an
existing lock, including one recording a dead PID. PID liveness followed
by deletion can remove a replacement lock acquired between those
operations; tick, probe accounting, wake, and direct supervisor startup
therefore preserve the path and require explicit operator recovery.
The older increment-B state lock retains its already-published stale-
takeover contract; this change is limited to D's new scheduler and run
locks.

The completed D regression suite is 375/375. It includes a concurrent
auth-disable regression proving that a rejected stale transition is
journalled without preventing the durable attempt checkpoint. A
combined isolated
mutation of recovery-state selection, pending-estimate cap admission,
measured-cost publication, default-only wake authority, and dead-run-
lock refusal produced 15 failures. Adjacent routing, config, structure,
generation, and policy/spec gates are green; the local UI-harness suite
skips because `tsx` is unavailable and is unrelated to D.

## Verdict

Verdict: aligned
Confidence: high

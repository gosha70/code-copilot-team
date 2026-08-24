# Origin Alignment Check — routing-recovery

Date: 2026-08-24 09:00 (record opened)
Last revised: 2026-08-24 — plan review round 1 (owner): three
runtime-contract amendments applied (see below); GO granted;
child issue #257 filed and stamped into plan.md frontmatter
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
3. **Wake is an idempotent argv replay**: the supervisor records a
   structured JSON argv vector (never a shell string); wake replays
   it verbatim (no eval/sh -c/reconstruction), revalidates
   disposition/mode/restriction/locks/root, and claims a per-park
   wake GENERATION atomically before launch — replays of a claimed
   generation are journaled no-ops; pre-exec launch failure releases
   the claim retryably; a live run lock always refuses.

## Verdict

Verdict: aligned
Confidence: high

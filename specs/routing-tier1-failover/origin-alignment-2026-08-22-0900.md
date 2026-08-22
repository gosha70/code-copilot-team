# Origin Alignment Check — routing-tier1-failover

Date: 2026-08-22 09:00 (record opened)
Trigger: rev-1 SDD bundle authored for increment B (#251) of #109 at the
owner's direction ("Yes proceed to this increment"), immediately after
increment A (#248) merged via PR #250.

## Origin sources read

- #109 §Delivery Plan Increment B (the five deliverable bullets), §4
  (backend-neutral packet: no session/conversation reuse, driver owns
  git), §5 (deterministic selection + journaled reasons), §6 (the
  classification→router-behavior table B now enacts), §8 (provider
  state vocabulary and persistence — B takes the non-probe subset),
  §10 (builder identity + reviewer independence), Scenarios 1–4 and
  8–10, Backward Compatibility (cooldown-supervisor keeps its current
  behavior as a compatibility mode).
- specs/routing-profile-foundation/ — increment A's frozen surfaces
  (registry, merge/tuples, taxonomy/classifier, state-file read side)
  consumed unchanged.
- scripts/cooldown-supervisor.sh — the seam: single-backend loop,
  coarse USAGE_PATTERN classification, cooldown+relaunch of the same
  backend, feature lock, caps.
- scripts/auto-build-loop.sh backend surface (claude|pi) and
  scripts/benchmark_runner/backends/codex.py (verified codex exec
  knowledge; decision-7 deferral).

## Working claim

Increment B = the umbrella's "Tier-1 failover" bullets on A's frozen
contracts: cause-driven action at the supervisor seam, circuit and
quota-pool state with crash-safe persistence, durable backend-neutral
checkpoints, deterministic journaled Tier-1 selection, cross-provider
and cross-backend continuation, and true builder identity into review
and analytics with independence re-evaluated. This is the increment
that delivers the owner's token-optimization motivation.

## Mismatches / deviations from the origin sketch

- **The codex leg of the B scenario is deferred to its own child
  increment** (plan decision 7). The umbrella's acceptance scenario
  names Claude→DeepSeek→Codex; B proves cross-PROVIDER failover with
  DeepSeek-style endpoint profiles and cross-BACKEND handoff with the
  already-first-class pi backend. A codex EXECUTION adapter for the
  driver (launch/result/review/cost wiring) is genuinely new surface
  beyond "failover machinery" and is proposed as a follow-on child
  issue reusing the benchmark's verified invocation knowledge.
  Deviation flagged for explicit review, not absorbed.
- **B's bounded unit is the supervised attempt, not a task packet**
  (plan decision 2). §4's task packets presuppose §3's task route
  metadata, which the umbrella assigns to increment C. B makes the
  attempt durable and backend-neutral; C refines granularity.
- **Recovery is time-based only** (plan decision 4). §8's
  probe/canary gating belongs to increment D; B decays cooled state
  to `unknown` (never `healthy`) at expiry and journals the decay as
  D's hook, so B never claims probe-verified health it cannot have.

## Plan review round 1 (owner) — approved with three amendments

All three deviations approved (codex deferral — with D7 now stating
B makes NO codex-support claim and requiring the codex child
increment to reuse B's normalized attempt/result/checkpoint contracts;
attempt-as-unit; time-only recovery decaying to unknown, never
healthy). Three required amendments, applied before filing:

1. **The cause→action table is TOTAL** (decision 3): all nine causes
   freeze scope / durable state / same-profile retry budget /
   next-selection / re-eligibility / terminal reason, including the
   missing-metadata branches (absent or malformed reset_at → named
   conservative default, journaled). Pins: rate_limited = exactly one
   same-profile retry per supervised attempt; request-local causes
   stay request-local (invalid_request writes no durable state;
   execution never reads as provider health).
2. **Crash/restart semantics frozen** (decision 5): persist
   attempt-started → one fresh child → persist terminal result →
   idempotent (attempt-id-keyed) circuit action → next-selection
   checkpoint. Attempt-started without a terminal result is
   INDETERMINATE: never replayed, never treated as failed —
   `routing_attempt_indeterminate` park/terminate.
3. **Model verification is tri-state** (decision 6): verified match /
   fail-closed named mismatch (`routing_model_identity_mismatch`,
   never rerouted around) / explicitly-unverified null. Per-adapter
   executability stated (claude-code verifiable; pi always
   unverified); requested and effective retained separately
   everywhere; no registry change (any future require-verified knob
   takes the refused→implemented→tested promotion path).

Also pinned: T1's pre-commit mutation floor (atomic RMW,
crash-indeterminate recovery, stale/partial-state refusal) before T2
builds on the store; the no-independent-reviewer outcome fails closed;
tier1-only boundary and providers.toml read-only reaffirmed.

## Verdict

Verdict: aligned
Confidence: high

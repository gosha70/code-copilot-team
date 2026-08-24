---
spec_mode: full
feature_id: routing-recovery
status: approved
date: 2026-08-24
risk_category: integration
justification: >
  Adds the first WRITE paths outside a supervised run (probe results,
  tick, operator re-enable) to circuit state that live supervisors
  read concurrently, plus a failback seam inside the supervision loop
  and a scheduler-facing CLI verb — integration risk across the state
  store's locking, the supervisor's boundary logic, and C's
  reconciliation flow.
origin:
  type: issue
  issue: 257
  parent: 109
  references:
    - "#109 §Delivery Plan Increment D — probe execution; failback at task boundaries; scheduled recovery command; recovery-aware selection"
    - "#109 §8 (provider state/recovery/failback: states, persisted schedule, timing precedence, real-canary contract, failback policy), §9 (scheduled recovery: the idempotent tick contract), Scenario 7, Acceptance §Recovery"
    - "specs/routing-tier1-failover/ — B's frozen store/actions/selector/supervisor contracts; B's decay-to-unknown journal line is the hook D consumes"
    - "specs/routing-tier2-delegation/ — C's reconciliation flow FR-D7 invokes; the promotion discipline the recovery/policy keys follow"
    - "scripts/lib/routing-state.sh, scripts/lib/routing-select.sh, scripts/cooldown-supervisor.sh, scripts/routing-cli.sh — the seams this increment extends"
  origin_claim: |
    #109 increment D: give every degraded routing state a VERIFIED
    exit — probe-verified recovery (never time-assumed health),
    hysteresis-guarded failback at task boundaries with the preferred
    profile enforced, a cron-idempotent `routing tick`, explicit
    operator re-enable of auth-disabled profiles, and
    reconciliation-on-recovery for outstanding provisional work.
---

# Plan: Probe-verified recovery + failback — increment D of #109

`spec.md` states the requirements; THIS file's decisions are the
normative implementation contract. A/B/C surfaces are consumed frozen
— where D extends the state vocabulary, the CLI, or the policy keys
it does so visibly with its own regressions.

## Decisions

1. **State-store extension, same schema, closed vocabulary.**
   `routing-state.sh` keeps `schema_version: 1`; profile/pool entries
   gain `next_probe_at`, `consecutive_probe_successes`,
   `last_probe_at`, and `healthy_since` (all nullable; absent in
   pre-D stores — reads treat absence as null, writes are additive).
   The state set is CLOSED at `unknown | cooldown | disabled |
   healthy | degraded | probe_due | probing`. Frozen read rules:
   - eligibility (rs_effective_info): `healthy` and `unknown` are
     selectable exactly as B selects today (`unknown` keeps its
     never-treated-as-healthy journal); `degraded | probe_due |
     probing` are NOT selectable; `cooldown | disabled` unchanged.
     B's pool-outranks-profile, decay-to-`unknown`, and fail-closed
     read rules are untouched — the B suite passes unmodified.
   - `healthy` is VERIFIED-GOOD only within its dwell provenance
     (healthy_since + the promoted dwell key); a stale `healthy`
     decays to `unknown` like any cooldown expiry, journaled.
   - `probing` is a crash-visible in-flight marker, and an ABANDONED
     marker is ABSENCE of evidence, never provider evidence (review
     round 1): a tick that dies mid-probe leaves `probing` +
     `next_probe_at`; the next tick journals
     `routing_probe_abandoned`, sets the state to `unknown`,
     schedules a fresh probe via the recovery backoff, and touches NO
     failure streak or consecutive-success counter — a supervisor
     crash is never attributed to the provider, and abandonment can
     never produce `healthy` either.
   - The seven-state transition matrix is CLOSED and executable
     (T1): the ONLY transition into `healthy` is a verified canary
     success reaching the threshold; every other edge is enumerated
     and everything else refuses.

2. **The probe engine is a lib with honest per-backend canaries.**
   `scripts/lib/routing-probe.sh` (`rb_*`): `rb_probe <profile-json>`
   runs (a) a small REAL inference — claude-code backend: one
   bounded `claude -p` prompt through B's exact env wiring
   (endpoint/credential refs, child-env only, output scrubbed);
   pi backend: the pi one-shot equivalent — and (b) when the
   profile's tool_profile implies tools (closed map, currently
   full-cct and local-builder-minimal), a minimal tool canary (one
   trivial Bash tool invocation) in a throwaway directory. Outcomes
   are a CLOSED tri-state: `probe_pass | probe_fail |
   probe_unverifiable` (a backend/harness that cannot run a real
   canary is unverifiable — state stays `unknown`, never assumed).
   `probe_fail` means ACTUAL negative canary evidence, never
   absence of evidence. A tool-profiled builder passing inference
   but failing the tool canary is `probe_fail` (SC-D2).

   Probes are NEVER an unmetered execution channel (review round 1);
   the invocation ordering is FROZEN:
   1. accounting debit/estimate via the EXISTING mechanism — a probe
      that was actually launched is accounted for even if its result
      is malformed, times out, crashes, or is later rejected;
   2. bounded invocation (named timeout default; caps checked BEFORE
      launch — a cap that blocks a due probe yields the named
      non-health result `probe_deferred_caps`, never a cap bypass
      and never a transition toward health);
   3. output scrubbed with B's secret-taint discipline BEFORE any
      journal/persistence;
   4. result classification;
   5. state transition.
   The probe child receives credential VALUES in its environment
   only (B's wiring); it receives no cost-file or ledger
   capability; transcripts are scrubbed and journaled with cost
   evidence. The test seam is
   `CCT_ROUTING_PROBE_CMD` (a mock canary), mirroring B's harness
   seam — the REAL default paths are exercised by executability
   checks, not live providers.

3. **Timing precedence + named backoff defaults.**
   `rb_next_probe_at` derives from, in order: the durable reset
   evidence B already persists (provider reset_at, Retry-After);
   subscription `rate_limits.*.resets_at` when the transcript carries
   it; else bounded exponential backoff with jitter:
   `RD_BACKOFF_BASE_SEC` (default 60) doubling to
   `RD_BACKOFF_MAX_SEC` (default 3600), jitter ±`RD_JITTER_PCT`
   (default 20) derived DETERMINISTICALLY from a hash of
   profile-id + failure count (reproducible in tests; no wall-clock
   randomness). All RD_* are named implementation defaults journaled
   when applied — not configuration.

4. **`cct routing tick --due --once` — the one impure verb.**
   `validate | status | explain` stay pure; `tick` writes, and its
   help says so. Contract per run: acquire the global state lock
   (B's mkdir lock; a held lock refuses by name — no queueing);
   select profiles/pools whose `next_probe_at` is due; set `probing`;
   run the probe; apply the result atomically (pass →
   `consecutive_probe_successes`+1, threshold reached → `healthy` +
   `healthy_since`; fail → reset successes, backoff reschedule);
   journal every transition. Idempotency: a second immediate run
   finds nothing due — proven as a byte-level state no-op.
   Wake is EXPLICITLY opt-in (`--wake`) and is an IDEMPOTENT ARGV
   REPLAY, never a shell string (review round 1). A routed
   supervisor records its exact argv as a STRUCTURED JSON ARRAY in
   the ledger at startup (additive field; unrouted ledgers
   unchanged); wake replays that vector verbatim — no `eval`, no
   `sh -c`, no quoting reconstruction, no inference from current
   configuration. Before launching, wake REVALIDATES: recorded
   disposition == `routing_no_eligible_profile`; the run was
   unattended; repo `recovery.wake_enabled` is not false; no live
   run lock; the recorded worktree root still exists. Durable
   idempotency: each park carries a wake GENERATION; wake claims
   the generation atomically (under the global + run locks) BEFORE
   launch, and any replay of a claimed generation is a journaled
   no-op/refusal. A launch failing before exec journals
   `wake_launch_failed` and releases the claim atomically
   (retryable); a stale unconfirmed claim is retryable ONLY when no
   live run lock exists — a live lock always refuses, so a
   successfully-woken run can never be double-woken.

5. **Failback lives in the supervisor loop, boundary-only.**
   After every completed attempt (the task boundary — never inside
   one), a routed run evaluates: preferred profile (the registry's
   `preferred_profile`, promoted to enforced behavior) is `healthy`
   AND `consecutive_probe_successes >= healthy_probes_required` AND
   `now - healthy_since >= minimum_profile_dwell_sec` (dwell ALSO
   gates the CURRENT ACTIVE profile — a switch is refused until the
   active profile has been active at least the same dwell, so
   flapping is contained on both sides) AND the repo
   `recovery.auto_failback_enabled` is not false AND the promoted
   `[policy] failback` is `auto` → the attempted-set entry for the
   preferred profile is cleared and selection naturally prefers it
   (no new selection mechanism — the total order already ranks it);
   the switch is journaled `routing_failback`. With `failback =
   "operator"` or the repo restriction, the run stays on the
   fallback and journals why. Hysteresis is therefore enforced at
   the CONSUMPTION point, not inside the store.

6. **Operator re-enable.** `cct routing enable <profile-id>`:
   auth-disabled → `probe_due` (never straight to eligible),
   journaled as an operator action with the profile named; any other
   state refuses by name (nothing else needs enabling). The next
   tick probes it; only a passed probe reaches `healthy`.

7. **Reconcile-on-recovery.** At a failback boundary (decision 5
   firing), before the next build attempt the supervisor iterates
   pending `verified_provisional` ledger records and runs C's
   reconcile flow for each (same code path as `--reconcile`, bounded
   to ONE reconcile attempt per record per boundary). A reconcile
   refusal/park follows C's semantics and is journaled; it does not
   cancel the failback. With no pending records the boundary is a
   plain failback.

8. **Promotions, both config layers, the established path.**
   - Repo `routing.recovery`: CLOSED object
     `{auto_failback_enabled?: bool, wake_enabled?: bool}` —
     restriction-only (false restricts; true/absent restrict
     nothing); unknown keys refused; validator + schema + rc_effective
     (`auto_failback_allowed`, `wake_allowed` fields with the
     explicit-null discipline — never `// true`).
   - Registry `[policy]`: `healthy_probes_required` (int ≥ 1,
     default 2), `minimum_profile_dwell_sec` (int ≥ 0, default 300),
     `failback` (`auto | operator`, default `auto`) move from
     RC_POLICY_FUTURE_KEYS to validated keys with behavior; defaults
     are named constants when the key is absent.
     `max_switches_per_task` STAYS refused by name.

9. **Scope honesty.** D adds no new terminal reasons (parked runs
   still park per B/C); wake never bypasses caps — a woken supervisor
   re-enters with its own attempt/wall budgets. The probe engine
   never writes ledgers of supervised runs; ticks and supervisors
   share only the circuit store, under its lock.

## Deliberately NOT in this slice (flagged deviations)

- **launchd/systemd generators** (umbrella §9 "optional installation
  helpers"): the cron-compatible `--once` command is the portable
  contract; generators can follow without contract changes.
- **`degraded` remains a reserved state**: the closed vocabulary
  includes it (umbrella §8) and the store round-trips it, but no D
  path emits it yet (a partial-canary policy that grades rather than
  fails is future work); emitting it is a visible follow-on, never a
  silent semantic.
- **`max_switches_per_task` stays refused** — no owning increment.
- **Wake does not resume ATTENDED parks** — only unattended
  `routing_no_eligible_profile` parks with recorded relaunch
  arguments; anything else needs an operator.

## Sequence

T1 state-store extension + timing/backoff lib (closed states, read
   rules, deterministic jitter) ->
T2 probe engine (canaries, tri-state honesty, scrubbing, cost) ->
T3 tick (lock, due-selection, idempotency, --wake under locks) ->
T4 supervisor failback (boundary-only, hysteresis at consumption,
   policy-key promotions) ->
T5 operator enable + recovery repo-key promotion +
   reconcile-on-recovery ->
T6 docs + CHANGELOG + pins + full sweep + origin refresh + deferred
   record.
C cadence: per-task suites + isolated-worktree mutations + review
holds between tasks.

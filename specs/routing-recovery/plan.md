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
   - The D recovery transition matrix is CLOSED and executable: its
     ONLY edge into probe-qualified `healthy` is a verified canary
     success reaching the threshold. B's inherited `rs_mark_success`
     still records a genuinely successful full attempt as `healthy`
     for byte-compatible history, but it carries no probe streak or
     `healthy_since` and can trigger neither D wake nor failback.

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
   Positive inference evidence is a per-run nonce returned as the
   parsed backend result, exact after surrounding whitespace is
   normalized. The prompt, transcript, stderr, and user-message fields
   are never searched for it; an echo cannot mint health. A non-JSON
   notice line cannot suppress a valid structured result or measured
   cost. The private probe directory is removed on every ordinary
   return path.

   Probes are NEVER an unmetered execution channel (review round 1);
   the invocation ordering is FROZEN:
   1. accounting debit/estimate via the EXISTING mechanism — a probe
      that was actually launched is accounted for even if its result
      is malformed, times out, crashes, or is later rejected;
   2. bounded invocation (named timeout default; caps checked BEFORE
      launch — a cap that blocks a due probe yields the named
      non-health result `probe_deferred_caps`, never a cap bypass
      and never a transition toward health; repeated cap deferrals
      advance scheduling backoff without changing provider evidence);
   3. output scrubbed with B's secret-taint discipline BEFORE any
      journal/persistence;
   4. result classification;
   5. state transition.
   The probe child receives credential VALUES in its environment
   only (B's wiring), never in process argv. Active accounting, state,
   registry, supervisor, and routing-artifact paths are rebound to a
   private per-probe tree, so libraries sourced by the child cannot
   fall back to the production files under `$HOME`; transcripts are
   scrubbed and journaled with cost evidence. This is capability
   hygiene, not an OS sandbox against a malicious same-user process
   that independently guesses host paths. The test seam is
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

4. **`cct routing tick --due --once` — the scheduled impure command.**
   `validate | status | explain` stay pure; scheduled `tick` and the
   explicit operator action `enable` write, and help says so. Contract
   per tick: acquire a dedicated global scheduler lock for the whole
   pass (held means named immediate refusal — no queueing), while B's
   short state lock still makes each publication atomic;
   select profiles/pools whose `next_probe_at` is due; set `probing`;
   run the probe; apply the result atomically (pass →
   `consecutive_probe_successes`+1, threshold reached → `healthy` +
   `healthy_since`; fail → reset successes, backoff reschedule);
   journal every transition. Idempotency: a second immediate run
   finds nothing due — proven as a byte-level state no-op.
   A live supervisor that reaches a selection boundary blocked only by
   due recovery markers invokes this same command without `--wake`,
   then reselects. Cron/launchd remains useful for parked-run wake and
   background failback, but is not a prerequisite for a live run to
   recover from its own cooldown. With no ledger-root override, the
   CLI discovers ledgers in this repository's registered worktrees;
   `--ledger-root` is documented and names an explicit shared root.
   The real wake launch exports the exact registry and ledger root that
   passed these checks; the child never re-resolves them from defaults.
   Wake is EXPLICITLY opt-in (`--wake`) and is an IDEMPOTENT
   CLOSED RECONSTRUCTION (T3 review round 2 — AMENDMENT, see
   below), never a shell string and never a ledger-supplied
   command. A routed supervisor records the STRUCTURED invocation in
   the ledger at startup (`routing_wake`: backend, profile, mode,
   on-incomplete, caps, generation, claim/ack — additive field;
   unrouted ledgers unchanged); wake rebuilds argv from a FIXED flag
   list, taking the
   executable from its own installation and re-validating every
   value it reads. Before launching, wake REVALIDATES: recorded
   disposition == `routing_no_eligible_profile` paired with the
   status an unattended refusal actually writes (`failed`); the run
   was unattended; repo `recovery.wake_enabled` is not false; no
   live run lock; the recorded worktree still OWNS this ledger; the
   backend is offered by a candidate in the run's own effective
   policy; both persisted cap views agree and contain exactly four
   non-negative integers; and at
   least one candidate is PROBE-QUALIFIED healthy — a wake is the
   consequence of recovery, not a retry timer. Durable
   idempotency: each park carries a wake GENERATION, minted in the
   SAME write as the park disposition; wake claims the generation
   atomically (under the run lock, same-directory rename) BEFORE
   launch, and any replay of a claimed generation is a journaled
   no-op/refusal. A launch that is never ACKNOWLEDGED (the child
   never takes the run lock and the ledger never moves) journals
   `wake_launch_failed` and releases the claim, leaving the park
   retryable
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
   the boundary target is set to preferred and fed through B's same
   selector (no second eligibility implementation);
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
   refusal/park follows C's semantics and is journaled; it parks the
   current boundary with the failback marker left retryable. With no
   pending records the boundary is a plain failback.

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

### Amendment A1 (T3 review round 2) — closed reconstruction replaces verbatim argv replay

Decision 4 originally specified that a routed supervisor record its
exact argv vector and that `--wake` replay that vector VERBATIM. The
T3 review established that this is an execution capability stored in
a file the supervisor itself treats as untrusted (`fail_corrupt`):
anything able to write a ledger could choose what the scheduler runs,
and a reviewer reproduced it. Avoiding `eval`/`sh -c` does not help —
a forged vector is arbitrary execution regardless of how carefully it
is tokenised.

The wake therefore reconstructs a CLOSED invocation instead:
`routing_argv` is gone; the ledger records identity only; the
executable comes from the tick's own installation; arguments come
from a fixed flag list; and every value is re-validated (closed
backend set additionally bound to the run's effective policy, integer
caps clamped to the supervisor's ceilings, worktree bound by
requiring it to own the ledger the tick found). This removes the
ledger-supplied-command capability. Amendments A3 and A4 narrow the
reconstructed authority further: automatic wake serves only the
code-owned default invocation, while non-default operator grants are
refused for manual resume.

Consequences recorded here so the SDD stays the source of truth:

- **The lossless-argv-encoding requirement is obsolete.** There is no
  free-form vector to encode, so the newline/quoting concerns it
  existed to address cannot arise.
- **`routing.recovery.wake_enabled` is promoted in T3, not T5.**
  Asserting wake policy while the key was still refused produced a
  test that passed for the wrong reason; the behaviour and its key
  must ship together.
- **A wake requires PROBE-QUALIFIED health**, not merely a candidate
  outside cooldown. `probe_due`, `probing`, `unknown` and `degraded`
  are all outside cooldown while being exactly the states
  `healthy_probes_required` exists to distinguish.
- **A routed supervisor refuses a second run over one ledger** and
  takes its run lock BEFORE reading or creating the ledger, so two
  fresh supervisors cannot both initialise it. This strengthens B's
  surface; it is recorded as an intentional change, not a side
  effect.

### Amendment A2 (T3 review round 3) — structured replay, mode, and observability

Five further gaps in the reconstruction were found in review and are
recorded as contract, not just fixes:

- **Bounded-work modes are NOT auto-wakeable.** `--delegate` and
  `--reconcile` can both stop for `routing_no_eligible_profile`, and
  their identity is a task id plus packet/done-file/round state. The
  ledger records a CLOSED mode discriminator (`run|delegate|
  reconcile`); wake serves `run` and refuses the other two BY NAME. An
  operator resumes bounded work. `--on-incomplete` is recorded and
  validated against its own closed enum; only the code-owned default
  `park` is auto-wakeable, because the ledger cannot grant `relaunch`.
- **The reconstruction uses code-owned defaults.** This supersedes
  A2's broader statement that validated persisted caps were replayed
  exactly. The two persisted
  cap views must be equal, closed to the four cap keys, and contain
  non-negative integers, but equality inside one mutable file proves
  consistency, not authority. Automatic wake accepts only the
  supervisor defaults shared by the supervisor and tick. A non-default
  invocation such as `--max-attempts 3`, or a partial/inconsistent
  record, is refused for an operator to resume.
- **The launch acknowledgement is a durable fact.** Liveness polling
  cannot decide whether a launch happened — a fast child acquires and
  releases the run lock between polls, a slow one acquires just after
  the last poll. The supervisor stamps `routing_wake.acked` under the
  run lock before doing any work; the tick waits for that, and
  releases a claim only through a COMPARE-AND-SET under the run lock
  (`claimed == generation AND acked != generation`), so a late
  acknowledgement is never overwritten and a stale timeout can never
  clear a newer park's claim. A claim under a run lock the tick cannot
  attribute is left alone rather than cleared.
- **`active` means alive.** Fallback-run marking requires a run lock
  with a live owner; `status: running` survives a crash forever. T4
  revalidates the marker when it consumes it at the boundary.
- **Wake and failback outcomes are journaled** as closed named events
  (`wake_claimed`, `wake_replay_noop`, `wake_launch_failed`,
  `wake_refused`, `wake_acked`, `failback_marked`) with timestamps, in
  the run's own `events.jsonl` — FR-D10 observability is a durable
  record, not console output a cron job discards.

### Amendment A3 (T3 review round 4) — bounds, authority, and accounting

- **The probe bound is enforced, not merely declared.** `RB_TIMEOUT_SEC`
  now runs through the repo's proven bounded runner (`ca_run_bounded`,
  #242 C2): own process group, TERM then KILL, escalation allowed to
  complete. Expiry (124) and an unestablishable bound (125) are both
  `probe_unverifiable` — absence of evidence, never a provider verdict.
  A hanging provider cannot hang `tick`, and `tick` hanging would stop
  every profile from ever recovering.
- **Structured replay cannot derive authority from the ledger.**
  `--wake` is explicit, the executable is fixed to this installation,
  and every persisted value is closed and typed. Only this
  installation's code-owned default caps and `on-incomplete=park` are
  reconstructed automatically. A non-default operator grant has no
  independent durable authority source in this slice and is refused
  for manual resume. The repository layer can veto wake with
  `wake_enabled=false`, but cannot define execution authority.
- **The wake is acknowledged only after startup validation.** A run
  that refuses for a terminated policy (exit 6) or a corrupt ledger
  (exit 5) never became runnable; acknowledging at lock acquisition
  permanently consumed a generation for a launch that could do no
  work. The stamp moved after every fail-closed startup check, making
  those refusals retryable — which is what they are.
- **Probe accounting is serialised.** T3 releases the state lock
  before probing, so probes overlap by design; `rb_debit`'s
  read-modify-write is now under an owner-aware lock (atomic rename
  retained for publication). An unserialised debit dropped rows, which
  breaks both "launched implies accounted" and every cap that counts
  them.

### Amendment A4 (T3 review rounds 5–6) — probe and replay boundaries

- **No repository-owned grant surface.** The attempted `wake_caps`
  design contradicted FR-D8: repository configuration is
  restriction-only. It is removed. `routing.recovery` contains only
  the two vetoes `wake_enabled` and `auto_failback_enabled`; the tick
  validates each per-run document through the executable automation
  validator before composition. Explicit `--wake` replays the
  supervisor with this installation's executable and code-owned
  defaults; the ledger contributes bounded identity and evidence, not
  execution authority.
- **Cap admission and reservation are ONE locked transaction.**
  Checking caps and then reserving separately is check-then-act: 20
  concurrent probes all admitted themselves past a cap of one. Cost
  admission compares current spend PLUS the pending estimate to the
  maximum before appending the reservation.
- **Accounting infrastructure is not a cap.** A real cap yields
  `probe_deferred_caps`; a corrupt ledger, unavailable lock, or failed
  reservation write yields `probe_unverifiable` without launching and
  follows the unknown/no-evidence transition.
- **The probe child receives no active accounting or state path.**
  `CCT_ROUTING_PROBE_LEDGER`, `CCT_ROUTING_STATE`,
  `CCT_ROUTING_REGISTRY`, `CCT_SUPERVISOR_DIR`, and adjacent routing
  paths are rebound to a private per-probe tree rather than unset (an
  unset variable would activate each library's `$HOME` fallback).
  The reservation is VERIFIED to still exist after execution — a
  probe whose accounting vanished is unverifiable, never a pass.
- **The execution mechanism is validated before any spend.** An
  invalid bound refuses without debiting a launch that cannot happen.
- **An interrupted tick reaps its probe immediately.** The tick
  installs INT/TERM/HUP/EXIT cleanup and the active-group handoff
  `ca_run_bounded` expects; without it a terminated tick left real
  provider work running until the watchdog deadline.
- **The wake acknowledgement moves to the END of routing admission** —
  after registry existence, validation, effective-policy composition
  and the enabled check (exit 64), not merely after ledger validation.

# Spec: Probe-verified recovery + failback — increment D of #109

A–C can ENTER degraded states — cooled pools, auth-disabled profiles,
parked runs, unreconciled provisional work — but only time or an
operator resolves them. Increment D gives every degraded state a
VERIFIED exit: real-inference probes instead of time-only decay,
hysteresis-guarded failback at task boundaries, an idempotent
scheduler command, explicit operator re-enable, and
reconciliation-on-recovery. The governing rule: **`healthy` is a
probe-verified claim, never an assumption** — time decay still ends
at `unknown`, and only a passed canary may say more.

## User Scenarios

- An Anthropic pool exhausts overnight. A cron-driven
  `cct routing tick --due --once` probes at the recorded reset time
  with a small REAL inference (and a minimal tool canary for
  tool-profiled builders); after the configured success threshold the
  pool is `healthy`, and a run parked for "no eligible profile" is
  woken under its locks and continues on the preferred profile.
- A supervised run is mid-fallback on a DeepSeek profile when the
  preferred pool recovers. The active attempt is NEVER interrupted;
  at the next task boundary the supervisor fails back to the
  preferred profile (dwell + threshold guarded), and outstanding
  Tier-2 provisional work gets reconciliation prioritized before new
  build tasks.
- An operator rotates a key for an auth-disabled profile and runs the
  explicit re-enable command. The profile returns as `probe_due` —
  never straight to eligible — and must pass a probe before selection
  treats it as recovered.
- A flapping provider passes one probe then fails again. Hysteresis
  (consecutive successes + minimum dwell) prevents oscillating
  failback; the journal names every transition.

## Requirements

- **FR-D1 (state vocabulary + schedule fields).** The circuit store
  gains the closed recovery states `healthy | degraded | probe_due |
  probing` beside B's `unknown | cooldown | disabled`, plus
  `next_probe_at`, `consecutive_probe_successes`, and probe
  provenance fields. Read-side rules are frozen: only a
  probe-verified `healthy` within its dwell window ranks as
  verified-good; time decay still lands on `unknown` (never
  `healthy`); `degraded`/`probing`/`probe_due` are NOT eligible;
  B's pool-outranks-profile and fail-closed read rules are unchanged.
  An ABANDONED `probing` marker (a tick died mid-probe) is absence of
  evidence, never provider evidence: it reads as `unknown`, journals
  `routing_probe_abandoned`, reschedules, and touches no failure or
  success counter — and can never produce `healthy`. The seven-state
  transition matrix is closed and executable; the ONLY edge into
  `healthy` is a verified canary success reaching the threshold.
- **FR-D2 (real probes).** A health probe performs a SMALL REAL
  inference through the profile's backend and, when the profile's
  tool_profile implies tool use, a minimal tool-call canary.
  `/v1/models`, `--version`, or a TCP connect are insufficient by
  contract. Per-backend executability is stated honestly: a backend
  that cannot run a real canary yields `probe_unverifiable` and the
  state stays `unknown` — never assumed healthy; `probe_fail` means
  actual negative canary evidence, never absence of evidence. Probes
  are never an unmetered execution channel: the frozen ordering is
  accounting debit/estimate (a launched probe is accounted even when
  its result is malformed, times out, or crashes) → bounded
  invocation (caps checked BEFORE launch; a blocking cap yields the
  named `probe_deferred_caps`, never a bypass) → secret-taint scrub
  → classification → state transition. The probe child gets
  credential values in its environment only and no cost-file
  capability.
- **FR-D3 (recovery timing precedence).** `next_probe_at` derives, in
  order: provider-supplied reset time; `Retry-After`; subscription
  `rate_limits.*.resets_at` when available; bounded exponential
  backoff WITH jitter. Backoff numerics are named implementation
  defaults, journaled when applied.
- **FR-D4 (failback with hysteresis).** Failback never interrupts an
  active attempt. The preferred profile (the registry's declarative
  `preferred_profile`, promoted here to enforced behavior) is
  re-selected only at a task boundary, only after
  `healthy_probes_required` consecutive successes and
  `minimum_profile_dwell_sec` of dwell — both promoted registry
  policy keys (previously refused-by-name futures). Every transition
  is journaled with a named event.
- **FR-D5 (`cct routing tick --due --once`).** A cron/launchd/systemd
  compatible IDEMPOTENT command: acquires the global state lock,
  probes exactly the profiles whose `next_probe_at` is due, applies
  results atomically, marks active fallback runs for
  next-boundary failback, and — only with an explicit `--wake` —
  relaunches runs parked for `routing_no_eligible_profile` as an
  IDEMPOTENT ARGV REPLAY: the ledger-recorded structured argument
  vector, verbatim (never a shell string, never reconstructed from
  current configuration), after revalidating disposition/mode/
  restriction/locks/root, under an atomically-claimed per-park wake
  GENERATION — a claimed generation replays as a journaled no-op,
  and a live run lock always refuses. Running the tick twice is a
  no-op the second time. `validate | status |
  explain` remain PURE; `tick` is the one deliberately impure verb
  and says so.
- **FR-D6 (operator re-enable).** `cct routing enable <profile-id>`
  is the ONLY path out of auth-disabled: explicit, journaled as an
  operator action, and landing on `probe_due` — a rotated key must
  prove itself before selection sees the profile again. Nothing
  automatic re-enables auth.
- **FR-D7 (reconcile-on-recovery).** At a failback boundary, pending
  `verified_provisional` records are prioritized: the supervisor runs
  the C reconciliation flow for each before taking new build tasks
  (bounded per boundary; a reconcile failure journals and parks per
  C's semantics rather than blocking the failback itself).
- **FR-D8 (`recovery` repo key promotion).** The repo `routing.recovery`
  key promotes refused→implemented→behaviorally-tested,
  RESTRICTION-ONLY and closed: a repository may forbid automatic
  failback (`auto_failback_enabled = false` — stay on the fallback
  until an operator acts) and forbid wake (`wake_enabled = false`);
  it can never widen, schedule, or define probes.
- **FR-D9 (registry policy promotions).** `healthy_probes_required`,
  `minimum_profile_dwell_sec`, and `failback` (`auto | operator`)
  promote from refused futures to validated `[policy]` keys with
  behavior. `max_switches_per_task` STAYS refused (no owning
  increment yet).
- **FR-D10 (observability).** Probes, decays, failbacks, wakes, and
  re-enables are journaled with closed named events; `cct routing
  status` renders the new states and next-probe times without
  becoming a second health system.

## Constraints

- A/B/C contracts are consumed frozen (result envelope, crash
  ordering, selection oracle, packet/reconcile machinery); where D
  extends the state vocabulary or CLI it does so visibly with its own
  regressions.
- Probes are the ONLY path to `healthy`; time-based transitions never
  exceed `unknown`; auth-disabled never exits without FR-D6.
- No session crossing, no credential values in durable output — probe
  children obey B's env wiring and scrubbing.
- Numeric backoff/jitter/dwell defaults are named implementation
  defaults journaled when applied — not compatibility surface;
  user-configurable knobs exist ONLY as the promoted FR-D9 keys.
- Routing stays opt-in end to end; absent configuration changes no
  existing behavior; bash 3.2; no new runtime dependency.

## Success criteria

- **SC-D1** The extended store round-trips the new states + schedule
  fields; read-side eligibility treats only in-dwell `healthy` as
  verified-good; decay still lands on `unknown`; an overdue
  `probing` marker yields `unknown` + `routing_probe_abandoned` with
  next_probe_at advanced and every counter untouched (never
  `probe_fail`, never `healthy`); the closed transition matrix
  refuses every unenumerated edge; B's suite passes unmodified.
- **SC-D2** A probe that passes inference+tool canaries transitions
  cooldown→healthy after the threshold; a failing probe re-schedules
  with backoff+jitter; an unverifiable backend yields
  `probe_unverifiable` and stays `unknown`; a tool-profiled builder
  failing only the tool canary never reaches `healthy`; a probe that
  launches then produces malformed evidence still records its cost;
  a probe child echoing a credential value leaves no trace in
  journal, state, or artifacts; a cap blocking a due probe yields
  `probe_deferred_caps` without launching.
- **SC-D3** Timing precedence proven per source (reset_at,
  Retry-After, rate_limits, backoff) including the jitter bound and
  the named-default journaling.
- **SC-D4** Failback: an active attempt is never interrupted
  (boundary-only switch proven); threshold and dwell each
  independently block premature failback (dwell gating BOTH the
  preferred profile's health age and the active profile's tenure);
  the preferred profile wins the next boundary; flapping is contained (hysteresis regression).
- **SC-D5** `tick --due --once` is idempotent (second run no-op),
  probes only due profiles, refuses concurrent execution via the
  global lock, marks fallback runs, and wakes a parked run ONLY with
  `--wake` and only under the run's locks via the recorded argv
  vector; a lock held by a live supervisor refuses the wake by name;
  a claimed wake generation replays as a journaled no-op; a
  pre-exec launch failure releases the claim retryably.
- **SC-D6** Auth-disabled exits ONLY via `cct routing enable`, lands
  on `probe_due`, and requires a passed probe before selection;
  automatic paths proven refused.
- **SC-D7** Reconcile-on-recovery: a failback boundary with pending
  provisional records runs C's reconcile flow first; its verdicts
  land per C; a reconcile failure does not cancel the failback.
- **SC-D8** The `recovery` repo key validates closed
  (restriction-only; unknown keys refused); `auto_failback_enabled =
  false` provably pins the run to the fallback profile;
  `wake_enabled = false` provably blocks `--wake`.
- **SC-D9** The three promoted `[policy]` keys validate, drive the
  hysteresis behavior, and `max_switches_per_task` remains refused by
  name.
- **SC-D10** Docs/CHANGELOG/pins land with the behavior; the full
  sweep stays green modulo the known host baseline; every SC above is
  mutation-verified in isolated worktrees.

## Non-goals (deferred per the umbrella)

Benchmarks, routing-quality metrics, shadow-mode recommendations,
learned routing (E); the codex execution adapter (own child
increment); launchd/systemd timer GENERATORS (the cron-compatible
`--once` command is the portable contract; generators may follow);
any change to providers.toml semantics; multi-run orchestration
beyond wake-under-locks.

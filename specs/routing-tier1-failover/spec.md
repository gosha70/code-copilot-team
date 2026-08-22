# Spec: Tier-1 failover — increment B of #109

Increment A froze the declarative layer: the profile registry, the
trust-asymmetric repo restrictions, the effective-policy merge, the
nine-cause failure taxonomy, and read-only inspection. Increment B
makes it act: when the preferred profile's provider becomes
unavailable, the run CONTINUES on the next eligible Tier-1 profile —
without silently sacrificing verification, review independence, or
spend accounting. This is the increment that delivers the owner's
stated goal (continuing on an external LLM when the preferred pool is
exhausted).

## User Scenarios

- An unattended overnight build hits the Anthropic subscription
  session limit. The supervisor classifies the failure as
  `quota_exhausted`, cools the WHOLE quota pool until the provider's
  reset time, checkpoints the attempt durably, selects the DeepSeek
  profile (same backend, different provider endpoint), and continues —
  journaling why every other profile was or wasn't chosen.
- A transient 429 does NOT poison the pool: the run honors Retry-After
  and retries the same profile before ever failing over.
- Every Tier-1 profile is exhausted or cooling: the run parks (or
  terminates under `unattended`) with #190's semantics — it never
  waits silently forever and never grabs a Tier-2 profile.
- After a failover, the gating reviewer is re-checked: a reviewer that
  is now the same provider+model as the active builder is not
  silently accepted as independent.

## Requirements

- **FR-B1 (the seam).** Failover lives in the cooldown supervisor as
  an EXPLICIT opt-in routing mode. Without it, current behavior is
  unchanged byte-for-byte (the umbrella's compatibility promise); with
  it, the legacy single-backend cooldown loop is replaced by
  profile-aware selection over increment A's effective candidates.
- **FR-B2 (class→action, TOTAL).** The supervisor classifies every
  failed attempt through increment A's classifier and acts by CAUSE
  per plan decision 3's normative table, which is TOTAL: every cause
  freezes action scope (attempt | profile | pool), durable state
  change, same-profile retry budget, whether another candidate may
  be selected, re-eligibility, and the terminal/exhaustion reason —
  including the missing-metadata branches (absent/malformed
  `reset_at` uses the named conservative default, journaled). Pinned
  particulars: `rate_limited` has exactly ONE same-profile retry per
  supervised attempt; request-local causes stay request-local
  (`invalid_request` writes NO durable circuit state and cannot
  poison a profile for unrelated future work; `execution` never
  masquerades as provider health); `denied` and `unknown` never
  retry, never fail over. The legacy usage regex survives only as
  recorded-confidence fallback evidence inside the normalized
  result.
- **FR-B3 (circuit state).** Profile/pool availability persists in
  `~/.code-copilot-team/routing-state.json` (the file increment A's
  `status` already reads): per-profile state
  (`unknown|healthy|cooldown|disabled|incompatible`), reason,
  timestamps, and per-pool cooldowns — written atomically under a
  global state lock, never trusted from memory across attempts.
  Re-eligibility in B is TIME-BASED only (reset/backoff expiry);
  probe-based recovery is increment D and B's journal says so when a
  cooled profile re-enters service.
- **FR-B4 (selection).** Deterministic and journaled: effective
  candidates (A's merge) filtered by role `build`, tier order
  `tier1`-only (Tier-2 selection is increment C), circuit state, and
  the per-unit attempted set; ordered by priority. Every candidate's
  verdict is journaled in explain's vocabulary. Bounded and
  cycle-free: within one unit, a profile is attempted at most once
  per eligibility change (Scenario 3).
- **FR-B5 (checkpoint + crash ordering).** Before any profile switch
  the attempt is checkpointed durably and backend-neutrally under the
  feature ledger (content per plan decision 5), and the ordering is
  FROZEN: persist attempt-started → launch exactly one fresh child →
  persist the normalized terminal result → atomically apply the
  circuit/pool action (IDEMPOTENT, keyed by attempt id) → checkpoint
  the next selection. A restart that finds attempt-started without a
  durable terminal result neither replays nor assumes failure — the
  outcome is indeterminate and the run parks/terminates as
  `routing_attempt_indeterminate` with checkpoint provenance. No
  session/conversation identifier ever crosses profiles or providers
  (Scenario 4). The driver remains the sole owner of git operations.
- **FR-B6 (launch wiring).** A profile launches through its declared
  backend: `claude-code` profiles wire `base_url`/`base_url_env` and
  `credential_env` into the CHILD environment only (values read at
  spawn, never logged, journaled, or persisted); `credential_mode`
  profiles use the backend's own login. `pi` profiles launch the
  existing pi build backend. Model verification is TRI-STATE (plan
  decision 6): verified match / mismatch (fail closed,
  `routing_model_identity_mismatch`, never rerouted around) /
  unverified (recorded null and journaled — requested is never
  synthesized as effective). Requested and effective are retained
  separately in checkpoints, journal, and analytics.
- **FR-B7 (identity + review independence).** The ACTIVE builder
  identity (backend, provider, profile, requested and effective
  model, tool profile) flows into the run ledger, review requests,
  and summary/analytics fields (additive). After every builder-profile
  switch, reviewer independence is re-evaluated: a gating reviewer
  resolving to the active builder's provider+model follows #190's
  disposition (park attended / terminate unattended); the router
  never downgrades independence to keep moving.
- **FR-B8 (exhaustion).** When no Tier-1 profile is eligible, the run
  parks (attended) or terminates (unattended) with #190 semantics,
  naming every profile's blocking reason and the earliest
  re-eligibility time; the supervisor may sleep to that time instead
  when it is within the run's wall-clock caps.
- **FR-B9 (accounting).** Attempts on ANY profile ride the existing
  cost/cap machinery unchanged; profile switches never reset or fork
  caps, and estimates apply per the existing rules.

## Constraints

- Routing mode is explicit opt-in; absent registry, absent flag, or
  effective-disabled policy ⇒ the legacy loop, unchanged.
- Tier-2 profiles are NEVER selected in B, regardless of registry
  contents.
- No probes, no `routing tick`, no failback-at-boundary beyond
  time-based re-eligibility (increment D); no task route metadata
  (increment C); no learned routing (E).
- State writes are atomic+locked; a crash between checkpoint and
  launch must be resumable from durable state without duplicate
  concurrent execution (Scenario 9's B-scope half).
- Credential VALUES appear only in spawned child environments.
- bash 3.2; no new runtime dependency.

## Success criteria

- **SC-B1** A stubbed backend emitting the captured session-limit
  output triggers: pool-wide cooldown with persisted reset time,
  durable checkpoint, selection of the next Tier-1 profile, and a
  journaled per-candidate explanation — in one supervised run.
- **SC-B2** Two profiles sharing `quota_pool` cool TOGETHER; the
  selector never burns an attempt on a sibling of an exhausted pool
  (Scenario 2's "does not waste time on the same exhausted pool").
- **SC-B3** `rate_limited` with Retry-After retries the SAME profile
  after the delay; `auth` disables exactly that profile and the run
  continues on the next; `denied` parks/terminates without any
  further selection; `unknown` parks/terminates without retry or
  failover — each proven by fixture-driven supervised runs.
- **SC-B4** The failover chain is bounded and cycle-free: with every
  profile unavailable, each is attempted at most once per eligibility
  window and the run ends in FR-B8's exhaustion outcome naming every
  reason.
- **SC-B5** Cross-backend handoff (claude-code profile → pi profile):
  the second attempt starts a fresh session from durable state; no
  session identifier from the first backend appears anywhere in the
  second launch; worktree changes and verifier evidence survive.
- **SC-B6** Cross-provider same-backend handoff (Anthropic →
  DeepSeek-style endpoint profile): the child environment carries the
  profile's base URL and the value behind its credential_env; neither
  value appears in any log, journal, ledger, or checkpoint.
- **SC-B7** Model identity is tri-state and each state is exercised:
  a matching transcript records verified; a mismatching transcript
  parks/terminates as `routing_model_identity_mismatch` with NO
  further selection; a transcript with no model identity records
  null + an UNVERIFIED journal line, and never copies requested into
  effective.
- **SC-B8** Reviewer-independence re-evaluation: after a switch that
  makes the gating reviewer collide with the builder, the run follows
  #190 disposition instead of proceeding — proven for gating and
  advisory postures.
- **SC-B9** Crash semantics honor the frozen ordering: a kill between
  attempt-started and the terminal result leaves a restart that
  NEITHER replays the attempt NOR fails over — it parks as
  `routing_attempt_indeterminate`; a kill after the terminal result
  but before action application re-applies IDEMPOTENTLY (the same
  attempt id never applies a failure action twice); and no path
  executes the unit twice concurrently.
- **SC-B10** Legacy byte-compatibility: without the routing flag the
  supervisor's behavior and outputs are unchanged (existing
  cooldown-supervisor suite passes unmodified); with routing enabled
  but no registry, the run refuses with guidance rather than
  guessing.
- **SC-B11** Docs/CHANGELOG/pins land with the behavior; every SC
  above is mutation-verified in isolated worktrees.

## Non-goals (deferred per the umbrella)

Increment C (task route metadata, Tier-2 selection, packets per SDD
task, reconciliation), increment D (probes/canaries, `routing tick`,
failback hysteresis, scheduled recovery), increment E (benchmarks,
learned routing); a Codex EXECUTION backend for the driver (see plan
decision 7 — proposed as its own child increment); any change to
reviewer `providers.toml` semantics.

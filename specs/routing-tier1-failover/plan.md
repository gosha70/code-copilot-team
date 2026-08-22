---
spec_mode: full
feature_id: routing-tier1-failover
status: approved
date: 2026-08-22
risk_category: integration
justification: >
  Wires increment A's declarative routing into the live supervision
  path: profile selection over real launches, circuit/quota-pool state
  with crash-safe persistence, durable checkpoints, credential wiring
  into child environments, and reviewer-independence re-evaluation —
  integration risk across the supervisor, the driver's launch/review
  paths, and the #190 disposition semantics.
origin:
  type: issue
  issue: 251
  parent: 109
  references:
    - "#109 §Delivery Plan Increment B — structured failure classification; provider/quota-pool circuit state; durable task checkpoint; ordered Tier-1 profile selection; cross-provider acceptance scenario; builder identity to review/analytics"
    - "#109 §6 (classification->router behavior table), §4 (backend-neutral packet/checkpoint), §5 (deterministic selection), §8 (provider state), §10 (reviewer independence), Scenarios 1-4, 8-10"
    - "specs/routing-profile-foundation/ — increment A's frozen contracts this consumes"
    - "scripts/cooldown-supervisor.sh — the relaunch loop this seam replaces under opt-in"
    - "scripts/benchmark_runner/backends/codex.py — verified codex exec knowledge, deferred to its own increment (decision 7)"
  origin_claim: |
    #109 increment B: make the preferred->fallback chain real for
    Tier-1 work — classify failures by cause, keep circuit and
    quota-pool state, checkpoint durably, select the next eligible
    profile deterministically, and carry the true builder identity
    into review and analytics. The owner's motivation (continuing on
    an external LLM when the preferred pool is exhausted) is delivered
    by exactly this increment.
---

# Plan: Tier-1 failover, increment B of #109

`spec.md` states the requirements; THIS file's decisions are the
normative implementation contract. Increment A's surfaces (registry,
merge, taxonomy, state-file read side) are consumed frozen — nothing
here changes them.

## Decisions

1. **The seam is the supervisor, opt-in by flag.**
   `cooldown-supervisor.sh --routing` activates the failover loop;
   the flag additionally requires a validating registry and an
   effective-enabled merge (with the repo `automation.json` when
   present), else the supervisor REFUSES with guidance (never guesses,
   never silently falls back to legacy). Without `--routing`, the
   script's behavior is byte-identical to today, proven by the
   existing suite passing unmodified. The driver stays
   one-profile-per-attempt and is not taught about routing.

2. **B's bounded unit is the supervised ATTEMPT.** Task-level packets
   arrive with increment C's task metadata; until then the supervisor
   already operates in attempt granularity, and the driver's own
   ledger provides resumability. The checkpoint (decision 5) makes
   that unit durable and backend-neutral. The route class for B is
   effectively `tier1_only`; Tier-2 profiles are filtered
   unconditionally.

3. **Class→action mapping — TOTAL, exactly one place.** A new
   `scripts/lib/routing-actions.sh` maps the frozen taxonomy to
   supervisor behavior. The supervisor calls increment A's
   `rr_result` over the SAME captured output the legacy regex read;
   the legacy `USAGE_PATTERN` grep result is recorded into the
   normalized result's evidence as fallback confidence only. The
   table is NORMATIVE and total — every cause freezes scope, durable
   state change, same-profile retry budget, whether another candidate
   may be selected, re-eligibility, and the exhaustion/terminal
   reason; the implementation may not invent a fallback the table
   does not name. All durations are named constants in the actions
   lib, journaled whenever applied.

   | cause | scope | durable state | same-profile retries | select next? | re-eligibility | terminal reason |
   |---|---|---|---|---|---|---|
   | `quota_exhausted` | POOL | pool cooldown `until reset_at`; when `reset_at` is absent or malformed, `RA_QUOTA_DEFAULT_COOLDOWN` (3600s) journaled as "reset evidence absent — conservative default" | 0 | yes (a different pool only) | time decay → `unknown` | `routing_pool_exhausted` naming pool + until |
   | `rate_limited` | profile | none on the FIRST occurrence; after the budget, profile cooldown until `retry_after_sec` (else `RA_RATE_COOLDOWN` 120s) | exactly ONE same-profile retry per supervised attempt, after `retry_after_sec` (else `RA_RATE_RETRY_DELAY` 60s) | yes, after the budget | time decay → `unknown` | `routing_rate_limited` |
   | `unavailable` | profile | after the budget, profile cooldown `RA_UNAVAILABLE_COOLDOWN` (300s) | exactly ONE retry after `RA_UNAVAILABLE_RETRY_DELAY` (30s) | yes, after the budget | time decay → `unknown` | `routing_provider_unavailable` |
   | `transport` | profile | after the budget, profile cooldown `RA_UNAVAILABLE_COOLDOWN` (300s) | exactly ONE retry after `RA_UNAVAILABLE_RETRY_DELAY` (30s) | yes, after the budget | time decay → `unknown` | `routing_transport_failure` |
   | `auth` | profile | profile DISABLED, never auto-decays | 0 | yes | operator action only (increment D adds operator-requested probes) | `routing_auth_failure` |
   | `invalid_request` | ATTEMPT-LOCAL | NONE — the profile joins this unit's attempted-set as incompatible; no circuit write, no provider penalty (a request-local cause must never poison a profile for unrelated future work) | 0 | yes | next supervised unit starts clean | `routing_task_incompatible` |
   | `denied` | run | none | 0 | NO — never rerouted around | n/a | park/terminate `routing_policy_denied` (#190 semantics) |
   | `execution` | not an availability event | none | n/a (router takes no action) | NO — the existing breaker path owns disposition | n/a | existing #190 semantics, unchanged |
   | `unknown` | run — FAIL CLOSED | none | 0 | NO | n/a | park/terminate `routing_unknown_failure` |

4. **Circuit state store.** `scripts/lib/routing-state.sh` owns
   `~/.code-copilot-team/routing-state.json` (schema_version 1;
   `profiles.<id>.{state,reason,failed_at,until,last_success_at}`;
   `pools.<pool>.{state,reason,until}`): read-modify-write under an
   exclusive lock directory (`routing-state.lock`, mkdir-based, stale
   after a journaled timeout) with temp+rename atomic writes.
   Pool cooldown OUTRANKS profile state at selection. Time-based
   re-eligibility only: when `until` passes, the entry decays to
   `unknown` (not `healthy` — B has no probes; the journal names the
   decay so D's probe layer has a clean hook). `auth`-disabled and
   `denied` never decay automatically.

5. **Checkpoint + the FROZEN crash-ordering contract.** The durable
   handoff document lives at
   `.cct/auto-build/<feature>/routing/checkpoint-<attempt>.json`:
   base commit, current HEAD, dirty flag, `git diff` sha256 + the
   patch bytes as a sibling artifact, the FULL normalized result of
   the failed attempt, prior profile id + requested/effective model,
   transcript path, attempt/cooldown counters, and the attempted-set.
   The ordering is NORMATIVE:

   1. persist attempt-started (attempt id + selected profile),
   2. launch exactly one FRESH child session,
   3. persist the normalized terminal result,
   4. atomically apply the circuit/pool action — IDEMPOTENT, keyed by
      attempt id (state entries record `last_applied_attempt`, so
      replaying checkpoint processing can never apply the same
      failure action twice),
   5. checkpoint the next selection.

   A restart that finds attempt-started WITHOUT a durable terminal
   result must NEITHER replay the attempt NOR fail over as though it
   definitely failed — the child may have mutated the workspace; the
   outcome is indeterminate. It parks/terminates with the named
   reason `routing_attempt_indeterminate` and full checkpoint
   provenance for the operator. The supervisor's existing feature
   lock prevents concurrent duplicate runs; the checkpoint never
   carries a session or conversation identifier — a new profile
   always cold-starts its backend from repository + ledger state
   (Scenario 4). This ordering matters more than session hygiene:
   without it, crash recovery can duplicate agent side effects.

6. **Launch wiring.** A profile launches via its backend:
   - `claude-code`: child env gains `ANTHROPIC_BASE_URL` (from
     `base_url` or the value behind `base_url_env`) and
     `ANTHROPIC_API_KEY` (value behind `credential_env`) — read at
     spawn into the child environment ONLY; never echoed, journaled,
     persisted, or checkpointed. `credential_mode: claude-login`
     wires nothing. The supervisor journals which VARIABLE NAMES were
     wired, never values.
   - `pi`: the existing pi build backend path, unchanged.
   Requested model comes from the profile; model verification is
   explicitly TRI-STATE, preserving increment A's never-assumed rule:

   - reported effective == requested → verified match, recorded;
   - reported effective != requested → FAIL CLOSED with the named
     reason `routing_model_identity_mismatch`, park/terminate — a
     gateway silently substituting models is an identity violation,
     never rerouted around (Scenario 10);
   - effective model unavailable → recorded null and journaled as
     UNVERIFIED; requested is never synthesized as effective.

   Per-adapter executability, stated not implied: the claude-code
   backend's result carries model identity (states 1 and 2 are
   executable); the pi backend currently does not (its attempts are
   always state 3, journaled unverified). Checkpoints, journal, and
   analytics always retain requested and effective SEPARATELY. No
   registry field changes (A is frozen); a per-profile
   "require verified identity" knob, if ever wanted, follows the
   refused→implemented→tested promotion path.

7. **Codex is NOT in this increment — B makes NO codex-support
   claim.** The umbrella's B bullet names a Claude→DeepSeek→Codex
   scenario. The architectural property (cross-BACKEND handoff from
   durable state, no session reuse) is proven here with the pi
   backend, which is already a first-class build backend;
   DeepSeek-style profiles prove the cross-PROVIDER half on the
   claude-code backend. A codex EXECUTION adapter for the driver is
   real new surface (the benchmark's verified `codex exec` knowledge
   transfers, but launch, result, review, and cost wiring are driver
   work) and is its own child increment after B — REQUIRED to reuse
   this increment's normalized attempt/result/checkpoint contracts
   rather than growing a codex-special path. Flagged as a deviation
   in the origin-alignment record.

8. **Identity + independence.** The supervisor exports the active
   profile identity to the driver
   (`CCT_ROUTING_PROFILE/BACKEND/PROVIDER/MODEL...`); the driver
   records it in the run ledger and review-request context, and the
   summary/analytics fields gain additive identity columns. After
   every switch the supervisor re-evaluates reviewer independence:
   it resolves the gating reviewer's provider+model (providers.toml,
   read-only) and on collision with the active builder follows #190
   disposition (park attended / terminate unattended; advisory
   journals and continues). providers.toml semantics are untouched.

9. **Exhaustion + caps.** No eligible profile: if the earliest
   re-eligibility time fits inside the remaining wall-clock cap the
   supervisor sleeps to it (journaled); otherwise FR-B8's
   park/terminate names every profile's reason. All existing
   attempt/wall/cooldown caps remain authoritative and are checked
   before every launch, unchanged.

## Deliberately NOT in this slice

Probes/canaries, `routing tick`, failback hysteresis and dwell
(increment D — B's time-based decay journals a hook for it); task
route metadata, Tier-2 selection, packets per SDD task,
reconciliation (increment C); a codex execution backend (decision 7,
own increment); benchmarks/learned routing (E); any registry or
taxonomy change (A is frozen; if B needs a schema change it amends A's
artifacts visibly, never silently).

## Sequence

T1 state store + lock + decay (lib) ->
T2 class→action policy (lib over A's classifier) ->
T3 selection engine over rc_effective + state + attempted-set ->
T4 supervisor routing mode: refusal rules, checkpoint, launch wiring,
   exhaustion/sleep, crash-resume ->
T5 identity propagation + reviewer-independence re-evaluation ->
T6 docs + CHANGELOG + pins + full sweep + origin refresh.
C3/A cadence: per-task suites + isolated-worktree mutations + review
holds between tasks.

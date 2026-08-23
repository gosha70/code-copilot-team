---
spec_mode: full
feature_id: routing-tier2-delegation
status: approved
date: 2026-08-23
risk_category: integration
justification: >
  Hands real build work to a lower-trust model tier and lets its output
  approach the mainline: packet construction from frozen artifacts,
  driver-owned scope/verifier enforcement, a provisional ledger state
  that gates must treat as incomplete, and a Tier-1 reconciliation
  flow — integration risk across the supervisor's routing mode, the
  driver ledger, and the #190 verification semantics.
origin:
  type: issue
  issue: 254
  parent: 109
  references:
    - "#109 §Delivery Plan Increment C — task route metadata + packet generation; Tier-2 eligibility validation; minimal local-builder tool profile; driver-owned repair loop + thrash detection; verified_provisional; Tier-1 reconciliation"
    - "#109 §3 (route classes + Tier-1-forced categories), §4 (backend-neutral task packet), §7 (quality-preserving Tier-2 continuation), Scenarios 5-6, Acceptance §Quality preservation"
    - "specs/routing-profile-foundation/ — increment A's frozen contracts (registry, merge, taxonomy, explain) consumed unchanged; A's recorded deviation (task-addressed explain deferred) closes here"
    - "specs/routing-tier1-failover/ — increment B's frozen contracts (result envelope, crash ordering, state store, selection oracle, launch wiring, independence gate) consumed unchanged"
    - "shared/schemas/verification.schema.json + specs/<feature>/verification.yaml — the #190 verifier source packets quote verbatim"
  origin_claim: |
    #109 increment C: the cost/capability half of the routing value
    proposition — send explicitly bounded tasks to a cheaper or local
    Tier-2 model by policy, even while Tier-1 is healthy, with the
    owner's architectural rule load-bearing throughout: Tier-2 is
    delegated bounded work, never another unrestricted failover
    target. Bounded packet in, durable evidence out, Tier-1
    reconciliation before anything becomes authoritative.
---

# Plan: Tier-2 delegation + reconciliation — increment C of #109

`spec.md` states the requirements; THIS file's decisions are the
normative implementation contract. A's and B's surfaces are consumed
frozen — where C extends an enum or adds an envelope it does so as a
visibly versioned sibling, never by mutating theirs.

## Decisions

1. **Task route metadata is a constrained artifact, validated like
   everything else.** `specs/<feature>/routing-tasks.yaml` uses the
   same constrained two-level YAML dialect as `verification.yaml`
   (reject-never-approximate; `schema_version: 1` the sole root
   scalar beside `tasks:`). Per task: `id` (stable, unique),
   `route_class` (closed: `primary_only|tier1_only|tier2_fallback|
   tier2_preferred`), `outcome` (one line, non-empty), `allowed_files`
   (exact repo-relative paths or single-directory globs; must resolve
   inside the repo root), `fr_refs` (each must exist in the feature's
   `verification.yaml` with at least one deterministic `test`
   verifier), `depends_on` (task ids in the same file; acyclic),
   `forbidden_categories` (subset of the safety-floor vocabulary,
   additive narrowing only), `reorderable` (bool). A new
   `scripts/lib/routing-tasks.sh` (`rk_*`) owns parse + validation +
   lookup; `cct routing validate` gains the artifact when present. A
   task absent from the file, or the file absent entirely, resolves
   `tier1_only`. Unknown keys, unknown route classes, dangling
   `fr_refs`, unknown `depends_on`, dependency cycles, and
   path-escaping `allowed_files` are named refusals.

2. **The safety floor is structural, evaluated twice, and cannot be
   annotated away.** A closed category vocabulary, defined once in
   `routing-tasks.sh` with one named path-pattern set per category:
   `architecture`, `auth`, `crypto`, `security_policy`,
   `db_migrations`, `dependency_manifests`, `public_api`,
   `ci_verification_tooling`, `routing_artifacts` (the routing/
   verification artifacts and their tests are always in-floor). A
   task whose `allowed_files` intersect any floor category cannot
   carry a `tier2_*` route class: metadata ADMISSION refuses it by
   name (validator error, never a silent downgrade), and PACKET BUILD
   re-evaluates the same predicate against the artifacts as frozen at
   build time — a floor violation introduced after admission is a
   second named refusal. The floor vocabulary and patterns are
   implementation surface with tests, not user configuration;
   `forbidden_categories` lets metadata NARROW further, never widen.

3. **Packet envelope — versioned, closed, driver-generated,
   provenance-bound, IMMUTABLE.** The packet is the immutable unit C
   executes, exactly as B made `result-N.json` the immutable recovery
   unit. `scripts/lib/routing-packet.sh` (`rp_*`) builds
   `.cct/auto-build/<feature>/routing/packet-<task>-<n>.json`:
   `schema_version: 1`, `packet_id`, `packet_digest` (sha256 over the
   canonical envelope bytes minus the digest field itself), feature
   id, task id + outcome, route class, `allowed_files`,
   `forbidden_categories` (effective = floor ∪ declared), `fr_refs`
   each with its `statement_sha` and its verifier `test` commands
   quoted VERBATIM from `verification.yaml`, `base_commit`,
   `current_diff_sha256` (hash and content from the same single
   capture), `routing_tasks_sha256` + `verification_spec_sha256`
   (digests of the two source artifacts as admitted — the provenance
   bindings), prior-evidence refs, `dependencies_complete` (computed,
   must be true to build). Envelope validation is closed — unknown
   keys refuse (sibling discipline of B's result envelope).
   Generation reads only FROZEN inputs (the two artifacts + git
   state); regenerating from unchanged inputs is byte-identical. The
   Tier-2 model never writes or edits a packet; after build, NOTHING
   edits a packet — a changed input means a NEW packet id, never a
   mutated envelope.

4. **Packet execution rides B's supervisor machinery — one new
   bounded mode, legacy and B byte-identical without it.**
   `cooldown-supervisor.sh <feature> --routing --delegate <task-id>`
   runs exactly one packet, and the packet is its ONLY authority —
   the frozen point-of-use sequence:

   1. validate the closed/versioned envelope (unknown key /
      version → named refusal),
   2. verify `packet_digest` over the envelope bytes,
   3. create the DEDICATED packet worktree from the packet's
      recorded `base_commit`,
   4. point-of-use provenance check: recompute the digests of
      `routing-tasks.yaml` and `verification.yaml` and compare to
      the packet's recorded `routing_tasks_sha256` /
      `verification_spec_sha256` — ANY drift is the named refusal
      `packet_provenance_drift` (never a silent rebuild, never a
      downgrade; the operator regenerates a new packet),
   5. execute from the packet alone — the run never rereads the
      mutable artifacts and reinterprets them; route class, scope,
      floor categories, and verifier commands come from the
      envelope.

   Selection uses `rt_select` over the packet's route class
   (decision 8), then B's frozen chain unchanged — fresh child
   session, `rt_launch_env` env wiring, `rt_scrub_out` secret
   scrubbing, the 5-step crash ordering with
   `started/result/checkpoint` documents, attempt-id idempotency,
   recorded-decision recovery, tri-state model identity. The child is
   launched with the profile's `tool_profile` (minimal:
   read/edit/bash-test only; no MCP, no browser, no network tools
   beyond the endpoint itself) and a packet-only prompt rendered from
   the envelope. The child never touches the main tree; the driver
   retains sole git ownership. Without `--delegate`,
   `--routing` behavior is byte-identical to B (proven by the B suite
   unmodified); without `--routing`, `--delegate` is a named refusal.

5. **Scope enforcement is driver-owned, post-hoc, CUMULATIVE, and
   phase-universal.** After EVERY modifying phase — the initial
   Tier-2 implementation, each Tier-2 repair round, AND Tier-1
   reconciliation changes — the driver diffs the packet worktree
   against the packet's `base_commit` (the cumulative diff, never a
   per-round delta). Any path outside `allowed_files` — including ANY
   verifier/test file and any path matching a floor category, which
   are protected even when listed — fails that phase with the named
   violation `packet_scope_violation` and reverts the worktree diff.
   Scope failure is terminal for the round even if every verifier
   passes. The ordering is frozen for all three phases:
   scope/safety → verifiers → (for reconciliation only) verdict.
   `accepted_with_changes` is NOT a path around scope — a Tier-1
   reconciler's edits obey the same allowlist and protections as the
   Tier-2 builder's. The scope check runs BEFORE verifiers in every
   phase (never execute out-of-scope code).

6. **Verifier-decided success + bounded repair + thrash detection.**
   Success is decided ONLY by the driver re-running the packet's
   verifier commands (in the packet worktree) plus the scope check —
   the model's self-report is evidence, never a verdict. A failing
   round may repair: `RC_MAX_REPAIR_ROUNDS` (default 2) fresh
   sessions, each fed the packet plus the driver's verifier output.
   THRASH ends the loop early with its own named reason, each a
   distinct journaled value: `packet_thrash_repeated_failure` (the
   normalized failure signature of round N equals ANY prior round —
   this subsumes A/B/A oscillation), `packet_thrash_rewrite` (an
   allowed file's diff replaces more than `RC_REWRITE_FRACTION`
   (default 0.8) of its lines), `packet_thrash_no_reduction` (the
   failing-verifier count did not decrease). The changed-line budget
   `RC_MAX_CHANGED_LINES` (default 400) is CUMULATIVE from the
   immutable packet base — `changed_lines = diff(packet.base_commit,
   current worktree)`, measured after every modifying phase — never a
   per-round allowance (two legal rounds cannot double the effective
   scope); exceeding it refuses as `packet_budget_exceeded`. Every
   repair round (and every reconciliation launch, decision 9) is a
   FRESH B-style supervised attempt with its own attempt id, result
   envelope, and checkpoint under B's frozen crash ordering —
   worktree state persists across rounds; agent sessions never do.
   There is no C-only execution lifecycle. All `RC_*` numerics are
   NAMED IMPLEMENTATION DEFAULTS journaled when applied — not
   configuration, not compatibility surface (a knob takes the
   refused→implemented→tested promotion path). Terminal packet
   reasons form a closed enum in `routing-packet.sh`, sibling of
   B's `routing_*` enum; no dynamic assembly.

7. **`verified_provisional` is a ledger state that satisfies
   nothing.** A packet passing scope + verifiers records
   `verified_provisional` in the driver ledger with full evidence:
   diff sha, per-verifier outputs, repair count, profile identity
   (B's `routing_identity` shape). The driver MAY commit the packet
   diff as a clearly-marked WIP commit (driver-owned git; pushing
   stays under the repository's existing push policy — C adds no
   auto-push). Every completion/phase/landing gate treats
   `verified_provisional` as INCOMPLETE: a run whose remaining work
   is all provisional ends parked/incomplete per #190 semantics, and
   the unrouted ledger stays byte-identical (the provisional state
   appears only for delegated tasks).

8. **Selection legality — the tier requirement is never weakened.**
   `rt_select` gains an OPTIONAL route-class argument (absent →
   B's behavior byte-identical: tier2 filtered unconditionally).
   With a route class: `primary_only` admits only the
   highest-priority tier1 candidate's profile; `tier1_only` = B's
   filter; `tier2_preferred` orders eligible tier2 candidates first,
   tier1 as fallback. `tier2_fallback`'s unlock predicate is pinned
   to B's AUTHORITATIVE selector output shapes — C never inspects
   `considered[]` (frozen as evidence-only) or reasons independently
   about whether Tier-1 is "really unavailable":

   - `selected != null` → run Tier-1;
   - `selected == null`, `earliest_retry != null`, `terminal_reason
     == null` (temporary exhaustion) → wait to `earliest_retry`,
     select again — Tier-2 does NOT unlock;
   - `selected == null`, `earliest_retry == null`, `terminal_reason
     == routing_no_eligible_profile` (permanent exhaustion) → the
     Tier-1 candidate set is permanently empty; Tier-2 may unlock.

   Terminal outcomes from an ACTUAL Tier-1 attempt are never
   transformed into a fallback opportunity: `denied`, `unknown`,
   model-identity mismatch, reviewer-independence refusal, crash
   ambiguity (`routing_attempt_indeterminate`) — all remain terminal
   per B; none becomes "Tier-1 unavailable, therefore Tier-2". All
   three B output shapes and the total order are unchanged within a
   tier. A `tier1_only`/`primary_only` task can never resolve a
   tier2 profile even as sole candidate; exhausted Tier-1 with no
   eligible Tier-2-safe packet parks per B.

9. **Tier-1 reconciliation is a fresh gated session, not a rubber
   stamp — and independence must be POSITIVELY established.**
   `--reconcile <task-id>` (supervisor, same refusal rules) binds to
   the SAME immutable packet and provisional result it promotes
   (decision-4 validation steps 1–2 and the provenance check apply;
   drift → `packet_provenance_drift`), selects a Tier-1 profile
   holding the `reconcile` role (registry vocabulary from A; role
   absent → named refusal), and evaluates B's reviewer-independence
   gate against the packet's BUILDER identity — reusing B's evaluator
   unchanged but applying a STRONGER C-specific disposition, because
   reconciliation is the promotion boundary:

   - `independent` → reconciliation may proceed;
   - `not_independent` → fail closed, named
     `reconcile_not_independent` — cannot promote;
   - `unevaluable` → fail closed, named
     `reconcile_independence_unevaluable` — its OWN disposition,
     never conflated with a collision; a Tier-2 change must never
     become `accepted` precisely when the system cannot establish
     that its reconciler is independent. (B's non-blocking
     unevaluable disposition is unchanged for B's own flows.)

   On `independent`, it launches a fresh session (a fresh B-style
   supervised attempt per decision 6) with the patch, the packet, and
   the verifier evidence. The reconciler may simplify or repair
   WITHIN the packet's scope (decision 5 applies to its cumulative
   diff: scope/safety → verifiers → verdict); the driver then re-runs
   the packet verifiers and records `accepted | accepted_with_changes
   | rejected` (closed) in the ledger — `rejected` reverts the
   packet's diff (and its WIP commit via driver-owned revert commit).
   Only `accepted`/`accepted_with_changes` flip the task from
   `verified_provisional` to done-eligible. Reconciliation attempts
   ride the same accounting/journal machinery as any attempt.

10. **Task-addressed explain closes A's recorded deviation.**
    `cct routing explain --feature <id> --task <task-id>` resolves
    route class + safety-floor evaluation from `routing-tasks.yaml`
    and renders A's candidate table for that route class. It stays
    PURE configuration resolution (A's must-not list: no network, no
    state writes — proven by the same PATH-shim + byte-identity
    harness); it reads the two artifacts read-only. `--task` without
    `--feature`, an unknown task id, or a missing artifact are named
    refusals.

## Deliberately NOT in this slice (flagged deviations)

- **Static quality checks** (dead code, duplication, complexity —
  umbrella §7 "where supported"): NOT in C. C's quality gates are
  scope, verifiers, budgets, and thrash; language-aware static
  analysis is deferred (E or a dedicated slice) because this repo's
  verifier contract (#190) is the authoritative quality surface and a
  half-supported linter matrix would be a silent quality claim.
  Reconciliation (decision 9) is the compensating control.
- **Scenario 7 residue**: automatic reconciliation of outstanding
  provisional work at provider RECOVERY is increment D's failback
  hook; C ships the reconciliation machinery invocable any time
  Tier-1 is eligible.
- **"Pushed as WIP"** (umbrella §7): C commits WIP driver-owned but
  adds NO auto-push — pushing remains governed by the repository's
  existing review/push policy.
- **Route-class inference** (regex/LLM proposal of classes): never in
  C; metadata is operator-authored.
- **Scheduler integration**: `--delegate`/`--reconcile` are
  operator/driver-invoked per packet in C; a planning loop that walks
  routing-tasks.yaml and dispatches packets automatically is a
  follow-on (it composes from C's parts; shipping it here would blur
  the bounded-packet audit story).
- The `tier2` repo-config key stays refused until this increment
  ships its final task; the promotion is part of C's closure, with
  the restriction-only asymmetry preserved (repo config may forbid
  tier2 delegation, never enable profiles).

## Sequence

T1 routing-tasks.yaml lib + validator + safety floor (admission) ->
T2 packet builder (envelope, determinism, floor re-check) ->
T3 selection legality (route-class-aware rt_select, B byte-compat) ->
T4 supervisor --delegate: packet worktree, bounded session, scope
   check, verifier rounds, repair/thrash/budget ->
T5 ledger verified_provisional + --reconcile flow + independence ->
T6 task-addressed explain + tier2 repo-key promotion ->
T7 docs + CHANGELOG + pins + full sweep + origin refresh.
B cadence: per-task suites + isolated-worktree mutations + review
holds between tasks.

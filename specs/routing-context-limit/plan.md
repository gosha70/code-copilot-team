---
spec_mode: lightweight
feature_id: routing-context-limit
status: draft
date: 2026-08-31
risk_category: policy
justification: >
  Increment F introduces genuine new contract surface — two config keys
  (registry `context_limit`, task `min_context_tokens`), a new
  routing-result field group, a new top-level key in the durable state
  store, and a new filter in the selection ladder. That is more than
  the codex adapter's "mirror an existing backend" shape, so
  spec_mode=none would under-document it; a full bundle would
  over-document a single capability dimension whose rules the owner
  fixed in advance. lightweight carries the Requirements and
  Constraints that the gates can check, and the decisions below carry
  the reasoning that the code cannot state for itself.
origin:
  type: issue
  issue: 109
  parent: 109
  references:
    - "#109 acceptance criteria — 'The actual upstream endpoint/context limit is recorded and enforced.' (the last unmet criterion; endpoint half shipped with increment B)"
    - "#109 §5 step 4 — 'Filter profiles lacking required context, tool, modality, or protocol capabilities.'"
    - "#109 §11 telemetry — 'Actual server context limit and prompt-size decision.'"
    - "#109 §Risks — 'Context overflow: mitigated by enforcing the actual upstream limit rather than the client-advertised limit.'"
    - "#109 §6 classification table — 'Context-window or unsupported-tool error | Mark the profile incompatible with this task; do not mark the complete provider unhealthy.' (the reactive third, already built)"
    - "specs/routing-profile-foundation/audit-2026-08-30.md — the acceptance audit that established 29/31 criteria met and scoped this increment"
    - "owner directive 2026-08-31 — the eight bounding rules reproduced verbatim under 'Owner-fixed rules' below"
    - "scripts/lib/routing-config.sh:437-448 — rc_profile_tuple as the COMPLETE EXECUTABLE IDENTITY backing the monotonic subset invariant"
    - "tests/fixtures .../vllm-context-overflow.out — the recorded capture proving an explicit numeric server maximum is present in real overflow evidence"
---

# Plan: context-limit recording and enforcement (Increment F of #109)

## Owner-fixed rules

The scope was set by the owner after an explicit choice between three
options. These are constraints, not preferences, and the code is
expected to be checkable against them:

1. `context_limit` and `min_context_tokens` are optional positive
   integers.
2. If a task declares a minimum, a profile with no known limit is
   INELIGIBLE — capacity is unproven.
3. Selection uses the conservative limit: `min(declared, applicable
   observed)`.
4. An observation may narrow eligibility, never broaden the operator
   declaration.
5. Parse only an explicit numeric server limit from overflow evidence;
   vague errors remain null and retain existing attempt-local
   incompatibility behaviour.
6. Bind observations to the exact profile execution identity. Do not
   reuse them after provider/model/endpoint identity changes.
7. Record declared, observed, chosen effective limit, evidence source,
   and rejection reason.
8. Do not add probing, pricing, learned policy, or general capability
   frameworks.

## Decisions

**D1 — the executable-identity tuple is a KEY, not a carrier.**
`rc_profile_tuple` is documented as the complete executable identity
and backs a monotonic subset invariant. Adding `context_limit` to it
would make two profiles differing only in a declared window
non-identical, which is wrong: a window is a capability attribute, not
part of what a profile executes as.

The same tuple is, however, exactly the right KEY for rule 6. Hashing
the canonical tuple gives an identity digest that changes the moment
provider, model, endpoint reference, credential reference, backend,
tier, pool, roles, tool profile or data policy change — so an
observation expires by construction rather than by a rule someone has
to remember to write. The limit therefore rides beside the tuple in the
effective document, and the tuple's digest keys the observation.

**D2 — an observation is an UPPER BOUND, never a capacity proof.**
This is the correctness crux and the reason rules 2, 3 and 4 compose
soundly. `maximum context length is 32768` is emitted *while failing*.
It proves the ceiling is at most 32768; it does not prove that 32768
works. So an observed value is only ever applied ON TOP of a
declaration:

| declared | observed | effective | eligible for a task declaring a minimum? |
|---|---|---|---|
| absent | absent | UNKNOWN | no (rule 2) |
| absent | 32768 | **UNKNOWN** | **no** — nothing to narrow; an upper bound is not a grant |
| 200000 | absent | 200000 | yes iff 200000 ≥ minimum |
| 200000 | 32768 | 32768 | yes iff 32768 ≥ minimum |
| 200000 | 400000 | 200000 | observation never broadens (rule 4) |

Row 2 is the one a naive reading gets wrong. Treating a bare
observation as the effective limit would let an overflow *failure*
promote an undeclared profile into eligibility — evidence of a ceiling
misread as evidence of capacity.

**D3 — fail-closed only where a requirement exists.** A task with no
`min_context_tokens` filters nothing, so every existing registry and
feature keeps behaving byte-identically. The fail-closed rule engages
only once someone states a requirement. This is what makes rule 2 safe
to adopt: it cannot retroactively strand an existing configuration.

**D4 — one numeric-extraction pattern, named and separate.** The
observed value comes from its own named pattern applied ONLY to
evidence already classified `invalid_request`, never from a free scan
of arbitrary output. A number appearing in an auth or transport failure
is not a context limit. Vague overflow wording ("prompt is too long"
with no number) records null and changes nothing — rule 5.

**D5 — observations are additive state.** A new top-level
`observations` key in `routing-state.json`, deliberately NOT added to
`rs_read`'s shape validation: an existing state file without it must
keep loading, absent meaning "no observations". Adding it to the shape
check would refuse every live state file on upgrade.

## What ships

- `routing-config.sh`: `context_limit` promoted into
  `RC_PROFILE_OPTIONAL` with positive-integer validation; `rc_effective`
  emits a `context_limits` map (id → declared) beside the candidate
  tuples, plus an `identities` map (id → tuple digest) so selection can
  look up observations without recomputing the tuple.
- `routing-tasks.sh`: `min_context_tokens` promoted into
  `RK_SCALAR_KEYS` with positive-integer validation.
- `routing-state.sh`: `rs_record_context_limit` (write, through
  `rs_apply`'s idempotency) and `rs_observed_context_limit` (read by
  identity digest).
- `routing-select.sh`: a context filter in `_rt_eval`, after the role
  check and before the attempted-set check, computing the effective
  limit per D2 and journaling every rejection in explain vocabulary.
- `routing-result.sh` + `shared/schemas/routing-result.schema.json`:
  `context_limit_declared`, `context_limit_observed`,
  `context_limit_effective`, and `context_limit_evidence`.
- `cooldown-supervisor.sh`: record the observation on an
  `invalid_request` result carrying a number, and journal a
  declared-vs-observed divergence.

## Deviation from the parent, recorded not glossed

#109 §Risks asks to enforce "the actual upstream limit rather than the
client-advertised limit". F enforces `min(declared, observed)` — which
is the actual limit **once one has been observed**, and the advertised
limit before that. It cannot be otherwise: no CLI backend reports its
served context window on a healthy run, so the actual limit is
observable ONLY inside an overflow error. The first overflow on a new
execution identity is therefore always enforced reactively (the
existing `invalid_request` → attempt-local-incompatible → failover
path, unchanged), and only subsequent selections enforce it
proactively.

This is a genuine narrowing of the literal spec text and is recorded
here rather than in prose elsewhere so `check-origin-alignment.sh` can
see it. The compensating control is the reactive path, which was
already built and pinned before F.

## Two wiring decisions, recorded

**W1 — the requirement is read from `routing-tasks.yaml`, not the
packet envelope.** Architecturally the packet is the immutable,
provenance-bound record of a task's constraints, and `route_class`
already lives there, so a context requirement belongs there too. It is
NOT put there because `RP_ENVELOPE_KEYS` is frozen and the envelope is
digest-bound: adding a key would change every packet digest and
invalidate existing packets. Instead the supervisor reads the value
from `routing-tasks.yaml` immediately AFTER `rp_provenance_check` has
verified `routing_tasks_sha256` against that exact file — so the bytes
are proven identical to the ones the packet was built from, and the
read is equivalent to reading the envelope without breaking it. If the
envelope is ever versioned for another reason, this value should move
into it.

**W2 — the filter is wired to BOTH the delegate and reconcile paths.**

This reverses an earlier decision, and the reversal is worth recording
because of *why* the first version was wrong. The filter was initially
wired to delegate only, on the argument that enforcing a builder's
minimum against reviewer profiles would strand `verified_provisional`
work behind reviewers that merely lack a declaration. That argument was
presented as supported by evidence: mutating the code to filter
reconcile produced 18 delegation-suite failures.

**That evidence was invalid.** The 18 failures were an unbound-variable
crash — `PKT_MINCTX` is referenced under `set -euo pipefail` and was
never initialized on the reconcile path — not a semantic signal about
reconciliation at all. A shell crash was read as a design finding.
`PKT_MINCTX` is now initialized globally, and with that fixed,
reconcile filtering passes.

On the merits the owner's call is correct: FR-F3 and the owner rule
attach the minimum to the TASK, not to a role, so an undeclared or
undersized reviewer is ineligible for exactly the reason a builder
would be. Both paths resolve the requirement through the same
fail-closed helper.

## Corrections from the contract review (round 2)

Eight findings, each reproduced before being fixed and each pinned by a
regression that fails when the fix is reverted.

**D7 — an observation store narrows monotonically.** Recording 32768
then 200000 previously *replaced* the bound and re-widened
eligibility. `rs_record_context_limit` now keeps the tightest bound
ever seen for an identity, in either arrival order.

**D8 — reads of durable state fail closed.** A malformed
`observations` store previously fell back to the declared limit —
discarding a proven narrower cap, the exact widening FR-F5 forbids.
`observations` is optional (absence is legitimate), but when present it
must be well-shaped; otherwise selection refuses.

**D9 — identity binds the RESOLVED endpoint.** `base_url_env` names a
variable; two registries naming the same variable can point at
different servers, so a name-only digest let an observation from server
A govern server B. `rc_identity_digest` now hashes the resolved value —
and only there, never in `rc_profile_tuple`, which must stay
environment-independent for the monotonic subset invariant. The digest
is endpoint-sensitive and deliberately NOT credential-sensitive:
rotating a credential leaves it unchanged, so the durable key cannot
become a secret-bearing surface.

**D10 — recovery uses the PERSISTED launch identity.** Replay derived
the key from the live configuration, so a config change between
execution and recovery could attach old evidence to a new
provider/model/endpoint. Every `started-N.json` now records the
launch-time identity, and the recording path reads that.

**D11 — telemetry reports the limit actually enforced.** An attempt
constrained by an earlier observation that then *succeeded* reported
the declaration as effective, contradicting the routing decision the
record exists to explain. `rr_result` now takes the selection-time
prior observation.

**D12 — extraction requires a connector.** The loose pattern turned
`error 42` into a durable 42-token cap and `code 503` into 503, while
rejecting legitimate single-digit limits. The phrase must now be
followed by `is`/`of`/`=`/`:` and the number taken after it.

**D13 — the task lookup is a testable, fail-closed helper.** An
unreadable source became an empty minimum and permitted routing.
`rt_task_min_context` distinguishes a definite absence (rc 0, empty)
from INDETERMINATE (rc 1). It is a named helper rather than inline code
specifically so it can be tested: packet-build validation and
`routing_tasks_sha256` provenance both refuse a malformed source
first, so an integration test stays green on those earlier guards and
would not notice this one being deleted.

**D14 — version boundaries are explicit in both directions.**

| Durable state | Result document |
|---|---|
| pre-F / no `observations` → accept | current version → accept |
| current version → accept | malformed → refuse |
| malformed → refuse | unknown future version → refuse |
| unknown future version → refuse | |

`schema_version` stays 1 and the four context fields stay OPTIONAL in
the JSON schema, so records written before F remain valid; completeness
and internal consistency are enforced at `rr_doc_invariant`, the
runtime boundary that only ever sees documents F itself produced. A
future version is refused outright rather than read optimistically as
today's shape.

## Test strategy

- **Compatibility gate first:** absent `context_limit`, absent
  `min_context_tokens`, absent observations → selection output
  byte-identical to today. This mirrors increment C's
  "tier1_only is byte-identical to the absent argument" pin.
- **The D2 table** becomes five direct assertions, including the row-2
  case (observed without declared stays ineligible), which is the one a
  plausible implementation gets wrong.
- **Identity binding:** an observation recorded under one identity must
  NOT apply after the model/provider/endpoint changes.
- **Extraction:** the recorded `vllm-context-overflow` capture yields
  32768; a vague overflow yields null and leaves behaviour unchanged; a
  number inside a non-`invalid_request` failure is never read as a
  limit.
- Every new assertion is mutation-tested before it is trusted.

## Not planned, explicitly

Probing for limits, pricing, learned policy, general capability or
modality frameworks (rule 8); prompt-size measurement (no backend
exposes it pre-dispatch); observation expiry on a timer — an
observation ends when the execution identity changes, not on a clock.

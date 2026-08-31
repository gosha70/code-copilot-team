# Spec: context-limit recording and enforcement (Increment F of #109)

Increment F closes the one #109 acceptance criterion still unmet:

> The actual upstream endpoint/context limit is recorded and enforced.

The endpoint half shipped with increment B (`routing_decision.endpoint`).
The context half has three parts, of which only one was built:

| Part | Before F |
|---|---|
| Reactive: a context-overflow error marks the PROFILE incompatible for this task, never the provider unhealthy | **built** (`routing-result.sh` `RR_PAT_INVALID` → `routing-actions.sh` `invalid_request`) |
| Recorded: the actual server context limit | absent |
| Enforced: profiles lacking required context are filtered at selection (#109 §5 step 4) | absent |

F builds the second and third.

## Requirements

**FR-F1 — declared limit.** `[[profiles]]` accepts an optional
`context_limit` key: a positive integer, tokens. Absent means
UNDECLARED — never "unlimited".

**FR-F2 — task requirement.** `routing-tasks.yaml` accepts an optional
scalar task key `min_context_tokens`: a positive integer. Absent means
the task states no context requirement, and selection behaves exactly
as it does today.

**FR-F3 — fail-closed eligibility.** When a task declares
`min_context_tokens`, a profile whose effective limit is UNKNOWN is
INELIGIBLE. Capacity is unproven, and an unproven capacity is not a
grant. Every rejection is journaled in explain vocabulary.

**FR-F4 — observed limit.** When a failure classifies as
`invalid_request` AND its evidence states an explicit numeric server
maximum, that number is recorded as the observed limit. Vague overflow
wording records null and retains today's attempt-local incompatibility
behaviour unchanged.

**FR-F5 — conservative effective limit.** Selection uses
`min(declared, applicable observed)`. An observation may only narrow;
it may never broaden the operator's declaration.

**FR-F6 — an observation is an upper bound, not a capacity proof.**
`maximum context length is 32768` was emitted while FAILING. It proves
the ceiling is at most 32768; it does not prove 32768 works. Therefore
an observed limit is only ever applied ON TOP of a declaration. With no
declaration there is nothing to narrow, and the profile remains
UNKNOWN (and so ineligible under FR-F3) no matter what was observed.

**FR-F7 — identity-bound observations.** An observation binds to the
exact profile EXECUTION IDENTITY that produced it, not to the profile
id. When provider, model, endpoint reference, credential reference,
backend, tier, pool, roles, tool profile or data policy change, the
observation no longer applies and the profile returns to its declared
limit. The binding is to the RESOLVED endpoint, not the
environment-variable name, and is deliberately insensitive to
credential values so the durable key never carries a secret. Recovery
compares against the identity PERSISTED at launch, never one
re-resolved from the current configuration.

**FR-F8 — recorded fields.** Each routed attempt records: the declared
limit, the observed limit, the chosen effective limit, the evidence
source for the observation, and — on a context rejection — the
rejection reason.

**FR-F9 — durable state narrows monotonically.** A recorded
observation may only ever be replaced by a TIGHTER one. A later, wider
reading is discarded.

**FR-F10 — reads of durable state fail closed.** Absence of the
observation store is legitimate and reads as "unobserved". A store that
is present but malformed REFUSES; it must never degrade to "absent",
which would discard a proven cap and widen eligibility.

**FR-F11 — explicit version boundaries.** For both the durable state
and the result document: a pre-F/current-version record is accepted, a
malformed one is refused, and an unknown FUTURE version is refused
explicitly rather than interpreted as today's shape.

## Constraints

- **No new selection path.** The context filter joins the existing
  `_rt_eval` ladder in `routing-select.sh`. One candidate evaluator
  serves every route class; that must remain true.
- **The executable-identity tuple is not extended.** `rc_profile_tuple`
  is the complete executable identity backing a monotonic subset
  invariant. A declared window is a capability attribute, not part of
  what a profile executes as; two profiles differing only in a declared
  window must remain the same identity. The limit rides BESIDE the
  tuple; the tuple is used as the identity KEY for observations
  (FR-F7), which is exactly what it is for.
- **Backward compatible by construction.** A registry with no
  `context_limit`, a feature with no `min_context_tokens`, and a state
  file with no observations must all behave byte-identically to today.
  This is the compatibility gate, tested as one.
- **State-store compatibility.** Observations live under a new
  top-level key in `routing-state.json`. It is NOT added to the
  `rs_read` shape check — an existing state file without it must keep
  loading, absent meaning "no observations".
- **Closed vocabulary discipline.** Both new keys follow the repo's
  refused → implemented → tested promotion path: accepted only
  together with the behaviour that enforces them.
- **Out of scope, deliberately:** probing for limits, token→USD
  pricing, learned or adaptive routing policy, and any general
  capability/modality framework. F ships exactly one capability
  dimension.

## Non-goals

- Inferring a limit from anything other than an explicit numeric server
  maximum in overflow evidence.
- Any prompt-size *measurement*. #109 §11 names "prompt-size decision";
  F records the limits that bound it, not a token count of the outgoing
  prompt, which no CLI backend exposes before dispatch.
- Re-verifying or expiring an observation on a timer. An observation
  ends when the execution identity changes (FR-F7), not on a clock.

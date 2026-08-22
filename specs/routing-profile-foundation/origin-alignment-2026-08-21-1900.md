# Origin Alignment Check — routing-profile-foundation

Date: 2026-08-21 19:00 (record opened)
Last revised: 2026-08-22 — T6 build-completion revision (T1–T6 built;
this revision is the fresh record T6 requires; supersedes the
spec-heading-conformance stamp)
Trigger: rev-1 SDD bundle authored for increment A of #109 at the
owner's direction ("I want you to work on this enhancement so I can
optimize my token usage with external LLM").

## Origin sources read

- #109 (the umbrella) in full — Summary, Problem, Goals, Terminology,
  Proposed Architecture §1 (registry), §2 (project restrictions),
  §5 (deterministic selection / explain), §6 (structured result),
  Acceptance Criteria "Configuration and contracts", Delivery Plan
  Increment A, Non-Goals, Backward Compatibility.
- The owner's stated motivation in the request itself: optimize token
  usage with an external LLM — i.e. the continuity/cost objective, not
  a speed objective (§Summary makes the same distinction).
- benchmarks/README.md backend contract (backend/model separation
  Increment A must reuse).
- scripts/providers-health.sh (`toml_get` minimal-TOML idiom),
  scripts/cct (dispatcher with planned-command slots),
  ~/.code-copilot-team/ (existing user-level config home holding
  providers.toml).
- knowledge/wiki/playbooks/drive-claude-code-with-local-vllm.md — the
  documented local-provider failure sequence feeding the classifier
  corpus.

## Working claim

Increment A = exactly the umbrella's "Execution-profile foundation"
bullet list: profile schema + validator; vocabulary; project trust and
policy merge; normalized backend result; `routing validate/status/
explain`; benchmark vocabulary reuse. Deliberately inert at runtime —
no build is routed, no state is written, no driver/supervisor/reviewer
path changes. Token-usage optimization itself arrives with B (Tier-1
failover) and C (Tier-2 bounded work); A is their load-bearing
contract layer.

## Mismatches / deviations from the origin sketch

- **`explain` takes `--route-class`, not `--feature/--task`.** The
  umbrella's example is `routing explain --feature <id> --task
  <task-id>`; task route metadata is Increment C's deliverable, so in
  A there is no task to resolve a class from. A's explain addresses
  the same explainability requirement at the config level and states
  in its output that it explains configuration, not availability. The
  task-addressed form arrives with C. Deviation flagged, not absorbed.
- **Repo `routing` block lands restriction keys only.** The umbrella's
  illustrative repo config shows `tier2` and `recovery` objects; those
  are C/D policy surfaces, refused by name until their increments ship
  (C1's established pattern), so a repo cannot configure semantics
  nothing enforces yet.
- **`status` reads a state file B owns.** The umbrella's provider-state
  section (§8) is Increment D-adjacent; A defines only the read side
  ("absent => every profile unknown") so the command surface is
  complete without inventing state semantics B/D own.

## Plan review round 1 (owner) — approved with two amendments

Architecture approved; A's inertness boundary and the three deviations
above all endorsed (explain stays config-level and gains an explicit
purity contract; refuse-by-name for future repo keys "strongly
approved"; status pinned to registry/policy state only, never a second
providers-health). Two required amendments, both applied before the
child issue was filed:

1. **Failure taxonomy frozen around CAUSE, not provider wording**
   (decision 5 rewritten): outcome success|failure +
   `quota_exhausted / rate_limited / unavailable / transport / auth /
   invalid_request / denied / execution / unknown`, metadata beside
   the enum, B owns class->action, `unknown` fails closed, fixtures
   pin raw->exactly-one-class with a weakened-pattern mutation. One
   flagged delta from the reviewer's core eight: `denied` is kept as
   a cause class because the umbrella's Scenario 8 (a policy denial is
   never rerouted around) makes it load-bearing; `invalid_request`
   absorbs context/tool incompatibility as profile-scoped cause.
2. **Constrained TOML dialect made explicit** (decision 1 rewritten):
   routing.toml accepts only the subset CCT implements; enumerated
   accepted grammar; duplicate keys/tables, dotted keys, inline
   tables, multiline strings, malformed quoting rejected by name —
   never approximated.

Also pinned from the same review: the trust asymmetry as an executable
subset invariant (decision 4, T4); tier vocabulary stays CLOSED
(`tier1|tier2` — semantic framework classes; priority/profile/pool are
the operator-defined knobs); credential hygiene reworded as structural
boundary with the value scan as defense in depth (decision 3).

## Build completion (T1–T6)

The build landed inside the recorded claim; the per-task reviews
produced contract tightenings, all execution-contract rather than
scope: T1's [policy] accepts only what A consumes (behavior-bearing
keys refused until owned — the promotion workflow is recorded in the
lib); T2's taxonomy gained the bidirectional success/failure
invariant at BOTH layers plus the ambiguous-permission_error pins;
T3's refusals are three named tiers proven load-bearing by mutation;
T4's subset invariant compares canonical collision-free JSON tuples
(roles as a set) after the review caught that naive delimiter joining
was not injective — and the generated matrix caught a real jq
`//`-operator defect that silently turned an explicit repo
enabled=false back into true; T5's three commands carry an executable
purity contract (network shim, byte-identical state) with T3
validation structurally preceding composition for every consumer.

The three recorded deviations shipped as recorded (config-level
explain awaiting C's task metadata; restriction-only repo keys with
tier2/recovery refused; read-only status over B-owned state).
Deferred scope is unchanged: #109 increments B (failover/circuit
state/checkpoints), C (Tier-2 task routing + reconciliation), D
(probes/recovery/failback/routing tick), E (benchmarks + shadow-mode
learning) — recorded on #248 with T6.

## Verdict

Verdict: aligned
Confidence: high

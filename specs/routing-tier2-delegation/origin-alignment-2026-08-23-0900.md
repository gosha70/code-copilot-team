# Origin Alignment Check — routing-tier2-delegation

Date: 2026-08-23 09:00 (record opened)
Last revised: 2026-08-23 — plan review round 1 (owner): four contract
amendments applied (see below); GO granted; child issue #254 filed
and stamped into plan.md frontmatter (origin previously anchored on
the umbrella pending the child)
Trigger: rev-1 SDD bundle authored for increment C of #109 at the
owner's direction ("my vote for the next roadmap slice is: carve
Increment C"), immediately after increment B (#251) merged via PR
#253. The child issue is filed on plan-review GO; until then the
origin anchors on the umbrella.

## Origin sources read

- #109 §Delivery Plan Increment C (the six deliverable bullets), §3
  (route classes; the mandatory Tier-1-forced category list; the
  Tier-2 task declaration fields), §4 (the backend-neutral packet —
  the illustrative envelope C now makes normative), §7
  (quality-preserving continuation: minimal tool profile, exact
  file-scope enforcement, protected verifier/test files, bounded
  repair + thrash, verified_provisional, the five-step Tier-1
  reconciliation), Scenarios 5–6, Acceptance §Quality preservation.
- The owner's carving directive (2026-08-22 session message): the
  architectural rule stated verbatim in spec.md's opening — "Tier-2
  is delegated bounded work, not another unrestricted failover
  target"; bounded task in, durable evidence out, reconciliation
  before authority.
- specs/routing-profile-foundation/ — A's frozen registry/merge/
  taxonomy/explain surfaces; A's origin record carries the recorded
  deviation (task-addressed explain deferred to C) that decision 10
  closes.
- specs/routing-tier1-failover/ — B's frozen result envelope, crash
  ordering, state store, selection oracle, launch wiring, and
  independence gate, all consumed unchanged (decision 4/8/9).
- shared/schemas/verification.schema.json + the verification.yaml
  contract (#190 C1–C3, merged) — the per-FR statement_sha +
  deterministic `test` verifier commands that packets quote verbatim;
  #109 names this dependency explicitly ("depends on the required
  #190 verification-contract slices").

## Working claim

Increment C = the umbrella's "Tier-2 task routing" bullets on A+B's
frozen contracts: operator-authored task route metadata with a
structural safety floor, deterministic driver-built packets, bounded
fresh-session execution under a minimal tool profile with driver-owned
scope + verifier enforcement and bounded repair, `verified_provisional`
as a gate-satisfying-nothing ledger state, Tier-1 reconciliation with
B's independence gate, route-class-aware selection legality, and the
task-addressed explain form. This delivers the deliberate
cost/capability half of the owner's token-optimization motivation.

## Mismatches / deviations from the origin sketch

- **Static quality checks deferred** (§7 "static checks for dead
  code, unused values, duplication, and excessive complexity where
  supported"): not in C. The repo's authoritative quality surface is
  the #190 verifier contract; C enforces scope, verifiers, budgets,
  and thrash, with Tier-1 reconciliation as the compensating control.
  A half-supported language matrix would be a silent quality claim.
  Flagged for explicit review, not absorbed.
- **Scenario 7's reconcile-on-recovery trigger is D's**: C ships the
  reconciliation machinery invocable whenever Tier-1 is eligible;
  wiring it to failback events belongs to increment D's
  recovery/hysteresis loop.
- **No auto-push of WIP** (§7 says provisional work "may be committed
  and pushed"): C commits WIP driver-owned only; pushing stays under
  the repository's existing review/push policy. Narrower than the
  origin sketch, deliberately.
- **No automatic packet dispatch loop**: §Delivery Plan's bullets are
  satisfied per packet (`--delegate`/`--reconcile` invoked by
  operator/driver); a planner that walks routing-tasks.yaml and
  dispatches automatically composes from C's parts as a follow-on.
  Scenario 5's "continue other independent Tier-2-safe tasks" is
  therefore satisfiable by repeated bounded invocations, not by an
  autonomous scheduler inside C.
- **Oscillation detection folded into the repeated-failure
  signature** (§7 lists "oscillating approaches" separately): an
  A/B/A oscillation reproduces a prior round's normalized failure
  signature and terminates via `packet_thrash_repeated_failure`; no
  separate oscillation heuristic is claimed.

## Plan review round 1 (owner) — HOLD, four amendments, then GO

All four judgment calls approved (supervisor as the seam; strict
tier2_fallback; floor mappings as implementation surface; no
autonomous dispatcher), and the recorded deviations accepted — the
static-quality deferral explicitly CONDITIONAL on reconciliation
remaining a real promotion boundary, which amendment 2 enforces.
Amendments applied to plan.md/spec.md/tasks.md, all
execution-contract rather than scope:

1. **Provenance-bound immutable packet** (decision 3/4): the packet
   is C's immutable unit, as result-N.json is B's — packet_id +
   digest + source-artifact digests; the frozen five-step
   point-of-use sequence for --delegate (validate envelope, verify
   digest, worktree from recorded base_commit, provenance re-check,
   execute from the packet alone — never rereading mutable
   artifacts); drift refuses as `packet_provenance_drift`, never a
   silent rebuild; --reconcile binds to the same packet/provisional
   result.
2. **Positively established reconciliation independence** (decision
   9): B's evaluator reused unchanged, C applies a stronger
   disposition at the promotion boundary — `not_independent` AND
   `unevaluable` both fail closed with their own named reasons;
   promotion is impossible when independence cannot be established.
   B's own non-blocking unevaluable disposition is untouched.
3. **Cumulative scope/budget, phase-universal, fresh attempts**
   (decisions 5/6): scope/safety → verifiers frozen for ALL
   modifying phases (initial, each repair, reconciliation);
   accepted_with_changes cannot escape the packet scope; the
   changed-line budget measures diff(packet.base_commit, worktree),
   never per-round; every repair/reconciliation launch is a fresh
   B-style supervised attempt (own attempt id/result/checkpoint) —
   worktree persists, sessions never; no C-only lifecycle.
4. **Fallback unlock pinned to B's selector shapes** (decision 8):
   the three-shape predicate is the executable definition;
   considered[] stays evidence-only; terminal outcomes from actual
   Tier-1 attempts (denied, unknown, identity mismatch, independence
   refusal, crash ambiguity) remain terminal and never become a
   fallback opportunity.

## Verdict

Verdict: aligned
Confidence: high

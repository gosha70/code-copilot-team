# Tasks: Tier-2 delegation + reconciliation — increment C of #109

Sequential; hold for user review between tasks. Contracts live in
`plan.md` (decisions) and `spec.md` (FR-C/SC-C); tasks reference,
never restate.

## T1 — Task metadata + safety floor (admission)

- `scripts/lib/routing-tasks.sh` per decisions 1–2: constrained
  parse/validate/lookup, closed route classes, fr_refs bound to
  verification.yaml, acyclic depends_on, path containment, the
  closed floor vocabulary with per-category pattern sets, admission
  refusal of `tier2_*` on in-floor tasks; `cct routing validate`
  picks the artifact up when present; absent metadata resolves
  tier1_only.
- Pre-commit mutation floor: each named refusal proven refusing;
  floor-category bypass mutations must be caught per category.
- Covers SC-C1, SC-C2 (admission half).

## T2 — Packet builder

- `scripts/lib/routing-packet.sh` per decision 3: closed versioned
  IMMUTABLE envelope from frozen inputs — packet id + digest +
  source-artifact provenance digests, verbatim verifier commands +
  statement_sha, single-capture diff hash, dependencies_complete
  computed, floor re-check at build (SC-C2 build half),
  byte-identical regeneration; digest-mismatch and
  `packet_provenance_drift` refusals proven (decision-4 validation
  steps 1–2 + 4 live in this lib for both --delegate and
  --reconcile).
- Covers SC-C2 (build half), SC-C3.

## T3 — Selection legality

- Route-class-aware `rt_select` per decision 8: optional argument,
  absent → B byte-identical (B suite unmodified); the four class
  behaviors; tier2_fallback's unlock pinned to B's selector output
  shapes (temporary-exhaustion shape waits + re-selects; only the
  `routing_no_eligible_profile` shape unlocks; `considered[]` never
  inspected; terminal attempt outcomes never unlock); output
  shapes/total order unchanged within tier.
- Covers SC-C8.

## T4 — Bounded packet execution

- Supervisor `--routing --delegate <task-id>` per decisions 4–6: the
  frozen five-step point-of-use sequence (envelope validation, digest
  verify, worktree from the packet's recorded base_commit, provenance
  check, packet-only execution — no reread of mutable artifacts),
  minimal tool profile, B's frozen launch/crash/idempotency chain
  reused unchanged with each repair round a fresh supervised attempt
  (own attempt id/result/checkpoint; worktree persists, sessions
  never), CUMULATIVE scope-before-verifiers enforcement against
  base_commit with revert, verifier-decided rounds, RC_* bounded
  repair with the CUMULATIVE changed-line budget, the three thrash
  signatures + budget as a closed terminal enum.
- Legacy + B byte-compatibility proven (both suites unmodified).
- Covers SC-C4, SC-C5.

## T5 — Provisional state + reconciliation

- Decisions 7 + 9: `verified_provisional` ledger state with full
  evidence, never gate-satisfying, unrouted/undelegated ledgers
  byte-identical; `--reconcile <task-id>` bound to the immutable
  packet + provisional result, the reconcile role, B's independence
  EVALUATOR with C's fail-closed disposition (`independent` proceeds;
  `reconcile_not_independent` and `reconcile_independence_unevaluable`
  both refuse promotion — all three states proven), reconciler edits
  under the same cumulative scope/protections (escape refused),
  re-verified `accepted | accepted_with_changes | rejected`,
  rejected reverts.
- Covers SC-C6, SC-C7.

## T6 — Task-addressed explain + tier2 key promotion

- Decision 10: `cct routing explain --feature --task` (pure, shim +
  byte-identity proven); the repo-config `tier2` key promoted
  refused→implemented→behaviorally-tested, restriction-only.
- Covers SC-C9; closes A's recorded explain deviation.

## T7 — Docs, gates, sweep

- README (Tier-2 delegation section beside A/B, opening with the
  bounded-work rule), CHANGELOG, count pins, full sweep, origin
  build-completion revision, deferred-scope record on the child
  issue.
- Covers SC-C10.

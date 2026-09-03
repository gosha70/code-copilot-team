# Origin alignment — session-analytics-similarity-cluster (E2 slice 3)

Verdict: aligned
Confidence: high

## Origin capture

Issue #289, opened as slice 3 of tracker #65's E2, immediately after
slice 2 (#287, PR #288) merged at `a4a65f9` and was closed. The owner
instructed "proceed to the next phase" after confirming #65's
remaining E2 inventory: "clustering and a similarity UI, neither
shipped here." Clustering is taken first because it builds directly
on the just-merged similarity substrate and the UI can then render
both; the UI remains its own slice on #65.

## The governing order, and where it binds

Inherited from the arc and restated in the issue before any design:

1. **Compatibility evidence precedes clustering semantics.** spec.md
   pins the DOMAIN first (FR-A: the reconciled `SIMILAR_TO` snapshot,
   one FR-A space per cluster — structural, but still asserted by a
   discriminator test) before defining what a cluster is (FR-B).
2. **Limitations stated deliberately, the FR-B discipline.** A
   cluster is a transitive discovery grouping — a component links A
   and C through B even when they share no edge — and every surface
   must say so rather than imply pairwise similarity. Snapshot
   semantics ("clusters describe the last completed `similar` pass")
   and the inherited name/tag limits are restated, not re-derived.
3. **The materialization question is an explicit fork.** V1 computes
   on read; materialized clusters would be derived state over derived
   state, needing the full #287 reconciliation discipline for zero
   current value. The upgrade path is recorded for the UI slice.

## Decisions taken on this plan's authority (flagged for review)

- **D1 components, not parametric clustering** (zero parameters,
  zero dependencies; alternatives recorded in Non-goals).
- **D2 compute-on-read** (the fork above).
- **D3 undirected adjacency** over the directed top-K edges.
- **D4 size >= 2** — edgeless sessions are "unclustered", never
  singleton clusters.
- **D5 read-only graph access everywhere**, absent-path prechecks,
  zero-creation assertions (the #287 T3 lifecycle).
- **D6 no new config keys** — clustering has no tunables in V1.
- **Space attribution left structural, not printed:** the graph alone
  cannot attest the space triple without envelope reads the snapshot
  rule forbids, so surfaces guarantee one-space-per-cluster instead
  of printing a triple — explicitly flagged in plan.md for the owner
  to overrule at plan review if the triple is wanted.

## What this record does NOT claim

- Plan-only: no code exists at submission.
- Nothing here makes E2 complete on #65 — the Studio UI slice remains,
  and E2 completeness is the owner's call.
- The materialization and algorithm forks are DEFINED, not promised.

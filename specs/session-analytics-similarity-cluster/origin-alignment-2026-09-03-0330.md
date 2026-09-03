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
   semantics ("clusters describe the `SIMILAR_TO` edges the graph
   currently holds") and the inherited name/tag limits are restated,
   not re-derived.
3. **The materialization question is an explicit fork.** V1 computes
   on read; materialized clusters would be derived state over derived
   state, needing the full #287 reconciliation discipline for zero
   current value. The upgrade path is recorded for the UI slice.

## Decisions taken on this plan's authority (flagged for review)

- **D1 components, not parametric clustering** (zero parameters,
  zero dependencies; alternatives recorded in Non-goals).
- **D2 compute-on-read** (the fork above).
- **D3 undirected adjacency** over the directed top-K edges, with the
  reported count named `directed_edge_count` (A→B and B→A are two
  records, one adjacency).
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

## Correction pass after plan review (PR #290)

The review authorized the scope (components, compute-on-read, no new
dependencies or knobs; transitive chaining accepted with the
disclosed limitation) and returned two contract corrections — no
redesign. Both applied across spec, plan, tasks, AND issue #289:

1. **Space attribution reconciled to the smaller V1** (P1). The
   scenarios, FR-E/FR-F, and the issue promised per-space reports or
   a shared-space value while plan.md omitted the information — an
   unimplementable contradiction. Resolved as the owner recommended:
   UNNAMED components, no per-space grouping promise anywhere,
   compatibility inherited from the similarity producer and asserted
   by the two-space discriminator. The current-envelope join is
   rejected outright, on reproduced evidence: re-embedding a member
   under another model leaves its old edges unchanged, so current
   envelopes cannot attest the historical space of stored edges.
2. **Stored-edge semantics separated from the current graph
   inventory** (P2). Reproduced: an incremental `graph` run moved
   nodes 2→3 and unclustered 0→1 while both similarity edges stayed
   unchanged — so the whole report cannot be frozen to the `similar`
   pass or byte-identical from unchanged edges alone. Pinned:
   membership derives from stored edges; the unclustered count from
   the current node inventory; the report labels both provenances;
   FR-C determinism is defined over the (edges, inventory) pair; and
   for session-id lookup a relational session absent from the graph
   gets `similar_sessions`' existing `prerequisite: "graph"` response
   (#287 discipline), never "unclustered". No snapshot storage added.

## Second correction pass — re-review of PR #290

A re-review at the owner's request checked the bundle against the
merged #285/#287 code rather than its own prose. The substrate claims
verified sound (`GraphNotReadyError`, `connect_read_only`,
`_FakeEdgeStore`, the `SIMILAR_TO` row shape, the five registered MCP
tools, `kuzu_path` plumbing). Three bounded corrections, no redesign,
still plan-only:

3. **The first correction pass's residue removed.** plan.md's Shape
   still described `run_clusters` as returning "per-space cluster
   stats" — the exact promise correction 1 deleted everywhere else,
   surviving in the line a builder reads first. Now: unnamed
   whole-snapshot component stats.
4. **No invented MCP outcome.** The bundle used `missing_graph_node`
   as though it were an MCP response key. In #287 it is only a
   counter field on `similar`'s CLI stats; the MCP answer to that
   condition is `prerequisite: "graph"` with "graph node" in the
   error, pinned by the #287 test
   `test_missing_graph_node_gets_graph_sync_guidance`. Taken
   literally the bundle would have introduced a new literal while the
   same bullet demanded consistency with `similar_sessions`. The real
   response shape is now named.
5. **`directed_edge_count` defined as stored DIRECTED records** (A→B
   and B→A count as two, forming one undirected adjacency), with the
   reciprocal fixture added to T1's expectations. Grouping stays
   undirected; only the count is directed. Previously unstated, and
   the two numbers diverge on every reciprocal pair — an arbitrary
   implementation choice that T2's deterministic-bytes assertion would
   have frozen.

Two adjacent wording errors fixed in the same pass, both owner-flagged:
FR-A no longer claims the stored edges are "untouched by anything
else" (`graph --rebuild` drops and recreates the rel tables via
`graph/schema.py:reset_schema`, so the store attests present contents,
never pass history); and #289's prerequisite-failure list no longer
includes "no edges", which is the healthy-empty exit-0 case.

The `graph_ready()` duplication between the read-only `GraphSnapshot`
and the write-capable `KuzuEdgeStore` is ACCEPTED and recorded in D5 —
no shared-helper refactor, so a later review does not re-raise it.

Still plan-only; no code exists.

## What this record does NOT claim

- Plan-only: no code exists at submission.
- Nothing here makes E2 complete on #65 — the Studio UI slice remains,
  and E2 completeness is the owner's call.
- The materialization and algorithm forks are DEFINED, not promised.

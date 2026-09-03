# Spec: E2-cluster — session clustering over the similarity snapshot

Issue #289, slice 3 of E2 from tracker #65. Slice 1 (#285, merged
`8e9ee49`) created validated provenance envelopes; slice 2 (#287,
merged `a4a65f9`) populated `SIMILAR_TO` inside compatibility-proven
embedding spaces. This slice groups — and inherits the arc's
governing order:

> **Compatibility evidence precedes clustering semantics.** A cluster
> is only ever defined WITHIN one embedding space. Nothing below
> defines a grouping rule until the domain it groups over — the
> reconciled `SIMILAR_TO` snapshot — is pinned, and every limitation
> a cluster inherits from that snapshot is stated deliberately.

## User Scenarios

1. **"What themes are in my session library?"** An operator runs
   `clusters` after `embed` + `similar` and sees the groups of
   mutually-reachable similar sessions, per embedding space, largest
   first — a map of recurring work, from stored evidence only.
2. **An agent asks for a session's cohort over MCP.** Given a session
   id, the tool returns the cluster that session belongs to — its
   siblings, with the shared space and `basis: "embedding"` — or an
   honest "unclustered" when the snapshot holds no edge for it.
3. **A mixed-model library stays honest.** Clusters never span
   embedding spaces; the report shows clusters grouped by space, so
   fragmentation from multiple models is visible, never papered over.
4. **A healthy empty answer.** A ready graph whose last `similar`
   pass wrote no edges (singleton spaces, below-threshold scores)
   yields zero clusters with exit 0 — absence of clusters is a
   result, not a failure; guidance is reserved for independently
   established prerequisites (absent/uninitialized graph).

## Requirements

### FR-A — the cluster domain, defined FIRST

Clusters are computed over exactly the **reconciled `SIMILAR_TO`
snapshot** — the edge set written by the last COMPLETED `similar`
pass (#287 FR-D/FR-E). Consequences, each a requirement and not an
accident:

- **One space per cluster.** `SIMILAR_TO` edges exist only inside one
  FR-A space `(provider, model, dim)` — pairs are formed inside
  groups, structurally (#287 D1) — so no component can span spaces.
  This slice must still assert it: a discriminator test seeds two
  spaces with internally-similar sessions and proves no cluster mixes
  them.
- **Snapshot semantics.** Clusters describe the last completed
  `similar` pass. Nothing in this slice reads envelopes, recomputes
  similarity, or contacts a backend; an operator who wants fresh
  clusters re-runs `similar` first. Relational changes made after
  that pass (new sessions, invalidated envelopes) are invisible here
  until the next pass — by design, and the report says so.
- **Inherited evidence limits.** Cluster membership inherits FR-B's
  name/tag guarantee verbatim: same recorded backend family, served
  name/tag, and geometry — never model-version identity.

### FR-B — what a cluster IS, and what it does NOT claim

V1 clusters are the **connected components of the undirected view of
the `SIMILAR_TO` snapshot**, restricted to components with two or
more members.

- The `similar` pass writes directed per-source top-K edges; two
  sessions are adjacent here iff at least one directed edge exists
  between them in either direction (scores are symmetric; top-K
  membership is not — #287).
- **Guaranteed:** every pair of members is connected by a chain of
  recorded, above-threshold edges from one completed pass, entirely
  within one embedding space.
- **NOT guaranteed — stated deliberately, the FR-B discipline:** a
  component links A and C through B even when score(A, C) is below
  the threshold, or when A and C share no edge at all. A cluster is a
  **transitive discovery grouping**, not a pairwise-similarity
  guarantee; any surface that shows a cluster must not imply
  all-pairs similarity.
- Sessions present in the graph with no incident `SIMILAR_TO` edge
  are **unclustered** — counted and reportable, never padded into
  singleton "clusters".

### FR-C — deterministic identity and order

- A cluster's identity is its **lexicographically smallest member
  `session_key`** — stable across runs on the same snapshot, with no
  RNG, no iteration-order dependence, no timestamps.
- Members are reported sorted by `session_key`; clusters are reported
  in a deterministic order (descending size, then ascending cluster
  identity). Two runs over the same snapshot must produce
  byte-identical reports.

### FR-D — compute-on-read (the materialization fork, decided)

V1 **computes clusters on read** and materializes nothing: no new
node/rel tables, no relational columns, no DDL change.

- Rationale: a materialized cluster assignment is derived state over
  derived state — it would need the full #287 FR-D reconciliation
  discipline (retirement, torn-pass protection, staleness rules) for
  zero added value while nothing consumes stored clusters. The
  snapshot is small (per-space session counts from `similar`'s own
  report); components over it are cheap.
- The fork is recorded, not foreclosed: if the Studio UI slice needs
  server-side cluster pagination or cluster-stability tracking across
  passes, materialization becomes its own decision there, with this
  spec's identity rule (FR-C) as the stable key.

### FR-E — the CLI surface

`./scripts/session-analytics clusters` (flags: `--dsn`, `--db-path`):

- Opens the graph with the **non-creating read lifecycle** (#287:
  `connect_read_only`; absent path is refused BEFORE any open, with
  zero filesystem creation, asserted in tests).
- Prerequisite ladder, mirroring `similar`'s exit-code discipline:
  absent graph path → usage error with "run graph first" guidance;
  ready-but-unbuilt graph (no `Session` table) → usage error; a
  ready graph with zero edges → **exit 0**, healthy empty report.
- Report: clusters grouped by space — identity, size, members, edge
  count — plus the unclustered-session count and a snapshot note
  ("clusters describe the last completed `similar` pass").
- No new config keys: clustering has no tunable parameters in V1
  (threshold and top-K belong to `similar`, where the edges are
  decided). The CLI must not grow speculative knobs.

### FR-F — the MCP surface

One tool, `session_clusters`, registered beside the existing five:

- `session_clusters(session_id=None, limit=10)`: with a session id,
  returns that session's cluster (siblings, shared space, edge
  count) or an honest `"unclustered"` outcome; without one, lists
  clusters (largest first, up to `limit`).
- Basis honesty: results carry `basis: "embedding"` and the snapshot
  note; they must never imply pairwise similarity (FR-B) or
  masquerade as keyword results.
- Prerequisite ladder consistent with `similar_sessions` (#287 FR-F):
  unknown session → error; absent/unopenable graph → `prerequisite:
  "graph"` with guidance; unbuilt graph → same; healthy empty (ready
  graph, no edges) → an honest empty result, no remedial default.
- The graph open is `connect_read_only` — the MCP read path cannot
  create or mutate the store (#287 T3 capture), and a
  disappearing-path race must be refused, not repaired.

## Non-goals

- The Studio similarity/clustering UI — its own slice on #65.
- Materialized cluster storage (FR-D records the upgrade path).
- Parametric or density-based algorithms (k-means, HDBSCAN, label
  propagation): all need parameters and/or new dependencies V1
  refuses; if transitive chaining proves too coarse in practice,
  algorithm choice becomes its own evidence-backed slice.
- Per-cluster KPI aggregates — deferred until the UI slice defines
  what it actually consumes.
- Anything touching embeddings: no backend calls, no envelope writes,
  no digest provenance, no live text-query embedding (all deferred as
  recorded on #287).

## Constraints

- **No new dependencies** (stdlib only; kuzu stays lazy and optional
  exactly as today) and **no schema changes** of any kind.
- **Read-only graph access everywhere in this slice** — no code path
  may open the graph create-capable or write to it.
- **Determinism** (FR-C) across runs and platforms.
- **No new config keys, env vars, or defaults** — nothing for the
  five-layer config to carry.
- Suites green under both pythons; the kuzu+mcp verification mode
  (zero skips) exercises the live read path; mutation-ledger evidence
  at closure per the arc's discipline.

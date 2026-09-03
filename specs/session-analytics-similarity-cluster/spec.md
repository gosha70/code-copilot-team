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
   mutually-reachable similar sessions, largest first — a map of
   recurring work, from stored evidence only.
2. **An agent asks for a session's cohort over MCP.** Given a session
   id, the tool returns the cluster that session belongs to — its
   siblings, with `basis: "embedding"` — or an honest "unclustered"
   when the stored edges hold none for it.
3. **A mixed-model library stays honest.** Clusters never span
   embedding spaces — inherited structurally from the similarity
   producer — but this slice reports UNNAMED components and promises
   no per-space grouping: space fragmentation is `similar`'s report
   to give (it reads the envelopes; this slice never does).
4. **A healthy empty answer.** A ready graph whose last `similar`
   pass wrote no edges (singleton spaces, below-threshold scores)
   yields zero clusters with exit 0 — absence of clusters is a
   result, not a failure; guidance is reserved for independently
   established prerequisites (absent/uninitialized graph).

## Requirements

### FR-A — the cluster domain, defined FIRST

Clusters are computed over exactly the **reconciled `SIMILAR_TO`
snapshot** — the `SIMILAR_TO` edges the graph holds at read time,
which a completed `similar` pass reconciles when it runs (#287
FR-D/FR-E). Consequences, each a requirement and not an accident:

- **One space per cluster — guaranteed, never named.** `SIMILAR_TO`
  edges exist only inside one FR-A space `(provider, model, dim)` —
  pairs are formed inside groups, structurally (#287 D1) — so no
  component can span spaces. This slice must still assert it: a
  discriminator test seeds two spaces with internally-similar
  sessions and proves no cluster mixes them. But components are
  reported **unnamed** (plan-review decision): the graph attests no
  triple, and a join against CURRENT envelopes cannot attest the
  HISTORICAL space of stored edges — re-embedding a member under
  another model leaves its old edges unchanged (reproduced at plan
  review), so a current-envelope label would lie about them. No
  per-space grouping is promised anywhere in this slice.
- **The compatibility claim, stated exactly.** What a cluster surface
  MAY claim: *its members are connected through stored edges that the
  similarity producer created under its compatibility rule* — a
  production-time property of the edges. What it may NOT claim, imply,
  or let a reader infer: *these members currently share an embedding
  envelope.* The two come apart the moment any member is re-embedded,
  and only the first is evidenced by anything this slice reads. Every
  surface's wording is held to this distinction.
- **Two inputs, two provenances — pinned, not blurred.** Cluster
  MEMBERSHIP derives from the edge set CURRENTLY stored in the graph.
  That set is what a completed `similar` pass last wrote, but the
  store attests only its present contents, never the pass history:
  `graph --rebuild` drops and recreates the rel tables
  (`graph/schema.py:reset_schema`), so an empty stored set can mean a
  rebuild as easily as a pass that found nothing. Describe the edges
  as they are; claim no observable sequence of passes behind them. The
  UNCLUSTERED count derives from the CURRENT graph node inventory,
  which incremental `graph` runs change independently of the edges
  (reproduced at plan review: adding a session and re-running `graph`
  moved nodes 2→3 and unclustered 0→1 with both edges unchanged). The
  report must label the two provenances distinctly and may not claim
  the whole report is frozen to the `similar` pass. Nothing in this
  slice reads envelopes, recomputes similarity, or contacts a
  backend; fresh clusters require re-running `similar`, and no
  snapshot storage is added to change any of this.
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
- **A cluster's reported `directed_edge_count` is the number of stored
  DIRECTED edge records internal to the component — not the number of
  undirected adjacencies.** A→B and B→A count as **two**, though they
  form one adjacency; a lone A→B counts as one. Grouping uses the
  undirected view (above); the count reports the stored evidence
  behind it. The two differ whenever any pair is reciprocal, so the
  choice is pinned here and asserted in tests, never left to the
  implementation.
- **Guaranteed:** every pair of members is connected by a chain of
  recorded, above-threshold edges from one completed pass, entirely
  within one embedding space.
- **NOT guaranteed — stated deliberately, the FR-B discipline:** a
  component links A and C through B even when score(A, C) is below
  the threshold, or when A and C share no edge at all. A cluster is a
  **transitive discovery grouping**, not a pairwise-similarity
  guarantee; any surface that shows a cluster must not imply
  all-pairs similarity.
- Sessions present in the CURRENT graph node inventory with no
  incident stored edge are **unclustered** — counted and reportable
  (FR-A's second provenance), never padded into singleton
  "clusters". A relational session ABSENT from the graph is neither
  clustered nor unclustered — it is a graph prerequisite failure
  (FR-F), the #287 discipline retained.

### FR-C — deterministic identity and order

- A cluster's identity is its **lexicographically smallest member
  `session_key`** — stable across runs on the same snapshot, with no
  RNG, no iteration-order dependence, no timestamps.
- Members are reported sorted by `session_key`; clusters are reported
  in a deterministic order (descending size, then ascending cluster
  identity). Two runs over the same PAIR of inputs — stored edge set
  AND current graph node inventory — must produce byte-identical
  reports; determinism is defined over both, because the inventory
  can change while the edges do not (FR-A).

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
- Report: unnamed clusters — identity, size, members, directed
  `directed_edge_count` (FR-B) — plus the unclustered-session count,
  with the
  two provenances labeled distinctly: cluster membership describes
  the `SIMILAR_TO` edges currently stored in the graph; the
  unclustered count reflects the current graph node inventory. No
  per-space grouping and no space triple anywhere (FR-A).
- No new config keys: clustering has no tunable parameters in V1
  (threshold and top-K belong to `similar`, where the edges are
  decided). The CLI must not grow speculative knobs.

### FR-F — the MCP surface

One tool, `session_clusters`, registered beside the existing five:

- `session_clusters(session_id=None, limit=10)`: with a session id,
  returns that session's cluster (siblings and `directed_edge_count`
  — unnamed, no space triple) or an honest `"unclustered"` outcome;
  without one, lists clusters (largest first, up to `limit`).
- Basis honesty: results carry `basis: "embedding"` and the FR-A
  provenance notes; they must never imply pairwise similarity (FR-B)
  or masquerade as keyword results.
- Prerequisite ladder consistent with `similar_sessions` (#287 FR-F),
  reusing its EXISTING response shape — this slice introduces no new
  outcome literal: unknown session → error; a known relational
  session ABSENT from the graph → `prerequisite: "graph"` with
  graph-sync guidance ("run graph") and "graph node" named in the
  error, exactly as `similar_sessions` answers that condition
  (pinned by `test_missing_graph_node_gets_graph_sync_guidance`), NOT
  "unclustered" — that word is reserved for graph members with no
  stored edge; absent/unopenable graph → `prerequisite: "graph"`
  with guidance; unbuilt graph → same; healthy empty (ready graph,
  no edges) → an honest empty result, no remedial default.
  (`missing_graph_node` remains what it is in #287 — a counter field
  on `similar`'s CLI stats — and is not an MCP outcome here.)
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

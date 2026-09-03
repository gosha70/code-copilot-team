---
spec_mode: full
feature_id: session-analytics-similarity-cluster
risk_category: integration
justification: |
  Groups the reconciled SIMILAR_TO snapshot into connected components
  within one embedding space: a pure component library, a read-only
  graph reader, and CLI/MCP surfaces with the #287 prerequisite
  discipline. No schema change, no new dependencies, no new config
  keys, no writes to any store anywhere in the slice. The load-bearing
  design work — what domain clusters are computed over, and what a
  transitive grouping does and does not claim — is settled in spec.md
  BEFORE any surface, per the arc's governing order.
status: draft
date: 2026-09-03
issue: 289
origin:
  issue: gosha70/code-copilot-team#289
  urls:
    - https://github.com/gosha70/code-copilot-team/issues/289
    - https://github.com/gosha70/code-copilot-team/issues/65
  origin_claim: |
    Issue #289 (E2-cluster, slice 3 of E2 from tracker #65, following
    the merged #285 and #287): clustering over the reconciled
    SIMILAR_TO snapshot with the arc's governing order — clusters
    defined only within one FR-A space, snapshot semantics stated,
    the transitive-chaining limitation stated deliberately in the
    FR-B discipline; deterministic identity; the
    materialize-vs-compute-on-read question an explicit fork with
    V1's choice justified; read-only graph access throughout; CLI and
    MCP surfaces with the #287 prerequisite ladder; Studio UI, KPI
    aggregates, and alternative algorithms out of scope.
---

# Plan: E2-cluster — session clustering

## Shape

Three small pieces, layered like #287 (pure math → reader → surface),
all read-only:

- `embedding/clusters.py` — PURE: connected components over an edge
  list (union-find or BFS over sorted keys — either is fine, but
  iteration must be sorted so FR-C determinism is by construction),
  cluster identity (lexicographically smallest member), deterministic
  report ordering. No kuzu, no I/O, no config.
- `embedding/cluster_reader.py` — a `GraphSnapshot` seam (Protocol:
  `graph_ready()`, `session_keys()`, `edges()` returning directed
  (src, dst, score) rows) with a Kùzu implementation over
  `GraphDatabase.connect_read_only`, plus `run_clusters(store)`
  returning per-space cluster stats. Reuses `GraphNotReadyError`
  semantics from #287 for the unbuilt-graph prerequisite.
- CLI `clusters` subcommand + MCP `session_clusters` in
  `mcp/tools.py`, registered in `mcp/server.py` beside the existing
  five, taking the already-plumbed `kuzu_path`.

Space attribution — RESOLVED at plan review (P1): V1 reports
**unnamed components** with no per-space grouping promise anywhere;
compatibility is inherited from the similarity producer and asserted
by the two-space discriminator, never named. The current-envelope
join is rejected outright, not merely deferred: the reviewer
reproduced re-embedding a member under another model while its old
edges remained unchanged — current envelopes cannot attest the
HISTORICAL space of stored edges, so a joined label would lie.

Two inputs, two provenances — pinned at plan review (P2): the
reader's `edges()` carries cluster MEMBERSHIP (stored edges, last
completed `similar` pass); `session_keys()` carries the CURRENT graph
node inventory, which incremental `graph` runs change independently
(reproduced: nodes 2→3, unclustered 0→1, edges unchanged). Reports
label the two distinctly, never claim the whole report is frozen to
the pass, and determinism (FR-C) is defined over BOTH inputs. For
session-id lookup, a relational session absent from the graph is a
`missing_graph_node` prerequisite (#287 discipline retained), not an
edgeless graph member. No snapshot storage is added.

## Design decisions (flagged for review)

- **D1 components, not parametric clustering.** Zero parameters, zero
  dependencies, deterministic; the threshold/top-K that shaped the
  edges already live in `similar`. Alternatives (k-means, HDBSCAN)
  need k/eps + deps — rejected for V1, recorded in Non-goals.
- **D2 compute-on-read.** Materialized clusters are derived state
  over derived state and would need the full FR-D reconciliation
  discipline for zero current value. Upgrade path recorded (spec
  FR-D).
- **D3 undirected view.** Adjacency = at least one directed edge in
  either direction (top-K membership is asymmetric; similarity is
  not).
- **D4 size >= 2.** Edgeless sessions are "unclustered", counted,
  never singleton clusters.
- **D5 read-only everywhere.** Every graph open in this slice is
  `connect_read_only`; the CLI absent-path precheck runs before any
  open; tests assert zero filesystem creation (the #287 T3 pattern,
  including the disappearing-path race).
- **D6 no new config keys.** Nothing added to defaults.json, env, or
  CLI beyond `--dsn`/`--db-path`.

## Test strategy

- **Pure (`clusters.py`):** chain components (A–B–C with no A–C
  edge — the transitive grouping IS the behavior, pinned), directed
  asymmetric adjacency, deterministic identity and ordering
  (shuffled input → byte-identical report), size >= 2 rule,
  empty edge set.
- **Reader (`cluster_reader.py`):** a fake `GraphSnapshot` (the
  #287 `_FakeEdgeStore` pattern, read-only subset); the two-space
  discriminator (no cluster mixes spaces — seeded via two
  disconnected same-shaped edge groups from a real `similar` run in
  the live class); the PROVENANCE discriminator (grow the node
  inventory with the edge set unchanged → membership byte-identical,
  unclustered count moves — the plan-review reproduction as a
  regression); unready graph → `GraphNotReadyError`; healthy empty.
- **CLI:** prerequisite ladder exit codes (absent path → usage, zero
  creation asserted; unbuilt graph → usage; empty snapshot → exit 0);
  deterministic report bytes over the same (edges, inventory) pair;
  no space triple anywhere in the output.
- **MCP:** session-id and list modes; unknown session; unclustered
  outcome; the missing-graph-node prerequisite distinct from
  "unclustered" (relational session absent from the graph → "run
  graph" guidance); prerequisite ladder; healthy empty; a
  registered-tool test driving the real server factory with a
  nondefault `kuzu_path` (gated on kuzu+mcp like #287).
- **Live Kùzu class:** end-to-end `embed`-fixture → `similar` →
  `clusters` over a real store, read-only open verified.
- **Closure:** consolidated mutation ledger (the #287 driver
  pattern: apply → clear `__pycache__` → FAIL+ERROR → restore),
  suites under both pythons, gates, origin record refreshed last.

## Not planned

Studio UI; materialization; per-cluster KPI aggregates; alternative
algorithms; any write path to the graph; any envelope read; any new
dependency or config key. See spec Non-goals.

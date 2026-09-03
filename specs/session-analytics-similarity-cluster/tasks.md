# Tasks: E2-cluster — session clustering

Gated like #285/#287: each task returns for review before the next
starts; no merge, no closures without the owner's explicit GO.

## T1 — pure component library

**Status: pending.**

**Implements:** FR-B, FR-C.

`embedding/clusters.py`: components over a directed edge list viewed
undirected (D3), identity = lexicographically smallest member (FR-C),
deterministic ordering, size >= 2 (D4). Pure — no kuzu, no I/O.

**Done when:** the chain fixture (A–B–C, no A–C edge) is pinned as a
single cluster WITH a test name that says transitive grouping is the
contract; shuffled input yields byte-identical output; empty and
all-singleton inputs yield zero clusters; no RNG, no dict-order
dependence anywhere.

## T2 — snapshot reader + CLI

**Status: pending.**

**Implements:** FR-A, FR-D, FR-E (plan D2, D5, D6).

`embedding/cluster_reader.py`: `GraphSnapshot` seam + Kùzu impl over
`connect_read_only`; `run_clusters`; CLI `clusters` subcommand with
the prerequisite ladder and exit-code discipline.

**Done when:** the two-space discriminator proves no cluster mixes
spaces; absent path → usage error with ZERO filesystem creation
(asserted); unbuilt graph → usage error; ready-but-empty snapshot →
exit 0 healthy report with the snapshot note; report bytes
deterministic across runs; no write statement anywhere in the slice.

## T3 — the MCP surface

**Status: pending.**

**Implements:** FR-F.

`mcp/tools.py:session_clusters(session_id=None, limit)`; registration
in `server.py` beside the existing five, on the plumbed `kuzu_path`.

**Done when:** session-id mode returns the cluster or an honest
`"unclustered"`; list mode is largest-first and bounded by `limit`;
results carry `basis: "embedding"` + the snapshot note and never
imply pairwise similarity; the prerequisite ladder matches
`similar_sessions`; a registered-tool test drives the real server
factory with a nondefault `kuzu_path`; the disappearing-path race is
refused, not repaired; existing tools' outputs byte-unchanged.

## T4 — closure

**Status: pending.**

README section (transitive-grouping limitation and snapshot semantics
in the FR-B discipline); consolidated mutation ledger re-run whole at
final HEAD under kuzu+mcp with zero skips; full suites under both
pythons; `validate-spec` / origin-alignment (record last) /
doc-accuracy / `git diff --check`; PR body/table refresh.

## Out of scope

spec.md §Non-goals. #285/#287 deliverables untouched. Studio UI, KPI
aggregates, materialization, and algorithm alternatives stay with
#65.

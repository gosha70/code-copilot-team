---
spec_mode: full
feature_id: session-analytics-similarity-similar
risk_category: integration
justification: |
  Adds similarity over the #285 embedding substrate: a pure
  compatibility+cosine library, an idempotent local pass writing the
  pre-existing SIMILAR_TO graph rel, and an MCP tool that names its
  basis. No backend contact anywhere in the slice; no schema change
  (the rel exists since #63). The load-bearing design work — what
  "same embedding space" means and what name/tag equality does and
  does not guarantee — is settled in spec.md BEFORE any similarity
  semantics, per the owner's governing order.
status: draft
date: 2026-09-02
issue: 287
origin:
  issue: gosha70/code-copilot-team#287
  urls:
    - https://github.com/gosha70/code-copilot-team/issues/287
    - https://github.com/gosha70/code-copilot-team/issues/65
  origin_claim: |
    Issue #287 (E2-similar, slice 2 of E2 from tracker #65, following
    the merged #285): similarity over stored envelopes with the
    owner's governing order — compatibility evidence precedes
    similarity semantics; the name/tag-vs-digest question is an
    explicit fork with V1's choice stating precisely what it
    guarantees and what it does not; SIMILAR_TO population and an MCP
    surface that reports its basis; no cross-space comparison under
    any configuration; live query-text embedding surfaced as a fork
    and kept out of V1.
---

# Plan: E2-similar — session similarity

## Shape

Three small parts plus closure, all inside `scripts/session_analytics/`:

| Part | New file(s) | Notes |
|---|---|---|
| Compatibility + math | `embedding/similarity.py` | pure functions: space key, grouping, cosine, top-K — unit-testable with no store |
| The `similar` pass | `embedding/similar_runner.py`, `cli.py` subcommand `similar` | reads envelopes (SQL), writes `SIMILAR_TO` (Kùzu), NO backend |
| MCP tool | `mcp/tools.py:similar_sessions` | basis-honest surface |
| Closure | README section, mutation ledger | the #285 T5 pattern |

Config: a `similarity` block in `defaults.json` (`threshold`, `top_k`)
resolved through the proven five-layer precedence; constants in
`constants.py`.

## Design decisions

**D1 — the space key is computed in ONE place.** `similarity.space_key
(envelope) -> (provider, model, dim)` after `validate_envelope`; the
grouper consumes keys, the pair-former iterates WITHIN groups. Cross-
space impossibility is structural (pairs are never formed across
groups), not a post-filter — a post-filter is one deleted line away
from the bug.

**D2 — `dim_conflict` is surfaced, not swallowed.** Same `(provider,
model)` with differing `dim` falsifies the name-equality assumption
for that name (FR-A). The pass reports the conflicting name and both
dims; those sessions are excluded from each other's spaces (they ARE
distinct spaces by the triple) but the report row is the point.

**D3 — per-source edge replacement.** For each source session the
pass deletes its outgoing `SIMILAR_TO` edges and writes the fresh
top-K. Idempotent by construction (same inputs → same edge set), and
re-embedding under `--overwrite` in #285 cannot leave stale neighbors
behind. MERGE-with-SET was considered and rejected: it updates scores
but cannot retire an edge whose target fell out of the top-K.

**D4 — the graph write path mirrors `graph/builder.py`.** Session
nodes are addressed by the existing `session_key = "<copilot>:<id>"`;
edges are written through the same `GraphDatabase` connection idiom as
`cmd_graph`. If a session has an envelope but no graph node yet, it is
counted `missing_graph_node` and skipped — the pass never creates
Session nodes, that is `graph`'s job; the report tells the operator to
run `graph` first.

**D5 — MCP reads, never computes embeddings.** `similar_sessions
(session_id, limit)` returns stored neighbors (edge-backed) with
`score` and `basis: "embedding"`, falling back to an explicit
`{"error": "no embedding/edges — run embed + similar"}` rather than a
silent keyword answer. `compare_approaches` untouched except a
docstring pointer.

**D6 — no `routing_calibration.py` import.** Its kNN normalizes and
evaluates leave-one-out over routing evidence; this slice needs plain
cosine top-K over session vectors. Referenced as prior art in the
issue; importing it would couple two unrelated evidence domains.

## Test strategy

- **space-key discriminators:** same triple → same space; each single
  component differing (provider / model / dim) → different space.
- **cross-space impossibility:** a store holding two spaces yields
  edges only within each; a mutation forming pairs across groups
  fails a named test (and the structural D1 shape means that mutation
  is the post-filter rewrite).
- **dim_conflict:** same name, different dim → both sessions
  reported, neither compared with the other, the conflicted name
  named in the report.
- **validated-only:** an invalid stored envelope (bad JSON / failing
  FR-9) is excluded + counted with a reason; never scored.
- **cosine correctness:** hand-computed fixtures (orthogonal → 0,
  identical → 1, opposite → −1); threshold and top-K respected;
  ties broken deterministically (stable order by session id).
- **idempotency + retirement:** run twice → identical edge set; drop
  a neighbor's envelope, re-run → the stale edge is gone.
- **strictly local:** the pass performs zero HTTP-level calls — the
  embedding registry is never consulted (pinned by asserting no
  backend construction, the #285 T4 idiom).
- **MCP basis honesty:** results carry `basis: "embedding"`; a
  session without edges gets the explicit error, not keyword results;
  `compare_approaches` output unchanged byte-for-byte on its fixtures.
- **config layering:** threshold/top_k through the five layers (the
  #285 T1 harness pattern, hermetic).

Every discriminator mutation-checked at build time (`__pycache__`
cleared, `ERROR:` checked as well as `FAIL:`), consolidated into a
ledger at closure — the #285 T5 pattern.

## Not planned

Everything in spec.md §Non-goals; plus score persistence anywhere
except `SIMILAR_TO` (no relational mirror column — one home per
fact).

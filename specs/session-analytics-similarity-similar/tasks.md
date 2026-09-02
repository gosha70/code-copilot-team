# Tasks: E2-similar — session similarity

Order is load-bearing, and it is the owner's governing order made
executable: **the compatibility rule exists and is tested before any
similarity semantics run** (T1 before T2), and the pass exists before
the surface that reads its output (T2 before T3).

> Navigation layer: the contracts live in `spec.md` (FR-A…FR-F);
> tasks point at them and name what makes each done.

## T1 — compatibility rule + pure similarity library + config

**Implements:** FR-A (space key), FR-B's V1 choice as code, FR-C
(cosine, config knobs).

`embedding/similarity.py`: `space_key(validated_envelope)`,
`group_by_space(...)` (surfacing `dim_conflict`s), `cosine(a, b)`,
`top_k(...)` with deterministic tie-breaks. `similarity` config block
(`threshold`, `top_k`) + constants, resolved through the proven
five-layer precedence.

**Done when:** the space-key discriminators pass (equal triple; each
single component differing); `dim_conflict` is detected and named;
cosine matches hand-computed fixtures; config layering proven with
the #285 T1 hermetic harness; no similarity function accepts an
unvalidated envelope (they take validated data or a validation error
is upstream — pinned by a test feeding an invalid envelope to the
grouping entry and getting a refusal, not a score).

## T2 — the `similar` pass + CLI

**Implements:** FR-D (edges), FR-E (strictly local lifecycle).

`embedding/similar_runner.py` + `cli.py similar`: durable state first;
nothing eligible → zero writes; per-source edge replacement (D3);
graph addressing per D4 (`missing_graph_node` counted, nodes never
created); report = written / per-space session counts /
excluded_invalid (reasons) / dim_conflicts / no_envelope /
missing_graph_node.

**Done when:** cross-space edges are impossible (named mutation);
run-twice yields an identical edge set and retired neighbors
disappear; the pass constructs NO embedding backend (asserted, the
#285 T4 idiom); an empty store reports truthfully with zero Kùzu
writes; `failed`-class conditions exit nonzero.

## T3 — the MCP surface

**Implements:** FR-F.

`mcp/tools.py:similar_sessions(session_id, limit)`; docstring pointer
from `compare_approaches`.

**Done when:** results carry `score` + `basis: "embedding"`; a
session without edges returns the explicit error, never keyword
results; `compare_approaches` fixtures byte-unchanged; the tool is
registered beside the existing four.

## T4 — closure

README section (state plainly: scores are discovery heuristics over a
same-named space, not model-version identity — FR-B's boundary);
consolidated mutation ledger re-run whole at final HEAD; full suite;
`validate-spec` / origin-alignment (record last) / doc-accuracy /
`git diff --check`; PR body/table refresh.

## Out of scope

spec.md §Non-goals. E2-embed untouched. Digest provenance is its own
future issue with its own capture.

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
single component differing); `dim_conflict` is detected and named —
including the three-session discriminator: two valid 768-dim sessions
plus one same-named 1024-dim session → the conflict is reported, the
768-pair REMAINS comparable, and the 1024 session remains eligible in
its own group (a conflict never disqualifies either whole group);
cosine matches hand-computed fixtures; config layering proven with
the #285 T1 hermetic harness; no similarity function accepts an
unvalidated envelope (they take validated data or a validation error
is upstream — pinned by a test feeding an invalid envelope to the
grouping entry and getting a refusal, not a score).

## T2 — the `similar` pass + CLI

**Implements:** FR-D (edges), FR-E (strictly local lifecycle).

`embedding/similar_runner.py` + `cli.py similar`: durable state
first; FULL reconciliation per FR-D/D3 (retire ineligible sources'
edges, replace eligible sources' edges); zero writes only when there
are no eligible sources AND no existing edges; graph addressing per
D4 (`missing_graph_node` counted, nodes never created); report =
written / retired / per-space session counts / excluded_invalid
(reasons) / dim_conflicts / no_envelope / missing_graph_node —
distinguishing "nothing to do" from "retirement ran".

**Done when:** cross-space edges are impossible (named mutation);
run-twice yields an identical edge set; a removed TARGET's stale edge
disappears; a removed SOURCE's outgoing edges are retired; an
all-ineligible store retires everything and reports it; the pass
constructs NO embedding backend (asserted, the #285 T4 idiom); a
truly empty store reports truthfully with zero Kùzu writes;
`failed`-class conditions exit nonzero.

## T3 — the MCP surface

**Implements:** FR-F, including the MCP-to-graph boundary (plan D7).

`mcp/tools.py:similar_sessions(session_id, limit)`; `build_server`
gains the configured `kuzu_path` (today it accepts only the DSN and
`_cmd_mcp` passes `cfg.dsn`); a NON-CREATING graph-read lifecycle for
the MCP path (`GraphDatabase.connect` mkdirs and opens
create-capable — the MCP path must not); docstring pointer from
`compare_approaches`.

**Done when:** results carry `score` + `basis: "embedding"`; an
edge-less session WITH a validated envelope returns an honest EMPTY
result and no remedial instruction (healthy outcomes: singleton
space, below-threshold — and absence of edges cannot prove the pass
never ran); a session with no validated envelope gets the
envelope-prerequisite guidance; an absent graph yields "graph absent"
with ZERO filesystem creation, asserted on the path afterwards; a
registered-tool test drives the real server factory with a NONDEFAULT
kuzu_path and reads that graph; `compare_approaches` fixtures
byte-unchanged; the tool is registered beside the existing four.

## T4 — closure

README section (state plainly: scores are discovery heuristics over a
same-named space, not model-version identity — FR-B's boundary);
consolidated mutation ledger re-run whole at final HEAD; full suite;
`validate-spec` / origin-alignment (record last) / doc-accuracy /
`git diff --check`; PR body/table refresh.

## Out of scope

spec.md §Non-goals. E2-embed untouched. Digest provenance is its own
future issue with its own capture.

# Tasks: E2-similar — session similarity

Order is load-bearing, and it is the owner's governing order made
executable: **the compatibility rule exists and is tested before any
similarity semantics run** (T1 before T2), and the pass exists before
the surface that reads its output (T2 before T3).

> Navigation layer: the contracts live in `spec.md` (FR-A…FR-F);
> tasks point at them and name what makes each done.

## T1 — compatibility rule + pure similarity library + config

**Status: complete** (one review round: numerically safe cosine via per-vector max-|component| scaling — FR-9 bounds finiteness, not magnitude; knobs validated before coercion, threshold in [-1,1], top_k a positive non-boolean integer; grouping calls the ONE `space_key`, after the review's provider-dropping mutation escaped the helper-only discriminators).

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

**Status: complete** (one review round: commit moved INTO the protected phase and cleanup preserves the original error — kuzu auto-aborts make unconditional ROLLBACK raise "No active transaction"; the absent/uninitialized graph became an explicit prerequisite, exit 2, zero filesystem creation; live failure tests compare complete (source, target, score) rows).

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

**Status: complete** (one review round: non-creation enforced at the OPEN via `connect_read_only` — the exists() precheck alone was a TOCTOU; `mcp>=1.0,<2` pinned in requirements + CLI hint, since 2.x renamed FastMCP; invalid envelopes get the targeted `embed --overwrite --session-id` guidance, with the advised recovery tested end to end; neighbor KPIs included with rubric identity and honest absence). The registered-tool test runs in CI, which now installs mcp<2.

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

**Status: complete.** README section (name/tag heuristic, last-pass snapshot semantics, and the deferred text-query embedding all explicit); the consolidated 24-mutation ledger re-run whole at the final HEAD under kuzu+mcp with zero test skips — 24 caught, 0 escaped (`mutation-ledger.md`); full suite and repo gates green; origin record refreshed last.

README section (state plainly: scores are discovery heuristics over a
same-named space, not model-version identity — FR-B's boundary);
consolidated mutation ledger re-run whole at final HEAD; full suite;
`validate-spec` / origin-alignment (record last) / doc-accuracy /
`git diff --check`; PR body/table refresh.

## Out of scope

spec.md §Non-goals. E2-embed untouched. Digest provenance is its own
future issue with its own capture.

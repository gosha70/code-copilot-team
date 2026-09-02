# Origin alignment — session-analytics-similarity-similar (E2 slice 2)

Verdict: aligned
Confidence: high

## Origin capture

Issue #287, opened as the second per-enhancement slice of tracker
#65's E2, immediately after slice 1 (#285) merged at `8e9ee49` and was
closed. The owner named E2-similar the next bet and delegated the
start ("the next substantive action is a fresh E2-similar issue/SDD
when you choose to start it").

## The governing order, and where it binds

The owner set two preconditions before any design, twice and in
almost the same words:

1. **Compatibility evidence precedes similarity semantics** — the SDD
   must not define cosine thresholds or edge-writing rules before
   deciding what "same embedding space" means. spec.md is structured
   to make that order visible: FR-A (the space triple) and FR-B (the
   fork) come before FR-C/FR-D, and tasks.md makes it executable
   (T1 strictly before T2).
2. **The digest question is an explicit fork.** V1 chooses name/tag
   equality within the (provider, model, dim) triple and FR-B states
   precisely what that guarantees (same host, between pulls, one set
   of weights, matching geometry) and what it does not (immutable
   model-version identity; cross-time/host comparability). The digest
   path is REJECTED for V1 with the reason recorded and the upgrade
   path defined (additive `model_digest` field → quadruple key),
   so `model == model` never quietly becomes stronger evidence than
   Ollama provides.

The factual substrate for both comes from #285's recorded capture
(`verification-ollama-embed.md`): the envelope `model` is a
server-confirmed name/tag, not a digest.

## Decisions taken on this plan's authority (flagged for review)

- **D1 structural cross-space impossibility** (pairs formed inside
  groups; never a post-filter).
- **D2 `dim_conflict` surfaced** — same name, different dim is
  evidence AGAINST the name-equality assumption and is reported, not
  just partitioned.
- **D3 per-source edge replacement** over MERGE-with-SET, because
  MERGE cannot retire an edge whose target fell out of the top-K.
- **D4 the pass never creates Session nodes** (`graph`'s job);
  `missing_graph_node` is counted with operator guidance.
- **FR-F's V1 boundary: live query-TEXT embedding is OUT** — it would
  put a backend call inside the MCP path and need query-time space
  matching. Surfaced as the fork the issue required, decided
  conservatively; a reviewer wanting it in V1 should say so at plan
  review.

## Correction pass after plan review (PR #288)

The review returned two P1s and two P2s plus one factual fix — tighter
contracts and bounded wiring, no architecture change. All applied:

1. **FR-B narrowed to recorded evidence** (P1). The first draft
   guaranteed "this host's server… one set of weights between pulls"
   — claims the envelope does not attest: it records no endpoint, the
   base URL can change between runs, and `--overwrite` preserves old
   envelopes on failed calls, so it cannot guarantee one model
   generation. V1's guarantee is now exactly the recorded triple;
   same-server and unchanged-weights are named UNVERIFIED ASSUMPTIONS;
   the overwrite mitigation claim is removed; `dim_conflict`
   establishes incompatible dimensions, with "re-pulled tag" one
   possible cause rather than the established one.
2. **Reconciliation covers all existing edges** (P1). The
   counter-example: create A→B, remove A's envelope — per-eligible-
   source replacement never visits A again and preserves exactly the
   edge whose evidence is gone; with every envelope invalid it
   preserves the whole stale graph. FR-D now retires ineligible
   sources' edges, distinguishes truly-empty from retirement-needed,
   pins source-removal and all-ineligible cases, and states that edge
   scores describe the last completed pass — nothing refreshes them
   implicitly.
3. **The MCP-to-graph boundary is in scope** (P2, verified in code:
   `build_server(dsn)` only; `GraphDatabase.connect` mkdirs and opens
   create-capable at `graph/schema.py:34`). D7 + T3 now carry the
   `kuzu_path` plumbing, a NON-CREATING read lifecycle for the MCP
   path, a nondefault-path registered-tool test, and an absent-graph
   test asserting zero filesystem creation.
4. **An empty neighbor set is a healthy answer** (P2). Singleton
   spaces and below-threshold scores legitimately produce no edges,
   and without pass metadata absence cannot prove the pass never ran
   — so the tool returns an honest empty result and reserves guidance
   for independently established prerequisites (no validated
   envelope; graph absent). "Run embed + similar" as a default answer
   is gone.
5. **Factual fix:** `compare_approaches` returns `match_score` with
   no `basis` field today; the scenario no longer claims otherwise.

FR-E was also re-aligned with the corrected FR-D (its "nothing
eligible → zero writes" would have contradicted retirement).

Still plan-only; no code exists.

## What this record does NOT claim

- No code exists; the bundle is plan-first per the house gate
  discipline. No cosine has been computed, no edge written.
- Nothing here makes E2 complete on #65 — that is the owner's call
  after this slice lands and is audited.
- The digest upgrade path is DEFINED, not promised: it becomes an
  issue only if evidence of tag-drift mispairing appears or the owner
  wants the stronger guarantee.

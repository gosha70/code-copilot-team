# Spec: E2-similar — session similarity over the embedding substrate

Issue #287, slice 2 of E2 from tracker #65. Slice 1 (#285, merged
`8e9ee49`) created validated provenance envelopes and deliberately
compared nothing. This slice is the comparison — and its governing
order, set by the owner before any design:

> **Compatibility evidence precedes similarity semantics.** Nothing
> below defines a cosine threshold or an edge-writing rule until
> "same embedding space" is decided — and the digest question is an
> explicit fork, never `model == model` quietly treated as stronger
> evidence than Ollama provides.

## User Scenarios

1. **"What did I do last time I hit this?"** A developer opens a
   session and asks for similar past sessions. The answer comes from
   stored vectors — semantically, not by keyword luck — with each
   result carrying its similarity score and KPIs.
2. **An operator runs the pass after embedding.** `similar` populates
   `SIMILAR_TO` edges for every session that has a validated envelope,
   entirely locally — no backend, pure DB + math — and reports
   written / skipped / excluded counts per embedding space.
3. **A mixed-model library stays honest.** Sessions embedded under
   different models are never compared; the report shows the space
   partition so the operator can see fragmentation and decide whether
   to re-embed onto one model.
4. **An agent asks over MCP.** A `similar_sessions` tool returns
   neighbors with `basis: "embedding"`; the existing keyword
   `compare_approaches` keeps returning `basis: "keyword"` — results
   never masquerade as something stronger than they are.

## Requirements

### FR-A — "same embedding space", defined FIRST

Two envelopes are in the same space **iff** their validated triples
are equal:

```text
(provider, model, dim)
```

- `provider` — a future second backend family emitting the same model
  name must not silently mix with Ollama's vectors.
- `model` — the server-confirmed name/tag (see FR-B for exactly what
  that means).
- `dim` — belt beside the name: an equal name with a different
  dimensionality is PROOF of drift (a re-pulled tag with different
  geometry), and such a pair is not merely skipped — it is surfaced
  in the pass report as a `dim_conflict`, because it falsifies the
  name-equality assumption for that name.

Only FR-9-validated envelopes participate at all: an envelope that
fails `validate_envelope` on read is excluded and counted with its
reason, never guessed at.

### FR-B — the name/tag-vs-digest fork, decided explicitly

**V1 chooses name/tag equality (within the FR-A triple), and states
its boundaries.**

What the choice GUARANTEES: both vectors were produced by whatever
model this host's server resolved under that name at each session's
embed time, with matching dimensionality, through the same backend
family. On a single host, between pulls, that is one set of weights.

What it does NOT guarantee: immutable model-version identity. A
re-pulled tag — `:latest` above all — may be different weights under
the same name; the envelope `model` is a server-confirmed NAME/TAG,
not a content digest (T3 capture, #285). Therefore similarity scores
are **discovery heuristics over a same-named space**, never proof of
semantic identity across time or hosts. Mitigations V1 already has:
`embedded_at` is recorded on every envelope, and `--overwrite`
re-embedding collapses a library onto one pull.

**The digest fork is REJECTED for V1**, not ignored: digest
provenance needs its own recorded capture (Ollama's model-list/show
surfaces, unread today), an additive envelope field, and a backfill
story — disproportionate before any observed mispairing from tag
drift. The upgrade path is defined now so V1 does not paint over it:
a future additive `model_digest` envelope field tightens the FR-A
triple to a quadruple; envelopes without a digest keep V1's rule.
That upgrade is its own issue with its own capture.

### FR-C — cosine over validated same-space pairs

The score is cosine similarity. A zero-norm operand is impossible by
upstream contract — FR-9 (#285) refuses zero vectors before any write
— and this spec CITES that rather than re-checking it per pair.
Threshold and top-K come from layered config; no hardcoded defaults
in source.

### FR-D — `SIMILAR_TO` edges, impossible to cross spaces

The pass writes into the existing
`SIMILAR_TO(FROM Session TO Session, score DOUBLE)` rel: for each
eligible session, its top-K same-space neighbors with
`score >= threshold`. Edge `a → b` means "b is among a's top-K"
(kNN is asymmetric; both directions are written only when each earns
the other). Writes are idempotent per source session — a re-run over
unchanged envelopes converges to the same edge set, and a source's
stale edges from earlier runs are replaced, not accumulated.

**A cross-space edge must be impossible by construction** — pairs are
formed inside space groups, never filtered after scoring — and a
mutation that forms one is caught by a named test.

### FR-E — a strictly local pass

The `similar` pass touches NO embedding backend: it reads stored
envelopes, computes, and writes edges. Lifecycle in the FR-6 spirit:
durable state first; nothing eligible → zero writes and a truthful
report; the report counts written edges, sessions per space,
excluded-invalid (with reasons), `dim_conflict`s, and sessions
without envelopes.

### FR-F — the MCP surface says its basis

V1 adds a `similar_sessions(session_id)` MCP tool over the stored
vectors/edges, each result carrying `score` and `basis: "embedding"`.
The existing keyword `compare_approaches` is UNCHANGED except that its
docstring points here; its results keep meaning what they meant.
**Live query-TEXT embedding is out of V1** — it would put a network
backend call inside the MCP path and require space matching at query
time; if wanted later it is its own decision.

## Non-goals

- Studio UI; clustering; anything E4.
- Touching E2-embed's pipeline, envelope schema, or backend.
- Digest provenance (the defined upgrade path, deliberately deferred).
- Comparing across embedding spaces under any configuration.
- Reusing `routing_calibration.py` code — its kNN is a design
  reference (#266), referenced, not imported.

## Constraints

- Tests: stdlib unittest + SQLite (+ the in-repo Kùzu harness the
  graph tests already use); no live network anywhere in this slice.
- Config keys as constants; layered precedence as proven in #285 T1.
- The similarity math is pure and unit-testable without any store.

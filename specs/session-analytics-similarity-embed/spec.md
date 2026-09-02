# Spec: E2-embed — session embedding pipeline (slice 1 of E2)

Issue #285, the first per-enhancement issue split from tracker #65's E2.
Delivers embeddings only. E2-similar (`SIMILAR_TO` edges, comparison
surfaces) is a separate issue gated on this one.

## What exists, verified at `54a34bd`

- `copilot_session.session_embedding TEXT` — nullable since #63,
  populated by nothing in the tree.
- `SIMILAR_TO(FROM Session TO Session, score DOUBLE)` in the Kùzu
  schema — unpopulated, out of scope here.
- `judge/ollama_judge.py` — the local-only HTTP pattern this feature
  copies, and the registry pattern (`judge/_register.py`) for
  pluggable backends.
- Redacted text already stored per turn as `content_preview`; the
  judge reads only that column (`judge/runner.py:_select_turns()`).

## User Scenarios

1. **A developer wants "sessions like this one".** Today
   `compare_approaches` matches keywords, so a session about the same
   bug phrased differently is invisible. After E2-embed + E2-similar,
   the comparison is semantic. This slice makes the vectors exist;
   the comparison itself is E2-similar.
2. **An operator runs the pass after ingest.**
   `./scripts/session-analytics embed` (the existing documented
   executable; no new alias) embeds every session lacking a vector,
   reports
   embedded / skipped_existing / failed / truncated counts, and exits
   nonzero if anything failed. Re-running with no work contacts the
   backend zero times.
3. **An operator switches embedding models.** Existing envelopes —
   whatever model wrote them — are untouched by an ordinary run and
   reported as `skipped_existing` with the stored-model distribution;
   `--overwrite` is the explicit path to re-embed. Nothing ever
   compares vectors across models (that rule binds E2-similar).
4. **A privacy-conscious user checks what left the machine.** Nothing:
   the default backend is localhost Ollama, and the embedding input is
   drawn from an explicit allowlist of already-redacted turn columns —
   a strict subset of what the judge already reads.

## Requirements

**FR-1 — redacted input only, by explicit allowlist.** The embedding
input is composed exclusively from these `copilot_turn` columns:

```text
sequence_num | role | content_preview
```

Nothing else. Not `project_path`, not `benchmark_run_dir`, not any
`copilot_session` column, not transcript-source fields — "already
stored" is NOT the boundary, because stored session metadata is not
behind the E8 text-redaction boundary. The allowlist is a strict
subset of what the judge reads (`judge/runner.py:_select_turns()`:
the same three plus `has_tool_use` and `prev_preview`), so E8's
guarantees transfer. No code path in this feature reads raw
transcript files or any unredacted column. Widening the allowlist
requires its own redaction audit, in a new SDD pass.

**FR-2 — local-only default.** The default backend is Ollama on
localhost, the same posture as the judge. No session content leaves
the machine on the default path. A non-default backend is an explicit
config choice.

**FR-3 — explicit absence; unknown stays unknown.** A session that
cannot be embedded — backend unreachable, embedding call failed,
empty input — keeps `session_embedding` NULL and is counted in the
pass report. Never a zero-vector, never a partial value, never a
fabricated placeholder.

**FR-4 — provenance rides with the vector, in one write.** The stored
value is a self-describing JSON envelope, not a bare array:

```json
{"schema_version": 1, "model": "<resolved model id>", "dim": N,
 "provider": "<backend family>", "embedded_at": "<iso8601>",
 "vector": [ ... ]}
```

Model identity is load-bearing: vectors from different models must
never be silently comparable, and E2-similar may only compare
same-`model` envelopes. The envelope is written atomically with the
vector — provenance never lands in a separate write that could be
skipped.

**FR-5 — the STORED model identity is the resolved one.** Config
`model: ""` means the backend's default, but what is persisted is the
model the backend actually reports for the call. If the backend
cannot report which model produced the vector, the session is NOT
embedded (FR-3) — an unattributed vector is a fabricated fact.

**FR-6 — the pass lifecycle is a fixed order.** Executable, not
aspirational:

1. Inspect durable DB state FIRST: sessions with NULL
   `session_embedding` (plus, under `--overwrite`, sessions with an
   envelope).
2. **No work → return without contacting the backend.** The
   zero-backend-calls idempotency guarantee binds BEFORE any probe.
3. Existing non-NULL envelopes are never overwritten without
   `--overwrite` — regardless of which model wrote them.
4. Probe the backend only when work exists; unreachable → refuse the
   pass before any write.
5. `embed(text)` returns the vector PLUS the authoritative
   `resolved_model` (FR-5).
6. Validate the complete envelope (FR-9), then ONE replacement write.

Reporting is truthful about what is knowable: an ordinary run reports
existing envelopes as `skipped_existing` (with the stored-model
distribution), NOT `skipped_other_model` — classifying an envelope as
"other model" requires an authoritative CURRENT resolved identity,
which an ordinary run that never contacts the backend does not have,
and which must never be derived from the configured/requested model
name. If T3's capture proves the backend has a trustworthy
pre-embedding model-resolution surface, a later pass may use it;
until then the claim is not made.

**Overwrite preserves the last valid value:** under `--overwrite`, a
failed backend call for a session leaves its existing envelope
intact — a failed re-embed must never destroy the last valid
embedding.

**FR-7 — deterministic input composition.** The text embedded for a
session is a pure function of its stored rows: ordered by
`sequence_num`, role-tagged, truncated at a configured character cap
(oldest-first retention, truncation counted in the report). Two runs
over unchanged rows produce byte-identical input.

**FR-8 — config discipline, with the loader's ACTUAL precedence.**
All knobs live in the existing layered config, whose documented order
(`config.py:8`) is:

```text
defaults.json < ~/.cct/session-analytics.json < repo-root .env
              < real env vars < CLI args
```

Knobs: backend family, model, base URL, input cap, workers. Config
keys are constants in `constants.py`. No hardcoded defaults in
source, per house rules.

**FR-9 — validation before write, over the WHOLE envelope.** The
envelope is validated at the write boundary; failing validation is
refused and counted as failed (FR-3), never persisted. Discriminated
separately, not as one shape check:

```text
[]                       -> refuse (no vector)
[0.0, 0.0, ...]          -> refuse (zero vector: cosine over zero
                            norm is undefined, and FR-3/#285 promise
                            "never a zero-vector")
NaN / ±Inf element       -> refuse
boolean element          -> refuse (finite REAL numbers only)
dim != len(vector)       -> refuse
dim == 0                 -> refuse
model empty              -> refuse
provider empty           -> refuse
schema_version != 1      -> refuse
embedded_at not ISO-8601 -> refuse
valid nonzero vector     -> accept
```

The envelope's "versioned, self-describing" promise is load-bearing,
so every contract field is validated — not only the vector.

## Non-goals

- `SIMILAR_TO` edges, cosine similarity, clustering, kNN, and any
  reuse of `routing_calibration.py` — E2-similar's design owns those.
- Studio or MCP surfacing.
- Embedding raw (unredacted) text under any configuration.
- pgvector or any vector-native storage — the existing TEXT column is
  the contract; a storage upgrade is a later, separate decision.
- Backfilling `phase` or anything E3.

## Constraints

- Schema change: none. `session_embedding` exists; the envelope lives
  inside it. If review concludes provenance needs its own column, it
  ships as a numbered DDL file per house convention — but the default
  design deliberately avoids schema churn.
- Tests: stdlib unittest + SQLite, fake backend shim (the judge-test
  pattern), no live network in tests.
- The exact Ollama embeddings endpoint and response shape are PINNED
  AT BUILD TIME against a live Ollama and recorded in the
  verification note — not asserted from memory (house rule: recorded
  capture is ground truth).

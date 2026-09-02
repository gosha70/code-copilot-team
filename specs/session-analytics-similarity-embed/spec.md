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
2. **An operator runs the pass after ingest.** `cct-sa embed` (name
   settled in T4) embeds every session lacking a vector, reports
   embedded / skipped / skipped_other_model / failed / truncated
   counts, and exits nonzero if anything failed. Re-running is free —
   zero backend calls when nothing changed.
3. **An operator switches embedding models.** Existing vectors from
   the old model are untouched; the pass reports them as
   `skipped_other_model` until the operator explicitly re-embeds with
   `--overwrite`. Nothing ever compares vectors across models.
4. **A privacy-conscious user checks what left the machine.** Nothing:
   the default backend is localhost Ollama, and the input was already
   redacted at ingest — the embedding path reads only the same columns
   the judge reads.

## Requirements

**FR-1 — redacted input only.** The embedding input is composed
exclusively from already-stored, already-redacted columns
(`content_preview` and session metadata already in the store). No
code path in this feature reads raw transcript files or any
unredacted column. The E8 boundary sits upstream by construction,
exactly as it does for the judge.

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

**FR-6 — idempotent, model-aware pass.** The CLI pass embeds sessions
whose `session_embedding` is NULL. A session already carrying an
envelope is skipped — including one from a DIFFERENT model, which is
neither overwritten nor mixed; `--overwrite` is the explicit path to
re-embed. Re-running the pass with no changes does zero embedding
calls.

**FR-7 — deterministic input composition.** The text embedded for a
session is a pure function of its stored rows: ordered by
`sequence_num`, role-tagged, truncated at a configured character cap
(oldest-first retention, truncation counted in the report). Two runs
over unchanged rows produce byte-identical input.

**FR-8 — config discipline.** All knobs live in the layered config
(`defaults.json` → `.env` → env → CLI): backend family, model,
base URL, input cap, batch/workers. Config keys are constants in
`constants.py`. No hardcoded defaults in source, per house rules.

**FR-9 — validation before write.** The envelope is validated at the
write boundary: `dim == len(vector)`, `dim > 0`, all elements finite
numbers, model non-empty. An envelope failing validation is refused
(FR-3 counts it as failed), never persisted.

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

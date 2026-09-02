---
spec_mode: full
feature_id: session-analytics-similarity-embed
risk_category: integration
justification: |
  Adds an embedding pipeline to session-analytics: a pluggable backend
  contract with a local Ollama implementation, a deterministic composer
  over already-redacted stored text, and an idempotent post-ingest CLI
  pass writing a self-describing JSON envelope into the existing
  nullable session_embedding column. Additive throughout — no schema
  change, no behavior change for anyone who never runs the pass.
  Coverage via the existing unittest suite with a fake backend shim.
  Tracking: #65 (E2 slice 1); groundwork: #63/PR #64.
status: draft
date: 2026-09-02
issue: 285
origin:
  issue: gosha70/code-copilot-team#285
  urls:
    - https://github.com/gosha70/code-copilot-team/issues/285
    - https://github.com/gosha70/code-copilot-team/issues/65
  origin_claim: |
    Issue #285 (E2-embed, split from #65 per its one-issue-one-PR rule
    and the §5.4 suggested split): embedding pipeline only — local-only
    Ollama default, input composed exclusively from already-redacted
    stored columns, explicit unembedded state (NULL, never zero-vector),
    stored model identity + dimension so vectors from different models
    are never silently compared, idempotent post-ingest CLI pass.
    SIMILAR_TO edges and all surfacing are E2-similar (separate issue).
    Ordering evidence: the 2026-09-02 verification comment on #65 —
    E3's cheap slice already shipped (judge/kpis.py writes
    phase_compliance_score today) and its remainder is design-heavy
    over pi-only phase data, so E2 leads the open set.
---

# Plan: E2-embed — session embedding pipeline

## Shape

Four small parts, all inside `scripts/session_analytics/`, mirroring
the judge's architecture because the problems are isomorphic (pluggable
local-first LLM call over redacted stored text):

| Part | New file(s) | Mirrors |
|---|---|---|
| Backend contract + registry | `embedding/contracts.py`, `embedding/registry.py`, `embedding/_register.py` | `judge/` equivalents |
| Ollama backend | `embedding/ollama_embed.py` | `judge/ollama_judge.py` |
| Input composer | `embedding/composer.py` | `judge/runner.py:_select_turns()` |
| Pass runner + CLI | `embedding/runner.py`, `cli.py` subcommand `embed` | `judge/runner.py`, `cli.py` judge wiring |

Plus: an `embedding` block in `config_data/defaults.json`, config keys
in `constants.py`, README section, and `tests/test_embedding.py`.

## Design decisions

**D1 — envelope in the existing TEXT column, no schema change.** The
provenance the contract needs (model, dim, provider, timestamp) rides
inside the JSON envelope, atomically with the vector. The alternative —
sidecar columns — costs a DDL file and splits one fact across two
writes. The envelope is versioned (`schema_version: 1`) so a future
storage upgrade (pgvector) has a defined migration source.

**D2 — resolved model identity, or no write.** Config `model: ""`
delegates to the backend default, but the envelope stores what the
backend reports. Ollama's response carries the model; if a backend
cannot say, the session stays NULL. This is the FR-E10 lesson from the
routing arc applied here: an unattributed value is worse than an
honest absence.

**D3 — skip-different-model, never overwrite silently.** The pass
targets NULL only. An envelope from another model is left standing;
`--overwrite` re-embeds explicitly. Rationale: mixing two models'
vectors in one column with no operator decision is the exact "silently
compared" failure FR-4 exists to prevent. The pass report counts
`skipped_other_model` separately so drift is visible.

**D4 — composer reads the same columns the judge reads.** Input =
role-tagged `content_preview` rows ordered by `sequence_num`, capped.
The judge already established that these columns are the redaction-safe
view; reusing exactly them means E8's guarantees transfer without a
new audit surface.

**D5 — startup probe, then per-session accounting.** The pass probes
the backend once before embedding anything; an unreachable backend
refuses the whole pass with a clear error (nothing half-done). During
the run, per-session failures leave NULL and are counted; the pass
exits nonzero if `failed > 0`.

**D6 — no reuse of `routing_calibration.py` here.** Its kNN operates
on routing evidence and belongs to E2-similar's design review.
Referenced to prevent rebuilding, not imported.

## Test strategy

Fake backend shim (the judge-test pattern), stdlib SQLite. The
load-bearing rules and their discriminators:

- **redacted-only input:** the composer receives a DB whose raw-text
  fixture differs from `content_preview`; the embedded input must
  contain the preview text and must not contain the raw marker.
- **NULL on failure:** a shim that errors for one session leaves that
  session NULL and the report counts it; asserting the column value,
  not just the count.
- **no zero-vector:** a shim returning an all-zeros vector of correct
  length is still persisted (zeros can be legitimate); but a shim
  returning an EMPTY vector or NaN is refused by FR-9 validation —
  discriminated separately.
- **provenance atomicity:** the stored value parses as the envelope
  with model+dim+vector consistent; a mutation dropping the model from
  the write fails.
- **model-aware idempotency:** second run = zero backend calls
  (shim counts invocations); a pre-existing other-model envelope
  survives an ordinary run and is replaced only under `--overwrite`.
- **determinism:** two composer runs over unchanged rows produce
  byte-identical input.
- **resolved-model rule:** a shim that reports no model identity
  results in NULL + failure count, never an envelope with model "".

Each discriminator is mutation-checked at build time (revert the
behavior, confirm the named test fails; `__pycache__` cleared, `ERROR:`
checked as well as `FAIL:` — house discipline).

## Live verification (build-time, recorded)

One live capture against a local Ollama pins the embeddings endpoint,
request shape, and response fields (including where the model id
appears). The capture is recorded in the bundle
(`verification-ollama-embed.md`) and the parser/tests derive from it —
not from memory. Recorded-capture-is-ground-truth is the house rule
this follows.

## Not planned

`SIMILAR_TO` population, similarity math, clustering, MCP/Studio
surfaces, pgvector, batch/streaming embedding daemons, per-turn
embeddings. E2-similar owns the first group; the rest needs its own
justification if ever wanted.

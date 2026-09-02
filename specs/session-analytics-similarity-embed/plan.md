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
backend authoritatively reports. Whether and where Ollama's response
carries the model id is a T3 capture question, NOT asserted here —
T1's contract is abstract: `EmbeddingResult{vector, resolved_model}`,
and a backend that cannot populate `resolved_model` embeds nothing.
This is the FR-E10 lesson from the routing arc applied here: an
unattributed value is worse than an honest absence.

**D3 — never overwrite silently; report only what is knowable.** The
pass targets NULL only; ANY existing envelope is left standing without
`--overwrite`. Rationale: mixing two models' vectors in one column
with no operator decision is the exact "silently compared" failure
FR-4 exists to prevent. Reporting: `skipped_existing` with the
stored-model distribution — NOT `skipped_other_model`, because an
ordinary run has no authoritative current resolved identity to
classify against (it may never contact the backend at all), and
deriving "other model" from the configured name would be a guess
wearing a report label. Under `--overwrite`, a failed backend call
leaves the session's existing envelope intact — the last valid value
is never destroyed by a failed replacement.

**D4 — composer reads a strict SUBSET of what the judge reads.** The
FR-1 allowlist is exactly `copilot_turn.sequence_num`, `role`,
`content_preview` — three of the five columns the judge selects (it
also reads `has_tool_use` and `prev_preview`; the composer needs
neither). No `copilot_session` column, no session metadata: stored is
not the same as redacted, and `project_path` / `benchmark_run_dir`
are stored but not behind the E8 text boundary. Input = role-tagged
previews ordered by `sequence_num`, capped.

**D5 — DB first, probe only when work exists.** The FR-6 lifecycle
order governs: inspect durable state first; no work → return with
ZERO backend contact (the idempotency guarantee binds before any
probe); only when work exists, probe once — unreachable refuses the
whole pass before any write. During the run, per-session failures
leave NULL (or, under `--overwrite`, the prior envelope) and are
counted; the pass exits nonzero if `failed > 0`.

**D6 — no reuse of `routing_calibration.py` here.** Its kNN operates
on routing evidence and belongs to E2-similar's design review.
Referenced to prevent rebuilding, not imported.

## Test strategy

Fake backend shim (the judge-test pattern), stdlib SQLite. The
load-bearing rules and their discriminators:

- **redacted-only input, allowlist-proven:** the fixture DB carries a
  sensitive marker in `project_path`, another in
  `benchmark_run_dir`, and a raw-text marker differing from
  `content_preview`; the payload the shim receives must contain the
  preview text and NONE of the three markers — proving the allowlist,
  not merely the absence of one raw string.
- **NULL on failure:** a shim that errors for one session leaves that
  session NULL and the report counts it; asserting the column value,
  not just the count.
- **no zero-vector, and each refusal for its own reason:** shims
  returning `[]`, an all-zeros vector, a NaN element, a boolean
  element, and a dim-mismatched vector are each refused by FR-9 —
  discriminated separately, and the zero vector explicitly (cosine
  over zero norm is undefined, and #285/FR-3 promise "never a
  zero-vector"). A valid nonzero vector is accepted.
- **provenance atomicity:** the stored value parses as the envelope
  with model+dim+vector consistent; a mutation dropping the model from
  the write fails.
- **lifecycle idempotency:** a no-work second run performs ZERO
  backend calls INCLUDING the probe (shim counts every HTTP-level
  invocation); any pre-existing envelope survives an ordinary run and
  is replaced only under `--overwrite`.
- **overwrite preserves the last valid value:** existing valid
  envelope + `--overwrite` + backend failure for that session → the
  old envelope is intact afterwards, asserted on the column value.
- **truthful reporting:** an ordinary run over existing envelopes
  reports `skipped_existing` with the stored-model distribution; a
  mutation that labels them `skipped_other_model` from the CONFIGURED
  model name fails.
- **determinism:** two composer runs over unchanged rows produce
  byte-identical input.
- **resolved-model rule:** a shim that reports no model identity
  results in NULL + failure count, never an envelope with model "".

Each discriminator is mutation-checked at build time (revert the
behavior, confirm the named test fails; `__pycache__` cleared, `ERROR:`
checked as well as `FAIL:` — house discipline).

## Live verification (build-time, recorded)

One live capture against a local Ollama pins the embeddings endpoint,
request shape, and response fields (including whether and where a
model id appears). The capture uses SYNTHETIC fixed text — never a
real session payload — because the raw request/response goes into the
repo. It is recorded in the bundle
(`verification-ollama-embed.md`) and the parser/tests derive from it —
not from memory. Recorded-capture-is-ground-truth is the house rule
this follows.

## Not planned

`SIMILAR_TO` population, similarity math, clustering, MCP/Studio
surfaces, pgvector, batch/streaming embedding daemons, per-turn
embeddings. E2-similar owns the first group; the rest needs its own
justification if ever wanted.

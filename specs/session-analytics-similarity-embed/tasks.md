# Tasks: E2-embed — session embedding pipeline

Order is load-bearing: the contract and config exist before the
backend that implements them; the composer's redaction guarantee is
proven before the runner embeds anything; the live capture happens
before the Ollama parser is finalized.

## T1 — contract, registry, config

**Implements:** FR-2 (default posture), FR-8 (config discipline),
FR-9 (validation).

`embedding/contracts.py` (EmbeddingBackend protocol + envelope
dataclass + `validate_envelope()`), `embedding/registry.py`,
`embedding/_register.py`; `embedding` block in
`config_data/defaults.json`; config-key constants in `constants.py`.

**Done when:** registry resolves `ollama` (stub OK at this point);
`validate_envelope()` refuses empty vector, dim mismatch, non-finite
elements, empty model — each with its own test; config layering
proven by an env-override test; no hardcoded default in any new
source file.

## T2 — deterministic redacted composer

**Implements:** FR-1, FR-7.

`embedding/composer.py`: role-tagged `content_preview` rows ordered by
`sequence_num`, configured char cap, truncation reported.

**Done when:** the redacted-only discriminator passes (raw marker
absent, preview text present); byte-identical output on repeat; cap
respected with truncation counted; empty-session input reported as
unembeddable, not embedded as "".

## T3 — live capture, then the Ollama backend

**Implements:** FR-2, FR-5.

FIRST the capture: one live call against local Ollama, recorded as
`verification-ollama-embed.md` (endpoint, request, response, where the
model id appears). THEN `embedding/ollama_embed.py` derived from it.

**Done when:** the verification note exists with the raw
request/response; the backend parses exactly that shape; a shim test
proves a response without a model identity yields no envelope (FR-5);
network errors surface as failures, not exceptions escaping the pass.

## T4 — pass runner + CLI

**Implements:** FR-3, FR-6, D5.

`embedding/runner.py` + `cli.py embed` subcommand: startup probe,
NULL-targeting selection, `--overwrite`, per-session accounting
(embedded / skipped / skipped_other_model / failed / truncated),
nonzero exit on failures.

**Done when:** second run performs zero backend calls (shim counts);
other-model envelope survives without `--overwrite` and is replaced
with it; failed session verifiably NULL in the column; unreachable
backend refuses the pass before any write.

## T5 — suite, README, mutation pass

**Done when:** `tests/test_embedding.py` covers every discriminator in
plan.md's test strategy; every discriminator mutation-checked (revert
behavior → named test fails; `__pycache__` cleared; `ERROR:` checked
as well as `FAIL:`); full session-analytics suite green; README gains
the `embed` command + envelope contract + E2-similar pointer;
`check-doc-accuracy` clean.

## Out of scope

Everything in spec.md §Non-goals. E2-similar is its own issue with
its own SDD.

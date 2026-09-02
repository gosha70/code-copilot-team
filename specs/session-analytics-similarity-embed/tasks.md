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

The contract is abstract: `EmbeddingResult{vector, resolved_model}`.
Whether Ollama can populate `resolved_model` — and from where — is
T3's capture question, not T1's.

**Done when:** registry resolves `ollama` (stub OK at this point);
`validate_envelope()` refuses each FR-9 case with its own test —
empty vector, ZERO vector, NaN/±Inf, boolean element, dim mismatch,
dim 0, empty model, empty provider, wrong schema_version, bad
embedded_at — and accepts a valid nonzero vector; config layering
proven against the loader's FULL documented precedence
(`defaults.json < ~/.cct/session-analytics.json < repo-root .env <
real env < CLI`, `config.py:8`), including a user-JSON-layer override
test; no hardcoded default in any new source file.

## T2 — deterministic redacted composer

**Implements:** FR-1, FR-7.

`embedding/composer.py`: role-tagged `content_preview` rows ordered by
`sequence_num`, configured char cap, truncation reported.

**Done when:** the allowlist discriminator passes — sensitive markers
planted in `project_path`, `benchmark_run_dir`, and raw text all
absent from the composed payload, preview text present; the composer
provably selects ONLY `sequence_num`, `role`, `content_preview`;
byte-identical output on repeat; cap respected with truncation
counted; empty-session input reported as unembeddable, not embedded
as "".

## T3 — live capture, then the Ollama backend

**Implements:** FR-2, FR-5.

FIRST the capture: one live call against local Ollama with SYNTHETIC
fixed text (the raw request/response enters the repo), recorded as
`verification-ollama-embed.md` (endpoint, request, response, whether
and where a model id appears). THEN `embedding/ollama_embed.py`
derived from it. If the capture shows Ollama does NOT authoritatively
report the serving model, the backend must refuse to embed AT ALL
(FR-5) — a configured model string is a request, never authoritative
serving evidence, so explicit configuration does not soften the
refusal. Surfaced in review, not papered over.

**Done when:** the verification note exists with the raw
request/response; the backend parses exactly that shape; a shim test
proves a response without a model identity yields no envelope (FR-5);
network errors surface as failures, not exceptions escaping the pass.

## T4 — pass runner + CLI

**Implements:** FR-3, FR-6, D5.

`embedding/runner.py` + `cli.py embed` subcommand implementing the
FR-6 lifecycle IN ORDER: durable-state inspection first; no work →
return with zero backend contact; probe only when work exists;
embed → validate → one replacement write. Accounting: embedded /
skipped_existing (with stored-model distribution) / failed /
truncated; nonzero exit on failures.

**Done when:** a no-work second run performs ZERO backend calls
including the probe (shim counts every HTTP-level invocation); any
existing envelope survives an ordinary run and is replaced only under
`--overwrite`; under `--overwrite`, a failed backend call leaves the
prior envelope intact (asserted on the column value); a failed
session is verifiably NULL in the column; an unreachable backend
refuses the pass before any write; the report never claims
`skipped_other_model` — a mutation deriving it from the configured
model name fails.

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

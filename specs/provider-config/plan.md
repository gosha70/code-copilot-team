---
spec_mode: full
feature_id: provider-config
risk_category: integration
justification: "New CCT capability touching shared/scripts/, shared/templates/, every adapters/<copilot>/setup.sh, plus the benchmark harness's BackendResult.backend_metadata recording schema. Delivered as additive extensions only — existing peer-review consumers see no breakage. Verified-facts basis at doc_internal/copilot-llm-support-matrix.md."
status: draft
date: 2026-05-08
issue: TBD
origin:
  user_message: "if this repo produces the setting for AI Copilot, then we MUST [know] if that copilot supports LLM customization and how"
  date: 2026-05-08
  related_specs:
    - specs/benchmark-harness/audit-2026-05-08.md
    - shared/templates/provider-profile-template.toml
    - doc_internal/copilot-llm-support-matrix.md
  origin_claim: |
    Today's CCT adapters emit conventions/rules only — no LLM/provider
    config. The user directive: make provider config a first-class CCT
    capability, embedded in the adapter setup workflow, with the
    benchmark harness as one consumer among several. Posture: CCT
    records, doesn't set.
---

# Implementation plan — provider-config

## Approach

Three independent deliverables, each its own commit, each lands when ready. None blocks the others; they collectively realize the spec's acceptance criteria.

## Phase 1 — Schema documentation + recording-schema lockdown

- Write `shared/templates/PROVIDER_PROFILE_README.md` covering all six copilot families with concrete env-var or config-file examples (the matrix from the spec, made executable).
- Add the `[meta]` block (optional, with `schema_version` + `documentation_url`) to `shared/templates/provider-profile-template.toml`. Existing profiles parse unchanged.
- Lock the benchmark recording-schema additions in `benchmarks/schema/run-record.schema.json`: `backend_metadata.provider_endpoint`, `provider_auth_token_present`, `provider_config_source`. Update `test_schemas.py` invariants.
- Update `scripts/benchmark_runner/backends/claude_code.py` to record `provider_config_source: "env" | "none"` (current implementation already records `provider_endpoint` and `provider_auth_token_present`).

Done when: `bash scripts/validate-spec.sh --feature-id provider-config` passes; the recording-schema test pins the new fields; existing peer-review TOMLs continue to parse.

## Phase 2 — `provider-emit.sh` translator + per-adapter `--provider` flag

- New `shared/scripts/provider-emit.sh <copilot> <provider-id>` that reads `~/.code-copilot-team/providers.toml` and emits the right per-copilot config:
  - For Claude Code / Aider / GH Copilot CLI: prints an env-var block to stdout the user sources (`. <(./shared/scripts/provider-emit.sh claude-code my-vllm)`).
  - For Codex: appends a `[model_providers.<id>]` block to `~/.codex/config.toml` (idempotent).
  - For Cursor / Windsurf: prints a settings-JSON snippet for paste-into-UI (best-effort; documented limitation).
- Each `adapters/<copilot>/setup.sh` accepts optional `--provider <id>` and `--providers-file <path>`. When set, calls `provider-emit.sh` and writes the output where the copilot expects it.
- Golden-output snapshot tests under `tests/test-provider-emit.sh` for each copilot family + a sample profile.

Done when: each `adapters/<copilot>/setup.sh --provider <id>` produces config that matches a committed snapshot; existing call patterns (no `--provider`) continue to work unchanged.

## Phase 3 — Benchmark consumer wiring (additional copilot backends)

- When issue #33's additional copilot backends land (Aider, Codex, GH Copilot CLI), each backend's `run()` reads its copilot-specific provider env vars at run time and writes them into `backend_metadata` using the canonical fields locked in Phase 1.
- The auth value is NEVER recorded — only presence as a boolean (existing rule, applied uniformly across copilots).

Done when: each shipped backend produces a run record whose `backend_metadata` distinguishes the four-state provider-routing matrix (URL set/unset × auth set/unset) plus the model dimension, regression-tested per backend.

## Phase boundaries

- Phase 1 is preconditional for Phase 2 (schema must be locked first).
- Phase 3 depends on issue #33's backend-readiness verification PRs landing.
- Each phase is a separate review gate. Phase 1 can land independently of issue #33's progress.

## Out of scope (this spec)

See `spec.md` § "Out of scope (this spec)". Notably: per-use-case TOML sub-blocks (Option 2 territory) — explicitly avoided to keep schema churn bounded.

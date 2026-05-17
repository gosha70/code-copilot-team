# Tasks — provider-config

Phased delivery per `plan.md`. Each task is bounded and independently verifiable. Phase 1 is preconditional for Phase 2; Phase 3 depends on issue #33's progress.

## Phase 1 — Schema documentation + recording-schema lockdown

### T1.1 — `PROVIDER_PROFILE_README.md`
- **Output:** `shared/templates/PROVIDER_PROFILE_README.md` covering all six copilot families with concrete env-var or config-file examples (the matrix from `spec.md`, made executable).
- **Done when:** README exists, links resolve, each copilot's env-var matrix matches `doc_internal/copilot-llm-support-matrix.md`.

### T1.2 — Optional `[meta]` block in profile template
- **Output:** `shared/templates/provider-profile-template.toml` gains an optional top-level `[meta]` block with `schema_version` (string, default "1.0") and `documentation_url` (string, default to spec path). Existing profiles without `[meta]` parse unchanged.
- **Done when:** `tests/test-validate-collaboration.sh` (or equivalent) round-trips both with-meta and without-meta profiles.

### T1.3 — Recording-schema additions in `run-record.schema.json`
- **Output:** `benchmarks/schema/run-record.schema.json` requires `backend_metadata.provider_endpoint` (string-or-null), `provider_auth_token_present` (boolean), `provider_config_source` ("env" | "toml" | "none"). `test_schemas.py` invariants pin them.
- **Done when:** schema validates the existing claude-code backend's run records; `test_schemas.py:TestSchemaInvariants::test_run_record_provider_routing_required` passes.

### T1.4 — Update `claude-code` backend to record `provider_config_source`
- **Output:** `scripts/benchmark_runner/backends/claude_code.py` adds `provider_config_source: "env" | "none"` to `backend_metadata`. "env" when `ANTHROPIC_BASE_URL` is set; "none" otherwise. (`provider_endpoint` and `provider_auth_token_present` are already recorded.)
- **Done when:** existing `test_claude_code_backend.py:test_provider_routing_state_*` matrix passes with the new field asserted.

**Phase 1 commit:** `feat(provider-config): schema docs + recording-schema lockdown`

## Phase 2 — `provider-emit.sh` translator + per-adapter `--provider` flag

### T2.1 — `provider-emit.sh` translator
- **Output:** `shared/scripts/provider-emit.sh <copilot> <provider-id> [--profile-file <path>]` reads the profile file (default `~/.code-copilot-team/providers.toml`), looks up the provider, emits per-copilot config:
  - claude-code: env-var block to stdout (`export ANTHROPIC_BASE_URL=...`)
  - aider: env-var block + suggested `--model <prefix>/<id>` flag to stdout
  - codex: appends `[model_providers.<id>]` block to `~/.codex/config.toml` (idempotent — skip if already present)
  - github-copilot: env-var block to stdout (`export COPILOT_PROVIDER_BASE_URL=...`)
  - cursor / windsurf: settings-JSON snippet to stdout for paste-into-UI
- **Done when:** `tests/test-provider-emit.sh` runs the translator for each (copilot, sample-profile) pair and snapshot-asserts the output matches a committed golden file.

### T2.2 — Per-adapter `--provider` flag
- **Output:** each `adapters/<copilot>/setup.sh` accepts optional `--provider <id>` and `--providers-file <path>`. When set: invokes `shared/scripts/provider-emit.sh <copilot> <provider-id>` and writes to the right destination (stdout-for-shell-rc, or copilot's config file).
- **Done when:** end-to-end smoke for each copilot — given a sample provider profile, `setup.sh --provider <id>` produces config that the copilot would actually read.

### T2.3 — Backwards compatibility test
- **Output:** existing `setup.sh` invocations (no `--provider`) continue to install conventions/rules unchanged. Test asserts the no-provider output is byte-identical (or content-equivalent) to pre-Phase-2 output.
- **Done when:** test in `tests/test-adapter-setup-backcompat.sh` (new) passes.

**Phase 2 commit:** `feat(provider-config): provider-emit translator + per-adapter --provider flag`

## Phase 3 — Backend consumer wiring (depends on issue #33)

### T3.1 — Aider backend reads OPENAI_API_BASE / OLLAMA_API_BASE
- **Output:** `scripts/benchmark_runner/backends/aider.py` (when shipped via #33) records `provider_endpoint` from whichever env var is in use; `provider_auth_token_present` follows.
- **Done when:** the aider backend's recording-schema-matrix test passes for all 4 routing states.

### T3.2 — Codex backend reads `~/.codex/config.toml`
- **Output:** `scripts/benchmark_runner/backends/codex.py` (when shipped via #33) records the active provider id + path to config.toml + `wire_api`. `provider_config_source = "toml"`.
- **Done when:** recording-schema test passes; reading a sample config.toml produces the expected `backend_metadata`.

### T3.3 — GitHub Copilot CLI backend reads COPILOT_PROVIDER_*
- **Output:** `scripts/benchmark_runner/backends/github_copilot.py` (when shipped via #33; gated on the verification PR per #33's acceptance criteria) records `COPILOT_PROVIDER_BASE_URL`, `COPILOT_MODEL`, `COPILOT_PROVIDER_TYPE`, `COPILOT_OFFLINE` (bool).
- **Done when:** recording-schema test passes.

**Phase 3 commit:** `feat(provider-config): backend consumer wiring (aider/codex/github-copilot)`

## Out of scope (this spec)

- Per-use-case TOML sub-blocks (Option 2). Separate spec if needed.
- CCT-side provider router/proxy.
- Hosted / shared provider profile registry.
- Provider-specific health check beyond the existing `healthcheck` schema field.
- Cross-provider dollar-cost reporting.

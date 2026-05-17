---
feature_id: provider-config
spec_mode: full
status: draft
issue: TBD
origin:
  user_message: "if this repo produces the setting for AI Copilot, then we MUST [know] if that copilot supports LLM customization and how"
  date: 2026-05-08
  related_specs:
    - specs/benchmark-harness/audit-2026-05-08.md
    - shared/templates/provider-profile-template.toml
    - doc_internal/copilot-llm-support-matrix.md
  origin_claim: |
    Today's CCT adapters (`adapters/<copilot>/setup.sh`) emit only
    conventions/rules — they do NOT emit LLM-provider configuration.
    The user's directive is to make provider configuration a
    first-class CCT capability so that when `setup.sh` runs for a
    given copilot, the user can opt to also wire up the provider
    they've chosen for that project. This is **embedded support**
    (used by all CCT users for their normal workflow), not a
    benchmark-only concern. The benchmark harness consumes the same
    config model.
---

# Provider-config — standalone CCT capability

> **Scope discipline (Option 1, minimal extension).** This spec
> deliberately does NOT introduce per-use-case sub-blocks under each
> provider (the "Option 2" framing in the audit). The schema at
> `shared/templates/provider-profile-template.toml` already exposes
> the primitives every consumer needs: `type`, `base_url`, `model`,
> `api_key_env`, `host`. Each consumer (peer review, benchmark,
> adapter setup) constructs its own per-copilot invocation from those
> primitives. The minimal extension covered by this spec is **a
> recording schema** (what each consumer captures about which provider
> a run used) and **adapter-setup emission** (each adapter's setup.sh
> learns to emit the right per-copilot config from a chosen provider
> profile). The TOML schema does not gain new fields.

## User Scenarios

1. **Maintainer points Aider at a local Ollama instance.** They edit `~/.code-copilot-team/providers.toml` to add a `[providers.local-ollama]` block (`type = "ollama"`, `host = "localhost:11434"`, `model = "qwen3.5"`). Then `./adapters/aider/setup.sh ~/myproject --provider local-ollama` emits an env-var block (`OLLAMA_API_BASE=http://localhost:11434`) and a suggested `--model ollama_chat/qwen3.5` flag. The user sources the block in their shell rc; future `aider` invocations route to Ollama.

2. **Team lead runs the benchmark harness and reads the provider out of the report.** They run `./scripts/benchmark run --benchmark aider-polyglot --backend claude-code --model sonnet --runs 1`. The run-record's `backend_metadata.provider_endpoint` field is `null` (default Anthropic API) or a URL (gateway-routed). The report renders distinct rows for each `(backend, provider)` tuple, so a teammate's runs against a vLLM gateway are visible-as-different from another teammate's runs against the Anthropic API.

3. **Curator adds a new provider that all CCT consumers pick up.** They add `[providers.gdx-spark]` to `~/.code-copilot-team/providers.toml` once. `./adapters/claude-code/setup.sh ~/myproject --provider gdx-spark` emits the right Anthropic-Messages env vars; `./adapters/codex/setup.sh --provider gdx-spark` appends the right `[model_providers.gdx-spark]` block to `~/.codex/config.toml`; `./scripts/peer-review.sh --provider gdx-spark` (existing flow) uses the same profile. One profile, three consumers — no duplicate config, no drift.

4. **CI smoke verifies emitted config is well-formed.** A test in `tests/test-provider-emit.sh` runs `provider-emit.sh <copilot> <sample-profile>` for each (copilot, sample) pair and snapshot-asserts the output. A schema change that breaks emission gets caught before the user-visible `setup.sh` does.

5. **Forensic on a stale benchmark run.** A maintainer reading a year-old run-dir sees `backend_metadata.provider_endpoint = "http://192.168.1.50:8000"` and can reconstruct what was actually being measured — even if the host is gone, the run's identity is in the record.

## Requirements

1. **Single source of truth.** `~/.code-copilot-team/providers.toml` (template at `shared/templates/provider-profile-template.toml`) is consumed by peer review, benchmark, and adapter setup uniformly. No per-feature TOML files; no parallel schema.

2. **Schema is unchanged for field semantics.** No new per-provider sub-blocks (`[providers.<id>.benchmark]` / `[providers.<id>.adapter_setup]`). Existing `type` / `base_url` / `model` / `api_key_env` / `host` / `command` fields cover all consumers' needs. Pure additions: optional top-level `[meta]` block (forward-compat versioning) + a README documenting the existing fields with worked examples.

3. **CCT records, doesn't set.** The benchmark harness reads provider env vars at run time and writes them into `backend_metadata`; it does not mutate the user's shell environment. Adapter setup emits config to stdout (or, for Codex, appends to a copilot-specific config file the copilot itself reads); the harness does not run a router/proxy.

4. **Auth values are never recorded.** Only presence-as-boolean. Locked at the recording-schema level (`run-record.schema.json` field `provider_auth_token_present`).

5. **Per-copilot translator.** `shared/scripts/provider-emit.sh <copilot> <provider-id>` is the single point that translates the abstract profile into copilot-specific config. Each `adapters/<copilot>/setup.sh` delegates to it via `--provider <id>` flag. Adapters do NOT learn the schema directly.

6. **Backwards compatibility.** Existing `providers.toml` files (without `[meta]`) parse and dispatch correctly. Existing `setup.sh` invocations (without `--provider`) continue to install conventions/rules unchanged.

7. **GUI copilot best-effort emission.** Cursor and Windsurf are out of scope as benchmark backends, but `provider-emit.sh cursor <id>` and `provider-emit.sh windsurf <id>` produce paste-into-UI settings JSON snippets — best-effort, with the limitation documented.

## Constraints

What this spec MUST NOT do:

- **No per-use-case TOML sub-blocks.** That's Option 2 territory and a separate spec if/when it becomes necessary.
- **No CCT-side provider router or proxy.** CCT remains out of the connection path. The user's chosen copilot talks directly to the user's chosen provider; CCT only records and emits.
- **No hosted / shared provider profile registry.** Profiles are local to `~/.code-copilot-team/`. Sharing across team members is via standard Git / file-share / config-management tooling, not a CCT-hosted service.
- **No auth-value recording, ever.** Tokens, keys, secrets — presence-only. This is a hard schema invariant.
- **No cross-provider dollar-cost reporting.** Permanently deferred (consistent with `specs/benchmark-harness/spec.md` § Constraints).
- **No re-implementation of peer review's command-template dispatch.** The existing schema's `command` field stays peer-review-specific. Benchmark and adapter setup construct their own invocations from `type` + `base_url` + `model` + `api_key_env`.

## Posture: CCT records, doesn't set

The harness *reads* provider env vars at run time and writes them into
run records. Per-copilot adapter setup *emits* config from a chosen
profile when the user invokes `setup.sh --provider <id>`. CCT does not
mutate the user's shell environment at run time, and does not run a
provider router or proxy of its own.

This keeps CCT out of the connection path — provider routing is a
shell-environment concern (or a config-file concern for copilots like
Codex that read from disk). The user always owns the routing decision.

## Provider env-var matrix per copilot

For each headless-driveable copilot, the relevant env vars / config
files are documented in `doc_internal/copilot-llm-support-matrix.md`
with primary-source citations. Summary:

| Copilot | Primary config surface | Env vars (or config file) the harness records |
|---|---|---|
| **Claude Code** | env vars (Anthropic Messages gateway) | `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN_present` (bool), `ANTHROPIC_DEFAULT_*_MODEL`, `CLAUDE_CODE_USE_BEDROCK`, `CLAUDE_CODE_USE_VERTEX` |
| **Aider** | env vars + YAML config | `OPENAI_API_BASE`, `OLLAMA_API_BASE`, presence of `OPENAI_API_KEY` / `OLLAMA_API_KEY`, the active `--model` arg |
| **Codex** | `~/.codex/config.toml` | path to config.toml + the active provider id from `[model_providers.<id>]` block + `wire_api` |
| **GitHub Copilot CLI** | env vars | `COPILOT_PROVIDER_BASE_URL`, `COPILOT_MODEL`, `COPILOT_PROVIDER_TYPE`, `COPILOT_OFFLINE` (bool) |

Cursor and Windsurf are GUI-only and out of scope as benchmark
backends; for adapter-setup emission, see "Future work" below.

## Recording schema in run records

When a benchmark backend produces a `BackendResult`, the runner writes
the relevant env-var snapshot into `backend_metadata` under three
canonical fields:

```json
{
  "family": "<copilot-id>",
  "model": "<model-id-or-empty>",
  "provider_endpoint": "<full-URL-or-null>",
  "provider_auth_token_present": true,
  "provider_config_source": "env|toml|none"
}
```

Per-copilot extensions (recorded under the same keys, since they map
to the same semantic):

- **Claude Code**: `provider_endpoint = ANTHROPIC_BASE_URL` (or null);
  `provider_auth_token_present = bool(ANTHROPIC_AUTH_TOKEN)`. Plus
  `claude_code_invocation: "launcher" | "bare"` for the invocation
  mode (per spec.md § "Backends vs providers"). Already implemented in
  `scripts/benchmark_runner/backends/claude_code.py`.
- **Aider** (when shipped): `provider_endpoint = OPENAI_API_BASE` (or
  `OLLAMA_API_BASE`); `provider_auth_token_present` follows whichever
  is in use.
- **Codex** (when shipped): `provider_endpoint = base_url` from the
  active `[model_providers.<id>]` block; `provider_config_source =
  "toml"` (path to `~/.codex/config.toml` recorded under
  `backend_metadata.codex_config_path`).
- **GitHub Copilot CLI** (when shipped): `provider_endpoint =
  COPILOT_PROVIDER_BASE_URL`; `provider_auth_token_present =
  bool(COPILOT_PROVIDER_API_KEY)`.

**Auth values are never recorded.** Only their presence, as a boolean.
This is locked at the schema level (see
`benchmarks/schema/run-record.schema.json` once the field is added).

## Adapter setup emission (`setup.sh --provider <id>`)

Each `adapters/<copilot>/setup.sh` gains an optional `--provider <id>`
flag. When set:

1. Read `~/.code-copilot-team/providers.toml` (or the explicit path
   passed via `--providers-file`).
2. Look up the provider section by id.
3. Translate the provider's `type` + `base_url` + `model` +
   `api_key_env` into the right per-copilot config:
   - **Claude Code**: print to stdout an env-var block the user
     sources (`export ANTHROPIC_BASE_URL=... ; export
     ANTHROPIC_AUTH_TOKEN=...`).
   - **Aider**: print the env-var block + suggested
     `--model <prefix>/<id>` flag.
   - **Codex**: emit a `[model_providers.<id>]` block to append to
     `~/.codex/config.toml` (idempotent — skip if already present).
   - **GitHub Copilot CLI**: print the env-var block.
   - **Cursor / Windsurf**: print a settings JSON snippet the user
     pastes into the IDE's Settings → Models pane (best-effort; GUI
     copilots can't be fully automated).

The translation logic lives in `shared/scripts/provider-emit.sh` (new)
keyed by copilot family; each adapter's `setup.sh` calls it. No
per-copilot adapter learns the schema directly — they all delegate to
`provider-emit.sh`.

## Schema extension (minimal)

The existing `shared/templates/provider-profile-template.toml` schema
is unchanged for **all field semantics**. Two pure additions:

1. A top-level optional `[meta]` block with `schema_version` (string)
   and `documentation_url` (string, default to this spec's path). For
   forward-compat versioning. Existing profiles without `[meta]` are
   treated as `schema_version = "1.0"`.
2. A README at `shared/templates/PROVIDER_PROFILE_README.md`
   documenting the existing fields, with worked examples per copilot
   (the env-var matrix above, made concrete). Not a schema change —
   documentation only.

No new per-provider fields. No `[providers.<id>.benchmark]` /
`[providers.<id>.adapter_setup]` sub-blocks. If a future use case
needs them, that's a separate spec (Option 2).

## Acceptance criteria

- [ ] `~/.code-copilot-team/providers.toml` is the single source of
      truth across peer review, benchmark, and adapter setup. Existing
      peer-review users see no breakage.
- [ ] `shared/scripts/provider-emit.sh <copilot> <provider-id>` emits
      the right per-copilot config for {claude-code, aider, codex,
      github-copilot, cursor, windsurf}. For each: tested against a
      committed sample profile + golden expected-output snapshot.
- [ ] Each `adapters/<copilot>/setup.sh` accepts `--provider <id>` and
      `--providers-file <path>` (default
      `~/.code-copilot-team/providers.toml`).
- [ ] Benchmark harness records `provider_endpoint`,
      `provider_auth_token_present`, `provider_config_source` in
      `backend_metadata` for every backend that has a configurable
      provider. Auth values are NEVER recorded.
- [ ] `shared/templates/PROVIDER_PROFILE_README.md` covers all 6
      copilot families with concrete env-var or config-file examples.
- [ ] Schema validation: existing `providers.toml` files (without
      `[meta]`) continue to parse and dispatch correctly.
- [ ] `bash scripts/validate-spec.sh --feature-id provider-config` passes
      (full-mode spec sections present).

## Out of scope (this spec)

- Per-use-case TOML sub-blocks (`[providers.<id>.benchmark]`,
  `[providers.<id>.adapter_setup]`). If they become necessary, they
  land in a separate Option-2 spec.
- A CCT-side provider router or proxy. CCT remains out of the
  connection path; it records and emits, never proxies.
- Hosted / shared provider profile registry. Profiles are local to
  `~/.code-copilot-team/`.
- Provider-specific health checks beyond the existing `healthcheck`
  field in the schema.
- Cross-provider dollar-cost reporting (deferred indefinitely per
  benchmark-harness spec).

## Future work (separate specs)

- **GUI copilot deep integration**: emit a Settings JSON file Cursor
  / Windsurf can import directly, vs the current paste-into-UI
  posture. Requires understanding their settings format and
  forward-compat strategy.
- **Provider profile validation**: `shared/scripts/validate-providers.sh`
  that checks each profile's reachability + auth + capabilities (tool
  calling, streaming, ≥128k context for GH Copilot) before any
  consumer uses it.
- **Migration tool** for users currently using ad-hoc env vars: read
  the user's shell rc, suggest a `providers.toml` skeleton.

## Source pointers

- `shared/templates/provider-profile-template.toml` — existing schema
  (unchanged by this spec).
- `shared/skills/provider-collaboration-protocol/SKILL.md` —
  peer-review consumer.
- `doc_internal/Multi_Copilot_Providers_PLAN.md` — earlier planning
  doc; review for relevance and merge useful pieces.
- `doc_internal/copilot-llm-support-matrix.md` — verified-facts
  per-copilot LLM-customization matrix.
- `specs/benchmark-harness/spec.md` § "Backends vs providers" — the
  benchmark consumer's view.

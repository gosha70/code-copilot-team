---
feature_id: provider-config
spec_mode: placeholder
status: draft-pending-design-decision
issue: TBD
origin:
  user_message: "if this repo produces the setting for AI Copilot, then we MUST [know] if that copilot supports LLM customization and how"
  date: 2026-05-08
  related_specs:
    - specs/benchmark-harness/audit-2026-05-08.md
    - shared/templates/provider-profile-template.toml
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

# Provider-config — standalone CCT capability (PLACEHOLDER)

> **Status: design pending.** This spec is a stub. Two prerequisites
> before it can be filled out:
>
> 1. Audit on `specs/benchmark-harness/audit-2026-05-08.md` is
>    approved by the user (locks the backend-vs-provider abstraction).
> 2. User's choice between **Option 1 (minimal extension)** and
>    **Option 2 (per-use-case extensions)** of the existing
>    `shared/templates/provider-profile-template.toml` schema (see
>    Open question below).
>
> Until both prerequisites land, this file remains a placeholder so
> that other docs can cross-reference the planned spec without
> committing to its contents.

## Problem

The repo's six AI-copilot adapters (`adapters/{aider,claude-code,codex,cursor,github-copilot,windsurf}/setup.sh`) install conventions and rules — but **not LLM/provider configuration**. A user who wants to point Aider at a local Ollama instance, or route Claude Code through a vLLM gateway, or configure Codex for OpenRouter, has to assemble the env vars and config files by hand based on each copilot's separate documentation.

CCT already has a partial solution for the **peer review** flow: `~/.code-copilot-team/providers.toml` (template at `shared/templates/provider-profile-template.toml`) defines providers with type-aware fields (`cli` / `openai-compatible` / `ollama` / `custom`). But that schema's `command` field is shaped for review invocation (`{review_request}`, `{model}` placeholders), and the broader workflow ("emit config files for each adapter") is not implemented anywhere.

This spec proposes a **standalone provider-config capability** that:

1. Extends the existing `~/.code-copilot-team/providers.toml` schema (does NOT duplicate it).
2. Adds a way for `adapters/<copilot>/setup.sh` to emit the right per-copilot configuration files / env-var setups based on a user-chosen provider profile.
3. Is consumed by the benchmark harness for the `backend_metadata.provider_endpoint` recording (the harness reads the env at run time; the env was set by either the user's shell rc or by a CCT-emitted profile).

## Strategic framing

CCT's value is **governance + measurement around copilot workflows**. Provider configuration is part of the workflow:

- For a developer, it's "I want Aider on my private Llama, Claude Code on my company's Bedrock, Codex on OpenRouter — make my env reflect that."
- For a team, it's "all reviewers route to the same provider for consistency; here's the team profile."
- For a benchmark, it's "this run used vLLM on `gpu-host-1`; that run used Anthropic API; the report should segment by provider."

The capability is therefore embedded (default workflow), not benchmark-only.

## Out of scope

- Authoring new copilots. CCT works with the six existing adapters; adding a new copilot family is a separate concern.
- Selling a hosted / SaaS provider profile registry. Provider profiles are local files in `~/.code-copilot-team/`.
- Replacing each copilot's native config. CCT *emits* the config the copilot expects, in the format the copilot's docs specify; it does not introduce a CCT-specific runtime layer between copilot and provider.

## Verified-fact basis

The full per-copilot LLM-customization fact base lives at `doc_internal/copilot-llm-support-matrix.md` (research run 2026-05-08). Highlights:

- **Headless-driveable copilots**: Claude Code, Aider, Codex, GitHub Copilot CLI. Each has its own provider-config surface (env vars, TOML, etc.).
- **GUI-only copilots** (out of scope as benchmark backends but in scope for provider-config emission): Cursor, Windsurf. CCT can still emit the right Cursor settings JSON or Windsurf profile entry.
- **Three integration formats matter**: Anthropic Messages, OpenAI Chat Completions, OpenAI Responses.

## Open question: extension scope of the existing schema

`shared/templates/provider-profile-template.toml` already has the right type taxonomy (`cli` / `openai-compatible` / `ollama` / `custom`) and forward-declared fields (`base_url`, `api_key_env`, `host`, `model`). Two ways to extend it for the standalone-feature use cases:

### Option 1 — minimal (no new fields)

The harness and adapter `setup.sh` scripts read provider type + base_url + model + api_key_env from the existing schema and construct copilot-specific commands themselves.

- Pro: zero schema churn; existing peer-review users see no diff.
- Pro: each consumer (peer review, benchmark, adapter setup) implements its own command-building logic — clean separation of concerns.
- Con: duplicated logic across consumers (peer review, benchmark, adapter setup all have to know "given an `openai-compatible` provider, here's how Aider talks to it" / "here's how Claude Code talks to it").

### Option 2 — per-use-case extensions

Add optional sub-blocks per provider that describe how each consumer should invoke it. Example:

```toml
[providers.gdx-spark]
type = "openai-compatible"
base_url = "http://192.168.1.50:8000/v1"
api_key_env = "GDX_SPARK_API_KEY"
model = "deepseek-coder-v2"

[providers.gdx-spark.peer_review]
command = "curl -sf {base_url}/chat/completions ..."

[providers.gdx-spark.benchmark]
temperature = 0.0
extra_headers = { "X-Trace" = "cct-bench" }

[providers.gdx-spark.adapter_setup]
# Per-copilot invocation hints (which env vars to set, which config file to emit)
claude_code = { gateway = "anthropic-messages", env = { ANTHROPIC_BASE_URL = "{base_url}" } }
aider = { env = { OPENAI_API_BASE = "{base_url}", OPENAI_API_KEY_env = "{api_key_env}" } }
codex = { config_toml = "[model_providers.gdx-spark]\nbase_url = \"{base_url}\"\nenv_key = \"{api_key_env}\"\nwire_api = \"chat\"" }
github_copilot = { env = { COPILOT_PROVIDER_BASE_URL = "{base_url}", COPILOT_MODEL = "{model}" } }
```

- Pro: declarative — once a provider is defined with all sub-blocks, every consumer (peer review, benchmark, adapter setup) can use it without ad-hoc per-copilot logic.
- Pro: a single provider profile drives the whole CCT workflow; users edit one file.
- Con: schema gets significantly richer; changes to any copilot's invocation surface require schema updates.
- Con: forward-compatibility risk — when a new copilot version changes its env-var names, every existing profile may need touching.

### Recommendation (pending user call)

Option 1 for the immediate work. Option 2 may be the right end-state but it's a much bigger schema commitment, and Option 1 is forward-compatible with Option 2 (just don't ship the `[providers.<id>.X]` blocks initially; add later when their shape stabilizes). If we ship Option 1 now, the benchmark harness's read-only consumption of the schema is trivial and we don't lock in a particular invocation contract for adapter setup.

User call expected before this spec is filled out.

## Provisional acceptance criteria (when this spec is finalized)

These are sketches; final criteria depend on the option chosen.

- [ ] `~/.code-copilot-team/providers.toml` is a single source of truth across peer review + benchmark + adapter setup.
- [ ] Each `adapters/<copilot>/setup.sh` accepts an optional `--provider <id>` flag that, when set, emits the right per-copilot configuration files alongside the existing conventions/rules.
- [ ] Documentation: `shared/docs/provider-config.md` (or equivalent) covers: (a) the TOML schema, (b) per-copilot setup invocation, (c) how the benchmark records what providers were used at run time.
- [ ] Backwards compatibility: existing peer-review users see no breakage; their `providers.toml` continues to work for the review flow.
- [ ] CI: a smoke test that emits each per-copilot config from a single profile and validates the emitted file matches the copilot's documented schema.

## Source pointers

- `shared/templates/provider-profile-template.toml` — existing schema; extend, don't duplicate.
- `shared/skills/provider-collaboration-protocol/SKILL.md` — peer-review flow that consumes the schema today.
- `doc_internal/Multi_Copilot_Providers_PLAN.md` — earlier planning doc on multi-copilot providers (review for relevance).
- `doc_internal/copilot-llm-support-matrix.md` — verified-facts per-copilot LLM-customization matrix.
- `specs/benchmark-harness/spec.md` § "Backends vs providers" — the benchmark consumer's view.

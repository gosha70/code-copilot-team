---
feature_id: llm-catalog
spec_mode: full
status: draft
date: 2026-11-10
issue: "#400"
origin:
  issue: "#400"
  urls:
    - https://github.com/gosha70/code-copilot-team/issues/400
    - https://code.claude.com/docs/en/llm-gateway
    - https://developers.openai.com/codex/config-reference
    - https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/models.md
    - https://kiro.dev/docs/cli/headless/
  transcripts:
    - specs/llm-catalog/origin/2026-11-10-issue-400-origin.md
---

# Spec: harness-agnostic LLM catalog and per-launch `--llm` selection

Revision 4 (2026-11-10, after the third review): `path_sha256` is its
own field so the stamped `origin` keeps the grammar `routing-result.sh`
validates; the hash is identity, not secrecy; D11's later ruling is a
recorded spec amendment.

Revision 3 (2026-11-10, after two bundle reviews): capability-matrix
probe with conclusive and attempt evidence and negative controls;
`--continue` keeps native behaviour and refuses `--llm`;
`credential_mode`; explicit bindings only; execution digest beside the
catalog digest, credential values excluded; one endpoint sanitizer
(origin plus path hash); Pi overlay decided by capture; Kiro
managed-model launcher in scope; state-file handling contract;
slice-specific decisions deferred to their captures.

## Why

CCT describes providers and models in three places that mean three
different things: the reviewer profile (`providers.toml`, command
templates for peer review), the routing registry (`routing.toml`,
execution profiles that bundle a connection with failover policy), and
each harness's own configuration (Claude Code environment variables,
Codex `model_providers`, Pi `models.json`). None of them lets a user
configure a named LLM target once and pick it when starting a harness.
Today that selection is done with global environment variables, which
leak into every session, change the harness's defaults, and put
credentials into shell history and multiplexer commands.

The issue asks for one user-level catalog of named targets, an optional
`--llm <id>` on every launcher, harness-specific launch adapters that
keep secrets out of argv and logs, a compatibility state decided
before the harness starts, and session stamps so a resumed session
cannot silently change model identity. When `--llm` is omitted nothing
changes.

The repository already holds the pieces: the routing library's
constrained-TOML grammar and credential-by-name boundary, the
supervisor's child-only environment wiring and secret scrub, the
routing probe's "real inference plus tool-call canary" contract, the
routing identity digest that binds the resolved endpoint, and a
launcher comment from #399 that defers applying gateway-compatibility
variables to exactly this selector. This spec composes them under a
new catalog that owns connection and model identity, and leaves
routing to own execution policy.

## Slicing (D1)

The issue's delivery plan has seven increments. The repository rule is
that a merged PR fully addresses its issue, so each increment ships
against its own issue and #400 stays open as the umbrella until every
increment, Kiro and Studio included, has landed; the PR for G closes
#400 only after A–F are merged. This bundle specifies the whole
feature so later slices build on settled contracts; `tasks.md`
details slices A and B and outlines C–G, each of which gets its own
task rows when its issue opens.

## User Scenarios

1. **Configure once, pick per launch.** A developer adds a provider,
   an endpoint, an LLM and a binding to `~/.code-copilot-team/
   llms.toml`, names the credential's environment variable, and runs
   `cct llm validate`. Later they start Claude Code on a project with
   `claude-code --llm deepseek-pro .`; the session runs against the
   DeepSeek endpoint with the named model, and the cmux workspace shows
   only `claude-code --llm deepseek-pro`.

2. **Nothing selected, nothing changed.** The same developer runs
   `claude-code .` with no `--llm`. The launcher injects no provider or
   model variable; Claude Code starts exactly as it did before this
   feature, including any gateway the developer configured natively.

3. **Refused before the harness starts.** A target whose endpoint
   speaks only the OpenAI Responses protocol is bound to Claude Code.
   `claude-code --llm spark-qwen .` exits before `claude` is executed
   with: "`spark-qwen@spark-claude` is `unsupported` on claude-code:
   endpoint `spark-responses` speaks openai-responses, claude-code
   speaks anthropic-messages". `cct llm compatibility spark-qwen`
   shows the same table.

4. **Probe before trusting.** `cct llm test deepseek-pro --harness
   claude-code` runs a headless Claude Code session through the
   resolved launch plan on a canary that exercises every capability
   the binding requires. The per-capability results, the effective
   model the harness reported, the rule version and the execution
   digest are recorded; the pair's state becomes `supported`. Removing
   tool-call support at the endpoint makes the `tool_call` check fail
   on the next probe, and the state becomes `incompatible`. A probe
   that times out records an attempt and leaves the earlier conclusive
   result in place.

5. **Resume keeps identity.** A session started with `--llm
   deepseek-pro` is later resumed with `claude-code --resume <id>`. The
   launcher restores the recorded binding, so the gateway variables the
   transcript needs are present again. `claude-code --resume <id> --llm
   spark-qwen` is refused with a recommendation to start or fork a
   session. A bare `claude-code --continue` is native: the launcher
   does not guess which session Claude Code will pick.

6. **Project narrows, never grants.** A repository's
   `.code-copilot-team/config.toml` lists `allowed = ["deepseek-pro"]`
   under `[llm]`. `--llm spark-qwen` in that project is refused; a
   project file carrying `credential_env`, an endpoint or any other
   key under `[llm]` is refused by name, so a cloned repository cannot
   redefine a user's target or introduce a credential.

7. **Explain the launch without secrets.** `cct harness explain
   claude-code --llm deepseek-pro` prints the launch plan: executable
   and arguments, the names of the variables that will be set (never
   their values, only whether each is currently set), the sanitized
   endpoint, the compatibility state with its evidence, both digests,
   and what will be cleaned up afterwards.

8. **Managed harness.** A Kiro user binds `llms.kiro-sonnet`
   (provider `kiro`, a Kiro model id) and runs `kiro-code --llm
   kiro-sonnet .`; the launcher passes `--model` and nothing else. A
   Kiro binding that names an endpoint is `unsupported`, and every
   harness list says so.

9. **Routing references the catalog (G).** A routing profile declares
   `llm = "deepseek-pro"` and `binding = "deepseek-claude"` instead of
   repeating provider, model, protocol, base URL and credential name.
   Interactive, cmux, headless and routed launches of that binding
   resolve the same execution digest and stamp the same provenance.

## Requirements

### Catalog

- **FR-1 File and location.** The catalog is
  `~/.code-copilot-team/llms.toml` (D2). One user-home helper resolves
  the catalog, the compatibility records and the session stamps, and
  honours `CCT_LLM_HOME` for tests, so #411 moves all three together.
  The file has `schema_version = 1`, `[providers.<id>]`,
  `[endpoints.<id>]`, `[llms.<id>]` and `[bindings.<id>]` tables. Ids
  match `[A-Za-z0-9][A-Za-z0-9_-]*` and are unique within their table.
- **FR-2 Entities.** A provider has `display_name`, `kind`
  (`api` | `managed`), `credential_mode` (`env` | `native` | `none`),
  `credential_env` (an environment-variable name; required when
  `credential_mode = "env"`, refused otherwise), optional
  `data_policy` (the routing vocabulary). `native` means the harness
  authenticates by its own login (Codex login, Kiro interactive);
  `none` means an unauthenticated local endpoint. A managed provider
  may use `env` (Kiro headless needs `KIRO_API_KEY`). An endpoint has
  `provider` (an `api` provider), `protocol` (closed: `anthropic-
  messages` | `openai-chat` | `openai-responses`), `base_url` or
  `base_url_env` (exactly one), `auth_header` (`none` | `bearer` |
  `x-api-key`; `none` required when the provider's credential mode is
  `none`, refused with `env`), optional `quirks` (closed list; v1
  defines `rejects-dynamic-tools`, the #399 gateway behaviour). An
  llm has `provider`, `model` (the remote or managed model id),
  optional `context_window`, `reasoning` (boolean) and `input`
  (`text` | `image` list). A binding has `harness` (closed:
  `claude-code` | `codex` | `pi` | `kiro`), `llm`, `endpoint`
  (required for an `api` provider, refused for `managed`) and
  harness-specific optional keys enumerated per adapter (FR-20–23); a
  key another harness owns is refused by name.
- **FR-3 Grammar.** The file is parsed by the same constrained-TOML
  grammar the routing registry accepts (comments, one root key, table
  headers, bare keys, basic strings, integers, booleans, single-line
  string arrays); anything else is rejected by name, never
  approximated. The grammar is shared with `routing-config.sh` by
  extracting its line lexer into `scripts/lib/cct-toml.sh` (D4); the
  routing suite's 365 assertions pin the extraction.
- **FR-4 Credentials are references.** No catalog field may hold a
  credential value; the secret-shape scan from the routing library
  runs over every value. Read-only commands may report whether a
  named variable is set. Only the child-side resolver (FR-10) reads
  its value, immediately before `exec`, and only into the child's
  environment. No CCT code path prints, logs, stamps or passes a
  credential value as an argument. Secure-store references are
  deferred (Constraints) and recorded as a narrowing.
- **FR-5 Validation.** `cct llm validate` reports every grammar and
  semantic violation by line and name: dangling references, duplicate
  bindings for one `(harness, llm, endpoint)`, protocol not in the
  closed set, credential mode and auth header disagreeing, `base_url`
  with userinfo, query or fragment, managed provider with an endpoint,
  endpoint on a managed provider, and binding keys owned by another
  harness. Exit 0 valid, 1 violations, 2 unreadable.

### Read-only CLI

- **FR-6 Commands.** `cct llm list`, `cct llm show <id>`, `cct llm
  validate`, `cct llm compatibility [<target>] [--harness <h>]`,
  `cct llm test <target> --harness <h>` and `cct harness explain <h>
  --llm <target>` are dispatched by `scripts/cct` to
  `scripts/llm-cli.sh`. Every command has `--json`; the JSON is what
  Studio consumes. `start` and `exec` are defined in A so adapters
  share them (D15): **start** chooses the session vehicle
  (multiplexer or direct), validates the target statically, and types
  or runs the id-only command; **exec** is the child-side step that
  resolves the plan, applies the compatibility gate, writes the stamp,
  materializes credentials and execs the harness. `start` never
  reads a credential value; `exec` never touches a multiplexer.
- **FR-7 Redaction.** Every output path (text, JSON, stamps, records,
  journal lines, error messages) passes through one redaction
  function that prints credential variable names only and renders an
  endpoint as **two fields**: `origin`, exactly the `rt_sanitize_
  origin` grammar (`scheme://host[:port]`, http(s) only, host
  lower-cased, userinfo, path, query and fragment dropped) that
  `routing-result.sh`'s `RR_ORIGIN_RE` validates and must keep
  validating; and `path_sha256`, the first 16 hex of the sha256 of the
  path, present only when the URL has a path. The readable path is
  never stamped: the supervisor drops it so "a base URL carrying a
  token or a tenant path can never become durable evidence". The
  hash is an identity field, not a secrecy measure: an unsalted hash
  of a guessable segment such as a tenant name can be recovered by
  trying candidates, so the origin-only rule is what protects a
  secret in the path, and no document describes `path_sha256`
  otherwise. The sanitizer moves to `scripts/lib/cct-endpoint.sh`
  with its own tests; the supervisor sources it, `origin` output is
  byte-identical for its existing callers, and the "single-sourced in
  cooldown-supervisor.sh" comments in `routing-result.sh` and
  `tests/test-routing-config.sh` are updated to the new location. The benchmark evidence code's `_endpoint_
  identity` (origin, readable path and full-URL hash) is a third
  convention and is recorded as follow-up, not changed here. The
  function also scrubs any wired secret value from captured child
  output before it is persisted.
- **FR-8 Resolution rule for `--llm <target>`.** A target is `<llm>`
  or `<llm>@<binding>`. `<llm>` resolves to the one explicit binding
  for `(harness, llm)`; several explicit bindings require the
  `@<binding>` form; none refuses with the remedy "add a binding".
  No binding is ever inferred (D5), so every probe record and stamp
  has a stable binding key.

### Resolution and launch plan

- **FR-9 LaunchPlan.** A resolver turns `(harness, target, project,
  resume-intent)` into a plan with: `executable`, `argv`, `env_set`
  (names and values, values present only in the child-side process),
  `env_names` (the redacted view with set/unset per name), `overlay`
  (files written for the harness, each with an owner and a lifetime:
  `none`, `launch`, `session`), `identity` (harness, harness version,
  llm id, binding id, provider, endpoint sanitized, protocol,
  requested model), `compatibility` (state, evidence, rule version),
  `catalog_digest` (sha256 over the canonical tuple of the resolved
  provider, endpoint, llm and binding, environment-independent, the
  `rc_profile_tuple` construction) and `execution_digest` (sha256
  over the catalog digest, the resolved endpoint value, the harness
  version and every launch-affecting adapter option, the
  `rc_identity_digest` construction; hashed, never stored in clear).
  Neither digest ever reads or includes a credential value; the
  credential enters both only as the variable name and mode, exactly
  as the routing digest never reads `credential_env`.
  Probe records, compatibility state and resume enforcement use the
  execution digest.
- **FR-10 Child-side resolution.** The command placed in cmux, tmux,
  shell history or a log carries only stable ids (the launcher name,
  `--llm <target>`, the project path, resume flags). The process that
  execs the harness runs the resolver, reads `credential_env`'s
  value, and execs the harness with the child environment; the outer
  launcher never has the value. For Claude Code this is the existing
  launcher running inside the multiplexer pane it created.
- **FR-11 Native behaviour preserved.** Without `--llm` (and without
  a stamp restored by exact resume under FR-18) the launcher sets no
  provider, model, protocol or compatibility variable and passes no
  model or provider flag; the only gateway-related behaviour that
  remains is the #399 notice, which prints and changes nothing. A
  mutation test removes the guard and expects the suite to fail.
- **FR-12 Refusal before launch.** A plan whose compatibility state
  is `unsupported`, `incompatible`, `unavailable` or `unverified` is
  refused with exit 3, the state, the reason and a remedy, before the
  harness executable runs. `--allow-unverified` launches an
  `unverified` plan with a notice; it never records `supported` and
  the stamp records that the gate was bypassed (D7).

### Compatibility

- **FR-13 States.** Closed set, computed per binding. `supported`:
  the latest conclusive probe record passed every capability the
  binding requires and matches the current execution digest and rule
  version. `unsupported`: the rule table says the harness cannot speak
  the binding's protocol or honour a declared quirk, or a managed
  harness was bound to an endpoint. `unverified`: statically
  supported, no matching conclusive record (including a record
  invalidated by a digest or rule-version change). `unavailable`: the
  credential variable is unset or empty under `env` mode, the base URL
  variable is unset, the harness executable is missing, or its
  version is below the adapter's minimum. `incompatible`: the latest
  matching conclusive record failed with behavioral evidence (a
  rejected request shape, a required capability that ran and did not
  do what was asked). An authentication failure is `unavailable`
  evidence, and a transport failure, timeout, crash or unparseable
  output is `unverifiable`; neither ever produces `incompatible` and
  neither overwrites a conclusive record.
- **FR-14 Rule table.** The static rules are data with a
  `rule_version`: per harness the protocols it speaks (`claude-code`:
  anthropic-messages; `codex`: openai-responses, and openai-chat only
  once the Codex adapter's capture proves the installed CLI accepts
  it; `pi`: openai-chat, openai-responses, anthropic-messages;
  `kiro`: managed only), the quirks it can honour, and the
  capabilities each harness requires of a binding. A declared quirk
  is configuration, never evidence. Changing the table changes
  `rule_version`, which degrades `supported` to `unverified`.
- **FR-15 Behavioral probe.** `cct llm test <target> --harness <h>`
  runs the harness headless through the resolved plan on a canary and
  records a per-capability matrix, each `pass | fail | unverifiable |
  not_applicable`: `auth`, `model_identity` (the effective model the
  harness's machine-readable output reports, compared with the
  requested one; `unverifiable` when the harness reports none),
  `streaming`, `system_prompt`, `tool_call` (one tool invocation),
  `tool_result` (the tool's result read back and used), `output_
  parsing` (the harness's result parsed cleanly), `clean_exit`,
  `reasoning_control` (when the llm declares `reasoning`),
  `image_input` (when the llm declares `image`), `limit_controls`
  (declared context and output limits honoured where the harness
  exposes them). The required set per harness comes from the rule
  table; a `not_applicable` check never blocks. The canary primitives
  (prompt, nonce, marker file, classification, secret scrub) are
  shared with `routing-probe.sh`; routing's accounting, caps and
  state transitions are not reused (D6). A test seam
  (`CCT_LLM_PROBE_CMD`) replaces the harness with a mock that receives
  the same environment and argv. **Negative controls:** a stub
  gateway (`tests/fixtures/llm-stub-gateway.py`, a local HTTP server
  speaking the three protocols) with switches that drop tool calls,
  ignore tool results, disable streaming, report a different model
  id, ignore the system prompt, reject the request shape, reject
  authentication, exceed declared limits and time out; every
  capability check has a test showing it fails under its switch and
  yields the state FR-13 assigns. In CI the stub gateway runs behind
  the mock harness; the owner-run capture of each adapter slice runs
  it behind the real harness and quotes the matrix. Probe temporary
  directories are removed on exit and on signal.
- **FR-16 Probe records.** Records live under the user home
  (FR-1) at `llm-compat/<harness>/<llm>@<binding>.json` with two
  parts: `latest_attempt` (every run: timestamp, outcome, matrix,
  execution digest, rule version, harness version, redacted evidence)
  and `latest_conclusive` (updated only by a `pass` or behavioral
  `fail`). `cct llm compatibility` is computed from the catalog, the
  rule table, the environment and these records; it never performs
  network I/O.

### Session and resume

- **FR-17 Stamp on exec.** The exec step writes, before the harness
  runs, `llm-sessions/<harness>/<session-key>.json` with `status =
  "attempted"`, harness and version, llm id, binding id, provider,
  requested model, protocol, sanitized endpoint, catalog digest,
  execution digest, compatibility state and rule version, whether the
  gate was bypassed, project path, timestamp. Never a credential value
  or variable value. The session key is the harness's session id,
  generated by the launcher and passed where the harness accepts one
  (`--session-id` for Claude Code and Pi; Codex and Kiro per their
  adapter captures) (D9). The stamp is promoted to `established`,
  and enriched with the effective model, only from the harness's own
  session evidence (its transcript or session record for that id),
  observed at a later resume or by `cct llm sessions`; a stamp never
  implies that a session or model was established.
- **FR-18 Resume rules.** New session, no `--llm`: native. New
  session with `--llm`: bind and stamp. Resume by exact id, no
  `--llm`: restore the stamped binding when a stamp exists, else
  native. Resume by exact id with the same target: allowed, stamp
  refreshed. Resume by exact id with a different target: refused with
  exit 3 and the advice to start or fork a session. Bare `--continue`
  or an interactive `--resume` picker without `--llm`: native, with a
  one-line notice that identity enforcement needs an exact id. Bare
  `--continue` or the picker **with** `--llm`: refused with exit 3,
  because CCT cannot know which session the harness will pick, so the
  explicit choice would either be ignored or switch the model
  mid-session; the remedy names `--resume <id> --llm <target>` or a
  new session. Identity-safe continuation is not claimed until the
  launcher can establish the exact session the harness will choose.
- **FR-19 Restored target is re-resolved.** A restored stamp goes
  through the same resolver and compatibility gate as a fresh `--llm`;
  a catalog or environment change that alters the execution digest is
  reported and the launch refused unless `--allow-unverified`.

### Adapter contracts

- **FR-20 Claude Code.** With `--llm`: `ANTHROPIC_BASE_URL`;
  `ANTHROPIC_AUTH_TOKEN` or `ANTHROPIC_API_KEY` by `auth_header`
  (nothing for `none`); `ANTHROPIC_MODEL` set to the remote model;
  `ANTHROPIC_DEFAULT_OPUS_MODEL`, `ANTHROPIC_DEFAULT_SONNET_MODEL`,
  `ANTHROPIC_DEFAULT_HAIKU_MODEL` and `ANTHROPIC_SMALL_FAST_MODEL` set
  to the binding's `small_fast_model` when given, else to the remote
  model, so alias and background requests do not leave the endpoint;
  the quirk `rejects-dynamic-tools` sets `CLAUDE_CODE_DISABLE_
  EXPERIMENTAL_BETAS=1`, `ENABLE_TOOL_SEARCH=false` and
  `DISABLE_FEEDBACK_COMMAND=1` and enters the execution digest,
  retiring the #399 notice for selected launches. Binding keys:
  `small_fast_model`, `max_output_tokens`. No file overlay. The
  launcher parses `--llm <target>`, `--llm=<target>` and
  `--allow-unverified` before its forward-unknown-flags rule. Minimum
  version: the one the #399 work pinned for the retry behaviour.
- **FR-21 Codex.** With `--llm`: `--model <remote>` and `-c`
  overrides that define `model_provider = cct-<binding>` and the
  `model_providers.cct-<binding>` table (`name`, `base_url`,
  `env_key = <credential_env>`, `wire_api` by protocol) — names and
  URLs only, no secret — plus the credential in the child environment
  (D10). Binding keys: `reasoning_effort`. The adapter's first task is
  a capture against the installed CLI that proves nested `-c` keys,
  `wire_api` values, `--profile` layering, `codex resume` and the
  effective-model field of `exec --json`; the rule table is amended
  from that capture, never from memory. If the capture disproves
  nested `-c`, the slice stops and the owner rules on a profile-file
  overlay; there is no silent fallback. Codex has no CCT launcher
  today; the slice adds `adapters/codex/bin/codex-code` with the same
  `--llm`, native passthrough and stamp contract.
- **FR-22 Pi.** With `--llm`: `--provider cct-<binding> --model
  <remote>` against a provider entry CCT supplies. How the entry is
  supplied is decided by the slice's first task, a capture comparing
  (a) a launch-scoped agent-directory overlay (`PI_CODING_AGENT_DIR`)
  that preserves or link-binds the user's sessions, auth, settings and
  extensions, and (b) a persistent merge into the user's `models.json`
  with an ownership manifest, collision refusal when the key exists
  and is not CCT-owned, locking, same-directory atomic replacement,
  permission preservation, symlink refusal and recovery. The overlay
  is preferred if the capture proves Pi behaves identically (D11,
  deferred). Binding keys: `thinking`. `apiKey` is `$<credential_env>`
  interpolation; the value is in the child environment only. Without
  `--llm` the launcher does not open `models.json` or set
  `PI_CODING_AGENT_DIR`.
- **FR-23 Kiro.** A managed-model-only launcher `adapters/kiro/bin/
  kiro-code` (slice E): with `--llm`, `--model <llm.model>`; resume by
  `--resume-id`; headless runs use `credential_mode = "env"` with
  `KIRO_API_KEY`, interactive runs `native`. No endpoint, base URL,
  header or protocol is ever passed; a Kiro binding with an endpoint
  is `unsupported` by rule, and every harness list states that Kiro
  accepts no external endpoint. The slice's first task is a capture of
  the installed `kiro-cli` (model ids, `--model` on new and resumed
  sessions, session id discovery, headless output format); a Kiro
  launcher is not a Kiro adapter (rules, hooks, setup), which remains
  a separate decision.

### Project policy, routing, Studio, compatibility, state files

- **FR-24 Project restriction.** `.code-copilot-team/config.toml` may
  carry `[llm]` with `allowed` (string array of llm ids or
  `<llm>@<binding>` targets) only; any other key under `[llm]` is
  refused by name with the reason "projects restrict, never grant"
  (D13). An `allowed` list narrows `--llm` and restored stamps; it
  never selects a target.
- **FR-25 Routing migration (G).** A `[[profiles]]` entry may declare
  `llm = "<id>"` and `binding = "<id>"`; then `backend` is derived
  from the binding's harness and `provider`, `model`, `protocol`,
  `base_url`, `base_url_env`, `credential_env` and `credential_mode`
  are derived from the catalog, and any of those given explicitly
  alongside `llm` is refused as a conflict. Profiles without `llm`
  keep today's fields and semantics. The supervisor resolves through
  the same resolver, so routed, headless and interactive launches
  share the execution digest; `routing_launch_env` journals the llm
  and binding ids.
- **FR-26 Studio (F).** Studio reads `cct llm list --json`,
  `compatibility --json` and `harness explain --json`, renders
  targets, states and the explained launch, edits non-secret catalog
  fields through the validator, and generates the id-only launch
  command for the user to run. Studio never reads or writes a
  credential and never spawns an **interactive harness session**;
  the headless benchmark steps the Session Analytics API already runs
  are unaffected. This narrows the issue's "start harness" to
  generating the command; it is recorded as a narrowing for the owner
  to approve (D14), with an amendment to #400's slice F text.
- **FR-27 Backward compatibility.** Every existing invocation of
  `claude-code`, `pi-code`, `cct start`, the supervisor and the
  benchmark backends without `--llm` is byte-for-byte unchanged in
  argv and environment; the provider-emit setup path and
  `providers.toml` are untouched; routing profiles without `llm`
  validate and execute as before.
- **FR-28 Diagnostics and docs.** `cct doctor` gains an **LLM
  catalog** section (file state, validation, per-binding
  compatibility, records degraded by digest or rule changes).
  `docs/llm-catalog.md` is the user guide; `docs/llm-routing.md`
  gains the `llm =` reference form in G; the feature catalogue gains
  `llm-catalog` with the real harness reach and the Kiro limit; the
  template `shared/templates/llm/llms.toml.example` is installed by
  reference, never copied over an existing file.
- **FR-29 State files.** Compatibility records, stamps and ownership
  manifests live in private directories (`0700`) as `0600` files,
  written to a temporary file in the same directory and renamed into
  place under a lock (`flock` where available, a lock directory
  otherwise); a symlink at any path CCT writes is refused; an
  interrupted write leaves no partial file and no stale temporary
  file; readers tolerate a missing file and refuse a malformed one by
  name. Probe temporary directories are created with `mktemp -d` and
  removed on exit and on `INT`/`TERM`.

## Constraints / What NOT to Build

- No universal proxy or gateway; CCT is not in the connection path.
- No "any LLM on any harness" claim anywhere; every harness list
  states protocols and the Kiro exception.
- No credential storage of any kind in v1: `credential_mode` is
  `env`, `native` or `none`. The value `keychain` is reserved and
  refused with the message "secure-store credentials are not
  implemented", so adding it later is not a schema change; this
  narrows the issue's "or a secure-store key" and is recorded for the
  owner, with an amendment to #400's credential sentence.
- No reuse of `--profile` for selection on any harness.
- No project-level default target, no project-level catalog entries.
- No Bedrock, Vertex or Foundry transports for Claude Code; the
  endpoint protocol set is the three the rule table names.
- No change to `providers.toml`, `provider-emit.sh` or peer-review
  dispatch; the overlap with the reviewer profile is recorded as
  follow-up, not solved here.
- No Kiro endpoint, key-forwarding or protocol configuration; no Kiro
  rules/hooks adapter in this feature (launcher only).
- No inferred bindings, no project-latest `--continue` restoration.
- No model capability discovery (`/models` listing) as evidence, and
  no declared quirk or flag as evidence.
- No Studio-spawned harness processes.
- No migration of `~/.code-copilot-team/` (that is #411); one
  user-home helper so #411 moves catalog, records and stamps together.

## Key Entities

| Entity | Identity | Owned by | Notes |
|---|---|---|---|
| provider | `providers.<id>` | catalog | `api` or `managed`; credential mode `env`, `native`, `none` |
| endpoint | `endpoints.<id>` | catalog | protocol, base URL, auth header, quirks |
| llm | `llms.<id>` | catalog | the `--llm` argument; remote or managed model id |
| binding | `bindings.<id>` | catalog | harness + llm + endpoint + harness keys; the stable key for records and stamps |
| rule table | `rule_version` | repo data file | protocols, quirks and required capabilities per harness |
| LaunchPlan | per launch | resolver | argv, env names/values, overlays, identity, two digests, state |
| probe record | `(harness, llm@binding)` | `llm-compat/` | `latest_attempt` and `latest_conclusive`, capability matrix, execution digest |
| session stamp | `(harness, session-key)` | `llm-sessions/` | `attempted` → `established`; redacted provenance for exact resume |
| project policy | `[llm].allowed` | project config | restriction only |

## Decisions (owner rules; each is open until ruled)

Recommendations revised after the two bundle reviews of 2026-11-10.
Decisions slices A and B need are marked for ruling now; D11 is
deferred to the Pi capture and ruled at slice D's Task 0, so the spec
gate does not wait on a capture nobody can run yet. **A deferred
ruling is a spec amendment, never a silent edit:** slice D's Task 0
records the capture under `specs/llm-catalog/verification/`, appends
the ruling to this section with its date and evidence, updates FR-22,
and writes a fresh origin-alignment record that the owner approves
before slice D builds; the approved spec's history stays in git.

- **D1 Slicing.** One spec bundle; one issue and one PR per
  increment A–G; #400 stays open as the umbrella and G's PR closes it
  only after A–F, Kiro and Studio included, are merged. Recommended.
  [NEEDS CLARIFICATION: owner ruling]
- **D2 User home.** `~/.code-copilot-team/` for the catalog, the
  compatibility records and the stamps, through one helper so #411
  moves them together. Alternative: wait for #411. Recommended:
  proceed now. [NEEDS CLARIFICATION: owner ruling]
- **D3 Three files.** `llms.toml` is new and separate; `routing.toml`
  references it in G; `providers.toml` stays the reviewer profile.
  Recommended: separate. [NEEDS CLARIFICATION: owner ruling]
- **D4 Parser.** Extract the line lexer of `routing-config.sh` into
  `scripts/lib/cct-toml.sh`, shared by both registries (bash 3.2).
  Alternatives: a second bash parser; Python `tomllib` (3.11+, which
  the launchers cannot assume). Recommended: extraction.
  [NEEDS CLARIFICATION: owner ruling]
- **D5 Bindings.** Explicit bindings only; `<llm>` resolves through
  the one explicit binding for `(harness, llm)`, `<llm>@<binding>`
  disambiguates. Inferred bindings were rejected in review because
  records and stamps need a stable binding key. Recommended:
  explicit only. [NEEDS CLARIFICATION: owner ruling]
- **D6 Probe reuse.** Share the canary primitives and the tri-state
  classification with `routing-probe.sh`; do not reuse routing's
  accounting, caps or state runner. Recommended. [NEEDS CLARIFICATION: owner ruling]
- **D7 Unverified launches.** Refuse by default; `--allow-unverified`
  launches with a notice, never records `supported`, and marks the
  stamp. The earlier recommendation (launch with a notice) was
  withdrawn: a notice is not a gate. Recommended: refuse by default.
  [NEEDS CLARIFICATION: owner ruling]
- **D8 Endpoint quirks.** `quirks = ["rejects-dynamic-tools"]` on the
  endpoint drives the three #399 variables for selected launches and
  enters the execution digest; the declaration is never evidence; the
  #399 notice stays for native launches. Recommended.
  [NEEDS CLARIFICATION: owner ruling]
- **D9 Session keys.** The launcher generates the session id and
  passes `--session-id` for Claude Code and Pi; stamps start as
  `attempted`; bare `--continue` and the interactive picker stay
  native. Project-latest restoration was withdrawn: the harness's
  "most recent" and CCT's "most recent stamp" are different sets.
  Recommended. [NEEDS CLARIFICATION: owner ruling]
- **D10 Codex overlay form.** `-c` overrides (names and URLs, no
  secret, nothing to clean up), adopted only after the capture proves
  nested keys on the installed CLI; a disproving capture stops the
  slice for a ruling, with no silent profile-file fallback.
  Recommended. [NEEDS CLARIFICATION: owner ruling]
- **D11 Pi overlay form.** Deferred to the capture in FR-22
  (launch-scoped agent-directory overlay versus owned merge); the
  overlay is preferred if it preserves Pi behaviour. The earlier
  "merge a `cct-` key" recommendation was withdrawn: it assumed
  ownership of a key the user may already own. **Deferred to slice
  D's capture; ruled at that slice's Task 0, not here.**
- **D12 Kiro.** In scope as a managed-model-only launcher (FR-23) in
  slice E, after a capture of the installed CLI; a Kiro rules/hooks
  adapter remains a separate decision. The earlier deferral was
  withdrawn because #400 names Kiro selection explicitly. The ruling
  here is scope only; model ids, resume and headless details come from
  slice E's capture. Recommended. [NEEDS CLARIFICATION: owner ruling]
- **D13 Project policy.** `[llm].allowed` only. Recommended.
  [NEEDS CLARIFICATION: owner ruling]
- **D14 Studio.** Edits non-secret fields, explains, generates the
  id-only command; never spawns a harness. This is a narrowing of the
  issue's "start harness" and needs the owner's explicit approval.
  Recommended: approve the narrowing. [NEEDS CLARIFICATION: owner ruling]
- **D15 Unified entry.** `start` and `exec` semantics defined in A
  (FR-6); `cct start --llm` for Claude Code from B; `cct harness
  start <harness>` and `cct harness exec` with F. Recommended.
  [NEEDS CLARIFICATION: owner ruling]

## Success Criteria

The issue's acceptance criteria, each with the proof this bundle
requires:

| Issue criterion | Proof |
|---|---|
| Omitting `--llm` leaves each harness's native configured behaviour unchanged | Launcher suites diff argv and environment of a stub harness with and without the feature code; mutation test on the FR-11 guard |
| No secret in argv, generated commands, shell history, logs, multiplexer commands or provenance | Stub cmux/tmux capture the typed command; stub harness dumps argv and env; every capture, record and stamp is grepped for the planted secret |
| An incompatible pair is refused before the harness starts, with a reason | Stub harness records whether it ran; exit 3 and message asserted for each refusing state, and for `unverified` without the escape hatch |
| Every supported pair has a behavioral probe that fails when tool-call or protocol support is removed | Stub gateway switches (FR-15 negative controls) flip each capability check and the state to `incompatible`; a timeout or auth rejection leaves `latest_conclusive` untouched; the owner-run capture repeats the switches behind the real harness |
| Direct, cmux/tmux, headless and routed launches resolve the same identity | One resolver; the suite compares the execution digest across the four paths (routed path in G) |
| A resumed session cannot silently switch provider or model | FR-18 exact-id cases, FR-19 changed-digest refusal, and the explicit native behaviour of bare `--continue` |
| Project configuration restricts but cannot introduce credentials or redefine a target | FR-24 refusals by name |
| Kiro never advertises arbitrary endpoint support | Rule-table test, launcher refusal of any endpoint-bearing binding, and a doc grep guard |
| Interactive and automated routing paths stamp the same identity | G: supervisor journal and launcher stamp compared by execution digest |
| Existing wrapper invocations without `--llm` remain backward compatible | FR-27 byte-for-byte assertions in the launcher, supervisor and benchmark suites |

Plus: `cct llm validate` on the shipped example exits 0; every CLI
command's `--json` validates against `shared/schemas/llm-catalog-
cli.schema.json`; FR-29 is proven with an interrupted write, a
symlinked path and a concurrent-writer test; the test-count pins and
`docs/repo-structure.md` move together; `validate-spec.sh
--feature-id llm-catalog` and the origin gate pass before each
slice's PR.

## Out of scope, unchanged

Peer-review provider dispatch; benchmark backend selection; Session
Analytics ingestion of stamps (a follow-up can read `llm-sessions/`);
the home-directory migration (#411); a Kiro rules/hooks adapter;
secure-store credentials; Bedrock/Vertex/Foundry; Studio-spawned
sessions; identity-safe bare `--continue`.

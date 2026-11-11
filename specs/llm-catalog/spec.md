---
feature_id: llm-catalog
spec_mode: full
status: approved
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

Revision 6 (2026-11-10, after the fifth review): a selected launch
clears competing credential, base-URL, header and provider-switch
variables (FR-30); resume refuses identity changes and reports tuning
changes; generated commands target bash and zsh and refuse paths that
need `$'…'` quoting; stale locks reclaimed by pid only on the writing
host; "adapter not implemented" applies only with `--llm`.

Revision 5 (2026-11-10, after the fourth review): `cct llm test` is the
controlled probe path, so the first record can exist; three digests
(provenance, launch identity, evidence) with resume enforcement on
launch identity only; API providers use `env` or `none`, managed
providers `native`; endpoint identity hashed read-only, credential
values child-side only; stamps carry the origin and the opaque launch
identity, no path hash; managed-harness evidence contract for Kiro;
slice A ships the plan schema and "adapter not implemented" refusals,
adapters follow their captures; typed-command quoting, probe watchdog,
stale-lock recovery and `cct llm sessions` specified.

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
   resolve the same launch-identity digest and stamp the same provenance.

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
  (`api` | `managed`), `credential_mode`, `credential_env` (an
  environment-variable name; required when `credential_mode =
  "env"`, refused otherwise), optional `data_policy` (the routing
  vocabulary). An `api` provider's mode is `env` or `none` (`none` is
  an unauthenticated local endpoint); `native` is refused for `api`
  providers, because sending a harness's ambient first-party login to
  a custom endpoint has no defined semantics. A `managed` provider's
  mode is `native` only: the harness authenticates by its own login,
  CCT never names, reads or materializes a credential for it, and a
  variable the harness itself requires (Kiro headless reads
  `KIRO_API_KEY`) passes through the inherited environment untouched
  like any other variable. An endpoint has
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
  harness. Exit 0 valid, 1 violations, 2 unreadable. The resolved
  value of `base_url_env` is checked by the same URL rule (absolute
  http(s), no userinfo, query or fragment) every time it is read:
  read-only commands report the binding `unavailable` with the
  reason, and the exec step refuses before any harness starts.

### Read-only CLI

- **FR-6 Commands.** `cct llm list`, `cct llm show <id>`, `cct llm
  validate`, `cct llm compatibility [<target>] [--harness <h>]`,
  `cct llm test <target> --harness <h>`, `cct llm sessions
  [--harness <h>] [--project <p>]` and `cct harness explain <h>
  --llm <target>` are dispatched by `scripts/cct` to
  `scripts/llm-cli.sh`. Every command has `--json`; the JSON is what
  Studio consumes. `test` is the controlled probe path (FR-15), the
  only command that starts a harness. `sessions` lists stamps and
  promotes `attempted` stamps to `established` by reading the
  harness's own session record for the generated id (Claude Code's
  transcript under `~/.claude/projects/`, Pi's session file; Codex
  and Kiro per capture), read-only on harness files, never reading a
  credential or a transcript body beyond the session's model field;
  its JSON lists each stamp with status, identity and the evidence
  that promoted it. `start` and `exec` are defined in A so adapters
  share them (D15): **start** chooses the session vehicle
  (multiplexer or direct), validates the target statically, and types
  or runs the id-only command; **exec** is the child-side step that
  resolves the plan, applies the compatibility gate, writes the stamp,
  materializes credentials and execs the harness. `start` never
  reads a credential value; `exec` never touches a multiplexer.
- **FR-7 Redaction.** Every output path (text, JSON, stamps, records,
  journal lines, error messages) passes through one redaction
  function that prints credential variable names only and renders an
  endpoint as its `origin` alone, exactly the `rt_sanitize_origin`
  grammar (`scheme://host[:port]`, http(s) only, host lower-cased,
  userinfo, path, query and fragment dropped) that
  `routing-result.sh`'s `RR_ORIGIN_RE` validates and must keep
  validating. Nothing durable or human-readable carries the path or a
  hash of it: the supervisor drops the path so "a base URL carrying a
  token or a tenant path can never become durable evidence", and an
  unsalted hash of a guessable segment could be recovered by trying
  candidates. Two endpoints behind one origin are told apart by the
  opaque launch-identity digest (FR-9), which binds the full resolved
  URL without exposing it. Tests plant a path token and assert its
  absence from every stamp, record, log and command. The sanitizer
  moves to `scripts/lib/cct-endpoint.sh`
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
  `env_names` (the redacted view with set/unset per name), `env_clear`
  (the variables FR-30 removes, by name), `overlay`
  (files written for the harness, each with an owner and a lifetime:
  `none`, `launch`, `session`), `identity` (harness, harness version,
  llm id, binding id, provider, endpoint sanitized, protocol,
  requested model), `compatibility` (state, evidence, rule version)
  and three digests, each sha256 over a canonical JSON tuple:
  `catalog_digest` (provenance: the declared provider, endpoint, llm
  and binding tables, environment-independent, the
  `rc_profile_tuple` construction); `launch_identity_digest` (what
  the launch executes as: the resolved endpoint value including its
  path, protocol, auth header, credential variable name and mode,
  remote model, quirks and every launch-affecting adapter option, the
  `rc_identity_digest` construction, never stored in clear); an
  `options_digest` over the tuning keys that do not change the target
  (`small_fast_model`, `max_output_tokens`, `reasoning_effort`,
  `thinking`); and `evidence_digest` (launch identity plus options,
  harness version and rule version, the key for probe validity).
  Quirks stay in launch identity because they change the request
  shape. Resume enforcement compares launch identity only, so a
  harness upgrade, a display-name edit or a changed output limit never
  refuses a resume; an options change is reported. No digest ever reads or
  includes a credential value, exactly as the routing digest never
  reads `credential_env`. Hashing the resolved endpoint reads
  `base_url_env`'s value, which is not a credential, so read-only
  commands may compute all three digests; only the exec step reads
  `credential_env`'s value.
- **FR-10 Child-side resolution.** The command placed in cmux, tmux,
  shell history or a log carries only stable ids (the launcher name,
  `--llm <target>`, the project path, resume flags). The process that
  execs the harness runs the resolver, reads `credential_env`'s
  value, and execs the harness with the child environment; the outer
  launcher never has the value. For Claude Code this is the existing
  launcher running inside the multiplexer pane it created. Ids are
  constrained; the project path is not. A typed command is built with
  the launcher's existing `printf %q` primitive for every element and
  targets bash and zsh, the shells the multiplexer panes run; a
  project path that `%q` can only render as `$'…'` (control
  characters, newlines) is refused before anything is typed, since
  `sh` and fish would not parse it. Direct execution passes argv
  arrays, never a joined string. Tests use paths with spaces, quotes,
  `$( )` and `;` and prove that no second command runs and the
  harness receives the path intact, and a newline path is refused.
- **FR-11 Native behaviour preserved.** Without `--llm` (and without
  a stamp restored by exact resume under FR-18) the launcher sets no
  provider, model, protocol or compatibility variable and passes no
  model or provider flag; the only gateway-related behaviour that
  remains is the #399 notice, which prints and changes nothing. A
  mutation test removes the guard and expects the suite to fail.
- **FR-12 Refusal before launch.** A session launch whose
  compatibility state is `unsupported`, `incompatible`, `unavailable`
  or `unverified` is refused with exit 3, the state, the reason and a
  remedy, before the harness executable runs. `--allow-unverified`
  launches an `unverified` plan with a notice; it never records
  `supported`, the stamp records that the gate was bypassed, and it
  never bypasses a launch-identity mismatch (FR-19) (D7). The
  controlled probe path `cct llm test` is exempt from the
  `unverified` and `incompatible` refusals and bound by FR-15.

### Compatibility

- **FR-13 States.** Closed set, computed per binding. `supported`:
  the latest conclusive probe record passed every capability the
  binding requires and matches the current evidence digest.
  `unsupported`: the rule table says the harness cannot speak
  the binding's protocol or honour a declared quirk, or a managed
  harness was bound to an endpoint. `unverified`: statically
  supported, no conclusive record for the current evidence digest
  (a changed endpoint, option, harness version or rule version all
  degrade here). `unavailable`: the credential variable is unset or
  empty under `env` mode, the base URL variable is unset or its value
  fails the URL rule, the harness executable is missing, or its
  version is below the adapter's minimum. `incompatible`: the
  conclusive record for the current evidence digest failed with
  behavioral evidence (a
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
  is the controlled probe path: it may execute a target that is
  statically supported and available even while its state is
  `unverified` or `incompatible`, and it refuses `unsupported` and
  `unavailable` targets with the same reasons a launch would. The
  transition `unverified` → `supported` through one `test` run is
  pinned by a regression test. Every probe runs under a watchdog:
  `CCT_LLM_PROBE_TIMEOUT_SEC` (default 120) ends the harness with
  `TERM`, then `KILL` after ten seconds, on its own process group so
  no child survives; expiry is classified `unverifiable`, never
  `incompatible`; the bounded runner is the routing probe's. The
  probe runs the harness headless through the resolved plan on a
  canary and records a per-capability matrix, each `pass | fail | unverifiable |
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
  the mock harness; the owner-run capture of each API-harness adapter
  slice (Claude Code, Codex, Pi) runs it behind the real harness and
  quotes the matrix. **Managed-harness evidence contract** (Kiro): no
  endpoint can be injected, so the stub gateway does not apply and no
  endpoint-injection negative control is claimed; the matrix covers
  only what headless output exposes (`model_identity`, `streaming`,
  `tool_call`, `tool_result`, `output_parsing`, `clean_exit`), marks
  the rest `not_applicable`, and its negative controls are an unknown
  model id (behavioral `fail`) and a missing `KIRO_API_KEY`
  (`unavailable`). **Ambient-credential control:** every probe and
  launch test plants a sentinel credential and a sentinel provider
  switch in the ambient environment and asserts that the stub gateway
  and the stub harness never receive them (FR-30). Probe temporary
  directories are removed on exit and on signal.
- **FR-16 Probe records.** Records live under the user home
  (FR-1) at `llm-compat/<harness>/<llm>@<binding>.json` with two
  parts: `latest_attempt` (every run: timestamp, outcome, matrix,
  evidence digest, rule version, harness version, redacted evidence)
  and `latest_conclusive` (updated only by a `pass` or behavioral
  `fail`). `cct llm compatibility` is computed from the catalog, the
  rule table, the environment and these records; it never performs
  network I/O.

### Session and resume

- **FR-17 Stamp on exec.** The exec step writes, before the harness
  runs, `llm-sessions/<harness>/<session-key>.json` with `status =
  "attempted"`, harness and version, llm id, binding id, provider,
  requested model, protocol, sanitized origin, the three digests,
  compatibility state and rule version, whether the gate was
  bypassed, project path, timestamp. Never a credential value
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
  through the same resolver and compatibility gate as a fresh `--llm`.
  A launch-identity digest that differs from the stamp's (another
  provider, endpoint, protocol, auth header, model, credential name
  or mode, or quirk) is refused with exit 3 and no flag bypasses it.
  An options-digest change (a tuning key) is reported in the notice
  and allowed. An evidence-digest change alone (harness or rule
  version) only degrades the state to `unverified`, which
  `--allow-unverified` may bypass.

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
  `DISABLE_FEEDBACK_COMMAND=1` and enters the launch-identity digest,
  retiring the #399 notice for selected launches. Binding keys:
  `small_fast_model`, `max_output_tokens`. Clear-list (FR-30):
  whichever of `ANTHROPIC_AUTH_TOKEN` / `ANTHROPIC_API_KEY` the
  binding does not set, `ANTHROPIC_CUSTOM_HEADERS`,
  `CLAUDE_CODE_USE_BEDROCK`, `CLAUDE_CODE_USE_VERTEX`,
  `CLAUDE_CODE_USE_FOUNDRY`, `CLAUDE_CODE_USE_ANTHROPIC_AWS`, their
  `ANTHROPIC_*_BASE_URL` companions and `ANTHROPIC_DEFAULT_MODEL`.
  Claude Code's documentation says a settings-file `env` block wins
  over a shell export; B's capture establishes whether that also
  overrides the child environment, and if it does the adapter reads
  the user and project settings files for conflicting `env` keys (by
  name, never values) and refuses the launch naming them. No file
  overlay. The launcher parses `--llm <target>`, `--llm=<target>` and
  `--allow-unverified` before its forward-unknown-flags rule. Minimum
  version: the one the #399 work pinned for the retry behaviour. The
  adapter is implemented in slice B after B's capture; until then a
  `claude-code` launch **with `--llm`** refuses with "adapter not
  implemented", and a launch without `--llm` is untouched.
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
  `--llm`, native passthrough, stamp, exact-id resume and byte-for-
  byte native contract (FR-17–19, FR-27). Clear-list (FR-30):
  `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `CODEX_HOME` overrides and the
  provider-switch variables the capture identifies. Until the slice
  lands a `codex` launch with `--llm` refuses with "adapter not
  implemented".
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
  `PI_CODING_AGENT_DIR`. Clear-list (FR-30): Pi's built-in provider
  credential variables and `PI_CODING_AGENT_DIR`, as the capture
  enumerates them. The slice carries the stamp, exact-id resume and
  native contracts (FR-17–19, FR-27); until it lands a `pi` launch
  with `--llm` refuses with "adapter not implemented".
- **FR-23 Kiro.** A managed-model-only launcher `adapters/kiro/bin/
  kiro-code` (slice E): with `--llm`, `--model <llm.model>`; resume by
  `--resume-id`; the provider is `managed` with `credential_mode =
  "native"`, so CCT materializes nothing, and a headless run's
  `KIRO_API_KEY` is the user's own inherited variable, neither named
  in the catalog nor read by CCT. Its evidence follows the
  managed-harness contract in FR-15, and it carries the stamp,
  exact-id resume and native contracts (FR-17–19, FR-27); its
  clear-list is empty, since nothing is injected; until the slice
  lands a `kiro` launch with `--llm` refuses with "adapter not
  implemented". No endpoint, base URL, header or protocol is ever
  passed; a Kiro binding with an endpoint
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
  share the launch-identity digest; `routing_launch_env` journals the llm
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
  place under a lock (`flock` where available; otherwise a lock
  directory recording pid, host and timestamp, reclaimed when the
  host matches and that pid is gone, or, for a lock written by
  another host as on a shared home directory, only when it is older
  than ten minutes, with a test that a writer succeeds after the
  previous one was killed); a symlink at any path CCT writes is refused; an
  interrupted write leaves no partial file and no stale temporary
  file; readers tolerate a missing file and refuse a malformed one by
  name. Probe temporary directories are created with `mktemp -d` and
  removed on exit and on `INT`/`TERM`.
- **FR-30 Competing variables cleared.** A selected launch removes
  from the child environment every credential, base-URL,
  custom-header and provider-switch variable of the harness that the
  plan does not itself set, so a credential nobody chose (a global
  `ANTHROPIC_API_KEY` beside a bearer-token binding, or the only
  credential present under `auth_header = none`) never reaches a
  process pointed at a third-party endpoint, and a global Bedrock,
  Vertex or Foundry switch cannot redirect the session away from the
  selected endpoint. Each adapter owns its clear-list (FR-20–23), the
  plan carries it as `env_clear`, `cct harness explain` prints it by
  name, and the stamp records the names cleared. The clear-list
  applies only when `--llm` is given; without it nothing is touched
  (FR-11). Removal uses `env -u` for each name, the primitive
  `pi-code`'s worktree hand-off already uses. Proof: the sentinel
  control in FR-15 and a launcher test that a planted ambient key and
  switch are absent from the stub harness's environment.

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
| probe record | `(harness, llm@binding)` | `llm-compat/` | `latest_attempt` and `latest_conclusive`, capability matrix, evidence digest |
| session stamp | `(harness, session-key)` | `llm-sessions/` | `attempted` → `established`; redacted provenance for exact resume |
| project policy | `[llm].allowed` | project config | restriction only |

## Decisions (ruled by the owner on 2026-11-10)

Recommendations revised after the two bundle reviews of 2026-11-10.
D1–D10 and D12–D15 were ruled on 2026-11-10 after five review rounds;
D11 is deferred to the Pi capture and ruled at slice D's Task 0, so the
spec gate does not wait on a capture nobody can run yet. **A deferred
ruling is a spec amendment, never a silent edit:** slice D's Task 0
records the capture under `specs/llm-catalog/verification/`, appends
the ruling to this section with its date and evidence, updates FR-22,
and writes a fresh origin-alignment record that the owner approves
before slice D builds; the approved spec's history stays in git.

- **D1 Slicing.** One spec bundle; one issue and one PR per
  increment A–G; #400 stays open as the umbrella and G's PR closes it
  only after A–F, Kiro and Studio included, are merged. Recommended.
  **Ruled 2026-11-10 by the owner: accepted as recommended.** Condition: every slice PR says "Part of #400"; only G's PR closes it.
- **D2 User home.** `~/.code-copilot-team/` for the catalog, the
  compatibility records and the stamps, through one helper so #411
  moves them together. Alternative: wait for #411. Recommended:
  proceed now. **Ruled 2026-11-10 by the owner: accepted as recommended.**
- **D3 Three files.** `llms.toml` is new and separate; `routing.toml`
  references it in G; `providers.toml` stays the reviewer profile.
  Recommended: separate. **Ruled 2026-11-10 by the owner: accepted as recommended.**
- **D4 Parser.** Extract the line lexer of `routing-config.sh` into
  `scripts/lib/cct-toml.sh`, shared by both registries (bash 3.2).
  Alternatives: a second bash parser; Python `tomllib` (3.11+, which
  the launchers cannot assume). Recommended: extraction.
  **Ruled 2026-11-10 by the owner: accepted as recommended.** Condition: the extraction is its own commit with the existing routing-config tests passing unchanged.
- **D5 Bindings.** Explicit bindings only; `<llm>` resolves through
  the one explicit binding for `(harness, llm)`, `<llm>@<binding>`
  disambiguates. Inferred bindings were rejected in review because
  records and stamps need a stable binding key. Recommended:
  explicit only. **Ruled 2026-11-10 by the owner: accepted as recommended.**
- **D6 Probe reuse.** Share the canary primitives and the tri-state
  classification with `routing-probe.sh`; do not reuse routing's
  accounting, caps or state runner. Recommended. **Ruled 2026-11-10 by the owner: accepted as recommended.**
- **D7 Unverified launches.** Refuse by default; `--allow-unverified`
  launches with a notice, never records `supported`, and marks the
  stamp; `cct llm test` is the one exempt path, or no first record
  could ever exist. The earlier recommendation (launch with a notice)
  was withdrawn: a notice is not a gate. Recommended: refuse by
  default. **Ruled 2026-11-10 by the owner: accepted as recommended.**
- **D8 Endpoint quirks.** `quirks = ["rejects-dynamic-tools"]` on the
  endpoint drives the three #399 variables for selected launches and
  enters the launch-identity digest; the declaration is never evidence; the
  #399 notice stays for native launches. Recommended.
  **Ruled 2026-11-10 by the owner: accepted as recommended.**
- **D9 Session keys.** The launcher generates the session id and
  passes `--session-id` for Claude Code and Pi; stamps start as
  `attempted`; bare `--continue` and the interactive picker stay
  native. Project-latest restoration was withdrawn: the harness's
  "most recent" and CCT's "most recent stamp" are different sets.
  Recommended. **Ruled 2026-11-10 by the owner: accepted as recommended.**
- **D10 Codex overlay form.** `-c` overrides (names and URLs, no
  secret, nothing to clean up), adopted only after the capture proves
  nested keys on the installed CLI; a disproving capture stops the
  slice for a ruling, with no silent profile-file fallback.
  Recommended. **Ruled 2026-11-10 by the owner: accepted as recommended.**
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
  slice E's capture. Recommended. **Ruled 2026-11-10 by the owner: accepted as recommended.**
- **D13 Project policy.** `[llm].allowed` only. Recommended.
  **Ruled 2026-11-10 by the owner: accepted as recommended.**
- **D14 Studio.** Edits non-secret fields, explains, generates the
  id-only command; never spawns a harness. This is a narrowing of the
  issue's "start harness" and needs the owner's explicit approval.
  Recommended: approve the narrowing. **Ruled 2026-11-10 by the owner: accepted as recommended.**
- **D15 Unified entry.** `start` and `exec` semantics defined in A
  (FR-6); `cct start --llm` for Claude Code from B; `cct harness
  start <harness>` and `cct harness exec` with F. Recommended.
  **Ruled 2026-11-10 by the owner: accepted as recommended.**

## Success Criteria

The issue's acceptance criteria, each with the proof this bundle
requires:

| Issue criterion | Proof |
|---|---|
| Omitting `--llm` leaves each harness's native configured behaviour unchanged | Launcher suites diff argv and environment of a stub harness with and without the feature code; mutation test on the FR-11 guard |
| No secret in argv, generated commands, shell history, logs, multiplexer commands or provenance | Stub cmux/tmux capture the typed command; stub harness dumps argv and env; every capture, record and stamp is grepped for the planted secret |
| An incompatible pair is refused before the harness starts, with a reason | Stub harness records whether it ran; exit 3 and message asserted for each refusing state, and for `unverified` without the escape hatch |
| Every supported pair has a behavioral probe that fails when tool-call or protocol support is removed | Stub gateway switches (FR-15 negative controls) flip each capability check and the state to `incompatible`; a timeout or auth rejection leaves `latest_conclusive` untouched; the owner-run capture repeats the switches behind the real harness |
| Direct, cmux/tmux, headless and routed launches resolve the same identity | One resolver; the suite compares the launch-identity digest across the four paths (routed path in G) |
| A resumed session cannot silently switch provider or model | FR-18 exact-id cases, FR-19 launch-identity refusal that no flag bypasses, and the explicit native behaviour of bare `--continue` |
| Project configuration restricts but cannot introduce credentials or redefine a target | FR-24 refusals by name |
| (FR-10) The typed command cannot be hijacked by a project path | Hostile-path tests: spaces, quotes, newlines, `$( )`, `;`; no second command runs |
| (FR-15) The first probe can run and the probe cannot hang | `unverified` → `supported` regression; watchdog test with a hanging mock harness → `unverifiable`, no orphan process |
| Kiro never advertises arbitrary endpoint support | Rule-table test, launcher refusal of any endpoint-bearing binding, and a doc grep guard |
| Interactive and automated routing paths stamp the same identity | G: supervisor journal and launcher stamp compared by launch-identity digest |
| Existing wrapper invocations without `--llm` remain backward compatible | FR-27 byte-for-byte assertions in the launcher, supervisor and benchmark suites |

Plus: `cct llm validate` on the shipped example exits 0; every CLI
command's `--json` validates against `shared/schemas/llm-catalog-
cli.schema.json`; FR-29 is proven with an interrupted write, a
symlinked path, a concurrent-writer test and a stale-lock recovery
test; a planted path token is absent from every artifact; the test-count pins and
`docs/repo-structure.md` move together; `validate-spec.sh
--feature-id llm-catalog` and the origin gate pass before each
slice's PR.

## Out of scope, unchanged

Peer-review provider dispatch; benchmark backend selection; Session
Analytics ingestion of stamps (a follow-up can read `llm-sessions/`);
the home-directory migration (#411); a Kiro rules/hooks adapter;
secure-store credentials; Bedrock/Vertex/Foundry; Studio-spawned
sessions; identity-safe bare `--continue`.

# The LLM catalog and `--llm`

Pick the LLM for one session when you start it, from a catalog of named targets in `${CCT_HOME:-~/.cct}/llms.toml`, so no provider, credential or model variable is ever exported in a shell.

```bash
cct llm list                       # the targets, and whether each can launch
cct start --llm deepseek .         # this session only, on DeepSeek
cct start --llm opus .             # this session only, on Anthropic
cct start .                        # unchanged: Claude Code as you configured it
```

`claude-code --llm <target> [path]` is the same thing; `cct start` passes its arguments to that launcher. Headless runs take it too: `claude-code --llm deepseek -p "…"`.

This is the first slice of the catalog specified in [#400](https://github.com/gosha70/code-copilot-team/issues/400): Claude Code only. What it does not do yet is listed [at the end](#not-in-this-version).

## Why not environment variables

Claude Code reads its endpoint, credential and model from the environment of its own process. Exporting them in a shell profile configures every session started from any shell: sessions meant for Anthropic are routed to the other provider, the `Opus`, `Sonnet` and `Haiku` aliases point at its models, a session made with one provider is resumed against another, and tuning chosen for one model applies to all of them.

`--llm` sets those variables in the one process that becomes `claude`, and removes the competing ones from it. Nothing is exported, and nothing a shell exports can redirect a selected session.

## Set it up

```bash
mkdir -p ~/.cct
cp shared/templates/llm/llms.toml.example ~/.cct/llms.toml    # from your checkout
$EDITOR ~/.cct/llms.toml
cct llm validate
cct llm list
```

A credential stays where it is: export the key itself (`export DEEPSEEK_API_KEY=…`) in your shell profile, and name that variable in the catalog. A key on its own routes nothing. Remove any `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_MODEL` or `ANTHROPIC_DEFAULT_*_MODEL` export from your profile: those are what the catalog replaces.

After pulling a version that has `--llm`, refresh the installed launcher once: `./scripts/setup.sh --sync --claude-code`.

## The file

Four kinds of table. The file is strict: an unknown table, key or value is refused by name, with its line.

```toml
schema_version = 1

# who serves a model, and how you sign in
[providers.deepseek]
display_name = "DeepSeek"
kind = "api"
credential_mode = "env"
credential_env = "DEEPSEEK_API_KEY"

# where it is reached, and how it is called
[endpoints.deepseek]
provider = "deepseek"
protocol = "anthropic-messages"
base_url = "https://api.deepseek.com/anthropic"
auth_header = "bearer"
quirks = ["rejects-dynamic-tools"]

# a model; its id is what --llm takes
[llms.deepseek]
provider = "deepseek"
model = "deepseek-chat"

# run this llm on this harness, through this endpoint
[bindings.deepseek-claude]
harness = "claude-code"
llm = "deepseek"
endpoint = "deepseek"
```

An id is letters, digits, `_` and `-`. The grammar is the routing registry's: `key = value` with double-quoted strings, integers, booleans and single-line arrays of strings, and comments on lines of their own (a comment after a value or a table header is refused).

### `[providers.<id>]`

| Key | Value |
|---|---|
| `kind` | `api`: reached at an endpoint you name. `managed`: the harness signs in itself (Claude Code's own login). |
| `credential_mode` | For `api`: `env` (a credential in an environment variable) or `none` (a local server that takes none). For `managed`: `native`. |
| `credential_env` | With `env`: the **name** of the variable that holds the credential. Never the value; a value that looks like a credential is refused. |
| `display_name` | Optional. Shown in the launch notice. |

### `[endpoints.<id>]`

| Key | Value |
|---|---|
| `provider` | An `api` provider. |
| `protocol` | `anthropic-messages`, `openai-chat` or `openai-responses`. Claude Code speaks only `anthropic-messages`; a binding to another one is refused at launch. |
| `base_url` or `base_url_env` | Exactly one. An absolute `http(s)` URL with no user, query or fragment, or the name of a variable that holds one. |
| `auth_header` | `bearer` or `x-api-key` for a provider with a credential; `none` for one without. |
| `quirks` | Optional. `["rejects-dynamic-tools"]` for an endpoint that rejects Claude Code's dynamic tool blocks (DeepSeek answers 422 `unknown variant tool_definition`): tool search, experimental betas and the feedback command are turned off for sessions on it. |

### `[llms.<id>]`

| Key | Value |
|---|---|
| `provider` | The provider that serves it. |
| `model` | The model id the provider expects. For Claude Code a `[1m]` suffix asks for 1M-context handling, as it does in `/model`. |
| `context_window`, `reasoning`, `input` | Optional descriptions (an integer, a boolean, `["text", "image"]`). Nothing reads them yet. |

### `[bindings.<id>]`

| Key | Value |
|---|---|
| `harness` | `claude-code`. The other harnesses are refused until their launchers take `--llm`. |
| `llm` | The model to run. |
| `endpoint` | Required for an `api` provider's model; not accepted for a `managed` one. |
| `small_fast_model` | Optional. The model for Claude Code's small, fast requests (the `Haiku` alias). Without it every alias is the main model. |
| `max_output_tokens`, `auto_compact_window`, `reasoning_effort` | Optional tuning for sessions on this binding. |

`--llm <llm>` uses the one binding the llm has for the harness. When it has several, name one: `--llm <llm>@<binding>`. A binding is never guessed.

## What a selected launch sets and removes

For an `api` endpoint:

| Set | From |
|---|---|
| `ANTHROPIC_BASE_URL` | the endpoint |
| `ANTHROPIC_AUTH_TOKEN` or `ANTHROPIC_API_KEY` | the credential variable, by `auth_header`. With `none`, a placeholder token, so Claude Code never falls back to its own login and sends that to the endpoint. |
| `ANTHROPIC_MODEL`, `ANTHROPIC_DEFAULT_OPUS_MODEL`, `ANTHROPIC_DEFAULT_SONNET_MODEL`, `ANTHROPIC_DEFAULT_FABLE_MODEL` | the model |
| `ANTHROPIC_DEFAULT_HAIKU_MODEL`, `ANTHROPIC_SMALL_FAST_MODEL` | `small_fast_model`, else the model |
| `CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS`, `ENABLE_TOOL_SEARCH`, `DISABLE_FEEDBACK_COMMAND` | the `rejects-dynamic-tools` quirk |
| `CLAUDE_CODE_MAX_OUTPUT_TOKENS`, `CLAUDE_CODE_AUTO_COMPACT_WINDOW`, `CLAUDE_CODE_EFFORT_LEVEL` | the binding's tuning keys |

Every alias is set so that a subagent or a background request asking for `sonnet` or `haiku` stays on the endpoint you chose.

For a `managed` provider only `ANTHROPIC_MODEL` and the tuning are set, and the gateway variables above are removed instead, so the session is Anthropic's even from a shell configured for a gateway. `ANTHROPIC_API_KEY` and `CLAUDE_CODE_OAUTH_TOKEN` are left alone there: they are ways Claude Code itself signs in.

Removed from every selected launch: the credential variable the binding does not use, `ANTHROPIC_CUSTOM_HEADERS`, `ANTHROPIC_DEFAULT_MODEL`, `CLAUDE_CODE_SUBAGENT_MODEL`, the Bedrock, Vertex, Foundry and other provider switches with their base URLs, `CLAUDE_CODE_USE_GATEWAY`, `ANTHROPIC_UNIX_SOCKET`, and any of the three tuning variables the binding does not set.

Removed from a launch on an `api` endpoint as well: `CLAUDE_CODE_OAUTH_TOKEN`. That token is Claude Code's own login, and Claude Code sends it to whatever base URL it is given when no other credential is set.

A command the launcher types into a new cmux workspace or tmux session carries only the launcher, the target and Claude Code's own flags. The launcher runs again inside that pane, and the credential is read there.

## Refusals

Each happens before Claude Code starts, with exit code 3 and the reason.

| Refused | Because |
|---|---|
| unknown llm or binding; several bindings and no `@<binding>` | the target does not name one binding |
| `unsupported` | the endpoint speaks a protocol Claude Code does not |
| `unavailable` | the credential variable is not set, or the base-URL variable is unset or holds a refused URL |
| the catalog is missing or not valid | the violations are listed |
| a settings file sets an endpoint, credential, model, switch or quirk variable of the launch | Claude Code applies a `settings.json` `env` block over the environment it is started with, so the selection would be undone. Remove the key from the `env` block. |
| a tmux session for the project already exists | attaching would not apply the selection |
| a project path, a forwarded flag or the launcher's own path that needs `$'…'` quoting, when the launch has to type a command into a new pane | the shell in that pane may not parse it. Start from inside a cmux or tmux pane, where nothing is typed. |

One thing in a settings file is said and not refused: `CLAUDE_CODE_MAX_OUTPUT_TOKENS`, `CLAUDE_CODE_AUTO_COMPACT_WINDOW` or `CLAUDE_CODE_EFFORT_LEVEL` in an `env` block. Tuning does not change which target a session reaches, so the launch goes ahead with a notice, and the settings file's value is the one the session uses, also when the binding sets its own.

## Providers

- **Anthropic.** A `managed` provider: `kind = "managed"`, `credential_mode = "native"`, an llm whose `model` is an alias or a model id, and a binding with no endpoint.
- **DeepSeek.** Its Anthropic-compatible endpoint, `auth_header = "bearer"`, and the `rejects-dynamic-tools` quirk.
- **Ollama.** It serves the Anthropic Messages API itself: `base_url = "http://localhost:11434"`, `credential_mode = "none"`, `auth_header = "none"`.
- **vLLM, OpenAI and anything else that speaks OpenAI's protocols.** Claude Code needs a gateway in front that translates to Anthropic Messages; the endpoint in the catalog is that gateway. [The DGX Spark cookbook](dgx-spark/setup-cookbook.md) sets one up with the LiteLLM proxy.

The example file has a target for each.

## Switching and resuming

The endpoint is fixed for the life of a session. Switching provider means starting another session with another `--llm`; inside a session `/model` switches only among that endpoint's models.

Resume a session with the target it was started with (`cct start --llm deepseek --resume`). The launcher does not record a session's target yet, so it cannot restore or check it for you; a session made on one provider and resumed on another usually fails.

## Not in this version

Specified in #400 and not built yet: a compatibility probe (`cct llm test`), so every launchable target reads `unverified`; a record of each session's target, with resume restored or refused from it; `--json` output and a Studio page; a project's own allow-list; and `--llm` on the Codex, Pi and Kiro launchers.

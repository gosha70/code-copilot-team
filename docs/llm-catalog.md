# The LLM catalog and `--llm`

Pick the LLM for one session when you start it, from a catalog of named targets in `${CCT_HOME:-~/.cct}/llms.toml`, so no provider, credential or model variable is ever exported in a shell.

```bash
cct llm list                       # the targets, and whether each can launch
cct harness explain claude-code --llm deepseek   # what that launch would set and remove
cct llm test deepseek              # run Claude Code on it once; a launch needs this to pass
cct start --llm deepseek .         # this session only, on DeepSeek
cct start --llm opus .             # this session only, on Anthropic
cct start .                        # unchanged: Claude Code as you configured it
```

`cct start` passes its arguments to the `claude-code` launcher, so `claude-code --llm <target> [path]` is the same thing. Headless runs take it too: `cct start --llm deepseek -p "…"`.

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
cct llm test <target>        # once per target, before its first launch
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

For a `managed` provider only `ANTHROPIC_MODEL` and the tuning are set, and the gateway variables above are removed instead, so the session is Anthropic's even from a shell configured for a gateway. `ANTHROPIC_API_KEY`, `CLAUDE_CODE_OAUTH_TOKEN` and the other forms of Claude Code's own credentials are left alone there: they are how Claude Code itself signs in.

Removed from every selected launch: the credential variable the binding does not use, `ANTHROPIC_CUSTOM_HEADERS`, `ANTHROPIC_DEFAULT_MODEL`, `CLAUDE_CODE_SUBAGENT_MODEL`, the Bedrock, Vertex, Foundry and other provider switches with their base URLs, `CLAUDE_CODE_USE_GATEWAY`, `ANTHROPIC_UNIX_SOCKET`, and any of the three tuning variables the binding does not set.

Removed from a launch on an `api` endpoint as well, Claude Code's own credentials in every form it reads: `CLAUDE_CODE_OAUTH_TOKEN`, `CLAUDE_CODE_OAUTH_REFRESH_TOKEN`, `CLAUDE_CODE_GATEWAY_TOKEN`, the file-descriptor forms `CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR`, `CLAUDE_CODE_API_KEY_FILE_DESCRIPTOR` and `CLAUDE_CODE_GATEWAY_TOKEN_FILE_DESCRIPTOR`, and the workload-identity token, `ANTHROPIC_IDENTITY_TOKEN` and `ANTHROPIC_IDENTITY_TOKEN_FILE`. They are for Anthropic: when no other credential is set, Claude Code sends its login token, and a key or token handed over by file descriptor, to whatever base URL it is given, and with a federation rule it posts the identity token to that base URL's token endpoint.

A command the launcher types into a new cmux workspace or tmux session carries only the launcher, the target and Claude Code's own flags. The launcher runs again inside that pane, and the credential is read there.

## See a launch before it runs

```bash
cct llm show deepseek                            # one llm, and what each of its bindings would launch
cct harness explain claude-code --llm deepseek   # the launch plan: what it sets and removes, by name
cct llm list --json                              # every cct llm command, and explain, takes --json
```

`cct harness explain` asks the resolver the launcher itself uses, so what it prints is what a launch with that target does: each variable it sets, a credential with the variable it is copied from and whether that is set, each variable it removes, the state, and why a launch would be refused (exit 3). No value is ever printed: an endpoint is shown as its origin (`scheme://host[:port]`), and a credential as its variable's name.

It also prints three digests:

- **catalog:** changes when anything declared for the target changes, a display name included;
- **launch identity:** changes only when what the launch executes as changes: the endpoint's full URL (its path too, which is never shown), the protocol, the auth header, the credential's variable and mode, the model, the quirks;
- **options:** the tuning keys (`small_fast_model`, `max_output_tokens`, `reasoning_effort`, `auto_compact_window`).

Compatibility records and session stamps are keyed on them. `shared/schemas/llm-catalog-cli.schema.json` describes the `--json` output. When a command cannot answer (a usage error, no catalog, a catalog with violations, `show` naming an llm the catalog does not define, `compatibility` or `test` unable to read its rule table or resolve its target, or `test` refusing a target or unable to run its probe), `--json` still prints the envelope, with an `error` field and nothing else, and exits as the text form does. A usage error's envelope has no `catalog`, and its `command` is null when no command was recognized. A harness other than `claude-code`, and `pi-code --llm`, are refused with "not implemented" until their slice of #400 lands.

## Compatibility

```bash
cct llm compatibility                  # every target's state, and why
cct llm compatibility deepseek --json  # one target (its claude-code binding), with its evidence
cct doctor                             # its "LLM catalog" section shows the same
```

Each target is in one of five states:

- **supported:** its latest conclusive test passed every capability the binding needs, and nothing has changed since but, at most, a newer `claude`. The reason says so when the test ran on an older one.
- **unverified:** it was never tested, or something changed since its test. The reason says what changed: the launch identity, the options, the version of `claude` (an older one than the test's, or one that cannot be read), or the rule version.
- **unavailable:** its credential or base URL variable is not set, or `claude` is not installed or older than the rule table's minimum, 2.1.305.
- **unsupported:** `claude` cannot speak the endpoint's protocol or honour a quirk it declares. The rules are data, in `shared/llm/compat-rules.json`, with a version.
- **incompatible:** its latest conclusive test failed.

The state is computed from the catalog, the rule table, the environment and the test records in `${CCT_HOME:-~/.cct}/llm-compat/`, and nothing is sent anywhere. A test that could not reach a verdict, for example one that timed out, never replaces a conclusive result. A rule table or a record that cannot be read refuses a `--llm` launch, naming the file.

### Testing a target

```bash
cct llm test deepseek          # the capabilities, the outcome, and the state that follows
cct llm test deepseek --json
```

`cct llm test` runs `claude` once, headless, on the target, with the environment a launch of it gets, and records what each capability did: `pass`, `fail`, `unverifiable` (it could not tell) or `not_applicable`. Claude Code is asked to run one script through its Bash tool, the only command the test allows it, and to answer one line: a marker, a token from a system prompt it was given, and what the script printed. The endpoint answers as the model, so a command of its own asked for in the same tool call is refused, and the test fails. Your own permission rules still apply, as in a launch, so the test also gives Claude Code a hook that blocks every tool call but that script's, whatever those rules allow; any other call the endpoint asks for fails the test, refused or not. Whatever turns Claude Code's hooks off turns that one off too: `cct llm test` warns before it runs when your settings file sets `disableAllHooks`, or when `CLAUDE_CODE_SIMPLE` or `CLAUDE_CODE_SAFE_MODE` is set in its `env` block or in your environment. It does not read managed settings. From that run it checks the credential, the model the endpoint reports, streaming, the system prompt, the tool call and its result, its own output, a clean exit, and the binding's `max_output_tokens` when it sets one. When the llm declares `reasoning = true`, it checks that thinking came back; when it declares `input = ["text", "image"]`, a second run sends a small image and asks its colour.

A run that passed or failed is conclusive and decides the state. A credential the endpoint refused, a timeout, a crash, an answer that cannot be read, or an error that does not say the request was malformed (an exhausted balance, an unknown model) is recorded, says so, and decides nothing. So does a model name the endpoint reports that only contains the requested one, as an alias resolves to a dated id. Each run is cut off after 120 seconds (`CCT_LLM_PROBE_TIMEOUT_SEC`), Claude Code's whole process group with it, and its scratch directory is removed, also when you interrupt it. The record holds no credential: the reply it keeps has the credential, the endpoint's path, the scratch directory and your home directory taken out. An `unsupported` or `unavailable` target is refused before anything runs, as a launch would be, and so is a test that a settings file's `env` block would redirect (see [Refusals](#refusals)). `cct llm test` exits 0 when the target passed, 1 when it did not, and 3 when it was refused.

### Launches need a passing test

A `--llm` launch, and a resume that restores a session's target, go ahead only when the target is `supported`. Otherwise they are refused before Claude Code starts, with exit code 3 and the way out:

| State | The launch |
|---|---|
| `supported` | goes ahead |
| `supported`, tested on an older `claude` | goes ahead, with a notice naming both versions and the `cct llm test` that tests it again |
| `unverified` | refused: test it with `cct llm test`, or add `--allow-unverified` to launch it untested, with a notice that its session's stamp records |
| `incompatible` | refused; `--allow-unverified` does not apply. Fix the endpoint or the binding, then test it again |
| `unavailable`, `unsupported` | refused, with the reason |

A newer `claude` keeps a passing test, because Claude Code updates often; anything else that changes since the test, including a tuning option or the rule table, needs a new one. The launcher that opens a new cmux workspace or tmux session checks before it opens it, and the launcher in the new pane checks again in that pane's own environment.

## A project's allow-list

A project can narrow which targets `--llm` may use on it, in its committed `.cct.toml`:

```toml
[llm]
allowed = ["deepseek", "opus@opus-claude"]
```

An entry is an llm id, which allows each of its bindings, or `<llm>@<binding>`, which allows that binding only. A target the list does not name is refused with exit 3, and `allowed = []` allows none. The list only restricts: any other key under `[llm]`, or the same table written another way (`llm.allowed = [...]` or `llm = {...}` at the top of the file, an `[llm.<x>]` or `[[llm]]` table), is refused by name, because a project never chooses a model for you. A quoted name (`["llm"]`) is the same table.

Write the list on one line, as above: double-quoted entries separated by commas, with no trailing comma and no comment after it. It is the only form a launch reads. Any other is refused, and the refusal shows this one: a list over several lines, a trailing comma, single-quoted entries, a quoted `"allowed"`. The header is `[llm]`, alone on its line or followed by a comment; spaces inside the brackets or a quoted name are the same header. Any other header naming the table, such as `[llm] x`, is refused too. `bash scripts/validate-cct-config.sh .cct.toml`, run from your checkout, reports another key under `[llm]` as an error. It reads the file as Pi does, so it passes some forms of the list that a launch refuses, such as a trailing comma or single-quoted entries.

It is read from `.cct.toml` at the project root, the git top level of the launch directory. When git names none, the directory's own `.cct.toml` applies, and so does that of the nearest directory at or above it holding `.git`, if there is one: git may be refusing a work tree there, and a project only restricts, so both lists apply. It is read from there only: never from `.cct.local.toml`, so a personal file cannot change what the team committed, and never from the legacy `.code-copilot-team/config.toml`. Only the `[llm]` table is read, so the rest of the file never affects a launch, and a launch without `--llm` reads none of it. The one exception is a line that begins like a header for the table: it is read as one wherever it is, even inside a value written over several lines, which Pi does not read either. A `.cct.toml` that cannot be read, or a project directory that cannot be searched for one, refuses a `--llm` launch: a restriction that cannot be read is never taken as none. `cct harness explain` applies the same list, from the current directory's project or the one `--project <dir>` names.

## Refusals

Each happens before Claude Code starts, with exit code 3 and the reason.

| Refused | Because |
|---|---|
| unknown llm or binding; several bindings and no `@<binding>` | the target does not name one binding |
| `unsupported` | the endpoint speaks a protocol Claude Code does not |
| `unavailable` | the credential variable is not set, the base-URL variable is unset or holds a refused URL, or `claude` is missing or older than 2.1.305 |
| `unverified`, unless `--allow-unverified` | no test of the target has passed, or something changed since it did; see [Launches need a passing test](#launches-need-a-passing-test) |
| `incompatible` | the target's latest conclusive test failed |
| the catalog is missing or not valid | the violations are listed |
| a settings file sets an endpoint, credential, model, switch or quirk variable of the launch | Claude Code applies a `settings.json` `env` block over the environment it is started with, so the selection would be undone. Remove the key from the `env` block. |
| a tmux session for the project already exists | attaching would not apply the selection |
| a project path, a forwarded flag or the launcher's own path that holds a control character (a newline, a tab, an escape), when the launch has to type a command into a new pane | a control character must never be typed into a pane. Start from inside a cmux or tmux pane, where nothing is typed. Printable non-ASCII is not refused. |
| a resume that would change a session's target; `--continue` or the picker with `--llm`; `--session-id` with `--llm` | see [Sessions and resuming](#sessions-and-resuming) |

One thing in a settings file is said and not refused: `CLAUDE_CODE_MAX_OUTPUT_TOKENS`, `CLAUDE_CODE_AUTO_COMPACT_WINDOW` or `CLAUDE_CODE_EFFORT_LEVEL` in an `env` block. Tuning does not change which target a session reaches, so the launch goes ahead with a notice, and the settings file's value is the one the session uses, also when the binding sets its own.

## Providers

- **Anthropic.** A `managed` provider: `kind = "managed"`, `credential_mode = "native"`, an llm whose `model` is an alias or a model id, and a binding with no endpoint.
- **DeepSeek.** Its Anthropic-compatible endpoint, `auth_header = "bearer"`, and the `rejects-dynamic-tools` quirk.
- **Ollama.** It serves the Anthropic Messages API itself: `base_url = "http://localhost:11434"`, `credential_mode = "none"`, `auth_header = "none"`.
- **vLLM, OpenAI and anything else that speaks OpenAI's protocols.** Claude Code needs a gateway in front that translates to Anthropic Messages; the endpoint in the catalog is that gateway. [The DGX Spark cookbook](dgx-spark/setup-cookbook.md) sets one up with the LiteLLM proxy.

The example file has a target for each.

## Sessions and resuming

The endpoint is fixed for the life of a session. Switching provider means starting another session with another `--llm`; inside a session `/model` switches only among that endpoint's models.

A `--llm` launch gives its session an id, which it prints at start, and records the target under that id before Claude Code runs. The record (a stamp) is a private file in `${CCT_HOME:-~/.cct}/llm-sessions/claude-code/`, with names and digests only, never a credential. Resume the session by that id:

```bash
cct start --resume <session-id>                              # on the target it was started with, said at start
cct start --resume <session-id> --llm deepseek               # the same, when deepseek is that target
cct start --resume <session-id> --fork-session --llm opus    # a new session from it, on another target
cct llm sessions                                             # the sessions, and whether each can be resumed now
```

A resumed target is resolved again, as for a new launch. These are refused, before Claude Code starts, with exit code 3:

| Refused | Because |
|---|---|
| `--resume <id> --llm <target>` naming a target other than the session's | it would switch the session's model; the refusal names both targets |
| `--resume <id>` after the target's launch identity changed (its endpoint, protocol, auth header, model, credential or quirks) | the same. A change of tuning only is said, and the target, now untested, needs a new test or `--allow-unverified`, as for a new launch |
| `--resume <id> --llm <target>` for a session with no stamp | the target it was started with is unknown. Resume it without `--llm`, or fork it |
| `--llm` with `--continue` (also beside `--resume <id>`: Claude Code acts on `--continue` first), with `--resume` and no id, or with a session's name instead of its id | Claude Code picks the session, so the selection would be ignored or would switch that session's model |
| `--llm` with `--from-pr` or `--teleport` | Claude Code finds that session for itself, the same way |
| a single-dash cluster in which `c` is a letter of its own, such as `-cd` or `-pc` | Claude Code reads it letter by letter, so that `c` is `--continue`, refused as above. In `-dc` or `-rc`, `c` is the value of the letter before it |
| `--resume <id>` of a stamped session, without `--llm`, beside any of these | Claude Code would resume another session, on the target restored for this one |
| `--llm` with `--session-id` | the launcher chooses the session's id; drop `--session-id` |

The launcher reads the arguments as Claude Code reads them:
- **A letter that takes a value** takes the rest of its cluster, or the next argument. `-pr <id>` and `-pr<id>` are `-p --resume <id>`, a resume of that session, while `-rp` is a resume by the name `p`.
- **An option that requires a value** takes the next argument, whatever it is. In `--append-system-prompt --resume <id>`, `--resume` is the system prompt and the id is the prompt, so the session is a new one. With `--llm` it gets a new stamp, and the session named there is left as it was.

Without `--llm`, `--continue` and the picker work as before; where stamps exist, they print a note that they check no target. A session started without `--llm` resumes as it always has, and a fork without `--llm` is a new session that runs as any other launch without it.

`/resume` inside a session can open a stamped session on the current session's target, which the launcher can't check: it runs only at launch. To keep a stamped session on its own target, resume it from the shell with `--resume <id>`.

`cct llm sessions` lists the stamped sessions, newest first: each one's id, target, model, state, project, and whether a resume by its id would go ahead now, with the reason when it would not. `--project <dir>` shows only the sessions started in that directory, and `--harness <h>` another harness's (only Claude Code's are stamped so far). A session is `attempted` until Claude Code's own transcript for it records a reply; it is then `established`, with the model that reply names. An API error, which Claude Code also records in the transcript, is not a reply, and neither is the history a fork copies from its source. `--json` prints the same, with the stamps' directory.

## Not in this version

Specified in #400 and not built yet: a Studio page, and `--llm` on the Codex, Pi and Kiro launchers.

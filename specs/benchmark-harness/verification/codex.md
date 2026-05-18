# Codex Backend Verification Record

Pinned version: **codex-cli 0.130.0**  
Verified: 2026-05-17 (captured live on the author's machine; see transcript below)  
Purpose: Per #33's backend verification gate — pins the exact headless invocation
surface for `codex exec` at `codex-cli 0.130.0` before the backend code ships.
If a future pinned version's flags differ, this record is refreshed and the
backend implementation is updated to match it.

## Version

```
$ codex --version
codex-cli 0.130.0
```

## Verified argv (the contract)

```
codex exec --json --sandbox workspace-write --skip-git-repo-check [--model <model>] -
```

With the **prompt on stdin** (trailing `-` causes codex to read instructions from
stdin). The `--model <model>` flag is **included only when the model is non-empty**;
if omitted, codex uses the `~/.codex/config.toml` default model.

### Flag contract

| Flag | Required | Rationale |
|------|----------|-----------|
| `exec` | yes | Runs codex non-interactively against a prompt. |
| `--json` | yes | Emits JSONL events to stdout (required for transcript parsing). |
| `--sandbox workspace-write` | yes | Permits the model to write files in the working directory while sandboxed. |
| `--skip-git-repo-check` | yes | The attempt worktrees created by the harness are plain directories, not git repos; without this flag codex aborts with an error. |
| `--model <id>` | conditional | Passed only when `ctx.model` is non-empty. When absent, codex uses its configured default (from `~/.codex/config.toml`). |
| `-` (trailing) | yes | Reads instructions from stdin. This avoids shell argument-length limits for large prompts (SWE-bench issue descriptions can be several KB). |

### Flag NOT present: `--ask-for-approval`

An earlier draft of this spec assumed `--ask-for-approval never` should be passed
to suppress interactive prompts. The verification probe **disproved this assumption**:
`codex exec --ask-for-approval never -` returned `exit=2` with a usage error, and
`codex exec --help` confirmed **no such flag exists on `exec`** in 0.130.0.
`codex exec` is **inherently non-interactive** — it does not prompt for approval.
This is the concrete justification for #33's per-backend verification-before-code gate:
it caught a flag assumption that would have caused every invocation to fail.

## JSONL transcript format

The `--json` flag causes codex to emit newline-delimited JSON events to stdout.
The events relevant to the harness parser are:

```
{"type":"thread.started","thread_id":"<uuid>"}
{"type":"turn.started"}
{"type":"item.completed","item":{"id":"...","type":"agent_message","text":"<model response text>"}}
{"type":"item.completed","item":{"id":"...","type":"command_execution","command":"...","aggregated_output":"...","exit_code":0,"status":"completed"}}
{"type":"item.completed","item":{"id":"...","type":"file_change","changes":[{"path":"...","kind":"add|modify|delete"}],"status":"completed"}}
{"type":"turn.completed","usage":{"input_tokens":N,"cached_input_tokens":N,"output_tokens":N,"reasoning_output_tokens":N}}
```

Token usage keys (in `turn.completed.usage`):

| codex key | harness field |
|-----------|---------------|
| `input_tokens` | `tokens_input` |
| `cached_input_tokens` | `cache_read_tokens` |
| `output_tokens` | `tokens_output` |
| `reasoning_output_tokens` | (recorded as-is; may be 0 or null) |

`null` vs `0` is preserved — the harness never coerces absent counts to zero.

## Real recorded transcript

Captured 2026-05-17 in `/tmp/codex-verify-test/` with the command:

```bash
printf 'Write a Python function called add(a, b) that returns the sum of a and b. Create a file called add.py with this function.' \
  | codex exec --json --sandbox workspace-write --skip-git-repo-check -
```

```jsonl
{"type":"thread.started","thread_id":"019e3913-6f96-7d23-8fef-92cd8d806c8b"}
{"type":"turn.started"}
{"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"I'll make the requested single-file change in the current workspace and then verify the file contents."}}
{"type":"item.started","item":{"id":"item_1","type":"command_execution","command":"/bin/zsh -lc 'pwd && ls'","aggregated_output":"","exit_code":null,"status":"in_progress"}}
{"type":"item.completed","item":{"id":"item_1","type":"command_execution","command":"/bin/zsh -lc 'pwd && ls'","aggregated_output":"/tmp/codex-verify-test\n","exit_code":0,"status":"completed"}}
{"type":"item.completed","item":{"id":"item_2","type":"agent_message","text":"The workspace is empty, so the minimal change is to add `add.py` with just the requested function."}}
{"type":"item.started","item":{"id":"item_3","type":"file_change","changes":[{"path":"/private/tmp/codex-verify-test/add.py","kind":"add"}],"status":"in_progress"}}
{"type":"item.completed","item":{"id":"item_3","type":"file_change","changes":[{"path":"/private/tmp/codex-verify-test/add.py","kind":"add"}],"status":"completed"}}
{"type":"item.started","item":{"id":"item_4","type":"command_execution","command":"/bin/zsh -lc \"sed -n '1,20p' add.py && python -m py_compile add.py\"","aggregated_output":"","exit_code":null,"status":"in_progress"}}
{"type":"item.completed","item":{"id":"item_4","type":"command_execution","command":"/bin/zsh -lc \"sed -n '1,20p' add.py && python -m py_compile add.py\"","aggregated_output":"def add(a, b):\n    return a + b\n","exit_code":0,"status":"completed"}}
{"type":"item.completed","item":{"id":"item_5","type":"agent_message","text":"Created [add.py](/private/tmp/codex-verify-test/add.py) with:\n\n```python\ndef add(a, b):\n    return a + b\n```\n\nValidation: `python -m py_compile add.py` passed."}}
{"type":"turn.completed","usage":{"input_tokens":76035,"cached_input_tokens":47616,"output_tokens":261,"reasoning_output_tokens":0}}
```

Exit code: `0`

## Provider routing (`~/.codex/config.toml`)

Codex reads its model and provider configuration from `~/.codex/config.toml`.
The file path is recorded in `backend_metadata.config_toml_path` at run time.
A typical config block:

```toml
model = "o4-mini"

[model_providers.my_openai]
name = "OpenAI"
base_url = "https://api.openai.com/v1"
# api_key is read from the CODEX_HOME/auth.json file, not from config.toml
```

The harness records `model_providers.<id>` (the config key, not any key value)
in `backend_metadata.provider_id`. API keys are **never** recorded — only their
presence as a boolean or the provider config key name.

## Reviewer checklist

A reviewer confirming this record maps to the `codex.py` implementation:

1. `codex exec --json --sandbox workspace-write --skip-git-repo-check` appears verbatim in `_build_argv`.
2. `--model <model>` is added **if and only if** `ctx.model` is non-empty.
3. Prompt is sent on **stdin** (trailing `-`), not in argv.
4. **No `--ask-for-approval` flag** anywhere in the argv.
5. `turn.completed.usage.{input_tokens, cached_input_tokens, output_tokens}` are mapped to `{tokens_input, cache_read_tokens, tokens_output}`.
6. `agent_message.text` is extracted as the model's text response.
7. `backend_metadata` carries `config_toml_path` and `provider_id` but **not** any API key value.

# Capture — Claude Code sessions and the FR-20 variables (#400 S4)

Recorded 2026-11-26 by `specs/llm-catalog/verification/capture-claude.sh` with `2.1.332 (Claude Code)`,
the real binary (`claude` on `PATH`, a wrapper script skipped), in a throwaway home under
`env -i`, against one local stub (`capture-stub.py`). The only credential is the planted
sentinel `capture-planted-credential`; no request left the machine for a model. Each run is
headless: `-p "Reply with the single word OK." --output-format json --max-turns 1` and the flags named. Session ids are generated per run:
`<S1>` and `<S2>` below.

## 1. A new session named by `--session-id`, through a bearer credential

- exit 0
- result: 'stub-ok'; is_error: False; session_id: `<S1>`
- models in the JSON result (`modelUsage`): capture-main
- stub: POST /v1/messages?beta=true | protocol anthropic-messages | model 'capture-main' | auth {'authorization': 'Bearer capture-planted-credential'}
- stderr: [claude-code:unrecognized_model] {"model":"capture-main","query_source":"sdk"}

## 2. A new session through an `x-api-key` credential

- exit 0
- result: 'stub-ok'; is_error: False; session_id: `<S2>`
- models in the JSON result (`modelUsage`): capture-main
- stub: POST /v1/messages?beta=true | protocol anthropic-messages | model 'capture-main' | auth {'x-api-key': 'capture-planted-credential'}
- stderr: [claude-code:unrecognized_model] {"model":"capture-main","query_source":"sdk"}

## 3. `--resume <S1>`

- exit 0
- result: 'stub-ok'; is_error: False; session_id: `<S1>`
- models in the JSON result (`modelUsage`): capture-main
- stub: POST /v1/messages?beta=true | protocol anthropic-messages | model 'capture-main' | auth {'authorization': 'Bearer capture-planted-credential'}
- stderr: [claude-code:unrecognized_model] {"model":"capture-main","query_source":"sdk"}

## 4. `--session-id <S1>` again, an id already in use

- exit 1
- stderr: Error: Session ID <S1> is already in use.

## 5. A bare `--continue`

- exit 0
- result: 'stub-ok'; is_error: False; session_id: `<S1>`
- models in the JSON result (`modelUsage`): capture-main
- stub: POST /v1/messages?beta=true | protocol anthropic-messages | model 'capture-main' | auth {'authorization': 'Bearer capture-planted-credential'}
- stderr: [claude-code:unrecognized_model] {"model":"capture-main","query_source":"sdk"}

## 6. `--resume <S1> --fork-session --session-id <S3>`

- exit 0
- result: 'stub-ok'; is_error: False; session_id: `<S3>`
- models in the JSON result (`modelUsage`): capture-main
- stub: POST /v1/messages?beta=true | protocol anthropic-messages | model 'capture-main' | auth {'authorization': 'Bearer capture-planted-credential'}
- stderr: [claude-code:unrecognized_model] {"model":"capture-main","query_source":"sdk"}

## 7. `--resume <S1> --session-id <S4>`, without `--fork-session`

- exit 1
- stderr: Error: --session-id with --continue or --resume also needs --fork-session.

## 8. `--continue --session-id <S5>`, without `--fork-session`

- exit 1
- stderr: Error: --session-id with --continue or --resume also needs --fork-session.

## 9. The transcripts the runs left

- `~/.claude/projects/<project>/<S2>.jsonl`: 22 lines; sessionId `<S2>`; assistant model capture-main
- `~/.claude/projects/<project>/<S1>.jsonl`: 51 lines; sessionId `<S1>`; assistant model capture-main
- `~/.claude/projects/<project>/<S3>.jsonl`: 30 lines; sessionId `<S3>`; assistant model capture-main
- `~/.claude/projects/<project>/<S6>.jsonl`: 22 lines; sessionId `<S6>`; assistant model capture-main

## 10. Variable names

`strings` over this binary and over the 2.1.329 binary, filtered to `ANTHROPIC_*` and
`CLAUDE_CODE_*`: 1052 names now, 1022 in 2.1.329.

Added since 2.1.329: `CLAUDE_CODE_BRIDGE_CHILD_HELD_TO_AUTO`, `CLAUDE_CODE_CHROME_SIDE_PANEL`, `CLAUDE_CODE_COWORK_SHELL_CHECK`, `CLAUDE_CODE_DISABLE_DESKTOP_SHIP`, `CLAUDE_CODE_DISABLE_POWERSHELL_LIBRARY_LOAD_GUARD`, `CLAUDE_CODE_DISABLE_REDIRECT_CHECK`, `CLAUDE_CODE_DISABLE_REDIRECT_DENY_RECHECK`, `CLAUDE_CODE_DISABLE_RESPONSE_COMPRESSION`, `CLAUDE_CODE_DISABLE_SHIP`, `CLAUDE_CODE_ELEGANT_MIST`, `CLAUDE_CODE_EXTRA_`, `CLAUDE_CODE_FETCH_PERSONAL_CLOUD_CONFIGURATION`, `CLAUDE_CODE_FULL_SIGN_IN_LINK`, `CLAUDE_CODE_HOST_ALLOW_RESETS_DENIAL_STREAK`, `CLAUDE_CODE_HOST_READS_NO_BASH_EDIT_DIFF`, `CLAUDE_CODE_HOST_SHORT_SCRATCHPAD`, `CLAUDE_CODE_HOST_STARTED_AHEAD`, `CLAUDE_CODE_INDEXED_SALAMANDER`, `CLAUDE_CODE_LAZY_WORKTREE`, `CLAUDE_CODE_MODEL_NOBODY_CHOSE`, `CLAUDE_CODE_PROJECTS_FEATURE_FLAGS`, `CLAUDE_CODE_RELAUNCH_BYPASS_SWITCH`, `CLAUDE_CODE_RELAUNCH_SEAT_LAUNCH`, `CLAUDE_CODE_RUNNER_START_NOTES`, `CLAUDE_CODE_SENDS_VIA_SESSION_SERVICE`, `CLAUDE_CODE_SHINY_FOUNTAIN`, `CLAUDE_CODE_SPEND_PROJECT`, `CLAUDE_CODE_STARTER_MAY_HOLD_CONNECTOR_FILE`, `CLAUDE_CODE_STOP_ON_UNUSABLE_PROFILE`, `CLAUDE_CODE_USER_DELEGATED_SESSION_ROUTINE_SERVER_CHECK_PROVIDERS`, `CLAUDE_CODE_USER_DELEGATED_SESSION_SERVER_CHECK_PROVIDERS`

Gone since 2.1.329: `CLAUDE_CODE_MCP_SERVE_MEMORY_WALKS_DEADLINE_MS`

## 11. The minimum version (FR-20)

Not run, and not measured by this script: Claude Code's documentation, "Tool search through
an LLM gateway" (https://code.claude.com/docs/en/mcp#tool-search-through-a-gateway), read
2026-11-25, says Claude Code retries a request without tool search after a 400 or 422 from
v2.1.305 on. That is the version the #399 work pinned, and the rule table's `min_version` for
`claude-code`.

## 12. The options that take a value

Every quoted option definition in the binary (1763 names with the letters), asked of the binary
itself in the throwaway home, with the runs' settings above. A probe of an option the parser
reads ends in a parse error, an unknown option last, so its action never runs:
`<option>=v --zu1` (does it take a value?), `<option> --zu1 --zu2` (is it known, and is a
value required, so that the next argument is read as it whatever it is?), and for a letter
`-L=v --zu1` (is the value optional?). An entry mode the binary takes before its parser gives no
parse error, so its probe runs it, within the time limit; the list below names them. The
launcher reads a launch's arguments with these two lists
(`LLM_CC_OPTS_REQUIRED` and `LLM_CC_OPTS_OPTIONAL`); every other option takes none, and one
Claude Code does not know is its own error, so it starts no session.

Require a value (86): `--add-dir` `--advisor` `--agent` `--agent-color` `--agent-id` `--agent-name` `--agent-type` `--agents` `--allowed-tools` `--allowedTools` `--append-subagent-system-prompt` `--append-subagent-system-prompt-file` `--append-system-prompt` `--append-system-prompt-file` `--attach-serve` `--autocompact` `--betas` `--channels` `--client-data-url` `--correlation-id` `--dangerously-load-development-channels` `--debug-file` `--deep-link-cwd-b64` `--deep-link-last-fetch` `--deep-link-repo` `--disallowed-tools` `--disallowedTools` `--effort` `--environment` `--fallback-model` `--fast-mode` `--file` `--forward-home-settings` `--inherit-permission-mode` `--initialize-fields` `--input-format` `--json-schema` `--lead-verify-key` `--managed-settings` `--max-budget-usd` `--max-thinking-tokens` `--max-turns` `--mcp-config` `--messaging-socket-path` `--metadata` `--model` `--name` `--on-branch` `--output-format` `--parent-session-id` `--permission-mode` `--permission-prompt-tool` `--permission-prompts` `--plan-mode-instructions` `--plugin-dir` `--plugin-dir-no-mcp` `--plugin-url` `--pool` `--prefill` `--prefill-b64` `--proactivity` `--project-config-root` `--ref` `--remote-control-session-name-prefix` `--resume-drops-turn` `--resume-session-at` `--rewind-files` `--runner-declares` `--sdk-url` `--session-began-as-copy` `--session-id` `--setting-sources` `--settings` `--system-prompt` `--system-prompt-file` `--system-prompt-snapshot` `--task-budget` `--team-name` `--teammate-mode` `--thinking` `--thinking-display` `--tools` `--watch-artifact` `--watch-artifact-no-autoreact` `--workload` `-n`

Take an optional value (13): `--cloud` `--debug` `--from-pr` `--prompt-suggestions` `--rc` `--remote` `--remote-control` `--resume` `--teleport` `--worktree` `-d` `-r` `-w`

Take none: 45. Unknown to the main command (a subcommand's, or not an option): 1606.

Handled before the option parser, so that the probe ran them instead of failing to parse (13): `--background` `--bg` `--bg-pty-host` `--bg-spare` `--check-against-schema` `--chrome-native-host` `--claude-in-chrome-mcp` `--computer-use-mcp` `--daemon-worker` `--eval-mock-server` `--gh-standin` `--handle-uri` `--preload`

Unresolved, a probe without the parse error that would settle it (0): none

## 13. `-pr <S1>` and `-pr<S1>`

A letter that takes a value takes the next argument, or the rest of its cluster: `-pr <S1>` is
`-p -r <S1>`, and `-pr<S1>` is `-p -r<S1>`.

- exit 0
- result: 'stub-ok'; is_error: False; session_id: `<S1>`
- models in the JSON result (`modelUsage`): capture-main
- stub: POST /v1/messages?beta=true | protocol anthropic-messages | model 'capture-main' | auth {'authorization': 'Bearer capture-planted-credential'}
- stderr: [claude-code:unrecognized_model] {"model":"capture-main","query_source":"sdk"}

- exit 0
- result: 'stub-ok'; is_error: False; session_id: `<S1>`
- models in the JSON result (`modelUsage`): capture-main
- stub: POST /v1/messages?beta=true | protocol anthropic-messages | model 'capture-main' | auth {'authorization': 'Bearer capture-planted-credential'}
- stderr: [claude-code:unrecognized_model] {"model":"capture-main","query_source":"sdk"}

## 14. `--append-system-prompt --resume <S1>`

An option that requires a value takes the next argument whatever it is: `--resume` is the
system prompt here, and `<S1>` the prompt, so the session is a new one, `<S6>`.

- exit 0
- result: 'stub-ok'; is_error: False; session_id: `<S6>`
- models in the JSON result (`modelUsage`): capture-main
- stub: POST /v1/messages?beta=true | protocol anthropic-messages | model 'capture-main' | auth {'authorization': 'Bearer capture-planted-credential'}
- stderr: [claude-code:unrecognized_model] {"model":"capture-main","query_source":"sdk"}

# Capture — Claude Code and the launch-first slice (#479)

Recorded 2026-11-19 on the owner's machine (macOS, bash 3.2.57) with
the installed Claude Code, `claude --version` → `2.1.329 (Claude Code)`.
This is the part of task B1 the launch needs. Not captured here, and
still B1's to do when their slices open: `--session-id` on a new
session, the `--output-format json` model field as evidence, and the
minimum version for the #399 retry.

## 1. What the real binary sends through `--llm`

**Method.** A Python script started two local HTTP servers that answer
`POST /v1/messages` with a minimal Anthropic Messages stream and log
each request's path, `authorization` header, `x-api-key` header and
`model`. It then ran the worktree's launcher, and once plain `claude`,
headless (`-p "Reply with the single word OK." --output-format json
--max-turns 1`) under `env -i` with a throwaway `HOME`, so no real
configuration, login or transcript was involved and no request left
the machine for a model. The catalog in that home named stub A as the
endpoint of three targets: no credential, a bearer credential, an
`x-api-key` credential. The credential variable held the planted value
`capture-planted-credential`.

**Output**, ports and the temporary home shortened:

```
=== 1. --llm open (no credential)
exit: 0
stderr: [claude-code] --llm open: open · capture-main · http://127.0.0.1:<A> (not probed: nothing has checked this model against Claude Code yet)
claude's result: stub-ok | model it reports: ['capture-main']
  request -> stub A (the selected endpoint): POST /v1/messages | authorization='Bearer none' x-api-key=None model='capture-main'

=== 2. --llm bearer (credential as bearer), from a shell carrying another key and a provider switch
exit: 0
claude's result: stub-ok | model it reports: ['capture-main']
  request -> stub A (the selected endpoint): POST /v1/messages | authorization='Bearer capture-planted-credential' x-api-key=None model='capture-main'

=== 3. --llm apikey (credential as x-api-key)
exit: 0
claude's result: stub-ok | model it reports: ['capture-main']
  request -> stub A (the selected endpoint): POST /v1/messages | authorization=None x-api-key='capture-planted-credential' model='capture-main'

=== 4. plain claude: process env names stub A, ~/.claude/settings.json env names stub B
exit: 0
claude's result: stub-ok | model it reports: ['claude-opus-5-5']
  request -> stub B (the endpoint a settings.json env block names): POST /v1/messages | authorization='Bearer capture-token' x-api-key=None model='claude-opus-5-5'

=== 5. the launcher with that settings file present
exit: 3
stderr: [claude-code] --llm open refused: a Claude Code settings file sets a variable this launch must control.
stderr:   Claude Code applies a settings env block over the environment it is started with, so the selection would be undone:
stderr:     <home>/.claude/settings.json: ANTHROPIC_BASE_URL
stderr:   Remove those keys from the env block, then retry.
  (no request reached a stub)
```

Run 2's environment also carried `ANTHROPIC_API_KEY=ambient-key-nobody-
selected`, `CLAUDE_CODE_USE_BEDROCK=1` and `ANTHROPIC_BASE_URL` naming
stub B.

**What it establishes.**

- The variables FR-20 names do what the adapter assumes in 2.1.329: the
  request goes to `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN` arrives
  as `authorization: Bearer …`, `ANTHROPIC_API_KEY` as `x-api-key`, and
  `ANTHROPIC_MODEL` is the `model` of the request.
- A selected launch from a shell configured for something else reaches
  the selected endpoint only: stub B received nothing in run 2, the
  ambient key was not sent, and the Bedrock switch did not redirect the
  session.
- With `auth_header = "none"` the placeholder arrives as
  `Bearer none`, and Claude Code runs.
- **A `settings.json` `env` block overrides the environment `claude` is
  started with**, for the API client itself (run 4: the process
  environment named stub A, the settings file named stub B, and the
  request went to B). This is the question FR-20 left to the capture.
  The adapter therefore refuses (run 5).

**What it does not establish.** That a real provider's endpoint works:
the stubs answer one fixed message. Only the main model's request was
observed; no request for the small, fast model was made in a one-turn
headless run, so the alias variables are asserted by the launcher
suite against a stub `claude`, not observed on the wire.

## 2. The variable names

Read from the installed binary (`strings` over
`~/.local/share/claude/versions/2.1.329`, filtered to `ANTHROPIC_*`,
`CLAUDE_CODE_USE_*` and the tuning names). Those the adapter sets or
removes: `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`,
`ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, `ANTHROPIC_DEFAULT_MODEL`,
`ANTHROPIC_DEFAULT_OPUS_MODEL`, `ANTHROPIC_DEFAULT_SONNET_MODEL`,
`ANTHROPIC_DEFAULT_HAIKU_MODEL`, `ANTHROPIC_DEFAULT_FABLE_MODEL`,
`ANTHROPIC_SMALL_FAST_MODEL`, `ANTHROPIC_CUSTOM_HEADERS`,
`CLAUDE_CODE_SUBAGENT_MODEL`, `CLAUDE_CODE_MAX_OUTPUT_TOKENS`,
`CLAUDE_CODE_AUTO_COMPACT_WINDOW`, `CLAUDE_CODE_EFFORT_LEVEL`,
`CLAUDE_CODE_USE_BEDROCK`, `CLAUDE_CODE_USE_VERTEX`,
`CLAUDE_CODE_USE_FOUNDRY`, `CLAUDE_CODE_USE_ANTHROPIC_AWS`,
`CLAUDE_CODE_USE_ANTHROPIC_GOOGLE_CLOUD`, `CLAUDE_CODE_USE_MANTLE`,
`ANTHROPIC_BEDROCK_BASE_URL`, `ANTHROPIC_BEDROCK_MANTLE_BASE_URL`,
`ANTHROPIC_VERTEX_BASE_URL`, `ANTHROPIC_FOUNDRY_BASE_URL`,
`ANTHROPIC_AWS_BASE_URL`, `ANTHROPIC_GOOGLE_CLOUD_BASE_URL`,
`CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS`, `ENABLE_TOOL_SEARCH`,
`DISABLE_FEEDBACK_COMMAND`.

Present in the binary and left alone, because what they do was not
established: `CLAUDE_CODE_USE_GATEWAY`, `ANTHROPIC_UNIX_SOCKET`.

A name in a binary says the variable exists, not what it does. The
meaning of the base URL, the two credentials and the model is shown by
section 1. The Opus, Sonnet, Haiku and small-fast alias variables and
`CLAUDE_CODE_MAX_OUTPUT_TOKENS` are the ones this repository's recipes
already export (`docs/dgx-spark/setup-cookbook.md`); the subagent,
effort and auto-compact variables are the ones the owner's own
per-provider file exported. The Fable alias and the provider switches
are taken by name. None of these was observed on the wire here.

## 3. A launch without `--llm` is unchanged

**Method.** Master's launcher (`git show origin/master:adapters/
claude-code/claude-code`, at `7186ff3`) and the worktree's were each
run under `env -i` with a stub `claude` that records its argv and
whole environment, a stub cmux and a stub tmux, from a shell carrying
`ANTHROPIC_BASE_URL`, `ANTHROPIC_API_KEY`, `CLAUDE_CODE_USE_BEDROCK`
and `CLAUDE_CODE_EFFORT_LEVEL`. Timestamps and the launcher's own path
were normalized; three things were compared per case.

```
headless     out     identical  (11 lines)
headless     claude  identical  (16 lines)
headless     mux     identical  (0 lines)
resume       out     identical  (11 lines)
resume       claude  identical  (16 lines)
resume       mux     identical  (0 lines)
inpane       out     identical  (20 lines)
inpane       claude  identical  (23 lines)
inpane       mux     identical  (0 lines)
intmux       out     identical  (19 lines)
intmux       claude  identical  (17 lines)
intmux       mux     identical  (0 lines)
typedcmux    out     identical  (19 lines)
typedcmux    claude  identical  (0 lines)
typedcmux    mux     identical  (1 lines)
typedtmux    out     identical  (19 lines)
typedtmux    claude  identical  (0 lines)
typedtmux    mux     identical  (1 lines)
version      out     identical  (2 lines)
version      claude  identical  (16 lines)
version      mux     identical  (0 lines)
differences: 0
```

`out` is what the launcher printed, `claude` what the stub received,
`mux` what was typed into cmux or given to tmux. The cases: a headless
`-p` run; `--resume <id> -p`; inside cmux with `--peer-review` and
`--continue`; inside tmux with a forwarded flag; a new cmux workspace
with peer review and `--review-max-rounds`; a new tmux session;
`--version`. The help text differs by the `--llm` lines only.

This comparison is not in the suite: CI checks out shallowly, so
master's launcher is not available there. The suite asserts the same
property against the planted variables and proves the assertions with
a mutated launcher.

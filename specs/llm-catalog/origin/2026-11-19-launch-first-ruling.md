# Origin record — the launch-first ruling (#479)

Recorded 2026-11-19 from the owner's messages in the build session of
that date and from what was observed on the owner's machine that
evening. Quotations are the owner's words; everything else is a fact
observed in the tree, on GitHub or on the machine.

## What happened

- A shell startup file sourced a per-provider env file that exported
  `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_MODEL`, the
  three `ANTHROPIC_DEFAULT_*_MODEL` aliases, `CLAUDE_CODE_SUBAGENT_MODEL`,
  `CLAUDE_CODE_EFFORT_LEVEL` and `CLAUDE_CODE_AUTO_COMPACT_WINDOW` into
  every shell.
- Every Claude Code session started from any shell was routed to that
  provider. The `Opus`, `Sonnet` and `Haiku` aliases were remapped, so
  only `Fable` (the one alias the file did not remap) still named an
  Anthropic model in the picker. Resuming a session made with Anthropic
  models failed, because it was sent to the other provider.
- A different session answered with "unset these variables in this
  terminal". The owner rejected that.
- `adapters/claude-code/claude-code` had no provider or model option; its
  only gateway-related code was the #399 notice, whose comment defers
  applying the variables "to an explicit per-launch selector (#400)".
- #400's spec bundle was approved on 2026-11-10 and merged as PR #444 on
  2026-11-11. GitHub records #400 as closed by that PR
  (`closedByPullRequestsReferences: [444]`). Nothing in the bundle was
  built: no `scripts/llm-cli.sh`, no `scripts/lib/llm-*.sh`, no slice
  issue.

## The owner's words

The request:

> URGENTLY ASAP - Find the solution of how I can easy switch b/w
> Anthropic models and others (DeepSeek, local ones - Ollama, vLLM,
> OpenAI); the curennt approach of setting this globally in environment
> is unacceptable and harmful

> I don't want to set and unset env, I want a freedom of selecting which
> model to use with AI Harness

What was put to the owner: remove the one startup-file line, and build
the launch part of #400 first, namely `--llm <id>` on `claude-code` and
`cct start`, `cct llm list` and `cct llm validate`, and
`~/.cct/llms.toml`, with this usage:

```
cct start --llm deepseek ~/proj      # this session only
cct start --llm ollama-qwen ~/proj
cct start --llm anthropic ~/proj     # native Anthropic, even from a dirty shell
cct start ~/proj                     # unchanged
cct llm list
```

and with this stated plainly: "That differs from the approved order,
which builds the catalog infrastructure before any launch works.
Compatibility probes, session stamps, the Codex/Pi/Kiro launchers,
Studio and routing would follow later."

The owner's confirmation question and ruling:

> Confirming, you recommend to remove .env settings, and instead -
> finalize the in-progress feature to specify LLM on the session start?

> ok, let's do this

## What the ruling covers, and what it does not

Covered: building the Claude Code launch before the rest of slice A; a
target for Anthropic by Claude Code's own login; deferring probes,
stamps, the other launchers, Studio and routing.

Not ruled individually: the implementation choices this slice had to
make where the approved text was silent or, read literally, would not
produce a working launch. Each is listed in spec.md, "Launch-first
slice", for the owner's review with the PR.

# Anthropic Agent Teams (experimental, advanced option)

Claude Code v2.1.32+ has an experimental feature called **Agent Teams** that coordinates multiple Claude Code sessions on the same machine via a shared task list and mailbox at `~/.claude/teams/`. **Disabled by default**; enable with `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`.

**Use only when all of these apply:**

- The task genuinely benefits from cross-teammate dialogue (e.g., competing-hypotheses debugging, parallel reviewers comparing notes), not just parallel execution.
- Each teammate's work is independent and heavy enough that summarizing back to a lead would lose important context.
- You can afford significantly higher token cost — approximately 7× when teammates run in plan mode (per Anthropic's cost docs). Actual cost depends on teammate count and mode.
- You don't need `/resume` or `/rewind` mid-team — neither restores in-process teammates.

**Don't use for routine multi-file feature builds.** The single-session subagent pattern in `agent-team-protocol` is cheaper, recoverable, and produces equivalent results for the common case.

**Limitations:** one team per session, lead is fixed for the team's lifetime, no nested teams, split panes don't work in VS Code's integrated terminal / Windows Terminal / Ghostty.

---
name: opus-4-7-features
description: "Optional guidance for sessions using Claude Opus 4.7: adaptive thinking, xhigh effort, prompt caching, /btw side questions."
---

# Opus 4.7 Features & Optimization

Optional guidance for sessions using Claude Opus 4.7 (v2.1.111+). Load this rule when you want to leverage Opus 4.7-specific capabilities.

## Adaptive Thinking (Breaking Change)

Opus 4.7 changes the API contract for extended thinking. The legacy form is **rejected**:

- `thinking: {type: "enabled", budget_tokens: N}` → returns **400 Bad Request** on Opus 4.7.
- Only `thinking: {type: "adaptive"}` is accepted.

With adaptive thinking, the model dynamically decides **when** and **how much** to think based on query complexity. There is no fixed token budget — Claude self-regulates depth.

**How to control depth:**

- Use the `effort` parameter (`xhigh` / `high` / `medium` / `low`) instead of `budget_tokens`.
- Thinking is also promptable in-message:
  - "Think carefully and step-by-step" → encourages deeper reasoning.
  - "Prioritize responding quickly" → encourages a shorter thinking pass.

**Older models:** `enabled`/`budget_tokens` is **deprecated** on Opus 4.6 and Sonnet 4.6 (still functional today, but on the way out). Migrate to `adaptive` proactively so your code keeps working when the deprecation lands.

## Effort Level: `xhigh`

Opus 4.7 introduces a new effort level `xhigh` between `high` and `max`. Other models fall back to `high` when `xhigh` is requested.

| Effort | When to use | Phase fit |
|--------|-------------|-----------|
| `low` | Quick lookups, file searches, trivial edits | — |
| `medium` | Standard implementation, build tasks | Build |
| `high` | Architecture, planning, detailed review | Research, Plan, Review |
| `xhigh` | Complex multi-file reasoning, deep architectural analysis, hard debugging | Plan (large features), Review (cross-cutting PRs) |

**Availability:** `xhigh` became selectable in Claude Code **v2.1.111+** when running Opus 4.7.

**Default change:** From Claude Code **v2.1.117+**, `xhigh` is the **default** effort level for Opus 4.7. On v2.1.111–v2.1.116 the default is still `high` and you must opt in with `/effort xhigh`. Other models continue to default to `high` regardless of Claude Code version.

Set per-session with `/effort <level>` (opens an interactive slider if called without arguments). Persist across sessions with the `effortLevel` setting in `settings.json`.

Use `xhigh` when the task requires reasoning across many files or making subtle architectural judgments. Drop to `high` or `medium` for routine work — `xhigh` trades speed for depth.

## Auto Mode

Auto mode is now GA — no longer requires `--enable-auto-mode`. A permission classifier handles tool approval automatically: safe read-only actions run without interruption, risky or destructive actions get blocked.

**When to use:** trusted repos where you are the sole developer and want minimal friction.

**When NOT to use:** unfamiliar repos, shared machines, or when onboarding to a new codebase where you want to see what the agent is doing.

**Configuration:** customize the classifier with the `autoMode` setting:

```json
{
  "autoMode": {
    "environment": ["Trusted personal repo, no production access"],
    "allow": ["Run tests", "Read any file", "Search codebase"],
    "soft_deny": ["Delete files", "Modify CI configuration"]
  }
}
```

The `environment` array gives the classifier context about the workspace. `allow` and `soft_deny` are prose rules — the classifier interprets them, not pattern-matches them.

## Cloud Commands

### `/ultrareview` — Parallel multi-agent code review

Runs a comprehensive code review in the cloud using parallel analysis agents. Results are synthesized into a single review.

- `/ultrareview` — review current branch vs base
- `/ultrareview 42` — review GitHub PR #42

Use for: complex PRs, cross-cutting changes spanning many files, or when you want a second opinion beyond the local `/review` agent.

### `/ultraplan` — Cloud-based planning

Drafts a plan in the cloud, opens a web editor for review and commenting, then runs it remotely or pulls it back local. Auto-creates a cloud environment on first run.

Use for: large feature planning that benefits from cloud compute, or collaborative review of the plan before execution.

## Permission Friction Reduction

### `/less-permission-prompts`

Scans your recent transcripts for common read-only Bash and MCP tool calls, then proposes a prioritized allowlist for `.claude/settings.json`. Run this after a few sessions to reduce approval friction on safe operations you use repeatedly.

### Bash improvements (v2.1.111+)

These no longer trigger permission prompts:
- Read-only bash commands with glob patterns (e.g., `ls *.ts`)
- Commands starting with `cd <project-dir> &&`

## Prompt Caching

### `ENABLE_PROMPT_CACHING_1H`

Set this environment variable to enable 1-hour prompt cache TTL (default is 5 minutes). Useful for long multi-phase sessions where the system prompt and early context stay warm across many turns.

```bash
export ENABLE_PROMPT_CACHING_1H=1
```

Or set in `settings.json`:

```json
{
  "env": {
    "ENABLE_PROMPT_CACHING_1H": "1"
  }
}
```

The 5-minute TTL is fine for short tasks. Use 1-hour when a session will span 30+ minutes with the same context.

### Caching Awareness

Per Anthropic's April 30 2026 guidance, prompt caching is the single most important optimization for Claude Code workflows — but adaptive thinking interacts with it in ways worth knowing:

- **Switching between `adaptive` and `enabled`/`disabled` thinking modes breaks cache breakpoints for messages.** System prompts and tool definitions remain cached, but per-message cache hits are lost.
- **Pick one thinking mode per session and stay with it.** Toggling mid-session quietly halves cache effectiveness.
- For long sessions on Opus 4.7, the recommended profile is: `adaptive` thinking + `ENABLE_PROMPT_CACHING_1H=1` + a single sustained `effort` level.

## Session Continuity

### Session recap (`/recap`)

When you return to a session after being away, Claude shows a one-line recap of what was happening. Enable with `/config` or the `awaySummaryEnabled` setting. Invoke manually with `/recap`.

Useful for multi-session workflows where you context-switch between projects.

### Monitor tool

The Monitor tool streams background events (stdout lines from a process) into the conversation. Claude can tail logs, watch builds, and react to events in real time.

Use for: tailing a dev server during UI work, watching a long build or test suite, or monitoring a background process you just started.

## CLI Facts (September 2026)

Version-gated Claude Code facts from the v2.1.269–v2.1.273 releases. These are CLI behaviour, not tied to a model. Each gate is taken from the Claude Code changelog.

### `/output-style [name]` (v2.1.269+)

Lists the available output styles, or switches to the named one. Works over Remote Control and in cloud and other headless sessions.

### Bash edit diffs (v2.1.269+)

When the Bash tool handles file edits, the tool result includes a diff of the files the command changed. Controlled by the `bashEditDiffEnabled` setting.

### MCP disconnect notice (v2.1.273+)

When an MCP server disconnects mid-session and automatic reconnection gives up, Claude Code shows a notification pointing at `/mcp`.

### Per-command network hosts in auto mode (v2.1.271+)

In auto mode with sandboxing, Bash, PowerShell and Monitor calls carry a per-command `allowed_domains`: the hosts a command needs are reviewed with it and opened for that command alone; other hosts are refused.

### Subagent frontmatter

Only `omitClaudeMd` is new in this window. The other fields are older and are listed with their real gates because this project now uses one of them.

| Field | Since | Notes |
|-------|-------|-------|
| `memory` | v2.1.33 | `user`, `project` or `local` persistent memory scope. |
| `isolation: worktree` | v2.1.50 | Runs the subagent in a temporary git worktree. |
| `effort` | v2.1.78 | `low` / `medium` / `high` / `xhigh` / `max`; overrides the session level while the subagent runs. The changelog entry names plugin-shipped agents; the sub-agents reference lists the field for every agent file. **Before v2.1.267 it was ignored on models whose default effort is pinned (Opus 4.7, Opus 4.8, Fable 5).** |
| `maxTurns` | v2.1.78 | From v2.1.246 a subagent that stops at the limit returns output marked partial and can be continued. |
| `omitClaudeMd` | v2.1.271 | Launches the subagent without user, project and local `CLAUDE.md` files; managed policy files still load. |

**This project's agents set `effort` in their own frontmatter** (`~/.claude/agents/*.md`). That value governs the subagent; read it there rather than from any prose. An unrecognised frontmatter key did not stop an agent from loading on v2.1.278 (tested); older versions were not tested.

**`omitClaudeMd` is declined on purpose for the shipped agents.** It suits a narrow worker that takes everything from its delegation prompt, such as a log scanner. `security-review` and `code-simplifier` exist to apply the project's coding standards, and silently dropping those conventions is the failure this harness prevents. The omission is a decision, not an oversight (issue #363).

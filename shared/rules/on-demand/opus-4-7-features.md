# Opus 4.7 Features & Optimization

Optional guidance for sessions using Claude Opus 4.7 (v2.1.111+). Load this rule when you want to leverage Opus 4.7-specific capabilities.

## Effort Level: `xhigh`

Opus 4.7 introduces a new effort level `xhigh` between `high` and `max`. Other models fall back to `high` when `xhigh` is requested.

| Effort | When to use | Phase fit |
|--------|-------------|-----------|
| `low` | Quick lookups, file searches, trivial edits | — |
| `medium` | Standard implementation, build tasks | Build |
| `high` | Architecture, planning, detailed review | Research, Plan, Review |
| `xhigh` | Complex multi-file reasoning, deep architectural analysis, hard debugging | Plan (large features), Review (cross-cutting PRs) |

Set per-session with `/effort xhigh` (opens interactive slider if called without arguments). Persist across sessions with the `effortLevel` setting in `settings.json`.

Use `xhigh` when the task requires reasoning across many files or making subtle architectural judgments. Do not default to `xhigh` for routine work — it trades speed for depth.

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

## Session Continuity

### Session recap (`/recap`)

When you return to a session after being away, Claude shows a one-line recap of what was happening. Enable with `/config` or the `awaySummaryEnabled` setting. Invoke manually with `/recap`.

Useful for multi-session workflows where you context-switch between projects.

### Monitor tool

The Monitor tool streams background events (stdout lines from a process) into the conversation. Claude can tail logs, watch builds, and react to events in real time.

Use for: tailing a dev server during UI work, watching a long build or test suite, or monitoring a background process you just started.

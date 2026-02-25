# Code Copilot Team — Enhancement Plan

## Research Summary

### Ralph Loop (Ralph Wiggum Technique)
A single-agent autonomous loop that repeatedly feeds a task prompt to a coding agent until completion. Named after the Simpsons character. Core pattern: `while true; do cat PROMPT.md | claude -p; done`. Each iteration reads a PRD/plan, picks the next incomplete task, implements it, runs tests, commits if passing, and appends learnings to a progress file. Claude Code ships an official plugin at `plugins/ralph-wiggum/` that uses a Stop hook to intercept exit and re-feed the prompt. Key components: PRD file (scoped stories), progress.txt (append-only learnings), `--max-iterations` safety limit, and a `--completion-promise` signal.

### Boris Cherny's Workflow (Claude Code Creator)
Surprisingly minimal customization. Key patterns: (1) Subagents for repeatable workflows — `code-simplifier` (post-cleanup) and `verify-app` (end-to-end testing). (2) PostToolUse hook for auto-formatting (handles the last 10%). (3) `/permissions` to pre-allow safe bash commands instead of `--dangerously-skip-permissions`. (4) MCP integrations (Slack, BigQuery, Sentry). (5) For long tasks: background verification agents, Stop hooks, or ralph-wiggum plugin. (6) Runs 5+ parallel sessions with system notifications. Most important tip: "Give Claude a way to verify its work — it 2–3x the quality."

### Claude Code Hooks & Subagents (Current Capabilities)
**Hooks:** 17 event types (PreToolUse, PostToolUse, Stop, SubagentStart/Stop, SessionStart/End, Notification, etc.). Three hook types: `command` (shell), `prompt` (single LLM call), `agent` (multi-turn with tools). Configured in `~/.claude/settings.json` (global) or `.claude/settings.json` (project). Stop hooks can force continuation. PreToolUse hooks can block/allow/modify tool inputs.

**Subagents:** Defined as markdown + YAML frontmatter in `~/.claude/agents/` (user) or `.claude/agents/` (project). Support `context: fork` for isolation. Can specify tool restrictions and custom models. Built-in types: Explore (read-only), Plan, general-purpose.

**Plugins:** Bundled collections of commands, hooks, agents, and skills in a git repo. Installed via `/install-plugin`.

---

## Enhancement Plan

### Phase 1: Ralph Loop Integration

**Goal:** Add Ralph Loop support as a configuration option alongside the existing three-phase workflow.

#### 1.1 — Ralph Loop Rule File
**File:** `claude_code/.claude/rules/ralph-loop.md`

Contents:
- When to use Ralph Loop vs three-phase team workflow (decision matrix)
- Ralph Loop works best for: well-defined tasks with verifiable completion, greenfield features with test suites, tasks expecting 10+ iterations
- Three-phase team works best for: complex multi-domain features, tasks needing human design decisions, projects without automated test suites
- Hybrid: use Ralph Loop inside Phase 2 (Build) — the Team Lead delegates a task to a sub-agent running in a Ralph Loop

#### 1.2 — Ralph Loop Slash Command
**File:** `claude_code/.claude/commands/ralph-start.md`

A guided command that:
- Accepts a task description and completion criteria
- Generates a scoped PRD (or reads from an existing one)
- Sets iteration limits based on task complexity
- Launches the loop with proper safety guards
- References the official `ralph-wiggum` plugin under the hood

#### 1.3 — PRD and Progress Templates
**File:** `claude_code/docs/ralph-loop-guide.md`

Contents:
- PRD format (JSON with user stories, each with `passes: boolean`)
- Progress file conventions (append-only, structured entries)
- Prompt writing best practices (clear completion criteria, incremental goals, TDD-driven, escape hatches)
- Example: single-feature Ralph Loop, multi-story Ralph Loop
- Safety: always use `--max-iterations`, stuck detection, when to abort

#### 1.4 — Update `agent-team-protocol.md`
Add a section: "Single-Agent Loop Mode" — explaining that the three-phase workflow can run with a single agent in loop mode during Build, and when to choose this over team delegation.

---

### Phase 2: Hooks

**Goal:** Ship a curated set of hooks that enforce the repo's existing rules deterministically.

#### 2.1 — Pre-Build Verification Hook (PostToolUse)
**File:** `claude_code/.claude/hooks/verify-after-edit.sh`
**Config:** `.claude/settings.json` PostToolUse matcher `Edit|Write`

What it does:
- After any file edit, checks if the edited file is in a source directory
- If so, runs the project's type checker and linter (auto-detected: `tsc`, `mypy`, `go vet`, `mvn compile`)
- Exits 2 with feedback if checks fail, so Claude auto-corrects
- Implements the `pre-build-verification.md` rule deterministically instead of relying on the LLM to remember

#### 2.2 — Auto-Format Hook (PostToolUse)
**File:** `claude_code/.claude/hooks/auto-format.sh`
**Config:** `.claude/settings.json` PostToolUse matcher `Edit|Write`

What it does:
- Runs the project's formatter (Prettier, Black, gofmt, google-java-format — auto-detected)
- Boris Cherny's approach: handle the last 10% of formatting automatically
- Prevents formatting nits from cluttering review

#### 2.3 — Protected Files Hook (PreToolUse)
**File:** `claude_code/.claude/hooks/protect-files.sh`
**Config:** `.claude/settings.json` PreToolUse matcher `Edit|Write`

What it does:
- Blocks edits to `.env`, `*.lock`, `.git/`, credentials files
- Implements `safety.md` rule deterministically
- Returns denial reason so Claude adjusts approach

#### 2.4 — Session Context Re-injection Hook (SessionStart)
**File:** `claude_code/.claude/hooks/reinject-context.sh`
**Config:** `.claude/settings.json` SessionStart matcher `compact`

What it does:
- After compaction, re-injects critical context: current phase, active PRD items, recent git log
- Prevents the "context amnesia" problem identified in session-splitting.md
- Outputs to stdout so Claude receives it as context

#### 2.5 — Notification Hook (Notification)
**File:** `claude_code/.claude/hooks/notify.sh`
**Config:** `~/.claude/settings.json` Notification matcher `*`

What it does:
- Sends desktop notifications when Claude needs input (macOS + Linux)
- Essential for multi-session parallelism (Boris runs 5+ sessions)
- Cross-platform: osascript on macOS, notify-send on Linux

#### 2.6 — Stop Verification Hook (Stop)
**File:** `claude_code/.claude/hooks/verify-on-stop.sh`
**Config:** `.claude/settings.json` Stop hook

What it does:
- When Claude finishes, runs the dev server / test suite as a final check
- If tests fail, feeds failure back so Claude continues fixing
- Checks `stop_hook_active` to prevent infinite loops
- Implements Boris's key insight: "Give Claude a way to verify its work"

#### 2.7 — Hooks Documentation
**File:** `claude_code/docs/hooks-guide.md`

Contents:
- Which hooks ship with Code Copilot Team and what each does
- How to customize (add/remove/modify via `/hooks` or `.claude/settings.json`)
- Hook precedence: project `.claude/settings.json` > global `~/.claude/settings.json`
- How to write your own hooks (input JSON, exit codes, matchers)

---

### Phase 3: Subagents

**Goal:** Ship reusable subagent definitions that implement the specialist roles from the existing templates.

#### 3.1 — Code Simplifier Agent
**File:** `claude_code/.claude/agents/code-simplifier.md`

Inspired by Boris's setup. Runs after Claude finishes a feature:
- Reviews generated code for unnecessary complexity
- Removes dead code, simplifies conditionals, extracts repeated patterns
- Read-only analysis + targeted edits
- Tools: Read, Grep, Glob, Edit

#### 3.2 — Verification Agent
**File:** `claude_code/.claude/agents/verify-app.md`

End-to-end verification specialist:
- Runs full test suite, type checks, linter
- Starts dev server, checks for console errors
- Verifies no regressions from recent changes
- Reports pass/fail with specific failure details
- Tools: Bash, Read, Grep

#### 3.3 — Security Review Agent
**File:** `claude_code/.claude/agents/security-review.md`

Checks for common security issues:
- Hardcoded secrets, credentials in code
- Missing input validation
- Unsafe SQL/queries
- Exposed debug endpoints
- Tools: Read, Grep, Glob (read-only)

#### 3.4 — Documentation Agent
**File:** `claude_code/.claude/agents/doc-writer.md`

Generates/updates documentation after feature work:
- Updates README if API changed
- Generates JSDoc/docstrings for new functions
- Updates CHANGELOG
- Tools: Read, Grep, Glob, Edit, Write

#### 3.5 — Phase Recap Agent
**File:** `claude_code/.claude/agents/phase-recap.md`

Runs at end of each phase to generate the handoff document:
- Summarizes what was built, what changed, what's left
- Generates the phase recap using `phase-recap-template.md`
- Writes to `docs/phase-X-recap.md`
- Context: fork (isolated, doesn't pollute main session)

#### 3.6 — Subagents Documentation
**File:** `claude_code/docs/subagents-guide.md`

Contents:
- What ships with Code Copilot Team and when each agent auto-triggers
- User vs project scope (`~/.claude/agents/` vs `.claude/agents/`)
- How to create custom agents (frontmatter format, tool restrictions)
- Agents vs skills vs hooks: decision guide
- Cost optimization (Haiku for review agents, Sonnet for implementation)

---

### Phase 4: Copilot Agent Builder (Future)

**Goal:** Automated configuration generation and session-over-session learning.

#### 4.1 — Project Analyzer
A command/skill that scans a project and recommends the optimal template:
- Detects stack (package.json, requirements.txt, pom.xml, go.mod)
- Counts source files and estimates complexity
- Suggests template + agent team composition
- Generates a project-specific CLAUDE.md

#### 4.2 — Session Monitor
With user permission, observes sessions and tracks:
- Which rules triggered and how often
- Where agents struggled (retry count, context resets)
- Token spend per phase
- Patterns leading to rework
- Outputs a session report to `docs/session-reports/`

#### 4.3 — Rule Refiner
End-of-session agent that reviews the conversation and suggests rule updates:
- Identifies new failure patterns not covered by existing rules
- Proposes specific rule additions or modifications
- Implements the "virtuous cycle" of self-improving conventions
- Can auto-append to rules files with user approval

---

## Implementation Priority

| Priority | Item | Effort | Impact |
|----------|------|--------|--------|
| P0 | 2.5 Notification hook | Small | High — enables multi-session |
| P0 | 2.6 Stop verification hook | Small | High — Boris's #1 tip |
| P0 | 2.1 Pre-build verification hook | Medium | High — deterministic rule enforcement |
| P1 | 3.1 Code simplifier agent | Small | Medium — post-build quality |
| P1 | 3.2 Verification agent | Medium | High — end-to-end checks |
| P1 | 1.1 Ralph Loop rule | Small | Medium — supports single-agent users |
| P1 | 2.2 Auto-format hook | Small | Medium — eliminates formatting noise |
| P1 | 2.3 Protected files hook | Small | Medium — deterministic safety |
| P2 | 1.2 Ralph Loop slash command | Medium | Medium — guided loop setup |
| P2 | 1.3 Ralph Loop guide doc | Small | Medium — reference material |
| P2 | 2.4 Context re-injection hook | Medium | Medium — compaction recovery |
| P2 | 3.3 Security review agent | Small | Medium — automated security |
| P2 | 3.4 Documentation agent | Small | Low — nice to have |
| P2 | 3.5 Phase recap agent | Small | Medium — automates handoff |
| P3 | 4.1 Project analyzer | Large | High — cold-start elimination |
| P3 | 4.2 Session monitor | Large | High — data collection |
| P3 | 4.3 Rule refiner | Large | High — self-improving system |
| Docs | 1.4 Update agent-team-protocol | Small | Medium |
| Docs | 2.7 Hooks guide | Small | Medium |
| Docs | 3.6 Subagents guide | Small | Medium |

## Suggested First Commit Batch

Start with the three P0 hooks + the two key subagents + the Ralph Loop rule:

1. `hooks/notify.sh` — desktop notifications
2. `hooks/verify-on-stop.sh` — test verification on stop
3. `hooks/verify-after-edit.sh` — type check after edits
4. `agents/code-simplifier.md` — post-build cleanup
5. `agents/verify-app.md` — end-to-end verification
6. `rules/ralph-loop.md` — single-agent loop guidance
7. Update `agent-team-protocol.md` — add single-agent loop mode
8. `docs/hooks-guide.md` — hooks documentation
9. `docs/subagents-guide.md` — subagents documentation

This batch gives users three deterministic hooks (no more relying on the LLM to remember), two reusable agents (Boris's top picks), and Ralph Loop support — covering all three enhancement categories in one release.

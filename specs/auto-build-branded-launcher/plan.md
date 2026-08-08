---
spec_mode: lightweight
feature_id: auto-build-branded-launcher
risk_category: integration
status: draft
date: 2026-08-08
origin:
  issue: https://github.com/gosha70/code-copilot-team/issues/195
  origin_claim: |
    Bug #195: "The autonomous build driver scripts/auto-build-loop.sh
    invokes the generic `claude` binary for its headless build sessions,
    instead of the project's own branded launcher `claude-code`. The PI
    backend already does the right thing — it invokes `pi-code`."
    Expected: driver defaults CCT_CLAUDE_BIN to claude-code; the
    launcher gains a headless passthrough mode (forward -p/--print,
    --output-format, --permission-mode, --max-turns, --resume to claude
    WITHOUT cmux/tmux and without treating -p's value as a path, still
    applying the launcher's config); and an explicit autonomous entry
    (`claude-code build <feature-id> [...]`) so no-human-in-loop intent
    never reaches for --dangerously-skip-permissions. pi-code behavior
    unchanged; backends symmetric.
---
# Plan: branded launcher for autonomous builds (#195)

Three coordinated parts, exactly the issue's proposed fix:

1. **Driver** — `CCT_CLAUDE_BIN` defaults to `claude-code` (symmetry
   with `pi-code`); env override kept. Preflight's `--version` probe and
   error text already name the override.
2. **Launcher headless passthrough** — a pre-parse scan of argv: any
   `-p`/`--print` (before a wrapper subcommand) or `--version` marks the
   invocation headless; ALL args forward verbatim to `claude` via exec
   (no cmux/tmux, no positional consumption, prompt never treated as a
   path). Config parity comes from what the launcher already sets up
   before parsing (BUN_OPTIONS ipv4-first fix, CLAUDE_CMD base) plus the
   project's own .claude/settings.json (permission tier + hooks), which
   headless claude reads from cwd exactly like interactive; the wrapper
   records the invocation in ~/.claude/logs/.
3. **`claude-code build <feature-id> [driver args...]`** — branded
   autonomous entry delegating to `scripts/auto-build-loop.sh` with
   `CCT_PROJECT_DIR=$PWD`. The installed launcher is a COPY, so
   setup.sh bakes the repo checkout path into `CCT_REPO_DIR_DEFAULT` at
   install; resolution order: `CCT_REPO_DIR` env > baked default > walk
   up from cwd; a miss is a hard error naming both remedies.

Tests: new `tests/test-claude-code-launcher.sh` (headless passthrough
with a mock claude, exit-code fidelity, no multiplexer, -p value not a
path, --version passthrough, build delegation argv/env, boundary with
wrapper subcommands, driver default grep); wired into sync-check CI.

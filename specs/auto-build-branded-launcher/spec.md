# Spec: branded launcher for autonomous builds (#195)

## Requirements

- FR-1: With no env overrides, `auto-build-loop.sh` defaults
  `CLAUDE_BIN` to `claude-code` (the branded launcher), symmetric with
  the PI backend's `pi-code`; `CCT_CLAUDE_BIN` still overrides.
- FR-2: `claude-code` supports headless passthrough: an invocation
  containing `-p`/`--print` (before any wrapper subcommand) forwards
  ALL arguments verbatim to `claude` via exec — no cmux/tmux attach, no
  wrapper flag parsing, and the `-p` value is never treated as a
  project path. `--version` passes through the same way.
- FR-3: A headless session inherits the launcher's environment parity:
  the BUN_OPTIONS ipv4-first DNS fix and the CLAUDE_CMD base the
  launcher applies to interactive sessions, plus the project's own
  `.claude/settings.json` (permission tier + hooks) that claude reads
  from cwd; the invocation is recorded in `~/.claude/logs/`.
- FR-4: `claude-code build <feature-id> [driver args...]` delegates to
  `scripts/auto-build-loop.sh` with `CCT_PROJECT_DIR` set to the
  current project — the branded no-human-in-loop entry, so autonomous
  intent never needs `--dangerously-skip-permissions`. The repo is
  resolved via `CCT_REPO_DIR` env, the install-time baked default, or
  walking up from cwd; failure is a hard error naming the remedies.
- FR-5: `pi-code` behavior is unchanged; the two backends invoke their
  branded commands symmetrically.

## Constraints

- No change to `run_pi_session` or any PI adapter surface.
- No new flags on the driver; the launcher's interactive surface
  (subcommands, session backends, peer-review flags) is untouched for
  non-headless invocations.
- stdout of a headless session stays pure claude output (the driver
  parses result JSON from it) — logging must never tee stdout.
- No `--dangerously-skip-permissions` anywhere in the new paths.

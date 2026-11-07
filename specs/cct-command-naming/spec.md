---
feature_id: cct-command-naming
spec_mode: lightweight
status: approved
date: 2026-11-07
origin:
  issue: 410
  transcripts:
    - specs/cct-command-naming/origin/2026-11-07-owner-direction.md
  origin_claim: |
    Starting a harness session should be a visibly CCT action, and every
    CCT command the user types should be spelled `cct`, not
    `code-copilot-team` (owner, 2026-11-07, #410). The provider-profile
    directory move proposed as the issue's third task is a directory,
    not a command, and planning found it is the Pi adapter's whole home;
    it is deferred to its own decision in #410.
---

# Spec: `cct` as the single user-facing command name

## Problem

A user who installs with `./scripts/setup.sh --claude-code` starts
sessions with `claude-code <path>`. That command is the harness launcher
(cmux/tmux session, transcript log, peer-review flags, `build`), but its
name reads as Anthropic's CLI, so the owner did not know they were
"starting within CCT". The front door that does carry the harness name,
`scripts/cct`, is not installed on `PATH` (docs/codespace-tour.md and
docs/llm-routing.md both say so) and cannot start a session.

Plugin installs see the long name instead: commands are
`/code-copilot-team:shape` and agents `code-copilot-team:build`, because
the plugin is named `code-copilot-team` in
`adapters/claude-code/plugin/.claude-plugin/plugin.json` and
`.claude-plugin/marketplace.json`.

## Requirements

- **FR-1 `cct start`.** `scripts/cct` gains `start [path] [launcher
  args…]`. It execs the installed `claude-code` launcher with every
  argument unchanged, found first on `PATH`, then at
  `~/.local/bin/claude-code`. With no launcher installed it exits 2 and
  names the install command. `cct help` documents it; an unknown
  command's "Did you mean" list includes it.
- **FR-2 `cct` on PATH.** `adapters/claude-code/setup.sh` installs
  `~/.local/bin/cct` at every site that installs the launcher (fresh
  install and `--sync`). The shim is a generated two-line script that
  execs `<checkout>/scripts/cct`, with the checkout path baked in the
  same way as the launcher's `CCT_REPO_DIR_DEFAULT` and overridable by
  `CCT_REPO_DIR`. A symlink would not do: `scripts/cct` locates its
  `lib/` from `BASH_SOURCE`, which for a symlink is the link's directory.
  A shim whose checkout has moved or been deleted exits 2 with a message
  naming `CCT_REPO_DIR` and the setup command, never bash's "no such
  file". `cct doctor` reports the `cct` on `PATH`: a warning when there is
  none, a failure when the shim's baked checkout is gone.
- **FR-3 plugin named `cct`.** The plugin and its marketplace entry are
  named `cct`, so plugin components read `/cct:shape` and `cct:build`,
  and the install line is `/plugin install cct@code-copilot-team`. The
  marketplace itself keeps the repository's name.
- **FR-4 docs follow.** README Quick Start and "Your first session" start
  with `cct start`; the two PATH caveats in docs/codespace-tour.md and
  docs/llm-routing.md say the shim is installed by `setup.sh --claude-code`
  and that `./scripts/cct` still works from a checkout; docs/install.md
  uses the new namespace and install line and tells existing plugin users
  how to move. CHANGELOG `[Unreleased]` records all of it.
- **FR-5 tests.** `tests/test-cct-cli.sh` covers FR-1 with a mock
  launcher. `tests/test-claude-code-launcher.sh` covers FR-2 by running
  the shim installer against a throwaway HOME. A release-readiness check
  asserts the plugin and marketplace names agree and equal `cct`.

## Constraints

- `claude-code` keeps working unchanged; it remains the adapter id for
  `setup.sh --claude-code` and the Pi adapter keeps `pi-code`.
- No new dependency; bash and python3 as today.
- `scripts/cct` from a checkout without an installed launcher must not
  silently run the repository's own launcher copy: that would start a
  session without the installed rules.
- Component counts: any assertion count that moves updates
  `tests/test-counts.env` and `docs/repo-structure.md` in the same commit.
- One PR, one commit per phase, off `origin/master` in a worktree; no
  push without the owner's review.

## Out of scope

- Moving `~/.code-copilot-team/` (the provider profile and the Pi
  adapter's home) to `~/.cct/`. Deferred in #410 with the planning
  finding; it is a migration, not a command rename.
- A `cct start --pi` or `cct start --codex` form. The owner's session is
  Claude Code; other harnesses keep their launchers.
- Renaming the GitHub repository, the marketplace, the `CCT_*`
  environment prefix, or the `code-copilot-team-pi` package.

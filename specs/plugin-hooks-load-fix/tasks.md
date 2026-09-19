# Tasks: make the shipped plugin's hooks loadable

| # | Task | File(s) | Done |
|---|------|---------|------|
| 0 | Plan approval; authorization for the two haiku runs (T1, T4) | `plan.md` | [x] |
| 1 | Runtime "before" run, plugin unmodified (FR-6) | scratchpad only | [x] |
| 2 | `"hooks"` wrapper; quote `${CLAUDE_PLUGIN_ROOT}`; version 1.0.1 (FR-1..FR-3) | `adapters/claude-code/plugin/hooks/hooks.json`, `.../.claude-plugin/plugin.json` | [x] |
| 3 | Plugin hooks manifest assertions; count pin 186 → 189 (FR-4) | `tests/test-hooks.sh`, `tests/test-counts.env`, `docs/repo-structure.md` | [x] |
| 4 | Runtime "after" run; compare with T1 (FR-6) | scratchpad only | [x] |
| 5 | Gates incl. `claude plugin validate` exit 0 (FR-5) | — | [x] |
| 6 | Origin alignment re-check, then `/review-submit` | — | [ ] |

## Results (2026-09-19, CLI 2.1.278)

**T1, before — classified "written".** The debug log has
`[WARN] Failed to load session plugin ... hooks.json declares
PreToolUse/PermissionRequest at its top level`, every plugin component
count is 0, and `.env` was written. The runtime failure is confirmed:
the whole plugin failed to load, not only its hooks.

**T4, after — classified "blocked by the plugin hook".** The log has
`Loading hooks from plugin: code-copilot-team`, then
`Hook PreToolUse:Write (PreToolUse) error: Blocked: .../.env is a
protected file. Reason: environment config files must not be modified
by agents`, then `Hook denied tool use for Write`; `.env` does not
exist. Caveat: the debug log does not print hook command paths, so the
script is identified by its exact message and by elimination (user
settings excluded, no project settings, same flags as T1), not by path.

Both runs: haiku, `--tools Write`, `--allowedTools "Edit(./.env)"`,
`--max-budget-usd 0.10`, `--setting-sources project`, 120 s tool
timeout (macOS has no `timeout` binary).

**Gates.**

- `claude plugin validate adapters/claude-code/plugin`: exit 0 (one
  warning, missing author — out of scope).
- The two jq assertions exit 1 against master's `hooks.json`.
- `tests/test-hooks.sh`: 152 passed, 37 failed + count line. Untouched
  master: 149 passed, the identical 37 failures (all `protect-git.sh`
  cases on this host). 152 + 37 = 189.
- `tests/test-shared-structure.sh`: 808 passed, 5 failed — identical to
  untouched master (four "installed hooks/… matches adapter/" checks
  against `~/.claude/hooks`, plus the count line they cause).
- `scripts/check-doc-accuracy.sh`: clean. `git diff --check`: clean.

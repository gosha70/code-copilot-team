---
feature_id: plugin-hooks-load-fix
spec_mode: lightweight
status: approved
date: 2026-09-19
issue: "#363 (found during it; separate PR from P1+P2; leaves #363 open)"
origin:
  transcripts:
    - specs/plugin-hooks-load-fix/origin/2026-09-19-owner-direction.md
  user_messages:
    - "2026-09-19: 'Fix the existing plugin first. ... Add the validation gate and verify a harmless protection hook actually fires. ... Also bump the plugin version with the fix.'"
---

# Spec: make the shipped plugin's hooks loadable

## Why

`adapters/claude-code/plugin/hooks/hooks.json` declares its five events
at the top level. The plugin format requires them under a top-level
`"hooks"` key. `claude plugin validate adapters/claude-code/plugin`
exits 1 on CLI 2.1.278:

> hooks: PreToolUse/PermissionRequest is declared at the top level,
> outside the "hooks" object — ... nothing it sits in is applied until
> the entry is fixed or removed

`docs/install.md:62-68` tells users the plugin "installs the same hooks
... as `setup.sh`". No test validates the plugin, and CI has no `claude`
CLI.

## Verified facts (2026-09-19)

| Fact | Source |
|---|---|
| Events must nest under top-level `"hooks"`; the only other documented top-level keys are `$schema` (plugins reference) and `description` (hooks reference) | `code.claude.com/docs/en/plugins-reference`, `code.claude.com/docs/en/hooks` |
| `claude plugin validate` exits 1 on this file | local run, 2.1.278 |
| `plugin.json` `version` pins marketplace installs; without a bump, installed users never see the update | plugins-reference, version section |
| Docs quote `"${CLAUDE_PLUGIN_ROOT}"` in shell-form hook commands; ours is unquoted | plugins-reference |
| The owner's `~/.claude/settings.json` registers the same seven hook scripts (installed by `setup.sh`) | local read, names only |

**Confirmed vs not.** Validation failure: confirmed, by the owner and
here. Runtime failure (hooks silently not loading for a marketplace
install): **not confirmed**. T4 settles it with a before/after run.

## Requirements

- **FR-1** `hooks/hooks.json` nests all five events under `"hooks"`.
  Matchers, commands and timeouts are unchanged, except FR-2.
- **FR-2** `${CLAUDE_PLUGIN_ROOT}` is double-quoted in each command, as
  the docs prescribe, so an install path with a space does not break
  the hook.
- **FR-3** `plugin.json` `version` 1.0.0 → 1.0.1.
- **FR-4** A CLI-independent structure test (runs in CI): top-level keys
  of `hooks.json` are within `{hooks, $schema, description}`; `hooks` is
  an object with at least one event; every script a command references
  exists under the plugin and is executable.
- **FR-5** `claude plugin validate adapters/claude-code/plugin` exits 0.
  Local gate, reported with output; not in CI (no CLI there).
- **FR-6** Runtime proof: in a scratch project with user settings
  excluded (`--setting-sources project`) and the plugin loaded by
  `--plugin-dir`, a write of synthetic content to `.env` is blocked, and
  the debug log identifies the plugin's own `protect-files.sh` as the
  blocker. A block from any other cause (permissions, model refusal) is
  inconclusive, not a pass. Run once before the fix and once after,
  each bounded in tools, budget and time (plan.md).

## Out of scope

Packaging skills, agents or commands into the plugin (step 2). Duplicate
hooks when `setup.sh` and the plugin are both installed (step 2).
`plugin/scripts/verify-after-edit.sh` has drifted 9 lines from the
adapter hook; generating the plugin in step 2 removes the copy, so it is
not reconciled here. `claude plugin eval` (step 3). The author and
description warnings from the validator.

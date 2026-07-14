# Spec: permission profiles for `claude-code init` (+ switch subcommand)

Issue #76. Source material:
`doc_internal/plans/2026-07-08-init-permission-profiles.md` (shaped
2026-07-08). `dontAsk` verified as a real `permissions.defaultMode` that
auto-denies unmatched tool calls without prompting while still honoring
`deny` — https://code.claude.com/docs/en/permission-modes.md

## User Scenarios

- US1: As someone initializing a project I own, I pick a permission tier at
  init (`--permissions balanced`) and get zero prompts for routine repo work
  — with dangerous operations still guarded by `deny` rules and the
  `protect-*` hooks. On a shared or unfamiliar codebase I take `default`
  (today's behavior) and everything still prompts.
- US2: As someone who already ran init (or hand-wrote settings), I switch an
  existing project onto a managed tier with `claude-code permissions
  balanced` instead of maintaining the JSON by hand — and the command never
  clobbers unrelated `settings.json` content.
- US3: As a maintainer, changing a safety boundary is always an explicit act:
  `sync` tells me a project's tier drifted from the profile definition but
  never re-applies it for me, and the `relaxed` (hook-disarming) tier refuses
  to write without an explicit dangerous-confirmation.

## Requirements

Tier selection at init (US1):
- FR-1: `claude-code init <type> [dir] --permissions <default|balanced|relaxed>`
  (default `default`). An unknown tier errors and lists the valid tiers. The
  selected tier is recorded in `.claude/template.json` (`permissions` key) for
  sync/drift.
- FR-1a: When `--permissions` is absent AND stdin is an interactive TTY,
  prompt for the tier with `default` preselected. When there is no TTY
  (scripts/CI), silently use `default` — init must never block automation.

`balanced` tier (US1):
- FR-2: `balanced` writes (jq-merge into, never clobber) `.claude/settings.json`
  with `permissions.defaultMode="dontAsk"`, the profile's `allow` list
  (Read, Glob, Grep, Edit, Write, Bash, WebSearch, WebFetch) and base `deny`
  list (`Read(./.env)`, `Read(./.env.local)`, `Read(./.env.production)`,
  `Bash(rm -rf:*)`, `Bash(sudo:*)`, `Bash(git push --force:*)`,
  `Bash(git reset --hard:*)`), plus any `deny-extras/<type>.json` entries for
  the template type. The merge is idempotent (re-applying adds no duplicates).
  `settings.json` is a project-tracked file (shared with the team on purpose);
  the git-approval `settings.local.json` writes are unchanged.

`relaxed` tier (US3):
- FR-3: `relaxed` = the `balanced` content PLUS an `env` block
  `{"HOOK_GIT_ALLOW":"true","HOOK_PROTECT_ALLOW":"true"}` (disarms
  `protect-git.sh` and `protect-files.sh`), with the `Read(./.env*)` denies
  DROPPED (read-deny + edit-allow is incoherent once protect-files is off) and
  the Bash deny guardrails KEPT. `relaxed` MUST NOT ever write
  `bypassPermissions` (that would skip `deny` too).
- FR-3a: Writing `relaxed` (at init or via the switch subcommand) REQUIRES
  explicit confirmation — `--yes-dangerous`, or an interactive y/N (default N)
  after a loud warning naming exactly what is disarmed. Without confirmation
  the command refuses, exits non-zero, and writes nothing.

Switch on an existing project (US2):
- FR-4: `claude-code permissions <tier> [dir]` applies/switches a tier on an
  existing project using the same jq-merge (never clobber unrelated
  `settings.json` keys) and updates `template.json`. `relaxed` demands the
  same FR-3a confirmation. `permissions default` strips the profile-managed
  keys the tiers add (`permissions.defaultMode`, the managed `allow`/`deny`
  entries, and the `relaxed` `env` vars) and leaves any other `settings.json`
  content intact.

Sync + distribution (US3):
- FR-5: `sync` (project-level) reports permission-profile drift only — the
  recorded tier vs. the current profile definition — and NEVER auto-applies.
  Switching tiers is always explicit (init flag or `permissions` subcommand).
- FR-5a: `setup.sh --sync` copies `adapters/claude-code/permissions/` to
  `~/.claude/permissions/` so the launcher resolves profiles from the synced
  location, matching how templates/skills/agents resolve.

Docs + tests (US1-US3):
- FR-6: `adapters/claude-code/docs/permissions-guide.md` is rewritten around
  the three tiers (recommend `balanced` for personal repos, `default` for
  shared/unfamiliar/high-risk). The per-stack enumerated allow/deny lists stay
  as an appendix WITH an explicit warning that enumeration re-triggers prompts
  on the next unlisted command.
- FR-7: Tests (repo `tests/` shell suite): init each tier into a temp dir and
  assert — `default` writes no `settings.json`; `balanced` writes jq-valid
  `settings.json` with the right `defaultMode`/allow/deny + per-type
  deny-extras; `relaxed` adds the env block, drops the env-read denies, never
  writes `bypassPermissions`, and is refused without `--yes-dangerous`; the
  tier is recorded in `template.json`; the `permissions` subcommand switches
  idempotently and preserves unrelated `settings.json` keys. Counts registered
  in `tests/test-counts.env` and any README suite line.

## Constraints

- Bash 3.2 compatible; jq for JSON; no new dependencies.
- Every `settings.json` write is a jq-merge that never clobbers existing keys
  and is idempotent (mirrors the existing `settings.local.json` pattern).
- No `bypassPermissions` in any tier; the Bash `deny` guardrails are retained
  in every tier including `relaxed`.
- Changing a permission boundary is always explicit: init flag or `permissions`
  subcommand. `sync` never auto-applies (auto-applying a safety boundary is
  rejected as too surprising).
- Profiles live in the repo (`adapters/claude-code/permissions/`) and are
  distributed by `setup.sh --sync`; adapters/generation stay drift-free
  (`generate.sh` + structure tests still pass).
- One issue per PR: this bundle covers exactly #76.

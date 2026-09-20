---
feature_id: plugin-generate-from-sources
spec_mode: lightweight
status: approved
date: 2026-09-19
issue: "#363 (plugin adoption step 2; separate PR; leaves #363 open)"
origin:
  issue: "#363"
  transcripts:
    - specs/plugin-generate-from-sources/origin/2026-09-19-owner-direction-step-2.md
  user_messages:
    - "2026-09-19: 'Package the existing skills, agents and commands from their authoritative sources. ... generate the plugin, don't maintain another authored copy. Keep setup.sh supported, and address duplicate hooks and plugin-namespaced commands when both installation paths coexist. No broad redesign is needed.'"
---

# Spec: generate the plugin's skills, agents and commands from their sources

## Why

The shipped plugin (`adapters/claude-code/plugin/`, fixed in #364)
carries seven hooks and nothing else. The 24 skills, 14 agents and 14
commands reach a user only through `setup.sh`. Its seven hook scripts
are hand-made copies of the adapter hooks, and one has already drifted.
The owner wants the plugin to be a real second install path, generated
from the same sources, with `setup.sh` still supported.

## Verified facts (2026-09-19, CLI 2.1.278)

Sources: `code.claude.com/docs/en/plugins-reference`, local runs.

| Fact | Source |
|---|---|
| A plugin ships `skills/<name>/SKILL.md`, `agents/*.md`, `commands/*.md` (flat files; docs call this form legacy but supported), `hooks/hooks.json` | plugins reference |
| Plugin skills, commands and agents are namespaced: `/code-copilot-team:shape`, `code-copilot-team:build` | plugins reference |
| **A plugin cannot ship always-loaded instructions**: no rules, and a `CLAUDE.md` at the plugin root is not loaded. "To ship instructions that load into Claude's context, put them in a skill." | plugins reference |
| A plugin `settings.json` honours only `agent` and `subagentStatusLine` | plugins reference |
| Plugin agents support `effort`, `model`, `tools`, `skills`, `memory`, `isolation`, `omitClaudeMd`; not `hooks`, `mcpServers`, `permissionMode` (ours use none of those three) | plugins reference |
| Marketplace installs are **copied** to `~/.claude/plugins/cache/…`; paths that leave the plugin root are rejected, and files outside it are not copied | plugins reference |
| `${CLAUDE_PLUGIN_ROOT}` is substituted "anywhere the placeholder appears" in skill and agent content, and exported to hook processes | plugins reference |
| A throwaway plugin holding all 24 skills, 14 agents and 14 commands passes `claude plugin validate` (exit 0). Only warnings: the 14 commands have no frontmatter; no author | local run |
| The plugin's `verify-after-edit.sh` differs from the adapter hook in comments only (stale copy) | local diff |
| CI already runs `scripts/generate.sh` and fails on drift, staging first so new files count | `.github/workflows/sync-check.yml` |
| Commands are authored in `adapters/claude-code/.claude/commands/`; `generate.sh` syncs no commands | `scripts/generate.sh` |

**What depends on files a plugin-only user does not have** (grep over
every command, agent and skill):

- `~/.claude/templates/sdd/…` — commands `shape`, `bet`, `cycle-start`,
  `cooldown`; agents `pitch-shaper`, `scope-executor`, `cycle-retro`,
  `cooldown-report`.
- `~/.claude/skills/<name>/SKILL.md` — agents `build`, `plan`,
  `research`, `review`, `phase-recap`, `pitch-shaper`, `visual-reviewer`.
- `~/.claude/scripts/review-decide.sh` — command `review-decide`.
- `~/.claude/agents/*.md` — command `list-agents`, which would tell a
  plugin-only user they have no agents while the plugin ships 14.
- Project-relative `scripts/*.sh` (`check-origin-alignment.sh`,
  `validate-spec.sh`, `auto-build-loop.sh`, …) — several commands and
  skills. **Not a plugin gap**: a `setup.sh` user is in the same
  position, since `setup.sh` does not install them either.

The four `~/.claude/` directories above are the complete set across
commands and agents.

**Not yet verified; settled at build time (plan.md):** whether a bare
agent name in prose ("the build agent") resolves to
`code-copilot-team:build` for a plugin-only user; what Claude Code does
with same-named skills, commands and agents when both installs exist
(a debug line reads "plugin skills loaded: N (M duplicate/user-owned
entries skipped)", which suggests it de-duplicates); whether
`${CLAUDE_PLUGIN_ROOT}` is substituted in `commands/*.md` bodies as it
is in skills.

## Requirements

- **FR-1** `scripts/generate.sh` gains a "Claude Code plugin" section
  that writes, under `adapters/claude-code/plugin/`: `skills/` from
  `shared/skills/`, `agents/` from the adapter agents (after the
  existing agent sync), `commands/` from the adapter commands,
  `scripts/` for the seven existing hooks from the adapter hooks,
  `templates/sdd/` from `shared/templates/sdd/`, and
  `scripts/review-decide.sh` from `scripts/`.
- **FR-2** In generated agents and commands only, `~/.claude/skills/`,
  `~/.claude/templates/`, `~/.claude/scripts/` and `~/.claude/agents/`
  (and the `$HOME` spelling) become `${CLAUDE_PLUGIN_ROOT}/skills/` etc.
  Nothing else in the body changes. Skills are copied byte-for-byte.
- **FR-3** Nothing under `plugin/` except `.claude-plugin/plugin.json`
  and `hooks/hooks.json` is authored by hand. Generated output is
  committed (a marketplace install clones the repo). Before writing, the
  generator removes the generated subdirectories only — `skills/`,
  `agents/`, `commands/`, `scripts/`, `templates/` — so a deleted source
  stops shipping. It never removes `plugin/` itself, `.claude-plugin/`
  or `hooks/`.
- **FR-4** Coexistence, hooks: when the plugin copy of a **non-safety**
  hook runs and the `setup.sh` copy is installed, the plugin copy exits
  0 so the work is not done twice. `protect-files.sh` and
  `protect-git.sh` carry no such guard: they run twice, by design.
- **FR-5** Coexistence, names: what Claude Code does with same-named
  components is verified and stated in `docs/install.md`. No
  de-duplication logic is written unless the verification shows real
  harm.
- **FR-6** `docs/install.md`, `plugin.json` and `marketplace.json` say
  what the plugin installs and what only `setup.sh` gives: always-loaded
  rules, the global manifest, the launcher, the status line, templates
  for new projects, the peer-review and memkernel hooks.
- **FR-7** Plugin version 1.0.1 → 1.1.0.
- **FR-8** `tests/test-generate.sh` asserts: every source skill, agent
  and command has a plugin copy; skills and hook scripts are identical
  to their sources; **and the reverse: every plugin skill, agent, command
  and script has a source**, so a stale copy fails; no
  `~/.claude/(skills|templates|scripts|agents)` or `$HOME/.claude/(…)`
  remains in plugin agents or commands; the templates and helper are
  present; `plugin.json` and `hooks/hooks.json` survive a generator run.
  `claude plugin validate` exits 0 (local gate).
- **FR-9** Runtime proof with the plugin as the only install
  (`--setting-sources project`, `--plugin-dir`): component counts in the
  debug log match the sources, one namespaced command resolves a
  rewritten path, and one agent is dispatched. Bounded, paid, needs
  authorization.

## Constraints

- One source per component. Generate; never author a second copy.
- `setup.sh` keeps working unchanged for its users, apart from FR-4's
  guard in the shared hook scripts, which is inert without the plugin.
- A safety hook must never be silenced by coexistence logic. Failing
  towards running twice is acceptable; failing towards not running is
  not.
- No broad redesign: the generator copies and applies one path rewrite.
- No paid call without the owner's authorization, each bounded in
  tools, budget and time. No `claude plugin eval` (step 3).
- Nothing is installed into `~/.claude` from the branch.
- Separate PR. It references #363 and leaves it open; no new issue.

## Out of scope

Step 3 (eval). Always-loaded rules through a SessionStart hook (see
plan.md D1). New hooks in the plugin (`peer-review-on-stop`, memkernel).
`userConfig`, MCP servers, a plugin `settings.json`. Frontmatter for the
14 commands (validator warning only). Making project-relative
`scripts/*.sh` available to plugin users. Renaming any skill. The 12
stale agent copies under `claude_code/.claude/agents/`. `cct doctor`
changes. The plugin author warning.

---
spec_mode: lightweight
feature_id: plugin-generate-from-sources
risk_category: infra
justification: |
  One new section in an existing generator that copies files and applies
  one path rewrite, a three-line guard in five hook scripts, tests and
  docs. The plugin format rules come from the plugin reference and the
  validator. FR-1..FR-9 in spec.md state the behaviour; a full bundle
  would restate them.
status: approved
date: 2026-09-19
issue: "#363"
origin:
  issue: "#363"
  transcripts:
    - specs/plugin-generate-from-sources/origin/2026-09-19-owner-direction-step-2.md
  user_messages:
    - "2026-09-19: 'generate the plugin, don't maintain another authored copy. Keep setup.sh supported, and address duplicate hooks and plugin-namespaced commands when both installation paths coexist. No broad redesign is needed.'"
  origin_claim: |
    Package the existing skills, agents and commands into the shipped
    plugin by generating them from their authoritative sources, never a
    second authored copy. Keep setup.sh supported. Address duplicate
    hooks and plugin-namespaced commands when both install paths
    coexist. No broad redesign. Eval is a later, separately authorized
    step and not a prerequisite.
---

# Plan: generate the plugin from its sources

## The shape of it

`scripts/generate.sh` already turns `shared/skills/` and the Claude Code
adapter into the codex, cursor, github-copilot and pi surfaces, and CI
already fails when generated output is stale. The plugin becomes one
more generated surface. Two files stay hand-authored because they are
the plugin's own definition: `.claude-plugin/plugin.json` and
`hooks/hooks.json`.

```
adapters/claude-code/plugin/
  .claude-plugin/plugin.json      authored   (version 1.1.0)
  hooks/hooks.json                authored   (unchanged from #364)
  scripts/<7 hooks>.sh            generated  <- adapters/claude-code/.claude/hooks/
  scripts/review-decide.sh        generated  <- scripts/review-decide.sh
  skills/<24>/SKILL.md            generated  <- shared/skills/            (byte-for-byte)
  agents/<14>.md                  generated  <- adapter agents            (path rewrite)
  commands/<14>.md                generated  <- adapter commands          (path rewrite)
  templates/sdd/*                 generated  <- shared/templates/sdd/
```

The path rewrite (FR-2) is one `sed` expression applied to agents and
commands: `~/.claude/{skills,templates,scripts,agents}/` →
`${CLAUDE_PLUGIN_ROOT}/{skills,templates,scripts,agents}/`. The `agents`
case is `list-agents`, which reads the global agents directory. The pi
adapter already converts commands during generation
(`scripts/pi-convert-command.sh`), so a transform step is not new here.

Like every other generated surface, the section clears its output
first. The trap here is that `plugin/` also holds the two authored
files, so the clean names the five generated subdirectories and nothing
else (FR-3), and a test asserts the authored files survive a run.

## Owner decisions

**Decided by the owner, 2026-09-19:** D1–D4 approved as recommended.
"Address plugin-namespaced commands" means verify and document (FR-5),
confirmed. Build in a `--no-track` worktree. The paid runtime runs were
held until tasks 1–4 and the free gates were done, then authorized the
same day as exactly four probes (results below).

**D1 — the six always-on skills.** `setup.sh` installs
coding-standards, copilot-conventions, copyright-headers,
origin-confirmation, safety and wiki-first-query as always-loaded rules.
A plugin cannot do that. Options:

- (a) **Recommended.** Ship all 24 as ordinary plugin skills. The six
  load when their description matches, not always. Say so plainly in
  `docs/install.md`: the plugin is the quick path, `setup.sh` is the
  full harness, and the two can be combined.
- (b) Inject the six through a SessionStart hook. Not recommended: it
  pushes tens of kilobytes into every session, is new machinery, and is
  the "broad redesign" the owner ruled out.
- (c) Leave the six out of the plugin. Not recommended: the agents and
  commands refer to them.

**D2 — duplicate hooks when both installs exist.** Each event would run
both copies. Recommended: a three-line guard at the top of the five
non-safety hook sources (`auto-format`, `verify-after-edit`,
`verify-on-stop`, `notify`, `reinject-context`):

```
if [[ -n "${CLAUDE_PLUGIN_ROOT:-}" && -x "$HOME/.claude/hooks/$(basename "$0")" ]]; then
  exit 0
fi
```

It only fires for the plugin copy, and only when `setup.sh`'s copy is
installed. `protect-files` and `protect-git` get **no** guard: if
someone has the file on disk but removed the registration from
`settings.json`, a guarded plugin copy would defer to a hook that never
runs. They are fast and deterministic, so running twice costs a
duplicate block message and nothing else. The alternative is
documentation only ("pick one install for hooks"), which leaves
`verify-on-stop` (180 s timeout) and notifications doubled.

**D3 — commands and agents that need templates or a helper script.**
Recommended: ship `templates/sdd/` and `review-decide.sh` inside the
plugin and rewrite the paths (FR-1, FR-2), so every command works for a
plugin-only user exactly as far as it works for a `setup.sh` user. The
alternative, packaging only the self-contained components, drops five
commands and leaves eight agents pointing at paths that do not exist.

**D4 — version 1.1.0.** New components, nothing removed.

## To verify at build time, before relying on it

1. **Bare agent names.** Agents and commands say "the `build` agent" in
   prose; a plugin-only user has `code-copilot-team:build`. If the model
   does not resolve the bare name, the rewrite gains one more rule for
   agent names; if it does, nothing changes. Settled by the FR-9 run.
2. **Same-named components with both installs.** Read the debug log's
   "duplicate/user-owned entries skipped" counts and the slash menu,
   then document what happens (FR-5).
3. **`${CLAUDE_PLUGIN_ROOT}` in `commands/*.md`.** Documented for skill
   and agent content. If it is not substituted in command bodies, the
   four template commands move from `commands/` to `skills/` form, which
   the plugin reference recommends for new plugins anyway.
4. **Context cost** of 24 skill descriptions and 14 agents, from
   `claude plugin details` if it accepts the local plugin, else from the
   debug log. Reported, not optimised.

If 1 or 3 turns out badly **and** the fix is larger than one more
rewrite rule, I stop and bring it back rather than grow the design.

## Runtime proof (FR-9) — needs authorization

Four `claude -p` runs on haiku in the session scratchpad, plugin loaded
by `--plugin-dir`, `--max-budget-usd 0.25` each (**combined configured
budget $1.00, not a guaranteed ceiling**: the cap is checked per
request, so an in-flight request may overrun it), tool timeout 120 s.
Exactly these four runs: no automatic retries or extra runs, nothing
installed, no `claude plugin eval`. Runs 1–3 use
`--setting-sources project` so the owner's installed harness cannot mask
anything:

1. Load only: debug-log component counts equal 24 / 14 / 14 and hooks
   load. No tool use.
2. A namespaced command that reads a template
   (`/code-copilot-team:shape` with a throwaway idea, tools limited to
   Read): the log shows the read resolving under the plugin root.
3. Dispatch one agent by bare name: answers verification item 1.
4. The same load-only run **without** `--setting-sources project`, so
   both installs are present: answers verification item 2.

## Runtime proof — results (2026-09-19, CLI 2.1.278)

Authorized by the owner as exactly four probes. Run once each, no
retries. Actual spend **$0.2973** ($0.0142 + $0.0834 + $0.1148 +
$0.0849) against the $1.00 combined configured budget. Logs stayed in
the session scratchpad; nothing was installed.

| # | Question | Result |
|---|---|---|
| 1 | Do the components load, plugin as the only install? | Yes. Debug log: 24 skills, 14 agents, 14 commands, 0 skipped; 7 hooks registered; no hook errors. Names are `code-copilot-team:<name>`. |
| 2 | Is `${CLAUDE_PLUGIN_ROOT}` substituted in a `commands/*.md` body? (verification 3) | **Yes.** `/code-copilot-team:shape` made the model request the absolute path `<plugin>/templates/sdd/pitch-template.md`. The four template commands stay in `commands/`. |
| 3 | Does a bare agent name resolve? (verification 1) | **Yes.** "Delegate to the build agent" dispatched `subagent_type=code-copilot-team:build`; it replied. No extra rewrite rule. |
| 4 | Same-named components with both installs? (verification 2) | **No de-duplication, no collision.** `shape` and `code-copilot-team:shape`, `build` and `code-copilot-team:build` all listed; "0 duplicate/user-owned entries skipped". No harm beyond double listing, so FR-5 stays documentation only. |

Context cost (verification 4): the plugin's always-listed text (names
and descriptions of 24 skills and 14 agents) is about 6.2 KB, roughly
1,500 tokens. `claude plugin details` only accepts an installed plugin,
so this is measured from the files. Reported, not optimised.

Two things the probes showed that the plan did not predict:

- **Probe 2's Read was denied, not completed.** Headless mode had no
  permission to read outside the project directory, and the plugin
  directory is outside it. The path resolution is proven; the file read
  itself is not. Not rerun (no extra runs were authorized).
  `docs/install.md` states that the usual outside-the-project read
  permission applies.
- **Probe 3 used Sonnet for the subagent** ($0.0213 of its cost): the
  `build` agent's own `model` frontmatter overrides `--model haiku`.

The stop rule did not trigger: neither verification 1 nor 3 needed a
change.

## Deliverables

1. `scripts/generate.sh`: the plugin section (FR-1..FR-3).
2. Five hook sources: the D2 guard (FR-4). Generated copies follow.
3. Generated plugin contents, committed.
4. `plugin.json` 1.1.0 and description; `marketplace.json` description;
   `docs/install.md` plugin section (FR-5..FR-7).
5. `tests/test-generate.sh` plugin assertions; `tests/test-hooks.sh`
   cases for the guard (fires only with both conditions; never present
   in the two protect hooks); count pins and `docs/repo-structure.md`
   (FR-8).

## Gates

`tests/test-generate.sh`, `tests/test-hooks.sh`,
`tests/test-shared-structure.sh`, `scripts/validate-spec.sh --all`,
`scripts/validate-collaboration.sh`, `scripts/check-doc-accuracy.sh`,
`scripts/check-origin-alignment.sh`, `git diff --check`,
`claude plugin validate adapters/claude-code/plugin` (exit 0), generator
idempotence (second run changes nothing), then `/review-submit`
(DeepSeek), then CI green before calling it ready.

## Risks

- **Limitation, by design.** A plugin-only user does not get
  always-loaded rules (D1). Stated in the docs, not hidden.
- **Limitation.** Commands that call project-relative `scripts/*.sh`
  work only in a project that has them. Same as `setup.sh` today.
- **Edge case.** The D2 guard trusts that a hook file under
  `~/.claude/hooks/` is also registered. That is why the safety hooks
  are excluded from it.
- **Size.** About 380 KB and roughly 60 generated files enter the repo.
  Generated and drift-checked, like the other adapters.

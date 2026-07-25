# T5.2 Design Read — Claude `permissions/*.json` importer (FR-009)

Status: **design read — paused for mapping decisions before implementation.**
Scope: import Claude Code profile permission files into Pi's existing
`PermissionRuleSet` shape. No enforcement-semantics change except via the
imported rules.

## Inputs (ground truth)

Claude profile files (`adapters/claude-code/permissions/`):
- `balanced.json`, `relaxed.json`, `deny-extras/web-dynamic.json`
- Shape: `permissions.{defaultMode, allow[], deny[]}` (+ optional `ask[]`), `env{}`.
- Entry forms present: bare tool (`"Edit"`), path-scoped deny (`"Read(./.env)"`),
  command deny (`"Bash(rm -rf:*)"`, `"Bash(git push --force:*)"`).

Pi target (`adapters/pi/runtime/policy/permissions.ts` — `PermissionRuleSet`):
`toolsAllow`, `toolsDeny` (lowercase), `pathsDeny` (= `security.protected_paths`,
glob, **write-tools only**), `pathsAsk`, `commandsDeny` (= `security.denied_commands`,
normalized prefixes), `commandsAsk`.

## Clean mappings (no ambiguity)

| Claude entry | Pi field | Notes |
|---|---|---|
| allow bare tool `"Edit"` | `toolsAllow += "edit"` | TitleCase -> lowercase |
| deny bare tool `"Bash"` | `toolsDeny += "bash"` | |
| deny `Bash(<prefix>:*)` | `commandsDeny += "<prefix>"` | strip trailing `:*`; Pi prefix word-boundary match == Claude `:*` |
| ask `Bash(<prefix>:*)` | `commandsAsk += "<prefix>"` | (no ask entries in current files) |

## Ambiguous mappings — decisions needed

### A. Path-scoped deny (`Read(./.env)`) — read-vs-write enforcement gap (significant)

Claude `Read(./.env)` denies **reading**. Pi enforces path rules only on **write**
tools (`edit`/`write`) via `checkPath`; reads are not path-checked today.

- **Recommended:** map any path-scoped deny (`Read(p)` / `Edit(p)` / `Write(p)`) ->
  `security.protected_paths` (`pathsDeny`). This protects the path from **writes**
  through the existing engine — no enforcement change. Honestly **report** that
  Pi does not path-gate reads, so a `Read(...)`-origin entry's read intent is
  `not-enforced` (no silent approximation). Extending read enforcement is out of
  scope ("do not change enforcement semantics").
- Alternatives: (B) skip `Read(...)` entries with a warning (loses `.env`
  protection on writes); (C) add read path-checking (out of scope).

### B. Path normalization (`./.env`)

`./.env` has a `./` slash, so Pi's `matchGlob` would anchor `^\./\.env$` and never
match a real candidate like `/proj/.env`.

- **Recommended:** strip a leading `./`, then a bare-name result (`.env`,
  `.env.production`) matches at any depth (Pi's any-depth rule for slash-less
  patterns) — the intended "protect `.env` in this project" semantics. Paths with
  internal slashes (`src/secret.txt`) are kept as-is (anchored). Leading `/`
  (absolute) kept as-is.

### C. `Bash(...)` colon grammar edge cases

- **Recommended:** strip only a **trailing `:*`** -> prefix (covers every current
  entry). An entry without `:*` (Claude exact-match, e.g. `Bash(npm run test)`)
  imports as a Pi **prefix** (slightly broader than Claude exact) — **warn** and
  import. An embedded `:` that is not a trailing `:*` -> **warn** and import the
  inner text verbatim as a prefix (none present today).

### D. Entries with no Pi target (report, do not fake)

| Claude entry | Reason | Disposition |
|---|---|---|
| `defaultMode` | ask-mode, not a rule | not imported (noted) |
| `env{}` | shell-hook toggles, not permissions | not imported (T5.1 adapter concern) |
| scoped **allow** `Bash(x:*)` | Pi has no command-allowlist | **warn + skip** (none present) |
| bare tool in `ask[]` | Pi has no tool-level ask | **warn + skip** (none present) |

## Proposed importer surface

Pure function, no enforcement wiring change:
`importClaudePermissions(json) -> { rules: Partial<PermissionRuleSet-lists>, warnings: string[], notEnforced: string[] }`
returning the five rule lists (toolsAllow/toolsDeny/pathsDeny/commandsDeny/commandsAsk)
plus `warnings` (unmapped entries) and `notEnforced` (e.g. Read-origin path denies).
How/where the imported lists feed the layered config is a follow-up wiring
decision; **this task delivers the importer + fixtures/tests only** unless you
say otherwise.

## Fixtures/tests planned

- `balanced.json` -> toolsAllow {read,glob,grep,edit,write,bash,websearch,webfetch};
  pathsDeny {.env, .env.local, .env.production}; commandsDeny {rm -rf, sudo,
  git push --force, git reset --hard}; notEnforced records the 3 Read-origin paths.
- `relaxed.json` -> same allow; commandsDeny the 4 git/rm/sudo prefixes; env ignored (noted).
- Adversarial fixtures: exact `Bash(cmd)` (warn+broaden), scoped allow (warn+skip),
  tool-level ask (warn+skip), `Read(src/secret.txt)` internal-slash path.

## Open questions for approval

1. **Decision A**: confirm map path-scoped deny -> `protected_paths` (write-enforced)
   + report read intent as `not-enforced`? (recommended) — or skip `Read(...)`?
2. **Scope**: importer + fixtures/tests only this PR, wiring the imported lists
   into the live config in a later task? (recommended, keeps it narrow) — or wire
   it now?

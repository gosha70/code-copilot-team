---
feature_id: pi-project-config
spec_mode: full
status: approved
date: 2026-11-18
issue: "#460"
origin:
  issue: "#460"
  urls:
    - https://github.com/gosha70/code-copilot-team/issues/460
  transcripts:
    - specs/pi-project-config/origin/2026-11-18-issue-460-origin.md
---

# Spec: per-project Pi configuration at `.cct.toml`

## Why

#411 made `~/.cct/` the one user home. At the project level the names
still differ: a project's committed Pi configuration lives in
`.code-copilot-team/config.toml` (with `config.local.toml` and the
`pi-code init` manifest `.cct-init.json`), while its runtime state lives
in `.cct/`. The owner ruled (2026-11-18) that the committed
configuration moves to `.cct.toml` at the repo root, so `.cct/` stays
purely untracked runtime state and needs no gitignore exception.

## User Scenarios

1. **New project.** A developer runs `pi-code init` in a repository. It
   creates `.cct.toml` (commented defaults) and `.cct-init.json` at the
   repo root, makes sure `.cct/` and `.cct.local.toml` are git-ignored,
   and prints what it did. The developer commits `.cct.toml` and
   `.cct-init.json`.
2. **Existing project, nothing moved yet.** A project still has
   `.code-copilot-team/config.toml`. On 2.1.x Pi reads it through the
   fallback; `pi-code doctor` names the legacy file and the command that
   moves it. Nothing moves on its own.
3. **Migrate.** The developer runs `pi-code migrate`. It moves
   `config.toml` to `.cct.toml`, `config.local.toml` to
   `.cct.local.toml`, and the manifest to `.cct-init.json` with its path
   entry rewritten, never overwriting an existing target; it removes
   `.code-copilot-team/` only when that leaves it empty, and reminds the
   developer to commit the rename. `pi-code doctor` is quiet afterwards.
4. **Mistaken ignore.** A global or project gitignore hides `.cct.toml`.
   `pi-code doctor` warns, so the team does not silently lose the
   shared configuration.
5. **2.2.** The fallback is gone: a project still on
   `.code-copilot-team/` gets no project layer, and `pi-code doctor`
   names the migrate command.

## Requirements

- **FR-1 Locations.** Project configuration `<repo>/.cct.toml`;
  personal override `<repo>/.cct.local.toml` (never committed); init
  manifest `<repo>/.cct-init.json` (committed). Runtime state stays in
  `<repo>/.cct/`.
- **FR-2 One rule, two readers.** The Pi runtime loader and `pi-code`
  resolve each project file the same way: the new file when it exists;
  otherwise, through 2.1.x, the legacy file
  (`.code-copilot-team/config.toml`, `.code-copilot-team/config.local.toml`,
  `.code-copilot-team/.cct-init.json`) when it exists; otherwise the new
  path. Each file resolves independently. The trust gate (FR-004a) is
  unchanged: neither location is read for an untrusted project.
- **FR-3 Precedence.** When both the new and the legacy file exist, the
  new one is read and the legacy one is ignored; `pi-code doctor`
  reports the pair.
- **FR-4 init.** `pi-code init` writes `.cct.toml` and `.cct-init.json`
  (its `generated` entry records `.cct.toml` and its hash), never
  overwriting either. In a project that still has a legacy config it
  creates nothing and names `pi-code migrate`. It makes sure `.cct/` and
  `.cct.local.toml` are ignored: in a git work tree it appends whichever
  line is missing to the project's `.gitignore` (creating the file if
  there is none), recognising `.cct/`, `/.cct/` and `.cct` as already
  ignoring `.cct/`; outside a git work tree it changes no ignore file.
  `--dry-run` reports every change and makes none.
- **FR-5 sync.** `pi-code sync` reads the manifest through FR-2 and keeps
  its ownership rule: the user configuration is never overwritten,
  whichever location it is in.
- **FR-6 migrate.** `pi-code migrate [--dry-run] [<project>]` is the only
  mover. For each legacy file present it moves it to its new name
  without ever replacing an existing target (a target that exists is a
  conflict: both are kept, reported, exit 1); the manifest moves with
  its `generated` path entry for the config rewritten to `.cct.toml`.
  It removes `.code-copilot-team/` only if it is then empty. It runs no
  git command. Every line it prints is safe to paste back into a shell:
  no `>`, `<`, `|`, `;`, `&`, `$` or backtick (the #463 lesson).
- **FR-7 doctor.** `pi-code doctor` reports, for the current project:
  which location each project file was read from; one warning per
  legacy file still present, naming `pi-code migrate`; a warning when
  `git check-ignore` reports `.cct.toml` (or `.cct-init.json`) as
  ignored; a warning when `.cct.local.toml` exists and is not ignored.
  Outside a git work tree the ignore checks are skipped.
- **FR-8 Other spellings.** `isSpecPath` in `workflow/sdd.ts` admits
  `.cct.toml` and `.cct.local.toml` (and, through 2.1.x, the legacy
  directory); the Pi hint in `shared/scripts/provider-emit.sh` names
  `.cct.toml`, with its golden fixtures regenerated; the comment in
  `policy/env-scrub.ts`, the Pi configuration reference, the pointer in
  `docs/cct-home.md` and the CHANGELOG (2.1 move, 2.2 removal) say the
  new names.
- **FR-9 Removal.** The first 2.2 change deletes the legacy branch of
  FR-2 in the loader and `pi-code`; a test pins that the fallback exists
  in 2.1.x, and the CHANGELOG names the removal.

## Constraints / What NOT to Build

- No automatic move: `init`, `sync`, the launcher and the runtime never
  move a file between locations (#411's rule).
- `migrate` never overwrites, never deletes a non-empty directory, and
  runs no git command; committing the rename is the developer's step.
- No change to the trust gate, the layer order (global, project,
  project-local, env, CLI, session) or the configuration schema.
- No change to the user home (`~/.cct`, #411) or to `.cct/` runtime
  state.
- No new structure guard: the existing tests that spell the project
  path are updated, and a test pins each reader.

## Key Entities

| Entity | Path | Committed |
|---|---|---|
| project configuration | `<repo>/.cct.toml` | yes |
| personal override | `<repo>/.cct.local.toml` | no (ignored) |
| init manifest | `<repo>/.cct-init.json` | yes |
| runtime state | `<repo>/.cct/` | no (ignored) |
| legacy directory | `<repo>/.code-copilot-team/` | read through 2.1.x only |

## Decisions (ruled by the owner on 2026-11-18)

- **D1 Location.** `.cct.toml` at the repo root, not `.cct/config.toml`:
  `.cct/` stays runtime state and needs no gitignore carve-out.
  **Ruled 2026-11-18 by the owner.**
- **D2 Gitignore.** No exception is needed; `init` only makes sure
  `.cct/` is ignored, and `doctor` warns if `git check-ignore .cct.toml`
  reports the configuration as ignored. **Ruled 2026-11-18 by the
  owner.**
- **D3 Migration.** An explicit command only; nothing moves silently.
  **Ruled 2026-11-18 by the owner.**
- **D4 Fallback.** Through 2.1.x, removed in 2.2, with the user-home
  fallback. **Ruled 2026-11-18 by the owner.**
- **D5 Companion files (derived from D1).** The personal override is `.cct.local.toml` and the
  manifest is `.cct-init.json`, both at the repo root beside
  `.cct.toml`; `init` adds `.cct.local.toml` to the ignore lines beside
  `.cct/`, since a personal file must not be committed. The migrate
  command is `pi-code migrate`, beside `init` and `sync`, which own the
  same files. **Approved 2026-11-18 by the owner with the bundle.**

## Success Criteria

| Criterion | Proof |
|---|---|
| A new project gets the new files | suite: `pi-code init` in a throwaway git repo creates `.cct.toml` and `.cct-init.json` (manifest entry `.cct.toml`), appends the missing ignore lines once, and `--dry-run` writes nothing |
| An unmigrated project keeps working | suite: a trusted project with only `.code-copilot-team/config.toml` resolves its project layer from it on 2.1.x; the new file wins when both exist |
| Nothing moves silently | suite: `init`, `sync` and loading leave the legacy files in place |
| migrate is safe | suite: moves all three files, rewrites the manifest entry, keeps both sides on a conflict (exit 1), removes the directory only when empty, prints no shell metacharacter |
| doctor tells the truth | suite: warnings for a legacy file, an ignored `.cct.toml`, an unignored `.cct.local.toml`; quiet for a migrated project |
| The trust gate holds | suite: an untrusted project reads neither location |

## Out of scope

- Renaming `.cct/` runtime state or any user-home file.
- Editing a global gitignore (doctor only reports it).
- Claude Code's per-project files (`CLAUDE.md`, `.claude/`).

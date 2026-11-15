---
feature_id: one-harness-home
spec_mode: full
status: approved
date: 2026-11-15
issue: "#411"
origin:
  issue: "#411"
  urls:
    - https://github.com/gosha70/code-copilot-team/issues/411
  transcripts:
    - specs/one-harness-home/origin/2026-11-15-issue-411-origin.md
---

# Spec: one harness home

## Why

CCT keeps its user-level state in two directories. `~/.cct/` holds the
harness identity stamp, the harness-stamps ledger and Session Analytics'
configuration and stores. `~/.code-copilot-team/` holds the reviewer
profile, the routing registry and its state, the Pi runtime home and the
Pi global config, and is where the approved #400 spec places the LLM
catalog. A user who asks "where does CCT keep its files" gets two
answers, `cct doctor` reports two roots, and every new file forces the
same question again (#410 asked it for `providers.toml`; #400 asked it
for `llms.toml`).

The issue asks for one decision and one migration. This spec takes the
issue's Option A for the user home: `~/.cct/` wins, every tool resolves
it through one helper per language, the legacy path is read as a
fallback for one minor release, nothing moves silently, and the doctor
says what is still in the old place. The per-project half of Option A
is a separate decision (D5), because the per-project `.cct/` directory
is untracked runtime state while `.code-copilot-team/config.toml` is
committed configuration, and merging the two would hide a project's Pi
configuration from its own repository.

## User Scenarios

1. **Fresh install.** A new user runs `scripts/setup.sh --claude-code
   --pi`. Everything lands under `~/.cct/`: `harness.json`,
   `providers.toml`, `pi/`, and later `routing.toml`, `llms.toml`, the
   analytics config and stores. `cct doctor` reports one home and no
   notice.
2. **Existing user, nothing moved yet.** A 2.0 user upgrades to 2.1 and
   runs `cct doctor`. Every reader finds its file in
   `~/.code-copilot-team/` through the fallback; the doctor prints one
   line naming the files still in the legacy home and the command that
   moves them. Peer review, routing, Pi and the hook keep working.
3. **Migrate.** The user runs `cct home migrate`. Each legacy file or
   directory is moved to `~/.cct/` unless a file of the same name
   already exists there, in which case both are left in place and
   listed; the command prints what moved and what did not; nothing is
   deleted or overwritten. `cct doctor` is quiet afterwards.
4. **Explicit home.** A user sets `CCT_HOME=/srv/cct`. Every tool,
   including Pi, which already honoured that variable, uses it; no
   fallback to either default is attempted.
5. **A reader that was missed.** A code path still spells
   `~/.code-copilot-team` directly. The structure suite's guard fails
   the build, so the move cannot be hidden by a reader nobody updated.
6. **2.2.** The fallback read is removed; a file still in the legacy
   home is reported by the doctor as not found, with the migrate
   command named. The CHANGELOG said so one release ahead.

## Requirements

- **FR-1 The home.** CCT's user home is `${CCT_HOME:-~/.cct}`. Every
  user-level file CCT reads or writes lives under it: `harness.json`,
  `harness-stamps.jsonl`, `session-analytics.json`, the Session
  Analytics stores, `providers.toml`, `routing.toml`,
  `routing-state.json`, `routing-probe-ledger.json`, `pi/` and the Pi
  global `config.toml`, and, when #400 lands, `llms.toml`,
  `llm-compat/` and `llm-sessions/`.
- **FR-2 One resolver per language.** Bash `scripts/lib/cct-home.sh`
  (`cct_home`, `cct_home_path <relative>`), Python
  `session_analytics/home.py` re-exported for `scripts/lib` callers
  (`cct_home()`, `cct_home_path(relative)`), TypeScript
  `adapters/pi/runtime/config/home.ts` (`cctHome()`,
  `cctHomePath(relative)`). No other code spells either directory name;
  the three resolvers are the only places the legacy name appears in
  code.
- **FR-3 Precedence and fallback.** `CCT_HOME` set: that directory,
  no fallback. Otherwise `~/.cct/<relative>` when it exists; otherwise
  `~/.code-copilot-team/<relative>` when it exists (the legacy
  fallback, read only); otherwise `~/.cct/<relative>` as the path to
  create. A per-file override that exists today (`CCT_PROVIDER_PROFILE`,
  `CCT_ROUTING_REGISTRY`, `CCT_ROUTING_STATE`,
  `CCT_ROUTING_PROBE_LEDGER`, `CCT_HARNESS_STAMPS`) keeps its meaning
  and wins over the home.
- **FR-4 Writes go to the new home.** A tool that creates a file
  creates it under `~/.cct/`; a tool that rewrites a file it found
  through the fallback rewrites it in place and the doctor keeps
  reporting it, so a half-migrated state is visible, never silently
  completed.
- **FR-5 Nothing moves silently.** No setup, launcher or tool moves a
  file between homes on its own. `cct home migrate` is the one mover:
  it moves each legacy entry to `~/.cct/` when the target is absent,
  leaves both and lists the conflict when the target exists, never
  deletes, never overwrites, and prints each action. `cct home` without
  arguments prints the resolved home and, per known file, where it was
  found.
- **FR-6 Doctor and setup notices.** `cct doctor` gains a **Home**
  section: the resolved home, the override in effect, and one line per
  file still read from the legacy home, ending with the migrate
  command. `scripts/setup.sh` prints the same one line when it finds a
  legacy home, and otherwise says nothing.
- **FR-7 Pi.** `pi-code`, `adapters/pi/setup.sh` and the runtime's
  `index.ts` default `CCT_HOME` to the resolver's answer; the Pi global
  `config.toml` is read through `cctHomePath("config.toml")` with the
  same fallback; `pi-code doctor` reports the home it used. Pi's
  per-project configuration is governed by D5.
- **FR-8 Session Analytics.** `config.py` resolves
  `session-analytics.json`, the Kùzu store default and the
  harness-stamps default through the Python resolver; the API's path
  allow-list (`server.py`) accepts the resolved home and, during the
  fallback release, the legacy home.
- **FR-9 Guard.** `tests/test-shared-structure.sh` fails when any
  tracked code file outside the three resolvers spells
  `.code-copilot-team` or `~/.cct` as a path; docs, CHANGELOG, specs
  and fixtures that assert the legacy fallback are listed exceptions.
- **FR-10 Docs and generated artifacts.** Every doc, template header,
  schema description, generated reference and golden fixture says
  `~/.cct/`; one page, `docs/cct-home.md`, states the home, the
  override, the fallback release and the migrate command; the
  CHANGELOG entry under 2.1 announces the move and that 2.2 drops the
  fallback.
- **FR-11 Removal.** In the first 2.2 change, the fallback branch of
  the three resolvers is deleted; a legacy file is then "not found"
  with the migrate command in the message. A test pins that the
  fallback exists in 2.1 and a note in `docs/cct-home.md` names the
  removal.
- **FR-12 #400 follows.** The approved #400 spec's FR-1 and D2 say
  the catalog lives beside `providers.toml` through one helper so #411
  moves it; when #411 lands first, slice A of #400 uses
  `cct_home_path("llms.toml")` and the #400 spec is amended as a
  recorded amendment; when slice A lands first, this feature moves
  `llms.toml` with the rest.

## Constraints / What NOT to Build

- No symlink between the homes.
- No automatic move on setup, launch or first run.
- No change to the per-project `.cct/` runtime-state directory.
- No change to where projects keep committed Pi configuration; that
  rename is its own issue and PR after this one (D5).
- No change to the per-file override variables' names or meaning.
- No migration of the Session Analytics store contents; the store
  file moves with the directory.

## Key Entities

| Entity | Identity | Notes |
|---|---|---|
| home | `${CCT_HOME:-~/.cct}` | one per user |
| legacy home | `~/.code-copilot-team` | read-only fallback through 2.1.x |
| resolver | one per language | the only code that spells either name |
| `cct home` | CLI | show; `migrate` moves, never overwrites |
| doctor Home section | `cct doctor` | per-file provenance, migrate hint |

## Decisions (ruled by the owner on 2026-11-15)

- **D1 Direction.** Option A: `~/.cct/` wins for the user home.
  Option B would retire `~/.cct/` but leave the per-project runtime
  state at `.cct/`, so the names would still differ between project and
  home. **Ruled 2026-11-15 by the owner: as recommended.**
- **D2 One override.** `CCT_HOME`, which Pi already honours, becomes
  the override for every tool; the per-file overrides stay above it.
  **Ruled 2026-11-15 by the owner: as recommended.**
- **D3 Migration mechanics.** Read fallback through 2.1.x; `cct home
  migrate` as the only mover, never overwriting; doctor and setup
  notices; fallback removed in the first 2.2 change. Alternative:
  `setup.sh` moves files automatically. Recommended: the explicit
  command; a move the user did not ask for is the issue's own
  objection to symlinks in another form. **Ruled 2026-11-15 by the owner: as recommended.**
- **D4 Delivery.** One PR for the user home (resolvers, every reader,
  `cct home`, doctor, docs, guard); the per-project half, if D5 says
  yes, is its own issue and PR. Recommended, since a 65-file mechanical
  change plus a convention change is two reviews. **Ruled 2026-11-15 by the owner: as recommended.**
- **D5 Per-project convention.** Keep `.code-copilot-team/config.toml`
  as the committed per-project Pi configuration, out of this feature.
  Option A moves it to `.cct/config.toml`, but `.cct/` is the untracked
  runtime-state directory (review artifacts, ledgers, memory); a
  committed config inside it needs every project to carve a gitignore
  exception, and `pi-code init`'s manifest records the path and hash.
  If you want the project side renamed too, it is a separate issue
  with its own fallback and manifest rule. **Ruled 2026-11-15 by the
  owner: rename the project side too, as a separate issue and PR after
  this one.** This feature ships the user home; the project-side issue
  carries its own fallback, manifest rule and gitignore guidance.
- **D6 #400 coupling.** FR-12 as written; whichever lands first moves
  `llms.toml`, with the #400 spec amended on record. **Ruled 2026-11-15 by the owner: as recommended.**

## Success Criteria

| Criterion | Proof |
|---|---|
| One home for a fresh install | suite: setup into a throwaway `HOME` leaves nothing under `~/.code-copilot-team` and the doctor prints no notice |
| An unmigrated 2.0 user keeps working | suite: fixtures under the legacy home are found by peer review, routing, the hook, Pi and analytics through the fallback; writes land in `~/.cct/` |
| Nothing moves silently | suite: setup and launchers leave the legacy files where they are; `cct home migrate` moves, lists conflicts, never overwrites |
| `CCT_HOME` wins everywhere | suite: with it set, no reader touches either default |
| A missed reader cannot hide | structure-suite guard fails on a planted direct spelling |
| Pi parity | `tests/test-pi-launcher.sh` and `tests/pi-runtime/*` pass with the home resolved, including the `CCT_HOME` and fallback cases |
| Docs and generated artifacts agree | doc-accuracy, generators `--check`, golden fixtures regenerated |
| Pins | `tests/test-counts.env` and `docs/repo-structure.md` together |

## Out of scope

The per-project convention (its own issue and PR, D5); Session
Analytics store migration; renaming the environment variables; the
`cct` CLI's other subcommands.

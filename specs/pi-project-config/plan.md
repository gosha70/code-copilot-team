---
spec_mode: full
feature_id: pi-project-config
risk_category: integration
justification: |
  Moves a project's committed Pi configuration from
  .code-copilot-team/config.toml to .cct.toml at the repo root, with the
  personal override and the init manifest beside it: the Pi runtime
  loader (TypeScript), pi-code init, sync, doctor and a new migrate
  (bash), the SDD write allow-list, provider-emit and its golden
  fixtures, six test files and the Pi docs, with a fallback through
  2.1.x. FR-1..FR-9.
status: approved
date: 2026-11-18
issue: "#460"
origin:
  issue: "#460"
  urls:
    - https://github.com/gosha70/code-copilot-team/issues/460
  transcripts:
    - specs/pi-project-config/origin/2026-11-18-issue-460-origin.md
  origin_claim: |
    #411 moves the user home to ~/.cct/. A project's committed Pi
    configuration still lives in .code-copilot-team/config.toml (plus
    config.local.toml and the .cct-init.json manifest that pi-code init
    writes with the config path and hash), while the project's runtime
    state lives in .cct/. The two names differ again at the project
    level. Owner ruling 2026-11-18: ".cct.toml at the repo root".
---

# Plan: per-project Pi configuration at `.cct.toml` (#460)

## Shape

One resolution rule, implemented twice because the two readers run in
different languages and the launcher must work without the runtime:

- **TypeScript** (`adapters/pi/runtime/config/project.ts`, new):
  `projectFile(projectDir, kind)` for `config`, `local`, `manifest`,
  returning the new path, else the legacy path when only it exists
  (through 2.1.x), else the new path; plus `legacyProjectFiles(projectDir)`
  for doctor. `loader.ts` reads the project and project-local layers
  through it; the trust gate stays where it is.
- **Bash** (`adapters/pi/bin/pi-code`): the same rule as one function
  used by `init`, `sync`, `doctor` and `migrate`. `pi-code doctor --json`
  already defers to the runtime CLI, which reports through the
  TypeScript rule.

## Files

| Area | Files |
|---|---|
| Resolver | `adapters/pi/runtime/config/project.ts` (new), `config/loader.ts` |
| Launcher | `adapters/pi/bin/pi-code`: `init` (new paths, manifest entry, ignore lines, legacy refusal), `sync` (manifest through the rule), `doctor` (FR-7), `migrate` (new) |
| Other spellings | `runtime/workflow/sdd.ts` (`isSpecPath`), `runtime/policy/env-scrub.ts` (comment), `shared/scripts/provider-emit.sh` and `tests/fixtures/provider-emit/golden/pi__*.txt` |
| Tests | `tests/pi-runtime/config.test.mjs`, `tests/pi-runtime/security-battery.test.mjs`, `tests/pi-runtime/project.test.mjs` (new), `tests/test-pi-launcher.sh`, `tests/test-sync.sh`, `tests/test-cct-cli.sh`; pins in `tests/test-counts.env` and `docs/repo-structure.md` |
| Docs | `adapters/pi/docs/configuration-reference.md`, `docs/cct-home.md` (pointer), `CHANGELOG.md` |

## Risks

| Risk | Mitigation |
|---|---|
| A project's ignore rules hide `.cct.toml` | FR-7: `git check-ignore` warning in `pi-code doctor` |
| `.cct.local.toml` gets committed | FR-4 adds it to the ignore lines; FR-7 warns when it is not ignored |
| `init` duplicates or mangles `.gitignore` lines | append only missing lines; recognise `.cct/`, `/.cct/`, `.cct`; `--dry-run` shows the change |
| migrate loses a file | no-replace moves (hard link then unlink, inside one project, so one filesystem); conflicts keep both sides; the manifest is written to its new name exclusively before the legacy one is removed |
| Pasted output does damage | FR-6: no shell metacharacter in migrate output, pinned by a test |
| The trust gate regresses | the security battery keeps an untrusted project reading neither location |

## Test strategy

Bash suites run against throwaway git repositories and a throwaway HOME;
the runtime suite drives the loader with trusted and untrusted fixtures
for each location and the both-present case. Each reader gets a test
that pins the 2.1.x fallback (FR-9). Golden fixtures are regenerated,
not hand-edited.

## Slicing

One implementation PR closes #460 after this spec PR merges (spec-first,
CONTRIBUTING).

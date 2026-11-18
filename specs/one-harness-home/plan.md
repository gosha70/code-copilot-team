---
spec_mode: full
feature_id: one-harness-home
risk_category: integration
justification: |
  Moves the user-level home of every CCT tool: three launchers and
  installers, the reviewer and routing readers, the Pi runtime (bash and
  TypeScript), Session Analytics (Python), the hook, the doctor, 65
  files that spell the old name, templates, schemas, golden fixtures and
  docs, with a one-release compatibility fallback. FR-1..FR-12.
status: approved
date: 2026-11-15
issue: "#411"
origin:
  issue: "#411"
  urls:
    - https://github.com/gosha70/code-copilot-team/issues/411
  transcripts:
    - specs/one-harness-home/origin/2026-11-15-issue-411-origin.md
  origin_claim: |
    The harness has two home directories, ~/.cct/ and
    ~/.code-copilot-team/. Decide the direction once and migrate as one
    change: every reader resolves the home through one helper per
    language with a fallback read of the legacy path for one minor
    release, cct doctor prints a one-line notice while only the legacy
    path exists, and the CHANGELOG carries the migration note.
---

# Plan: one harness home (#411)

## Shape

Three resolvers, every reader switched to them, one command that moves
files, one doctor section, one guard, docs. Nothing changes what any
file contains.

1. **Resolvers.** `scripts/lib/cct-home.sh` (bash 3.2),
   `scripts/session_analytics/home.py` with `scripts/lib/cct_home.py`
   importing it, `adapters/pi/runtime/config/home.ts`. Each implements
   FR-3 and nothing else, and carries the only occurrence of the legacy
   name in code, in a constant with a comment naming the 2.2 removal.
2. **Readers.** Every site in the origin record's inventory calls its
   resolver: the hook, `adapters/claude-code/setup.sh`
   (`harness.json`, `providers.toml` scaffold), `scripts/setup.sh`
   help text, `peer-review`/`review-round-runner.sh`,
   `auto-build-loop.sh`, `cooldown-supervisor.sh`, `routing-state.sh`,
   `routing-probe.sh`, `provider-emit.sh`/`provider-setup.sh`,
   `cct_config.py`, `cct_doctor.py`, `config_reference.py`, Session
   Analytics `config.py` and `api/server.py`, Pi `pi-code`,
   `setup.sh`, `index.ts` and `loader.ts`.
3. **`cct home`** in `scripts/cct` → `scripts/cct-home.sh`: `show`
   (default) and `migrate` (FR-5), bash, jq-free.
4. **Doctor** Home section (FR-6) in `cct_doctor.py`; the setup notice
   in `scripts/setup.sh`.
5. **Guard** in `tests/test-shared-structure.sh` (FR-9) with an
   exception list of exactly the three resolvers and the fixtures that
   assert the fallback.
6. **Docs**: `docs/cct-home.md`, the 9 pages, README, the template
   headers, `providers.schema.json`, the generated configuration
   reference, the provider-emit golden fixtures, CHANGELOG.

## Interfaces

- bash: `cct_home` → the directory; `cct_home_path <relative>` → the
  path FR-3 selects; `cct_home_legacy_hits` → the relative paths
  currently served from the legacy home (for the doctor and setup).
- Python: `cct_home()`, `cct_home_path(relative: str) -> Path`,
  `legacy_hits() -> list[str]`.
- TypeScript: `cctHome()`, `cctHomePath(relative)`, `legacyHits()`.
- `cct home [show|migrate] [--dry-run]`; exit 0, 1 on a conflict left
  in place, 2 on a failed move.

## Test strategy

- `tests/test-cct-home.sh`: the bash resolver's precedence table
  (override, new, legacy, neither), `migrate` on fixtures (move,
  conflict, dry run, nothing to do), `show` output, no deletion ever.
- `scripts/session_analytics/tests/test_home.py`: the Python resolver's
  table and `config.py` using it for the three defaults; `server.py`
  allow-list.
- `tests/pi-runtime/home.test.mjs`: the TypeScript resolver; `index.ts`
  and `loader.ts` with `CCT_HOME`, new and legacy homes;
  `tests/test-pi-launcher.sh` cases for `pi-code` and `pi-code doctor`.
- Existing suites that spell the paths move to the resolver or to the
  new default: `test-hooks.sh`, the routing suites, `test-peer-review.sh`,
  `test-review-loop.sh`, `test-auto-build-loop.sh`,
  `test-cooldown-supervisor.sh`, `test-provider-emit.sh` (golden files
  regenerated), `test-cct-cli.sh` (doctor Home section, `cct home`).
- Structure-suite guard with a planted-spelling mutation test.
- Pins in `tests/test-counts.env` and `docs/repo-structure.md` in the
  same commit as each count change.

## Risks

| Risk | Mitigation |
|---|---|
| A reader is missed and keeps reading the legacy home | FR-9 guard: no direct spelling outside the resolvers |
| A tool writes to the legacy home after the move | FR-3/FR-4: a new top-level entry is created under the new home; a write inside an entry the legacy home still serves stays there, so nothing is split, and the doctor reports that entry until `cct home migrate` moves it |
| `cct home migrate` destroys a file | never overwrites, never deletes; conflicts listed; dry run |
| Pi's init manifest records the global home | the manifest records the per-project config only (D5 keeps it); `pi-code doctor` reports the home |
| The hook and analytics disagree on `harness-stamps.jsonl` | `CCT_HARNESS_STAMPS` keeps winning (#448); both defaults come from the same resolver rule |
| #400 lands in between | FR-12: whichever lands first moves `llms.toml`, amendment on record |

## Delivery gates

`validate-spec.sh --feature-id one-harness-home`, origin gate, every
suite above, generators `--check`, doc accuracy, `git diff --check`,
`pre-pr-check.sh --closes 411`, peer review, Linux CI green on the final
head read from GitHub.

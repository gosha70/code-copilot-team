# Origin alignment check — pi-project-config (draft bundle)

Date: 2026-11-18

Origin: issue #460, the #411 D5 ruling it follows, and the owner's
rulings of 2026-11-18, recorded in
`origin/2026-11-18-issue-460-origin.md`; the repository at `05aee21`.

## Issue section → bundle section

| Origin | Bundle |
|---|---|
| The project-level names differ (`.code-copilot-team/` config vs `.cct/` state) | spec.md § Why; FR-1 |
| One resolver | FR-2 (one rule in the loader and in `pi-code`) |
| A fallback for one minor release | FR-2, FR-9; D4 (through 2.1.x, removed in 2.2) |
| `pi-code doctor` names a project still on the legacy path | FR-7 |
| No silent move | FR-6 (`pi-code migrate` the only mover); Constraints; D3 |
| `pi-code init` scaffolds the new path | FR-4 |
| Gitignore guidance | D2: no exception needed at the root; `init` makes sure `.cct/` (and `.cct.local.toml`) is ignored; FR-7 warns when `.cct.toml` is ignored |
| The init manifest records the config path and hash | FR-4 (new entry), FR-5 (sync), FR-6 (migrate rewrites the entry) |
| Update `provider-emit.sh`'s Pi output and the tests | FR-8; plan § Files |

## Deviations, owner-ruled

- The issue proposed `.cct/config.toml` with a gitignore carve-out. The
  owner ruled `.cct.toml` at the repo root (D1, 2026-11-18), which
  removes the carve-out the issue worried about.
- D5 (the override's and the manifest's names and places, and the
  command name) follows from D1 and is confirmed when the owner
  approves this bundle.

## Mismatches

None.

Verdict: aligned
Confidence: high

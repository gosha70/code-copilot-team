# T6.4 Design Read — `pi-code init` + `pi-code sync [--dry-run]` (FR-000a)

Status: **design read — paused for decisions before implementation.**
Scope: `pi-code init` reuses the existing scaffolder; `pi-code sync [--dry-run]`
reuses the existing sync contract. Boundary conservative per review framing.

## Ground truth (verified)

**The Claude scaffolder is Claude-hard-wired, not shared.** `init_project()` /
`sync_project()` / `infer_template()` live only in the `adapters/claude-code/claude-code`
launcher and are wired to `.claude/` throughout: `TEMPLATES_DIR=~/.claude/templates`,
reads `$target/.claude/template.json`, copies to `$target/.claude/…`, infers from
`$target/CLAUDE.md`'s first line. There is **no shared scaffolder function** to
call. So reuse is CONCEPTUAL (same contract shape), not literal delegation — the
T6.1 thin-driver framing.

**The contract shape (worth reusing conceptually):**
- init writes a metadata/identity file `.claude/template.json`
  `{name, initialized, templateHash}`; never overwrites pre-existing extra
  files/dirs (only `CLAUDE.md` prompts).
- sync classifies: **managed** (`.claude/**`, `commands/**`, `.github/**`) →
  overwrite changed; **user-owned** (`CLAUDE.md`, consumer subdirs/files,
  permission profile, `settings.local.json`) → **diff/report only, never
  overwrite**; preserves `initialized`, adds `lastSynced`.
- `infer_template()` = **exact heading match only** — an edited heading returns
  no match, so sync **refuses rather than guessing** (the user-owned safety
  mechanism).
- `--dry-run` = every mutating branch individually gated (`echo` intended action
  vs `cp`/write); reports "N file(s) would be updated."

**Pi's shape is different (this is decisive).** Pi is a **global managed install**
(`~/.code-copilot-team/pi/`: authored `runtime/` + generated advisory `resources/`)
plus a **project-local footprint that Pi READS, never scaffolds**:
`.code-copilot-team/config.toml` (+ `config.local.toml`, gated by fail-closed
project trust) and `.cct/{pi-workflow,verify,review}` state (written by *runners*,
not init). Pi has **no `.claude/`, no `CLAUDE.md`, no per-project `template.json`,
and no code that creates any project-local file.** An `init` is greenfield for Pi.

**Pi's existing sync contract** = `scripts/generate.sh` (regenerate
`adapters/pi/resources/` from `shared/`) + `adapters/pi/setup.sh --sync` (regen +
reinstall). **Drift detection** = `sync-check.yml`: `git add -A adapters/ ; git
diff --cached --exit-code adapters/` — it STAGES first because plain `git diff` is
blind to newly-generated untracked files.

**`pi-code` dispatch**: pre-loop `case` (`:81` classifier, `:130` dispatch);
`config|features|export|resources|doctor` delegate to `runtime/cli.ts`, which is
**read-only and runs UNTRUSTED** (`cli.ts:43`). No `init`/`sync` arm exists. bash-3.2
constraints are load-bearing (empty-array `${a[@]+…}` guards, the `CCT_PI_MODE`
case-not-loop discipline).

## How your guardrails resolve the central ambiguity

The read's key open question was "does `pi-code init` scaffold `.claude/`-style, or
Pi-native?" Your guardrail #4 (**don't force Pi into `.claude/`; prefer a Pi-shaped
target**) resolves it: **Pi-native**. So:

- **`init` = scaffold the Pi-native project footprint only** — a starter
  `.code-copilot-team/config.toml` (commented defaults) + an ownership manifest
  `.code-copilot-team/.cct-init.json` `{name, initialized, generated: [files], hash}`
  giving the provable template-identity/generated-file record your guardrail #1
  requires. It does NOT emit `.claude/`, `CLAUDE.md`, or `.cct/` state (runner-owned).
  Idempotent: never clobbers an existing `config.toml` (report + skip).
- **`sync` = reuse Pi's LITERAL existing sync contract** — regenerate the managed
  advisory resources (`generate.sh` + `setup.sh --sync` semantics) and report
  drift. It updates only generated/owned resources; it NEVER touches
  `config.toml`/`config.local.toml` (user-owned) or `.cct/` state.
- These sit at different layers (init = project config; sync = managed resources),
  which is correct for Pi's architecture (vs Claude where both are project-level).

## Proposed design (pending approval)

- New `pi-code` **launcher** subcommands (bash, `CCT_DIAGNOSTIC_CMD`-classified,
  bash-3.2-safe), NOT `cli.ts` (which is read-only/untrusted):
  - `init [project-dir]`: create `.code-copilot-team/config.toml` (from a checked-in
    starter template) + `.cct-init.json` manifest. No-clobber; `--dry-run` reports.
  - `sync [--dry-run]`: delegate to the existing `generate.sh` + `setup.sh --sync`
    managed-resource regeneration; report what would change.
- **User-owned safety (guardrail #2)**: sync only writes files listed in the
  manifest as generated/owned; `config.toml`/`config.local.toml` and any file not
  in the manifest are **preserved and reported**, never overwritten — mirroring
  `infer_template`'s refuse-on-edit stance.
- **`--dry-run` (guardrail #3)**: report-only; **no writes AND no `git add`/staging**
  (Pi's drift check stages — the user-facing dry-run must not).

## Decisions needed

- **A — init's owned-file set.** Confirm `init` scaffolds ONLY
  `.code-copilot-team/config.toml` + `.cct-init.json` manifest (Pi-native), not a
  `.claude/`-style bundle. Should it seed config from a named `--profile`/template's
  Pi-relevant fields, or a single generic starter? (I lean generic starter, optional
  `--profile`.)
- **B — sync's target (the crux).** Confirm `sync` = the LITERAL Pi sync contract
  (regenerate managed `resources/` via `generate.sh` + `setup.sh --sync`), NOT a
  Claude-`sync_project`-style per-project template diff (Pi has no scaffolded
  project content to diff). Or should sync ALSO reconcile the project manifest?
- **C — reuse boundary.** Confirm: init reuses the contract SHAPE conceptually
  (manifest identity, no-clobber, dry-run) since the Claude scaffolder can't be
  called; sync reuses the LITERAL `generate.sh`/`setup.sh --sync` contract.
- **D — placement.** Launcher bash subcommands (recommended) vs `cli.ts` (would
  require giving the untrusted read-only CLI write capability — I lean against).
- **E — dry-run guarantee.** Report-only, no writes, **no `git add`/staging**.
  (Your guardrail #3 — confirming the no-stage nuance explicitly.)
- **F — user-file protection.** Manifest-driven ownership: only manifest-listed
  generated files may be updated; user-edited/ambiguous → preserved + reported.
  Confirm.

## Scope boundary + tests

IN: `pi-code init`/`sync [--dry-run]` launcher arms (bash-3.2-safe); a starter
`config.toml` template + manifest schema; the manifest-driven sync ownership guard;
`--dry-run` no-write/no-stage; `test-pi-launcher.sh` cases (init creates the owned
files + manifest, no-clobber on re-init, sync dry-run writes nothing/stages nothing,
sync preserves an edited `config.toml` and reports it, unknown-subcommand still
forwards to pi).

OUT: emitting a `.claude/`-style bundle; `cli.ts` write capability; scaffolding
`.cct/` runner state; generalizing the Claude template registry into Pi.

## Decisions — CONFIRMED

- **A** — Pi-native only. `init` creates a starter `.code-copilot-team/config.toml`
  + `.cct-init.json` manifest; no `.claude/`, no `CLAUDE.md`. Generic starter,
  optional `--profile` seeding.
- **B** — `sync` = the LITERAL Pi managed-resource contract (`generate.sh` +
  `setup.sh --sync`). No Claude-style per-project template diff. Manifest
  reconciliation is limited to **owned init artifacts, not user config**.
- **C** — conceptual reuse for `init` (contract shape), literal reuse for `sync`.
- **D** — launcher bash subcommands; `cli.ts` stays read-only / untrusted-runtime
  safe (no write capability added).
- **E** — `--dry-run` report-only: **no writes, no staging, no `git add`**.
- **F** — manifest-driven ownership only. A manifest-listed generated file may be
  updated ONLY if its **current hash matches** the manifest (proof it's still the
  generated version); a hash mismatch = user-edited/ambiguous → **preserved and
  reported**, never overwritten.

### Consequence for `config.toml` (recorded so implementation is unambiguous)
`config.toml`/`config.local.toml` are **user config** (B): `sync` NEVER overwrites
them regardless of hash. The manifest records `config.toml`'s init hash so `sync`
can REPORT its state — hash-match = "pristine starter", mismatch = "customized
(preserved)". In v1 the only project init artifact is user config, so `sync`'s
project write-set is empty; `sync`'s real action is managed-resource regeneration
+ a drift report. The hash-match update rule (F) is the general ownership guard for
any future owned-generated project file.

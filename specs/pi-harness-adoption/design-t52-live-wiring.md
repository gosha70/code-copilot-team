# T5.2 Design Read — live-wiring the Claude permissions importer (FR-009)

Status: **design read — paused for decisions before implementation.**
Scope: wire `importClaudePermissions()` into the layered config so Claude
`permissions/*.json` profile content is reused at runtime by the permission
engine. The converter + fixtures/tests already shipped (T5.2 part 1); this is the
deferred "live-wiring" that flips T5.2 to done.

## Ground truth (verified)

**The converter is a pure function with no live caller.**
`importClaudePermissions(json)` (`policy/import-permissions.ts:97`) returns
`{ rules, warnings, notEnforced }` where `rules: ImportedRules` has
`toolsAllow, toolsDeny, pathsDeny, pathsAsk, commandsDeny, commandsAsk`. Its only
callers today are its tests. Nothing in the config path invokes it.

**The converter output maps 1:1 onto the keys the engine already reads**
(`policy/permissions.ts:229-234`):

| ImportedRules | live config key | floor? |
|---|---|---|
| `toolsAllow`  | `tools.allow`               | no  |
| `toolsDeny`   | `tools.deny`                | no  |
| `pathsDeny`   | `security.protected_paths`  | **yes** (array-union) |
| `pathsAsk`    | `permissions.paths.ask`     | no  |
| `commandsDeny`| `security.denied_commands`  | **yes** (array-union) |
| `commandsAsk` | `permissions.commands.ask`  | no  |

**The layer model** (`config/loader.ts:164-255`): ordered `Layer[]` of
`{name, source, table}` merged leaf-by-leaf (`:258-294`):
`defaults < profile chain < global < project < project-local < env < cli`.
A computed table (not just a file) can be pushed as a layer.

**Merge semantics are split** (`:261-292`):
- **Floor keys** (`SECURITY_FLOOR`: `security.protected_paths`,
  `security.denied_commands` = array-union; plus the security booleans) route
  through `applyFloorValue`: monotonic — later layers may only STRENGTHEN;
  weakening is blocked+recorded unless the layer is in `RELAXATION_LAYERS`
  (`project-local, cli, env, session`) where it relaxes *with an audit*.
- **Non-floor keys** (`tools.allow`, `tools.deny`, `permissions.paths.ask`,
  `permissions.commands.ask`): plain **last-layer-wins REPLACE** (arrays replace
  wholesale, no union).

So: imported denies (`protected_paths`, `denied_commands`) compose additively and
safely through the floor regardless of placement. Imported allow/ask lists
(non-floor) are REPLACED by any later layer that sets the same key — **placement
decides whether the imported allow/ask list is the base or the winner.**

**The two profile systems are separate.** Pi-native profiles
(`config/profiles.ts`: `minimal, disciplined, review-heavy, autonomous,
local-first, air-gapped, ci, peer-reviewer` — TOML partials) have NO reference to
the Claude permission profiles (`adapters/claude-code/permissions/{balanced,
relaxed}.json` + `deny-extras/web-dynamic.json`). Live-wiring must introduce the
bridge that says "this run reuses permission profile X."

**Sample input** (`balanced.json`) imports to: `toolsAllow=[read,glob,grep,edit,
write,bash,websearch,webfetch]`, `protected_paths=[.env,.env.local,
.env.production]` (all Read-scoped → each also emits a `notEnforced` note: Pi
gates writes only), `denied_commands=[rm -rf, sudo, git push --force,
git reset --hard]`.

**Trust**: project config layers are read only when `trusted===true`
(`projectGate`, FR-004a fail-closed). Any project-supplied import source must
inherit the same gate; the in-repo `adapters/claude-code/permissions/*.json` is a
trusted first-party source.

## Proposed design (pending approval)

- **Selection = profile-owned** (DRY, no chicken-and-egg): add an optional
  `importPermissions?: string[]` field to `Profile`. A Pi profile names the
  Claude permission profile(s) it reuses (e.g. `disciplined` → `["balanced"]`).
  The loader, while walking the resolved profile chain, loads each named
  `adapters/claude-code/permissions/<name>.json` (+ `deny-extras/<name>.json`),
  runs `importClaudePermissions()`, and injects the result as a computed layer.
- **Placement = a single computed layer named `imported` inserted just ABOVE
  `defaults` and BELOW the Pi `profile` chain.** Consequence: imported denies
  union into the floor as the base protective posture (Pi profile + user layers
  can only strengthen, or relax with audit); imported non-floor allow/ask lists
  are the BASE that a Pi profile's own TOML or a user layer may override.
- **Reuse the existing floor + merge machinery** — the imported layer is just
  another `Layer`; NO new merge path, NO change to `applyFloorValue`, NO change
  to the engine or the converter. Only the loader gains the inject step.
- **Warnings/notEnforced are surfaced, never dropped**: fold the importer's
  `warnings` + `notEnforced` into `LoadResult.warnings` (tagged with the source
  profile) so `pi-code doctor`/`config`/`features` report them — mirroring the
  honesty model (the read-vs-write gap stays visible live).

## Decisions needed

- **A — selection mechanism + the profile→json mapping.** Confirm profile-owned
  `Profile.importPermissions?: string[]` (recommended) vs a top-level config key
  `permissions.import` vs a launcher/`LoadOptions` input. AND: which Pi profiles
  map to which Claude profiles? (I do NOT want to pick the security mapping
  unilaterally. Safe default: map only where intent is obvious — e.g. a new/opt
  reuse — and leave existing profiles unchanged unless you specify a mapping.)
- **B — import source.** In-repo `adapters/claude-code/permissions/<name>.json`
  as the single cross-adapter source of truth (recommended). Also compose
  `deny-extras/<name>.json`? Allow a project-provided path (trust-gated) now, or
  defer? (I lean: in-repo only for v1; project paths later.)
- **C — layer placement.** Confirm the imported layer sits just above `defaults`,
  below the Pi `profile` chain (imported = base posture; profile/user refine).
  Alternative: above the profile (imported wins over Pi profile non-floor lists).
  (I lean base/below-profile — safest composition; floor still protects denies.)
- **D — non-floor list semantics.** For `tools.allow` / `commands.ask` /
  `paths.ask` (not floor-protected): keep plain layer REPLACE (imported is the
  base, later layers replace) — or union imported allow/ask with defaults? (I
  lean REPLACE to match existing loader semantics; unioning allowlists silently
  is a relaxation that shouldn't be invisible.)
- **E — warning surfacing.** Confirm importer `warnings`+`notEnforced` flow into
  `LoadResult.warnings` and are shown by diagnostics (not silently consumed).
- **F — scope.** T5.2 live-wiring = loader inject + reporting + tests ONLY. NOT:
  changing the converter contract, adding Claude profiles, per-phase permission
  switching (separate/Phase-5 note in loader), or a project-path import source.
  Confirm.

## Scope boundary + tests

IN: `Profile.importPermissions` field (or the chosen selector); loader inject of
a computed `imported` layer via `importClaudePermissions()`; floor composition
proven for imported denies; warning/notEnforced surfacing; tests — imported
denies union into `protected_paths`/`denied_commands` and survive the floor,
imported allow/ask sit as base and are overridable, a later user layer can still
strengthen, warnings/notEnforced reach `LoadResult`, and an unknown/malformed
import name is reported (not fatal).

OUT: converter changes; new permission profiles; project-supplied import paths;
per-phase permission switching; any engine/enforcement-semantics change.

## Decisions — CONFIRMED

- **A — selection + mapping.** `Profile.importPermissions?: string[]` (profile-owned).
  Most-derived profile in the chain wins (REPLACE, not union across the chain).
  Mapping: `disciplined`→`["balanced"]`, `peer-reviewer`→`["balanced"]`,
  `autonomous`→`["relaxed"]`, `air-gapped`→`["balanced"]`. No `web-dynamic` this slice.
- **B — source.** In-repo `adapters/claude-code/permissions/<name>.json` only.
- **C — placement.** Computed `imported` layer above `defaults`, below the Pi profile.
- **D — non-floor lists.** REPLACE (imported is the base; profile/user may override).
- **E — reporting.** `warnings` + `notEnforced` fold into `LoadResult.warnings`,
  tagged `permissions import '<name>': …`; surfaced by load/doctor/config.
- **F — scope.** Loader-inject + resolver + reporting + tests. No enforcement
  semantic change — the engine consumes the now-populated config unchanged.

## Implementation findings (surfaced while building)

1. **Managed-install source gap → bundle via setup.sh.** The Pi runtime in a
   managed install (`~/.code-copilot-team/pi/`) has no `adapters/claude-code/`, so
   the reused JSONs are unreachable there. Resolved (confirmed): `setup.sh` copies
   `adapters/claude-code/permissions/` → `$MANAGED_DIR/permissions/`, and the
   resolver searches **managed first, repo checkout fallback** (via
   `import.meta.url`). `--repair` checks it. Live-wiring now functions in both.

2. **Floor requires base ∪ imported for denies.** The monotonic floor's
   `array-union` uses a non-superset incoming array as its REMOVAL-detection
   signal — a *partial* imported deny list reads as "remove the defaults" and is
   blocked. So the resolver presents `base ∪ imported` for `security.protected_paths`
   / `security.denied_commands` (base from `BUILTIN_DEFAULTS`, passed by the
   loader). Imported denies then compose as an audited `strengthened` decision;
   the floor engine itself is unchanged.

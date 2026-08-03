# FU-2 Design Read — `pi-code provenance` command (FR-027)

Status: **design read — approval needed on the version source and the
absent-field boundary before implementing.** FU-2 is P2: a single read-only
report that aggregates the FR-027 provenance fields. It composes existing
surfaces (`features`/`seedCapabilities`, `load()` trust, the install identity) —
no new data model.

## FR-027 (verbatim)

> every executable package/extension exposes source, version, checksum where
> available, scope, trust state, enabled modules, dependency status, security
> classification.

## What the runtime can compose (ground truth)

`setup.sh` installs only `runtime/`, `resources/`, `compat.env`, `permissions/`
into the managed dir — **NOT `package.json` or `sbom.cdx.json`**. So at the
installed location the runtime cannot read the version from `package.json` or the
dependency graph from the SBOM. The launcher (`pi-code`) has `PI_CODE_VERSION`
and writes it to `.cct-init.json`, but does **not** pass it to the runtime.

| FR-027 field | Runtime source | Availability |
|---|---|---|
| **version** | `CCT_VERSION` env (launcher) → fallback `package.json` (dev) → `"unknown"` | needs one launcher line (below) |
| **source** | the documented install identity `git:github.com/gosha70/code-copilot-team` | available (constant) |
| **enabled modules** | `seedCapabilities()` — counts by `runtime_status` | available |
| **security classification** | `security_level`s live in `catalog.yaml` / `COMPATIBILITY.md`, NOT in the runtime seed (`seedCapabilities()` carries kind × status only), and the runtime has no YAML parser | **absent → pointer** (`shared/capabilities/COMPATIBILITY.md`) |
| **scope + trust state** | `load(opts)` (trust resolution + profile) — same as `doctor` | available |
| **dependency status** | runtime deps: **none** (stated); build-only devDeps live in the SBOM | available (summary) |
| **checksum** | — not installed at runtime | **absent → null** (in the release `SHA256SUMS`) |
| **full SBOM / dep graph** | — not installed at runtime | **absent → pointer** (`adapters/pi/sbom.cdx.json`, release artifact) |

Honesty discipline (unchanged): a field the runtime cannot obtain is reported
**`null`/absent with a pointer to where it lives** (the release artifacts), never
fabricated.

## Version source (the one real decision)

The launcher owns the version (`PI_CODE_VERSION`) and it is NOT installed as a
file. Cleanest: **the launcher passes it via env** — one line in `pi-code`:

```sh
export CCT_VERSION="$PI_CODE_VERSION"
```

`provenance` reads `process.env.CCT_VERSION`; **fallback** to reading the repo
`package.json` version when the env is absent (direct `node` / tests); else
`"unknown"`. This keeps `PI_CODE_VERSION` (launcher) the single source and needs
no file install.

## Command shape

A new `provenance` case in `cli.ts` `runCli`, `--json` + text like the others:

```ts
function provenance(opts: CliOptions, json: boolean): CliResult
```

Text:
```
=== provenance ===
package:      code-copilot-team-pi 1.1.0
source:       git:github.com/gosha70/code-copilot-team
scope:        <profile> · trust: <trusted|untrusted>
dependencies: runtime: none (build-only devDeps in the SBOM)
capabilities: 19 total · 8 enabled · 9 degraded · 2 disabled   (authority: COMPATIBILITY.md)
security:     classification in shared/capabilities/COMPATIBILITY.md (not bundled at runtime)
checksum:     (not available at runtime — see the release SHA256SUMS)
sbom:         adapters/pi/sbom.cdx.json (release artifact)
```

JSON: the same as a structured object, with `null` for absent fields.

Read-only, redacted (it prints no config values — only counts + identity), and
composes `features`/`doctor` data rather than duplicating it.

## Enforceable vs declared

| element | status |
|---|---|
| version / source / scope / trust / capability summary | **exposed** (composed from real surfaces) |
| dependency status (runtime: none) | **exposed** (stated; full graph in the SBOM) |
| checksum / full SBOM / security-level classification at runtime | **absent → null/pointer** — honest, not fabricated. Checksum + SBOM point to the release artifacts; the security-level taxonomy (enforcing/critical/advisory) lives in `catalog.yaml`/`COMPATIBILITY.md`, which are not bundled into the managed runtime (and the runtime has no YAML parser). |

## Scope (in / out)

**In:** `pi-code provenance [--json]` (`cli.ts` `provenance()` + dispatch); one
`export CCT_VERSION` line + a usage-help line in `pi-code`; a version helper
(env → package.json → unknown); tests (`cli`/adapter: text + JSON shape, absent
fields are null, version resolves from env). Design doc.

**Out:** installing `package.json`/SBOM into the managed runtime (unneeded — env
carries the version); computing a live checksum at runtime; changing the
capability registry.

## Open questions for approval

1. **Version source** — `CCT_VERSION` env from the launcher (+ `package.json`
   fallback for dev/tests, else `"unknown"`). Lean: **yes** (launcher owns it; no
   file install needed).
2. **Absent-at-runtime fields** — `checksum`, the full SBOM/dep-graph, and the
   security-level classification are reported **absent with a pointer** (null /
   `{available:false, ...}`) to where each lives, not fabricated. Confirm.
3. **Composition** — `provenance` aggregates version/source + capability
   summary + trust/scope, read-only, `--json` + text; it does not duplicate
   `features`/`doctor`, it composes them. Confirm.

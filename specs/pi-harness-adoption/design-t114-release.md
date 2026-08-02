# T11.4 Design Read — SBOM, checksums, release workflow, changelog, publishing (DoD item 13 / FR-027)

Status: **design read — approval needed on the artifact set, the version source,
and the provenance scope before implementing.** T11.4 is the final P1. It is
release *tooling + a changelog + an SBOM* — greenfield (no CHANGELOG / SBOM /
checksums / release workflow exist today).

## Ground truth

- **The Pi package is dependency-free.** `code-copilot-team-pi` v0.1.0,
  `dependencies: none`; devDeps (`typescript`, `@types/node`) are **build/
  type-check only**, not shipped. So the SBOM is small and honest.
- **Install path is git-tag based** — `pi install git:…@<tag>` clones the repo at
  a tag. There is **no external registry**; "publish" = the tag + a GitHub
  Release.
- **A `v1.0.0` tag already exists**, but `package.json` says `0.1.0` — a version
  mismatch to resolve (decision 5).
- **`resources()` already reads `resources/provenance.json`** (skill/prompt
  source), and `features` reports capabilities — but the runtime has **no
  version or checksum data source**, so a `pi-code provenance` command would not
  compose cleanly today (decision 4).
- **`dist/` is already git-ignored** — the natural staging dir.
- Existing workflows (`pi-tests.yml`) give the CI shape to mirror (ubuntu, node
  22, `npm ci`, run gates).

## Proposed artifact set

| Artifact | Committed? | Produced by | Purpose |
|---|---|---|---|
| `CHANGELOG.md` | **yes** | authored (Keep a Changelog) | source of release notes |
| `adapters/pi/sbom.cdx.json` | **yes** (drift-guarded) | `scripts/generate-sbom.sh` | CycloneDX component/dependency manifest |
| `SHA256SUMS` | **no** (release artifact) | `scripts/prepare-release.sh` → `dist/` | per-file checksums over the Pi package tree |
| `dist/RELEASE_NOTES.md` | **no** (staging) | `prepare-release.sh` (extract latest CHANGELOG section) | GitHub Release body |
| GitHub Release (on tag) | n/a | `release.yml` | attaches sbom + SHA256SUMS + notes |

Rationale for committed-vs-generated: the **SBOM is stable** (deps:none — changes
only on a version/component change) → commit + drift-guard, like
`COMPATIBILITY.md`. **SHA256SUMS changes on any content edit** → not stable →
generated at release time, not committed.

## Generator contract — `scripts/generate-sbom.sh`

Mirrors `generate-capability-docs.sh`:

- **default** → write `adapters/pi/sbom.cdx.json`.
- **`--check`** → regenerate to a temp buffer, diff the committed SBOM, exit
  non-zero on drift (the guard). Wired into `test-pi-adapter.sh`.
- **`--stdout`** → print.

Deterministic (no timestamps / random serials — pass a fixed `version` from the
package, no `Date.now`). CycloneDX 1.5 JSON: one primary component
(`code-copilot-team-pi`), the external runtime requirement (`pi >= 0.79.0` from
`compat.env`) as a dependency with scope `required`, and the build-only devDeps
marked scope `optional`/`excluded`. Honest: an empty runtime-dependency graph is
stated, not padded.

## Prepare contract — `scripts/prepare-release.sh [version]`

The **local dry-run** the workflow also calls (testability lean):

1. verify the SBOM is current (`generate-sbom.sh --check`) — fail if stale.
2. resolve the version (arg > `git describe`/tag > `package.json`); **fail if the
   tag and `package.json` disagree** (forces decision 5 to stay resolved).
3. generate `dist/SHA256SUMS` over the Pi package tree (sorted, deterministic).
4. extract the matching `CHANGELOG.md` section → `dist/RELEASE_NOTES.md`.
5. print a summary. **No network, no publishing.**

Everything lands in `dist/` (git-ignored). Runs fully offline → testable.

## Workflow contract — `.github/workflows/release.yml`

- **trigger:** `on: push: tags: ['v*.*.*']`.
- **permissions:** `contents: write` (create the Release) — nothing else.
- **steps:** checkout → setup node 22 + ruby → `npm ci` → **run the required
  gates** (pi runtime suite, adapter suite, `validate-capabilities.sh`, the SBOM
  + capability-doc `--check` drift guards) → `bash scripts/prepare-release.sh` →
  `gh release create "$TAG" dist/SHA256SUMS adapters/pi/sbom.cdx.json
  --notes-file dist/RELEASE_NOTES.md`.
- **No registry push.** The install path (`pi install …@<tag>`) is unchanged and
  documented as advisory.

## FR-027 provenance — how it is exposed (decision 4)

FR-027 wants each package to *expose* source, version, checksum, scope, trust,
enabled modules, dependency status, security classification. **Recommended
(Option A):** these are exposed by the release artifacts + existing reports, no
new runtime command:

| FR-027 field | Exposed by |
|---|---|
| source | the git tag / commit (GitHub Release) |
| version | the tag + `package.json` (kept in sync) |
| checksum | `SHA256SUMS` (release artifact) |
| dependency status | `sbom.cdx.json` (deps:none, stated) |
| enabled modules + security classification | the capability registry / `pi-code features` / `COMPATIBILITY.md` |
| scope + trust state | `pi-code doctor` (trust + profile + floor) |

A dedicated `pi-code provenance` command (Option B) would need new runtime
plumbing (version + checksum data sources) and is a **runtime change beyond
T11.4's release-tooling scope**. Per your own guidance ("otherwise extend
`resources --json` only if the data model already fits" — it does not today), I
lean **Option A** and document the mapping in the release docs, leaving a
`pi-code provenance` command as a named follow-up.

## Scope (in / out)

**In:** `CHANGELOG.md`; `scripts/generate-sbom.sh` + committed
`adapters/pi/sbom.cdx.json` (drift-guarded in `test-pi-adapter.sh`);
`scripts/prepare-release.sh` (offline dry-run) + a test that it produces the
artifacts; `.github/workflows/release.yml`; a short "Release & provenance"
section in the Pi docs mapping FR-027; design doc.

**Out:** an external registry push; a `pi-code provenance` runtime command
(follow-up); any runtime source change.

## Open questions for approval

1. **Artifact set + committed-vs-generated split** — SBOM committed +
   drift-guarded; SHA256SUMS + notes generated into `dist/`. Confirm.
2. **SBOM format/location** — CycloneDX 1.5 JSON at `adapters/pi/sbom.cdx.json`,
   deterministic, generated by `generate-sbom.sh`. Confirm (vs SPDX / a
   different path).
3. **Workflow** — tag-triggered, runs the gates, prepare-release, `gh release
   create` with artifacts + CHANGELOG notes, `contents: write`, no registry.
   Confirm.
4. **Provenance** — Option A (artifacts + existing reports expose FR-027; document
   the mapping) vs Option B (new `pi-code provenance` command). Lean **A**.
5. **Version source** — the release version comes from the **tag** (authoritative);
   `prepare-release.sh` fails if `package.json` disagrees. **This surfaces the
   existing 0.1.0-vs-v1.0.0 mismatch** — should I bump `package.json` to match
   the intended release line (and what version — align to `1.0.x`, or start the
   Pi package at its own `0.1.0` line)? Your call.

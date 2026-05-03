# Domain Pack — Versioned Content Distribution (JVM + Python)

## Stack
- **Content format**: TBX 3.0 (ISO 30042) for terminology — generalizes to JSON-LD, Turtle, CSV, regex rule sets, allow/deny-lists, ontology subsets.
- **Manifest**: YAML — declares pack name, version, schema version, license (data + code), source attribution.
- **JVM wrapper**: Java 17+, Gradle (Kotlin DSL), `java-library` + `maven-publish` + signing → Maven Central.
- **Python wrapper**: Python 3.10+, `pyproject.toml` (PEP 621), `setuptools` with `package_data` → PyPI.
- **Coordinated release**: same SemVer string flows to both registries; one tag triggers a dual publish.
- **Schema validation**: every PR runs content through a format-specific validator (TBX validator for terminology, JSON Schema for JSON-LD, etc.) so malformed content fails at PR time, not at consumer install time.

## Architecture

```
├── content/                    # Single source of truth — never duplicated.
│   ├── data.tbx                # Or .ttl / .jsonld / .csv / .yaml — pack-specific.
│   ├── manifest.yaml           # name, version, schema_version, licenses, sources.
│   └── LICENSE-DATA            # Data license (often differs from wrapper-code license).
├── jvm-wrapper/                # JVM consumer surface.
│   ├── build.gradle.kts        # 'java-library' + 'maven-publish' + signing.
│   ├── settings.gradle.kts
│   └── src/
│       ├── main/
│       │   ├── java/.../       # Loader API (PackLoader, PackEntry, PackManifest).
│       │   └── resources/
│       │       └── <pack>/     # Synced from ../content at build time.
│       └── test/java/.../      # JUnit tests that load the sample content.
├── python-wrapper/             # Python consumer surface.
│   ├── pyproject.toml          # PEP 621; package_data points at src/<pkg>/data/.
│   └── src/<pack_name>/
│       ├── __init__.py         # Public API mirrors the JVM loader.
│       ├── loader.py
│       ├── models.py
│       └── data/               # Synced from ../content at build time.
│   └── tests/
├── scripts/
│   ├── sync-content.sh         # Sync content/ → both wrappers' resource dirs.
│   └── publish.sh              # Coordinated dual release (Maven Central + PyPI).
├── .github/workflows/
│   ├── pack-content.yml        # Schema validation on every PR.
│   └── pack-publish.yml        # On tag, dual publish (gated on signing creds).
├── PROJECT.md                  # This file.
└── specs/                      # SDD artifacts and lessons learned.
```

## Architecture Rules
> **Non-negotiable.** Violations must be flagged during review, not silently accepted.

- **Single content source.** `content/` is the only authoritative copy. Wrappers reference it via the sync script — never duplicate, never edit the synced copy directly.
- **Coordinated versioning.** The version string in `content/manifest.yaml` is the source of truth. `build.gradle.kts` and `pyproject.toml` read it; release tags must match.
- **Mirrored loader API.** The JVM loader and Python loader expose the same surface (`load()`, `entries()`, `manifest()`, `version()`). Adding a method on one side without the other is a defect.
- **Reference-based reads.** Loaders return iterators / streams — never load the entire dataset into memory eagerly unless the consumer asks (`load_all()`).
- **No wrapper-side data transforms.** Wrappers parse and expose; they do not enrich, normalize, or filter content. Consumers do that downstream. This keeps the pack reproducible across language ecosystems.
- **License separation.** Data license (in `LICENSE-DATA`) is independent of code license (in the wrapper module's `LICENSE`). Manifest declares both explicitly.

## Versioning Policy
- **SemVer applies to the consumer-visible API and content shape.**
  - **Major** — schema change, removal of an entry/term, breaking change to loader API.
  - **Minor** — additive content changes, new optional manifest fields, new loader methods.
  - **Patch** — typo fixes, attribution corrections, no semantic content change.
- **Removing an entry is a breaking change.** Even in a minor-looking change. Consumers may pin to that entry's `id`. If you must drop content, bump major.
- **Both registries get the same SemVer string.** No `-jvm` / `-py` suffix divergence.
- **Pre-release tags** (`1.0.0-rc.1`) publish to staging registries only; CI gates production publish on the absence of pre-release suffixes.

## Schema Validation
- The CI workflow `pack-content.yml` runs the following gates on every PR; failure blocks merge.
  - **Manifest** — `content/manifest.yaml` is validated against `content/manifest.schema.json` (JSON Schema 2020-12) using `jsonschema`. Both files ship in this template.
  - **Content presence** — the file declared in `content_file` must exist.
  - **TBX** — `xmllint --noout` confirms the content is well-formed XML. Drop `content/tbx.xsd` or `content/tbx-basic.dtd` into the pack to upgrade the gate to full structural schema validation; the workflow auto-detects either file and runs `xmllint --schema` / `--dtdvalid` accordingly.
  - **Wrapper sync** — `scripts/sync-content.sh` is exercised so a misconfigured content layout fails at PR time rather than at release time.
- **Never bypass this gate** — malformed content discovered at consumer install time is a 10× worse defect than catching it on PR.
- For other content formats (JSON-LD, Turtle, CSV), extend `pack-content.yml` with the appropriate validator (`pyld`, `riot --validate`, header schema). The manifest's `content_format` field gates which validator runs.

## Manifest Contract
`content/manifest.yaml` must declare, at minimum:
```yaml
name: nemo-pack-legal-en
version: 1.0.0
schema_version: 1
description: "Legal-domain English terminology pack."
content_format: tbx-3.0
content_file: data.tbx
licenses:
  data: CC-BY-SA-4.0
  code: Apache-2.0
sources:
  - name: IATE
    url: https://iate.europa.eu/
    license: CC-BY-4.0
  - name: EuroVoc
    url: https://op.europa.eu/en/web/eu-vocabularies
    license: CC-BY-4.0
```
The loaders read this manifest and expose it via `manifest()`. Consumers should not parse YAML themselves.

## Commands

```bash
# Sync content/ into both wrappers' resource dirs (run before build/test/publish).
bash scripts/sync-content.sh

# JVM wrapper
(cd jvm-wrapper && ./gradlew build)
(cd jvm-wrapper && ./gradlew test)
(cd jvm-wrapper && ./gradlew publishToMavenLocal)

# Python wrapper
(cd python-wrapper && pip install -e ".[dev]")
(cd python-wrapper && pytest)
(cd python-wrapper && python -m build)

# Coordinated release (requires PYPI_TOKEN, OSSRH_USERNAME, OSSRH_TOKEN, SIGNING_KEY).
bash scripts/publish.sh
```

## Testing
- **Content tests** — schema validators run on every PR (no manual step).
- **JVM loader tests** — JUnit 5; a real test resource directory loads sample content and asserts manifest fields, entry count, and a known entry's shape.
- **Python loader tests** — pytest; mirrors the JVM assertions exactly so any divergence is caught immediately.
- **Loader-parity test** (recommended) — a single fixture comparing JVM and Python output on the same sample content, run nightly or on release-candidate tags.

## Agent Team

### Roles

| Role | Trigger | Owns |
|------|---------|------|
| **Team Lead / Pack Maintainer** (default) | Versioning decisions, release coordination, manifest contract, license review | Overall, `content/manifest.yaml`, `PROJECT.md` |
| **Content Curator** | Adding/removing/correcting entries, source attribution, schema bumps | `content/` |
| **JVM Wrapper Engineer** | Loader API on the JVM side, Gradle build, Maven Central publishing | `jvm-wrapper/` |
| **Python Wrapper Engineer** | Loader API on the Python side, build/test, PyPI publishing | `python-wrapper/` |
| **Release & CI Engineer** | Validators, dual-publish workflow, signing credential management | `.github/workflows/`, `scripts/` |

### Team Lead — Default Behavior
You ARE the Team Lead. For every user request:
1. Determine whether the request is **content** (data change), **wrapper** (loader/build), or **release** (versioning, publish, CI). Single-domain → handle directly or delegate to one specialist.
2. Cross-cutting changes (e.g., new manifest field) require coordinated edits in `content/manifest.yaml`, both loaders, and both test suites — coordinate, don't delegate piecemeal.
3. Every entry-removal request is a breaking change. Confirm intent and bump major in manifest.
4. Reject any wrapper change that diverges the JVM and Python public APIs without an explicit reason logged in the PR description.
5. Never ship a release where `content/manifest.yaml` version disagrees with the git tag.

### Delegation Prompts
```
You are the [ROLE] on a domain-pack distribution project.

Architecture: Single content/ source feeds two thin wrappers (jvm-wrapper/, python-wrapper/)
that publish coordinated releases to Maven Central and PyPI. Loader APIs are mirrored.

Your task: [specific task description]

Constraints:
- content/ is single source of truth — never edit synced copies in wrapper resource dirs
- JVM and Python loader APIs must stay in sync (same method names, same return shapes)
- Manifest version is authoritative; build files and tags must match
- License separation: LICENSE-DATA != wrapper LICENSE
- [role-specific constraints below]
- Return: code changes + summary of what was changed and why
```

### Content Curator
Expertise: TBX 3.0 / JSON-LD / Turtle authoring, term terminology and disambiguation, source attribution, license compatibility.
Constraints: never alter an existing entry's `id` (consumers pin to it). Removing or renaming an entry requires a major version bump. Every entry must have a verifiable source citation. Schema bumps require a migration note in `CHANGELOG.md`.

### JVM Wrapper Engineer
Expertise: Gradle Kotlin DSL, `java-library` + `maven-publish` + `signing` plugins, Maven Central staging workflow (Nexus / Central Portal), JUnit 5, JAR resource loading via `ClassLoader.getResourceAsStream`.
Constraints: Loader must read content from `src/main/resources/<pack>/` only — never from arbitrary filesystem paths. Use `Iterator<PackEntry>` for streaming reads. POM metadata (license, SCM, developer) is required for Central. Sign every artifact.

### Python Wrapper Engineer
Expertise: PEP 621 `pyproject.toml`, `setuptools` `package_data`, `importlib.resources` for portable resource access, pytest, `build` + `twine` for PyPI publishing.
Constraints: Loader must access content via `importlib.resources` — never hardcoded paths. Type-annotated public API; mypy strict on `loader.py` and `models.py`. Wheels must be `py3-none-any` (pure Python).

### Release & CI Engineer
Expertise: GitHub Actions, Maven Central signing key handling, PyPI trusted publishing, semver enforcement, schema validators (`xmllint`, `pyld`, `riot`).
Constraints: Both publish steps must succeed or the release is aborted (no half-published versions). Pre-release tags publish to staging only. Manifest version mismatch with the tag aborts the workflow. Never store credentials outside GitHub Secrets / OIDC.

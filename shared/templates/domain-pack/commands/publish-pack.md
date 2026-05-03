# /publish-pack

Cut a coordinated release to Maven Central + PyPI.

## Pre-release checklist

- [ ] `content/manifest.yaml` `version` bumped per SemVer (major if entries removed/renamed, minor if additive, patch otherwise).
- [ ] Both wrappers' test suites pass on `master`/`main`.
- [ ] CHANGELOG (or release notes) updated with the same version.
- [ ] License-data file in `content/` reviewed if sources changed.
- [ ] Required secrets configured in the GitHub repo: `SIGNING_KEY`, `SIGNING_PASSWORD`, `OSSRH_USERNAME`, `OSSRH_TOKEN`, **and** PyPI trusted publishing OR `PYPI_TOKEN`.

## Cut the release

```bash
# Tag the release (must match content/manifest.yaml)
v=$(awk -F': *' '/^version:/ { gsub(/"/, "", $2); print $2; exit }' content/manifest.yaml)
git tag -a "v$v" -m "Release v$v"
git push origin "v$v"
```

The `pack-publish.yml` workflow:

1. **preflight** — verifies the tag matches `content/manifest.yaml`.
2. **publish-jvm** — builds, signs, and publishes to Maven Central (skipped with a notice if `SIGNING_KEY` is empty).
3. **publish-pypi** — builds sdist + wheel, publishes via PyPI trusted publishing.

If either publish step fails, **do not retag with the same version** — bump patch and retry. Maven Central rejects re-publishes of the same coordinates; PyPI yanks but does not allow overwrites.

## Local dry run

```bash
bash scripts/publish.sh
```

Uses `publishToMavenLocal` for the JVM side so you can verify artifact shape without touching Central. PyPI side requires `PYPI_TOKEN` or it will prompt.

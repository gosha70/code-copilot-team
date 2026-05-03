# /publish-plugin

Publish the plugin to the Gradle Plugin Portal.

## Pre-release checklist

- [ ] `gradle/libs.versions.toml` `pluginVersion` bumped per SemVer (major if a public type was removed/renamed, minor if additive, patch otherwise).
- [ ] All unit + functional tests green on the version you're about to ship.
- [ ] `sample-consumer/` builds end-to-end with the new plugin version.
- [ ] CHANGELOG (or release notes) updated with the same version.
- [ ] GitHub Secrets `GRADLE_PUBLISH_KEY` and `GRADLE_PUBLISH_SECRET` configured (Plugin Portal API credentials from <https://plugins.gradle.org/u/me>).
- [ ] `gradlePlugin { website / vcsUrl / plugins { displayName / description / tags } }` in `plugin/build.gradle.kts` filled in (not the template placeholders).

## Cut the release

```bash
v=$(awk -F'"' '/^[[:space:]]*pluginVersion[[:space:]]*=/ { print $2; exit }' gradle/libs.versions.toml)
git tag -a "v$v" -m "Release v$v"
git push origin "v$v"
```

The `gradle-plugin.yml` workflow:

1. **unit + functional + sample-consumer** — gating jobs run as on every push.
2. **publish** (tag-only) — preflights that the version catalog matches the tag, checks for credentials, then runs `./gradlew :plugin:publishPlugins`. Skipped with a notice if credentials aren't configured.

If the publish step fails, **do not retag with the same version** — bump patch and retry. The Plugin Portal does not allow republishing the same coordinates.

## Local dry run

```bash
# Validate the publication metadata without uploading
./gradlew :plugin:validatePlugins
./gradlew :plugin:publishPluginJar :plugin:generatePomFileForExamplePluginPublication
```

If you have credentials in `~/.gradle/gradle.properties`, you can do a real
publish from your laptop with `./gradlew :plugin:publishPlugins`. Prefer the
CI path — the env-var-driven flow is what's reproducible.

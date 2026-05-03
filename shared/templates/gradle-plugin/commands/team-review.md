# /team-review

Coordinate a multi-role review of the current change.

## When to Run
- After any change to the plugin source, functional tests, sample consumer, build scripts, or CI workflow.
- Before tagging a release.

## Procedure

1. **Team Lead** opens by stating the change in one sentence and which domains it touches: plugin code, functional tests, sample consumer, build/version-catalog, CI.
2. Spawn the relevant specialist via the Agent tool. Use the delegation prompt in `PROJECT.md` and substitute the role.
3. Each role checks its constraints:
   - **Plugin Engineer** — no `tasks.create`, no `afterEvaluate`, every property is a `Property<T>`/`Provider<T>`, every task input/output is annotated, public API is stable.
   - **Functional Test Engineer** — every new public API has a TestKit functional test asserting on `TaskOutcome`. The matrix still covers the minimum supported Gradle version. `sample-consumer/` still builds end-to-end.
   - **Build & Release Engineer** — `gradle/libs.versions.toml` `pluginVersion` is consistent with any release tag. `com.gradle.plugin-publish` config is intact (`gradlePlugin { plugins {} }` block, website/vcs URLs, tags). No credentials committed.
4. **Team Lead** synthesizes findings, blocks merge on any failure, and (only after green) approves the change.

## Output
A short review summary in the PR description listing each role, the checks they ran, and the disposition (PASS / FAIL / N/A).

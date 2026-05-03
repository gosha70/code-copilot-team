# Gradle Plugin — Idiomatic `Plugin<Project>` with TestKit

## Stack
- **Plugin language**: Kotlin (JVM target 17). Gradle plugins authored in Kotlin get strongly-typed access to the Gradle API and avoid Groovy's loose-typing footguns.
- **Build**: Gradle 8.x (Kotlin DSL), single `:plugin` module hosting both `test` and `functionalTest` source sets, plus `sample-consumer/` as an out-of-tree consumer build.
- **Plugin scaffolding**: `java-gradle-plugin` (provides the `gradlePlugin {}` DSL, `pluginManager` testing helpers, and metadata for the Plugin Portal).
- **Publishing**: `com.gradle.plugin-publish` — Gradle Plugin Portal. Maven Central is optional; configure it only if you also want non-portal consumers.
- **Testing**: JUnit 5 for unit tests, Gradle TestKit for functional tests, multi-Gradle-version matrix in CI.
- **Style**: [`idiomatic-gradle`](https://github.com/jjohannes/idiomatic-gradle) conventions — lazy task configuration via `Property<T>`/`Provider<T>`, `tasks.register` (never `tasks.create`), strict configuration-cache compatibility.

## Architecture

```
├── settings.gradle.kts            # Root settings; includes :plugin only.
├── build.gradle.kts               # Root build (allprojects config, repositories).
├── gradle/
│   └── libs.versions.toml         # Version catalog — SINGLE SOURCE OF TRUTH for deps.
├── plugin/
│   ├── build.gradle.kts           # `java-gradle-plugin` + `com.gradle.plugin-publish`
│   │                              # + `jvm-test-suite`. Registers the `functionalTest`
│   │                              # source set and wires it via
│   │                              # `gradlePlugin.testSourceSets(...)` so TestKit's
│   │                              # `withPluginClasspath()` works.
│   └── src/
│       ├── main/kotlin/com/example/gradleplugin/
│       │   ├── ExamplePlugin.kt   # `class ExamplePlugin : Plugin<Project>`
│       │   ├── ExampleExtension.kt   # DSL extension exposed to user build script
│       │   └── ExampleTask.kt     # `abstract class ExampleTask : DefaultTask` (lazy properties)
│       ├── test/kotlin/com/example/gradleplugin/
│       │   └── ExamplePluginTest.kt   # ProjectBuilder unit tests (in-process)
│       └── functionalTest/kotlin/com/example/gradleplugin/
│           └── ExamplePluginFunctionalTest.kt   # TestKit-based; runs against a Gradle-version matrix.
├── sample-consumer/               # Out-of-tree project that applies the plugin via includeBuild.
│   ├── settings.gradle.kts        # `pluginManagement { includeBuild("../") }`.
│   └── build.gradle.kts           # `plugins { id("com.example.gradle-plugin") }`.
├── .github/workflows/
│   └── gradle-plugin.yml          # Unit tests + functional-test matrix + portal publish on tag.
├── PROJECT.md
└── specs/                         # SDD artifacts and lessons learned.
```

## Architecture Rules
> **Non-negotiable.** Violations must be flagged in review, not silently accepted.

- **Lazy by default.** Every task input is a `Property<T>`, `ListProperty<T>`, `MapProperty<K,V>`, or `Provider<T>`. Never read `extension.someValue` eagerly in the plugin's `apply()` method — wire it as a `Provider` so configuration-cache and incremental builds work.
- **`tasks.register`, never `tasks.create`.** `register` is the configuration-avoidance API; `create` forces eager realization and breaks lazy configuration. Same for `configurations.register` over `configurations.create`.
- **Plugin code and tests both live in `:plugin`** — the `test` source set holds in-process unit tests, the `functionalTest` source set holds TestKit tests. The functional source set is registered with `gradlePlugin.testSourceSets(...)` so the `java-gradle-plugin` plugin emits `plugin-under-test-metadata.properties` on its runtime classpath. Without that registration, `GradleRunner.withPluginClasspath()` throws `InvalidPluginMetadataException`.
- **`gradlePlugin { plugins {} }` declares plugin IDs in the build script.** Never hand-write `META-INF/gradle-plugins/<id>.properties` — the `java-gradle-plugin` plugin generates it from the DSL.
- **Configuration-cache compatible.** No `Project` references captured into task actions. No `System.getenv` / `System.getProperty` reads at execution time — read at configuration time and pipe through a `Provider`.
- **Worker API for parallelism.** If a task does CPU-bound or I/O-bound work in parallel, use `WorkerExecutor` + `WorkAction`. Never spawn raw threads from a task action.
- **Public API is the extension and the plugin ID.** Anything else is internal — name internal types `Internal*` or place them in an `internal` package and document instability.

## Plugin Authoring Rules
- Plugin IDs follow reverse domain: `com.example.gradle-plugin` (lowercase, hyphens).
- The plugin class is **not** the extension class. Keep them separate.
- Extensions are configured via `project.extensions.create(...)` in `apply()`. Use `nested` extensions for grouped settings.
- Tasks declared by the plugin must extend `DefaultTask` (or a built-in task type) and use `@get:Input` / `@get:OutputFile` / `@get:OutputDirectory` annotations on every property — this is what makes incremental builds and the build cache work.
- Avoid `afterEvaluate {}`. If you find yourself reaching for it, you almost certainly need `Provider`-based wiring instead.
- Never modify another plugin's tasks at configuration time. Use the appropriate `Plugins` extension hook (e.g. `plugins.withId("java") { ... }`).

## Functional Test Rules
- TestKit tests live in the `functionalTest` source set inside `:plugin` (`plugin/src/functionalTest/`) — never in `src/test/`. The source set is wired via `gradlePlugin.testSourceSets(...)`; do not bypass that registration or `withPluginClasspath()` will fail.
- Each functional test seeds a temporary Gradle project (settings, build script, sample sources) and runs `GradleRunner.create().withPluginClasspath().build()`.
- Run the matrix against multiple Gradle versions. The default matrix is `8.5`, `8.10`, `latest` — adjust per project but always test both the minimum supported and latest.
- Functional tests must assert on task outcome (`SUCCESS` / `UP_TO_DATE` / `FROM_CACHE`), not just exit code, to catch incremental-build regressions.

## Sample Consumer Rules
- `sample-consumer/` is **not** a Gradle subproject. It's an independent build that uses `pluginManagement { includeBuild("../") }` to consume the plugin via composite build.
- Run `cd sample-consumer && ./gradlew check` (using the consumer's wrapper) as a smoke test of the end-to-end consumer experience.
- Do not check in `sample-consumer/build/` or any wrapper-generated files — `.gitignore` handles this.

## Publishing Rules
- **Plugin Portal first.** `com.gradle.plugin-publish` is the canonical distribution channel for Gradle plugins. Configure it before considering Maven Central.
- Publish credentials come from env vars (`GRADLE_PUBLISH_KEY`, `GRADLE_PUBLISH_SECRET`) or `~/.gradle/gradle.properties`. Never commit them.
- Tag-driven release: pushing `v1.2.3` runs the publish workflow which validates that `gradle/libs.versions.toml` (or `version =` in `plugin/build.gradle.kts`) matches the tag.
- All public types must follow strict semver — adding a property to an extension is a minor bump, removing/renaming is major. The functional test matrix protects against accidental Gradle-API breakage.

## Commands

```bash
./gradlew check                                    # unit tests + functional tests + compile
./gradlew :plugin:test                             # unit tests only
./gradlew :plugin:functionalTest                   # TestKit functional tests (current Gradle)
./gradlew :plugin:functionalTest -PgradleTestVersion=8.5   # specific Gradle version
./gradlew :plugin:publishPlugins                   # publish to Plugin Portal (requires creds)
(cd sample-consumer && ./gradlew check)            # end-to-end consumer smoke test
```

## Agent Team

### Roles

| Role | Trigger | Owns |
|------|---------|------|
| **Team Lead / Plugin Architect** (default) | Plugin API design, extension DSL, configuration-cache compat, release coordination | Overall, `:plugin` public surface, `PROJECT.md` |
| **Plugin Engineer** | Implementing tasks, extensions, plugin lifecycle, lazy configuration | `plugin/src/main/` |
| **Functional Test Engineer** | TestKit harnesses, Gradle-version matrix, configuration-cache assertions | `plugin/src/functionalTest/`, `sample-consumer/` |
| **Build & Release Engineer** | Version catalog, `com.gradle.plugin-publish` config, GHA workflow, signing | `gradle/`, `.github/workflows/`, root build files |

### Team Lead — Default Behavior
You ARE the Team Lead. For every user request:
1. Determine whether the task is **plugin code** (extension/task), **test infrastructure** (TestKit, sample-consumer), or **release** (publishing, version catalog, CI). Single-domain → handle directly or delegate to one specialist.
2. Cross-cutting changes (e.g. new extension property → wire through plugin → assert in functional test → bump version) require coordinated edits — coordinate, don't delegate piecemeal.
3. Reject any task implementation that captures `Project` into a task action, uses `tasks.create`, or reads from the extension eagerly in `apply()`. These are configuration-cache violations.
4. Reject any new public API that doesn't have a matching functional test asserting on task outcome.
5. Never ship a release where the version catalog or `plugin/build.gradle.kts` version disagrees with the git tag.

### Delegation Prompts
```
You are the [ROLE] on a Gradle plugin project.

Architecture: Single-module Gradle build. `:plugin` holds the Plugin<Project>
impl + extension + tasks, plus two test source sets: `test` (in-process
ProjectBuilder unit tests) and `functionalTest` (TestKit functional tests
against a matrix of Gradle versions, wired via `gradlePlugin.testSourceSets`).
`sample-consumer/` is an out-of-tree composite build that applies the plugin
end-to-end.

Your task: [specific task description]

Constraints:
- Lazy configuration only — Property<T>/Provider<T>, tasks.register, no afterEvaluate
- Configuration-cache compatible: no Project capture, no exec-time env reads
- Public API: extension class + plugin ID. Internal types in `internal` package.
- [role-specific constraints below]
- Return: code changes + summary of what was changed and why
```

### Plugin Engineer
Expertise: Gradle Plugin API (`Plugin<Project>`, `Project.extensions`, `Project.tasks`), lazy configuration (`Property<T>`, `Provider<T>`, `ObjectFactory`), task input/output annotations, `WorkerExecutor`, `Plugins.withId`, IntelliJ IDEA plugin integration.
Constraints: Never use `tasks.create`, `configurations.create`, or `afterEvaluate {}`. Every task input/output is annotated for incremental builds. Public types stable across minor versions. Internal types in `internal` package or `Internal*`-prefixed.

### Functional Test Engineer
Expertise: Gradle TestKit (`GradleRunner`, `withPluginClasspath`, `withGradleVersion`), JUnit 5, multi-Gradle-version matrices, configuration-cache assertions (`--configuration-cache` + `BuildResult.output`), composite-build patterns for sample-consumer.
Constraints: Functional tests live in `plugin/src/functionalTest/`, never in `src/test/`. The source set must stay registered via `gradlePlugin.testSourceSets(...)`. Every functional test asserts task outcome (`SUCCESS` / `UP_TO_DATE` / `FROM_CACHE`). Matrix tests both minimum supported and latest Gradle. Sample-consumer kept as an independent composite build, not a subproject.

### Build & Release Engineer
Expertise: Gradle version catalogs (`gradle/libs.versions.toml`), `com.gradle.plugin-publish` configuration, GitHub Actions matrix builds, Plugin Portal publishing flow, semver enforcement, GPG signing for optional Maven Central publishing.
Constraints: Version catalog is the sole version authority. Tag-driven publish must abort on mismatch with the catalog. Credentials never committed. Pre-release tags publish to a staging channel only (or are gated out entirely). The functional-test matrix runs on every PR — never gate it behind `if: contains('release')`.

# /functional-test

Run TestKit-based functional tests locally against the same matrix CI uses.

## Procedure

```bash
# Default: runs against the wrapper's Gradle version
./gradlew :plugin:functionalTest

# Specific Gradle version (matches what CI's matrix uses)
./gradlew :plugin:functionalTest -PgradleTestVersion=8.5
./gradlew :plugin:functionalTest -PgradleTestVersion=8.10
./gradlew :plugin:functionalTest -PgradleTestVersion=current

# End-to-end via the sample consumer (real composite build, real plugin apply)
(cd sample-consumer && ../gradlew exampleHello --stacktrace)
```

## What to assert in functional tests

Every functional test must assert on **task outcome**, not just exit code:

```kotlin
val result = runner().withArguments("myTask").build()
assertEquals(TaskOutcome.SUCCESS, result.task(":myTask")?.outcome)

// Re-run to verify incremental wiring
val second = runner().withArguments("myTask").build()
assertEquals(TaskOutcome.UP_TO_DATE, second.task(":myTask")?.outcome)
```

For tasks meant to be cached, also test `TaskOutcome.FROM_CACHE` after a clean.

## Common failures and what they mean

| Failure                                                    | Likely cause                                                          |
|------------------------------------------------------------|-----------------------------------------------------------------------|
| `NoSuchMethodError` from a Gradle API class                | API drift — failing version is outside the supported window           |
| Task outcome is `SUCCESS` on the second run, not `UP_TO_DATE` | Missing input/output annotation, or a non-deterministic input        |
| `Cannot mutate the build state in execution phase`         | Reading config-time state at execution time — wire via `Provider<T>` |
| TestKit hangs                                              | Daemon issue — set `org.gradle.testkit.dir` to a clean dir per test  |

## Refuse to merge if
- Any new public API lacks a functional test.
- Any functional test only asserts exit code without checking `TaskOutcome`.
- The matrix doesn't cover both the minimum supported Gradle version and the latest.

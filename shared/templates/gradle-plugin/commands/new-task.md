# /new-task

Add a new Gradle task type to the plugin.

## Procedure

1. **Decide the task's inputs and outputs.** Every input is `@get:Input`, `@get:InputFile`, or `@get:InputDirectory`. Every output is `@get:OutputFile` or `@get:OutputDirectory`. Anything that is neither is `@get:Internal`. No exceptions — Gradle uses these annotations to drive incremental builds and the build cache.

2. **Create the task class** under `plugin/src/main/kotlin/com/example/gradleplugin/`:
   ```kotlin
   abstract class MyNewTask : DefaultTask() {
       @get:Input
       abstract val someValue: Property<String>

       @get:OutputFile
       abstract val outputFile: RegularFileProperty

       @TaskAction
       fun run() {
           outputFile.get().asFile.writeText(someValue.get())
       }
   }
   ```
   The class must be `abstract` and every property `abstract val ...: Property<T>` so Gradle synthesises the implementation and injects the `ObjectFactory`. **Do not write a constructor.**

3. **Register the task in `ExamplePlugin.apply()`** using `tasks.register` (never `tasks.create`):
   ```kotlin
   project.tasks.register("myNewTask", MyNewTask::class.java) { task ->
       task.someValue.set(extension.someValue)
       task.outputFile.set(project.layout.buildDirectory.file("..."))
   }
   ```

4. **Add a unit test** under `plugin/src/test/kotlin/...` using `ProjectBuilder` (verifies registration + default values).

5. **Add a functional test** under `plugin/src/functionalTest/kotlin/...` that:
   - Seeds a synthetic build that applies the plugin and configures the extension.
   - Runs the task via `GradleRunner.create()`.
   - Asserts on `TaskOutcome.SUCCESS` for the first run.
   - Re-runs the task and asserts on `TaskOutcome.UP_TO_DATE` (proves incremental wiring).

6. Run locally:
   ```bash
   ./gradlew :plugin:check               # unit + functional via the check aggregate
   ./gradlew :plugin:functionalTest      # functional tests only
   ```

## Refuse to merge if
- Any input/output property is missing its annotation.
- The task is registered with `tasks.create` instead of `tasks.register`.
- There is no functional test asserting on `TaskOutcome` for the new task.
- The task action captures `project.<anything>` instead of using a `Provider`.

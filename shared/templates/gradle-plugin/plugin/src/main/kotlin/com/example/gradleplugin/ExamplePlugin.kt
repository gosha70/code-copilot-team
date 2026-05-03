package com.example.gradleplugin

import org.gradle.api.Plugin
import org.gradle.api.Project

/**
 * Plugin entry point. Registers the extension and a single task wired to it.
 *
 * Notes for maintainers:
 *  - We use `tasks.register` (configuration avoidance), never `tasks.create`.
 *  - The extension's `greeting` property is wired via `Provider`, so it is
 *    read at execution time, not eagerly in `apply()`. This keeps the plugin
 *    configuration-cache compatible.
 *  - Defaults go through `convention(...)` so consumer overrides win without
 *    requiring `afterEvaluate`.
 */
class ExamplePlugin : Plugin<Project> {

    override fun apply(project: Project) {
        val extension = project.extensions.create("example", ExampleExtension::class.java)
        extension.greeting.convention("Hello from ExamplePlugin")

        project.tasks.register("exampleHello", ExampleTask::class.java) { task ->
            task.group = "example"
            task.description = "Writes the configured greeting to an output file."
            task.greeting.set(extension.greeting)
            task.outputFile.set(project.layout.buildDirectory.file("example/greeting.txt"))
        }
    }
}

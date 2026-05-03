package com.example.gradleplugin

import org.gradle.api.DefaultTask
import org.gradle.api.file.RegularFileProperty
import org.gradle.api.provider.Property
import org.gradle.api.tasks.Input
import org.gradle.api.tasks.OutputFile
import org.gradle.api.tasks.TaskAction

/**
 * Reads `greeting` from the extension and writes it to an output file.
 *
 * Demonstrates the canonical Gradle plugin task shape:
 *  - extends `DefaultTask`
 *  - properties are `Property<T>` / `RegularFileProperty` (lazy)
 *  - inputs/outputs are annotated for incremental builds + the build cache
 */
abstract class ExampleTask : DefaultTask() {

    @get:Input
    abstract val greeting: Property<String>

    @get:OutputFile
    abstract val outputFile: RegularFileProperty

    @TaskAction
    fun run() {
        val out = outputFile.get().asFile
        out.parentFile.mkdirs()
        out.writeText(greeting.get())
    }
}

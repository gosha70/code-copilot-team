package com.example.gradleplugin

import org.gradle.testfixtures.ProjectBuilder
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertNotNull
import org.junit.jupiter.api.Test

/**
 * Unit tests using `ProjectBuilder` — fast, in-process, no Gradle daemon.
 * Functional tests (TestKit, real builds) live in the `functionalTest`
 * source set under `plugin/src/functionalTest/`.
 */
class ExamplePluginTest {

    @Test
    fun `plugin registers extension and task`() {
        val project = ProjectBuilder.builder().build()
        project.plugins.apply("com.example.gradle-plugin")

        val ext = project.extensions.findByType(ExampleExtension::class.java)
        assertNotNull(ext, "extension should be registered")

        val task = project.tasks.findByName("exampleHello")
        assertNotNull(task, "exampleHello task should be registered")
    }

    @Test
    fun `default greeting is set via convention`() {
        val project = ProjectBuilder.builder().build()
        project.plugins.apply("com.example.gradle-plugin")

        val ext = project.extensions.getByType(ExampleExtension::class.java)
        assertEquals("Hello from ExamplePlugin", ext.greeting.get())
    }
}

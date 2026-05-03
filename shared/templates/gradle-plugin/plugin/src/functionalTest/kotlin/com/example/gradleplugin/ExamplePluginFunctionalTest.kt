package com.example.gradleplugin

import org.gradle.testkit.runner.GradleRunner
import org.gradle.testkit.runner.TaskOutcome
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.io.TempDir
import java.io.File

/**
 * TestKit-based functional tests. Each test seeds a synthetic Gradle project,
 * applies the plugin, runs `:exampleHello`, and asserts on task outcome and output.
 *
 * The Gradle version under test can be overridden via `-PgradleTestVersion=8.5`
 * on the wrapping `./gradlew` invocation. This is what the CI matrix uses.
 */
class ExamplePluginFunctionalTest {

    @TempDir
    lateinit var projectDir: File

    private val gradleVersion: String? = System.getProperty("gradleTestVersion")

    @Test
    fun `exampleHello runs and writes the configured greeting`() {
        File(projectDir, "settings.gradle.kts").writeText("""
            rootProject.name = "ft-sample"
        """.trimIndent())

        File(projectDir, "build.gradle.kts").writeText("""
            plugins {
                id("com.example.gradle-plugin")
            }

            example {
                greeting.set("Hi from the functional test")
            }
        """.trimIndent())

        val result = runner().withArguments("exampleHello", "--stacktrace").build()

        assertEquals(
            TaskOutcome.SUCCESS,
            result.task(":exampleHello")?.outcome,
            "exampleHello should succeed; output:\n${result.output}"
        )

        val out = File(projectDir, "build/example/greeting.txt")
        assertTrue(out.exists(), "greeting.txt should exist at $out")
        assertEquals("Hi from the functional test", out.readText())
    }

    @Test
    fun `re-running exampleHello hits UP_TO_DATE without re-executing`() {
        File(projectDir, "settings.gradle.kts").writeText("rootProject.name = \"ft-sample\"")
        File(projectDir, "build.gradle.kts").writeText("""
            plugins { id("com.example.gradle-plugin") }
            example { greeting.set("cached") }
        """.trimIndent())

        runner().withArguments("exampleHello").build()
        val second = runner().withArguments("exampleHello").build()

        assertEquals(
            TaskOutcome.UP_TO_DATE,
            second.task(":exampleHello")?.outcome,
            "second invocation should be UP_TO_DATE; output:\n${second.output}"
        )
    }

    private fun runner(): GradleRunner {
        val r = GradleRunner.create()
            .withProjectDir(projectDir)
            .withPluginClasspath()
            .forwardOutput()
        return if (gradleVersion.isNullOrBlank()) r else r.withGradleVersion(gradleVersion)
    }
}

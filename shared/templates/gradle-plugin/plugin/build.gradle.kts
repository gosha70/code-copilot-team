plugins {
    alias(libs.plugins.kotlin.jvm)
    `java-gradle-plugin`
    `jvm-test-suite`
    alias(libs.plugins.plugin.publish)
}

group = "com.example"
version = libs.versions.pluginVersion.get()

java {
    toolchain {
        languageVersion.set(JavaLanguageVersion.of(17))
    }
}

testing {
    suites {
        // Standard `test` source set: in-process unit tests via ProjectBuilder.
        val test by getting(JvmTestSuite::class) {
            useJUnitJupiter(libs.versions.junit.get())
        }

        // Functional tests live in a SEPARATE source set inside :plugin so
        // that `gradlePlugin.testSourceSets(...)` (below) can wire the
        // plugin-under-test metadata onto its runtime classpath. Without
        // that wiring, `GradleRunner.withPluginClasspath()` throws
        // InvalidPluginMetadataException.
        register<JvmTestSuite>("functionalTest") {
            useJUnitJupiter(libs.versions.junit.get())

            dependencies {
                implementation(project())
                implementation(gradleTestKit())
            }

            targets.configureEach {
                testTask.configure {
                    // Run after unit tests
                    shouldRunAfter(test)
                    // Allow CI / local runs to override the Gradle version
                    // under test: ./gradlew :plugin:functionalTest -PgradleTestVersion=8.5
                    val gradleTestVersion = project.findProperty("gradleTestVersion") as String?
                    if (!gradleTestVersion.isNullOrBlank()) {
                        systemProperty("gradleTestVersion", gradleTestVersion)
                    }
                }
            }
        }
    }
}

dependencies {
    // Unit tests already pull JUnit via the test suite block above.
}

gradlePlugin {
    website.set("https://example.org/replace-me")
    vcsUrl.set("https://example.org/replace-me.git")

    // Wire plugin-under-test metadata onto the functionalTest source set so
    // GradleRunner.withPluginClasspath() can find the plugin under test.
    // This is the supported `java-gradle-plugin` API for custom test source
    // sets — see https://docs.gradle.org/current/userguide/java_gradle_plugin.html
    testSourceSets(sourceSets["functionalTest"])

    plugins {
        register("examplePlugin") {
            id = "com.example.gradle-plugin"
            implementationClass = "com.example.gradleplugin.ExamplePlugin"
            displayName = "Example Gradle Plugin"
            description = "Replace with a one-line description of what your plugin does."
            tags.set(listOf("example", "replace-me"))
        }
    }
}

// `./gradlew check` should run both unit and functional tests.
tasks.named("check") {
    dependsOn(testing.suites.named("functionalTest"))
}

// `com.gradle.plugin-publish` reads GRADLE_PUBLISH_KEY / GRADLE_PUBLISH_SECRET
// from env or ~/.gradle/gradle.properties. Never commit credentials.

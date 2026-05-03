package com.example.gradleplugin

import org.gradle.api.provider.Property

/**
 * DSL surface exposed to consumer build scripts.
 *
 * Example usage in the consumer's `build.gradle.kts`:
 * ```
 * example {
 *     greeting.set("Hello from the plugin")
 * }
 * ```
 *
 * Every property is a `Property<T>` so the plugin and its tasks can wire values
 * lazily — read at execution time, not at configuration time.
 */
abstract class ExampleExtension {
    abstract val greeting: Property<String>
}

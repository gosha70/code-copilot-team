// sample-consumer is an OUT-OF-TREE consumer build. It is NOT a subproject
// of the plugin build. It uses pluginManagement.includeBuild to consume the
// plugin via composite build, mirroring the experience consumers have when
// the plugin is published to the Plugin Portal — minus the network hop.

rootProject.name = "sample-consumer"

pluginManagement {
    includeBuild("..")
    repositories {
        gradlePluginPortal()
    }
}

rootProject.name = "gradle-plugin-template"

include(":plugin")

dependencyResolutionManagement {
    repositories {
        gradlePluginPortal()
        mavenCentral()
    }
}

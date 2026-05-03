// Root build. Applies common config to every subproject; subprojects own their plugins.

plugins {
    base
}

allprojects {
    repositories {
        gradlePluginPortal()
        mavenCentral()
    }
}

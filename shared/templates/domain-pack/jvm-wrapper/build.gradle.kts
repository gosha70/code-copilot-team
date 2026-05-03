// Domain-pack JVM wrapper. Reads version, name, and licenses from
// ../content/manifest.yaml so the manifest stays the single source of truth.

import java.util.Properties

plugins {
    `java-library`
    `maven-publish`
    signing
}

// ── Read manifest ───────────────────────────────────────────────────────────
val manifestFile = rootProject.layout.projectDirectory.file("../content/manifest.yaml").asFile
val manifestText = if (manifestFile.exists()) manifestFile.readText() else ""

fun manifestField(key: String): String {
    val regex = Regex("(?m)^${Regex.escape(key)}:\\s*\"?([^\"\\n]+)\"?\\s*$")
    return regex.find(manifestText)?.groupValues?.get(1)?.trim()
        ?: error("Manifest field '$key' not found in $manifestFile")
}

fun manifestNestedField(parent: String, key: String): String {
    val regex = Regex("(?ms)^${Regex.escape(parent)}:\\s*\\n((?:[ \\t]+.+\\n?)+)")
    val block = regex.find(manifestText)?.groupValues?.get(1)
        ?: error("Manifest section '$parent' not found")
    val lineRegex = Regex("(?m)^[ \\t]+${Regex.escape(key)}:\\s*\"?([^\"\\n]+)\"?\\s*$")
    return lineRegex.find(block)?.groupValues?.get(1)?.trim()
        ?: error("Manifest field '$parent.$key' not found")
}

val packName = manifestField("name")
val packVersion = manifestField("version")
val codeLicense = manifestNestedField("licenses", "code")

group = "com.example.domainpack"
version = packVersion

java {
    toolchain {
        languageVersion.set(JavaLanguageVersion.of(17))
    }
    withSourcesJar()
    withJavadocJar()
}

repositories {
    mavenCentral()
}

dependencies {
    testImplementation("org.junit.jupiter:junit-jupiter:5.10.0")
    testRuntimeOnly("org.junit.platform:junit-platform-launcher")
}

tasks.test {
    useJUnitPlatform()
}

// ── Sync content/ → src/main/resources/ before processing resources ─────────
val syncContent by tasks.registering(Sync::class) {
    from(rootProject.layout.projectDirectory.dir("../content"))
    into(layout.buildDirectory.dir("synced-content"))
}

sourceSets {
    main {
        resources {
            srcDir(syncContent.map { it.destinationDir })
        }
    }
}

tasks.processResources {
    dependsOn(syncContent)
    // Place content under a stable resource prefix the loader can find.
    eachFile {
        if (path.endsWith(".tbx") || name == "manifest.yaml" || name == "LICENSE-DATA") {
            path = "domain-pack/$name"
        }
    }
}

// ── Publishing ──────────────────────────────────────────────────────────────
publishing {
    publications {
        create<MavenPublication>("library") {
            from(components["java"])
            artifactId = packName
            pom {
                name.set(packName)
                description.set("Domain pack JVM wrapper — $packName")
                url.set("https://example.org/replace-me")
                licenses {
                    license {
                        name.set(codeLicense)
                        url.set("https://opensource.org/licenses/${codeLicense}")
                    }
                }
                developers {
                    developer {
                        id.set("replace-me")
                        name.set("Replace Me")
                        email.set("you@example.org")
                    }
                }
                scm {
                    connection.set("scm:git:https://example.org/replace-me.git")
                    developerConnection.set("scm:git:ssh://git@example.org/replace-me.git")
                    url.set("https://example.org/replace-me")
                }
            }
        }
    }
    repositories {
        // OSSRH staging repository for Sonatype-hosted Maven Central.
        // Override OSSRH_RELEASES_URL / OSSRH_SNAPSHOTS_URL to point at the
        // Central Portal (`https://central.sonatype.com/api/v1/publisher/...`)
        // or a self-hosted Nexus once you have one provisioned.
        maven {
            name = "ossrh"
            val releaseUrl = System.getenv("OSSRH_RELEASES_URL")
                ?: "https://s01.oss.sonatype.org/service/local/staging/deploy/maven2/"
            val snapshotUrl = System.getenv("OSSRH_SNAPSHOTS_URL")
                ?: "https://s01.oss.sonatype.org/content/repositories/snapshots/"
            url = uri(if (version.toString().endsWith("SNAPSHOT")) snapshotUrl else releaseUrl)
            credentials {
                username = System.getenv("OSSRH_USERNAME") ?: ""
                password = System.getenv("OSSRH_TOKEN") ?: ""
            }
        }
    }
}

signing {
    val signingKey: String? = System.getenv("SIGNING_KEY")
    val signingPassword: String? = System.getenv("SIGNING_PASSWORD")
    if (signingKey != null && signingPassword != null) {
        useInMemoryPgpKeys(signingKey, signingPassword)
        sign(publishing.publications["library"])
    }
}

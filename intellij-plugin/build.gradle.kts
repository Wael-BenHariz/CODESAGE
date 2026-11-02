import org.jetbrains.intellij.platform.gradle.TestFrameworkType

plugins {
    id("java")
    kotlin("jvm") version "2.0.21"
    id("org.jetbrains.intellij.platform") version "2.1.0"
}

group = providers.gradleProperty("pluginGroup").get()
version = providers.gradleProperty("pluginVersion").get()

repositories {
    mavenCentral()
    intellijPlatform {
        defaultRepositories()
    }
}

dependencies {
    intellijPlatform {
        intellijIdeaCommunity(providers.gradleProperty("platformVersion").get())
        testFramework(TestFrameworkType.Platform)
        instrumentationTools()
        pluginVerifier()
        zipSigner()
    }
    testImplementation("junit:junit:4.13.2")
}

kotlin {
    jvmToolchain(17)
}

tasks.withType<Test>().configureEach {
    // Git collection tests shell out to the system `git`, exactly like the VS Code suite.
    systemProperty("codesage.parity.dir", layout.projectDirectory.dir("src/test/resources/parity").asFile.absolutePath)
    maxHeapSize = "1g"
}

intellijPlatform {
    buildSearchableOptions = false

    pluginConfiguration {
        // No "intellij"/"ide" in the plugin ID: since 2024 the Plugin Verifier and
        // Marketplace reject template words in plugin IDs (TemplateWordInPluginId).
        id = "com.codesage.localreview"
        name = providers.gradleProperty("pluginName")
        version = providers.gradleProperty("pluginVersion")

        description = """
            <p>Review local Git changes with CodeSage and see findings inline in your IDE.</p>
            <p>Ports the CodeSage VS Code extension: same commands, settings, review payload and
            report. Findings arrive from the local CodeSage backend as editor highlights, and the
            review report is rendered with the same HTML and styling as the VS Code panel.</p>
        """.trimIndent()

        vendor {
            name = "CodeSage"
            url = "https://github.com/Wael-BenHariz/CODESAGE"
        }

        ideaVersion {
            sinceBuild = "233"
            // All JetBrains IDEs 2023.3 and newer: no upper bound.
            untilBuild = provider { null }
        }
    }

    pluginVerification {
        ides {
            // Explicit versions: `recommended()` in plugin 2.1.0 asks for IC 2025.3,
            // which does not exist in the IntelliJ repository.
            //
            // 2.1.0 adds every `ide(...)` coordinate to ONE dependency configuration
            // (`intellijPluginVerifierIdesDependency`), so two versions of the same
            // product collapse to the newest via Gradle conflict resolution — only
            // the 2025.1 run actually happens. Override to check another IDE:
            //   gradle verifyPlugin -PverifierIde=2024.3
            ide("IC", providers.gradleProperty("verifierIde").getOrElse("2025.1"))
        }
    }
}

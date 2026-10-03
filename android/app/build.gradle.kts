import java.util.Properties

plugins {
    id("com.android.application")
    id("com.chaquo.python")
}

// The Python pipeline and its data live at the repository root and are shared
// with the desktop / Docker versions. Copy them into the build directory so the
// APK always carries the current code, templates and forms registry.
val repoRoot: File = rootProject.projectDir.parentFile
val generatedDir: File = layout.buildDirectory.dir("generated/formfiller").get().asFile

// Chaquopy needs a Python 3.13 on the build machine. If it isn't the one found
// on the PATH, point to it with a `buildPython=C:/.../python.exe` line in
// android/local.properties (which is machine-specific and not committed).
val localProperties = Properties().apply {
    val file = rootProject.file("local.properties")
    if (file.isFile) file.inputStream().use { load(it) }
}
val localBuildPython: String? = localProperties.getProperty("buildPython")

sync {
    from(repoRoot) { include("main.py", "parser.py", "web_gui.py", "pdf_export.py") }
    into(File(generatedDir, "python"))
}
sync {
    into(File(generatedDir, "assets/seed"))
    from(repoRoot) { include("forms.json") }
    from(File(repoRoot, "templates")) {
        into("templates")
        include("*.docx")
        exclude("~\$*")
    }
    from(File(repoRoot, "configs")) {
        into("configs")
        include("*.json")
    }
    from(File(repoRoot, "web")) { into("web") }
}

android {
    namespace = "com.ilansi.formfiller"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.ilansi.formfiller"
        minSdk = 24
        targetSdk = 34
        versionCode = 1
        versionName = "1.0"

        ndk {
            // arm64-v8a: phones and tablets. x86_64: the emulator.
            abiFilters += listOf("arm64-v8a", "x86_64")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    sourceSets {
        getByName("main") {
            assets.directories.add(File(generatedDir, "assets").path)
        }
    }
}

chaquopy {
    defaultConfig {
        version = "3.13"
        localBuildPython?.let { buildPython(it) }
        pip {
            install("python-docx==1.2.0")
            // Newest lxml with a prebuilt Android wheel in Chaquopy's repository.
            install("lxml==5.3.0")
        }
    }
    sourceSets {
        getByName("main") {
            srcDir(File(generatedDir, "python"))
        }
    }
}

dependencies {
    implementation("androidx.core:core:1.13.1")
}

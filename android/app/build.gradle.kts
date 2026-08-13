plugins {
    id("com.android.application")
    id("com.chaquo.python")
}

android {
    namespace = "com.furkancanyilmaz.divan"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.furkancanyilmaz.divan"
        minSdk = 24
        targetSdk = 36
        versionCode = 2026081002
        versionName = "2026.08.10.2"

        ndk {
            // Yeni 64-bit telefonlarla birlikte, Android'i 32-bit çalışan
            // eski Samsung cihazlarında da aynı APK kurulabilsin.
            abiFilters += listOf("arm64-v8a", "armeabi-v7a")
        }
    }

    buildTypes {
        debug {
            applicationIdSuffix = ".debug"
            versionNameSuffix = "-debug"
        }
        release {
            isMinifyEnabled = false
            // This APK is a private sideload build. Using this Mac's stable
            // signing key keeps future personal updates installable.
            signingConfig = signingConfigs.getByName("debug")
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    buildFeatures {
        buildConfig = false
    }
}

dependencies {
    implementation("androidx.core:core:1.17.0")
    implementation("com.google.android.gms:play-services-code-scanner:16.1.0")
}

chaquopy {
    defaultConfig {
        // Python 3.12 ve sonrası yalnız 64-bit Android destekliyor.
        // 3.10, uygulama koduyla uyumlu ve eski 32-bit cihazları kapsıyor.
        version = "3.10"
    }
}

val commonDivanFiles = listOf(
    "server.py",
    "index.html",
    "secure_sync_transport.py",
    "sync_engine.py",
    "sync_service.py",
    "sync_qr.py",
    "qrcodegen.py",
)
val commonDivanRoot = rootProject.file("../core")
val androidPackageSourceRoot = layout.projectDirectory.dir("src/main").asFile
val embeddedDivanRoot = layout.projectDirectory.dir("src/main/python").asFile

val syncDivanSources by tasks.registering(Copy::class) {
    description = "Güncel Divan sunucusunu Android paketine taşır."
    from(commonDivanRoot) {
        include(*commonDivanFiles.toTypedArray())
        include("assets/portraits/**")
    }
    into(embeddedDivanRoot)
}

val verifyDivanEmbedding by tasks.registering {
    group = "verification"
    description = "Mobil paketin güncel, gizlisiz Divan kaynaklarını kullandığını doğrular."
    dependsOn(syncDivanSources)
    inputs.files(commonDivanFiles.map { commonDivanRoot.resolve(it) })
    inputs.files(commonDivanFiles.map { embeddedDivanRoot.resolve(it) })
    doLast {
        commonDivanFiles.forEach { relativePath ->
            val source = commonDivanRoot.resolve(relativePath)
            val embedded = embeddedDivanRoot.resolve(relativePath)
            check(source.isFile) { "Ortak Divan kaynağı eksik: $relativePath" }
            check(embedded.isFile) { "Android paket kaynağı eksik: $relativePath" }
            check(source.readBytes().contentEquals(embedded.readBytes())) {
                "Android paket kaynağı güncel değil: $relativePath"
            }
        }

        val syncEngine = embeddedDivanRoot.resolve("sync_engine.py").readText()
        check(Regex("""(?m)^BATCH_VERSION\s*=\s*2\s*$""").containsMatchIn(syncEngine)) {
            "Android paketi cihaz eşitleme protokolü v2'yi içermiyor."
        }

        val forbiddenDatabases = fileTree(androidPackageSourceRoot) {
            include("**/*.db", "**/*.db-*", "**/*.sqlite", "**/*.sqlite3")
        }.files
        check(forbiddenDatabases.isEmpty()) {
            "Android paket kaynaklarında kullanıcı veritabanı bulundu: " +
                forbiddenDatabases.joinToString { it.name }
        }

        val secretPattern = Regex(
            """sk-(?:proj-)?[A-Za-z0-9_-]{20,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"""
        )
        val textSources = fileTree(androidPackageSourceRoot) {
            include(
                "**/*.py", "**/*.html", "**/*.json", "**/*.txt", "**/*.md",
                "**/*.java", "**/*.kt", "**/*.xml", "**/*.properties",
            )
        }.files
        val secretMatches = textSources.filter { file ->
            secretPattern.containsMatchIn(file.readText())
        }
        check(secretMatches.isEmpty()) {
            "Android paket kaynaklarında API/özel anahtar benzeri içerik bulundu: " +
                secretMatches.joinToString { it.name }
        }
    }
}

tasks.named("preBuild") {
    dependsOn(verifyDivanEmbedding)
}

tasks.matching {
    it.name.startsWith("merge") && it.name.endsWith("PythonSources")
}.configureEach {
    dependsOn(verifyDivanEmbedding)
}

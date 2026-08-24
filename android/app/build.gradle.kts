import java.nio.file.Files
import java.security.MessageDigest

fun sha256(file: java.io.File): String = MessageDigest
    .getInstance("SHA-256")
    .digest(file.readBytes())
    .joinToString("") { byte -> "%02x".format(byte.toInt() and 0xff) }

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
        versionCode = 2026082215
        versionName = "2026.08.22.15"

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
            isDebuggable = false
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

    lint {
        // Önceki kişisel APK'lar tarih tabanlı yüksek versionCode ile
        // dağıtıldı. Android'in yerinde güncelleme kuralını bozmadan daha
        // küçük bir şemaya dönemeyiz; diğer bütün lint hataları fatal kalır.
        disable += "HighAppVersionCode"
        abortOnError = true
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
val expectedCommonSha256 = mapOf(
    "server.py" to "e205b2e1efc92575cb99262ea85812e4d986369dc4635193bd9e508d31a4fe7b",
    "index.html" to "5f03a514745ea90dedb53507393a05711e9432df67f48182868d18365eefb6ab",
    "secure_sync_transport.py" to "fef550a2b5d5c7ad27c62cbd679d5fdb07d621544ebc0edd98ac376c4f9dc5f4",
    "sync_engine.py" to "39005a82d5d358557e222e7de7a6c3a2284453ecf2a8ad69584a142dafacc512",
    "sync_service.py" to "aab750f309884aa84b5c47be106da03459066538a3dd71a76ed6112155f3580c",
    "sync_qr.py" to "794b422a8e91453cde30103c9c0efc6a4980f0777c2176d060a622b177a4ef4f",
    "qrcodegen.py" to "db4736e1d2662e251423314a97d146a16f4d084266e740a76f10299db3ac7a8a",
)
val commonDivanRoot = rootProject.file("../freud-dev")
val schemaPathContractFixture =
    commonDivanRoot.resolve("tests/fixtures/schema_path_v4_contract.json")
val expectedSchemaPathContractSha256 =
    "30e2cac7c8ced6e58a3f8860ea887f1f1e6f42cb888d21da6bcaad7803294197"
val tusCatalogRelativePath = "assets/tus/catalog-v1.json"
val expectedTusCatalogSha256 =
    "88d868de90435a2cc38e1c41d35c25b20bddbaa6221b412715c4009735a12182"
val androidPackageSourceRoot = layout.projectDirectory.dir("src/main").asFile
val embeddedDivanRoot = layout.projectDirectory.dir("src/main/python").asFile

val syncDivanSources by tasks.registering(Copy::class) {
    description = "Güncel Divan sunucusunu Android paketine taşır."
    from(commonDivanRoot) {
        include(*commonDivanFiles.toTypedArray())
        include("assets/portraits/**")
        include("assets/imagery/**")
        include("assets/tus/**")
    }
    into(embeddedDivanRoot)
}

val verifyDivanEmbedding by tasks.registering {
    group = "verification"
    description = "Mobil paketin güncel, gizlisiz Divan kaynaklarını kullandığını doğrular."
    dependsOn(syncDivanSources)
    inputs.files(commonDivanFiles.map { commonDivanRoot.resolve(it) })
    inputs.files(commonDivanFiles.map { embeddedDivanRoot.resolve(it) })
    inputs.file(schemaPathContractFixture)
    inputs.file(commonDivanRoot.resolve(tusCatalogRelativePath))
    inputs.file(embeddedDivanRoot.resolve(tusCatalogRelativePath))
    doLast {
        commonDivanFiles.forEach { relativePath ->
            val source = commonDivanRoot.resolve(relativePath)
            val embedded = embeddedDivanRoot.resolve(relativePath)
            val expectedDigest = expectedCommonSha256.getValue(relativePath)
            check(source.isFile) { "Ortak Divan kaynağı eksik: $relativePath" }
            check(embedded.isFile) { "Android paket kaynağı eksik: $relativePath" }
            check(sha256(source) == expectedDigest) {
                "Ortak Divan kaynağı dondurulmuş sürümden farklı: $relativePath"
            }
            check(sha256(embedded) == expectedDigest) {
                "Android paket kaynağı dondurulmuş sürümden farklı: $relativePath"
            }
            check(source.readBytes().contentEquals(embedded.readBytes())) {
                "Android paket kaynağı güncel değil: $relativePath"
            }
        }

        check(schemaPathContractFixture.isFile) {
            "Schema Path v5 sözleşme fixture'ı eksik."
        }
        check(sha256(schemaPathContractFixture) ==
            expectedSchemaPathContractSha256) {
            "Schema Path v5 sözleşme fixture'ı dondurulmuş sürümden farklı."
        }

        val sourceTusDirectory = commonDivanRoot.resolve("assets/tus")
        val embeddedTusDirectory = embeddedDivanRoot.resolve("assets/tus")
        val sourceTusCatalog = commonDivanRoot.resolve(tusCatalogRelativePath)
        val embeddedTusCatalog = embeddedDivanRoot.resolve(tusCatalogRelativePath)
        check(sourceTusCatalog.isFile && embeddedTusCatalog.isFile) {
            "TUS metadata kataloğu ortak veya Android pakette eksik."
        }
        check(!Files.isSymbolicLink(sourceTusCatalog.toPath()) &&
            !Files.isSymbolicLink(embeddedTusCatalog.toPath())) {
            "TUS metadata kataloğu bağlantı olamaz."
        }
        check(sourceTusDirectory.listFiles()?.map { it.name }?.toSet() ==
            setOf("catalog-v1.json") &&
            embeddedTusDirectory.listFiles()?.map { it.name }?.toSet() ==
            setOf("catalog-v1.json")) {
            "TUS katalog klasöründe allowlist dışı dosya bulundu."
        }
        check(sourceTusCatalog.length() in 1..(8L * 1024L * 1024L) &&
            embeddedTusCatalog.length() == sourceTusCatalog.length()) {
            "TUS metadata kataloğunun boyutu geçersiz."
        }
        check(sha256(sourceTusCatalog) == expectedTusCatalogSha256 &&
            sha256(embeddedTusCatalog) == expectedTusCatalogSha256 &&
            sourceTusCatalog.readBytes().contentEquals(
                embeddedTusCatalog.readBytes())) {
            "Android TUS metadata kataloğu dondurulmuş ortak katalogla aynı değil."
        }
        val tusCatalogText = sourceTusCatalog.readText()
        check(Regex(""""protocol"\s*:\s*"divan_tus_catalog_v1"""")
            .containsMatchIn(tusCatalogText)) {
            "TUS metadata katalog protokolü geçersiz."
        }
        val forbiddenTusContentField = Regex(
            """(?i)"(?:answer|answers|choice|choices|content|contents|explanation|explanations|option|options|prompt|question|questions|question_text|raw|sentence|sentences|sentence_text|solution|solutions|stem|text)"\s*:"""
        )
        check(!forbiddenTusContentField.containsMatchIn(tusCatalogText)) {
            "TUS metadata kataloğunda ham soru/cümle alanı bulundu."
        }

        val sourceImagery = commonDivanRoot.resolve("assets/imagery")
        val embeddedImagery = embeddedDivanRoot.resolve("assets/imagery")
        val sourceManifest = sourceImagery.resolve("manifest.json")
        val embeddedManifest = embeddedImagery.resolve("manifest.json")
        check(sourceManifest.isFile && embeddedManifest.isFile) {
            "Freud imgeleme destesi manifesti eksik."
        }
        val sourceCards = sourceImagery.listFiles()
            ?.filter { it.isFile && it.extension.lowercase() == "webp" }
            ?.sortedBy { it.name }
            .orEmpty()
        val embeddedCards = embeddedImagery.listFiles()
            ?.filter { it.isFile && it.extension.lowercase() == "webp" }
            ?.sortedBy { it.name }
            .orEmpty()
        val sourceImageryEntries = sourceImagery.listFiles()?.toList().orEmpty()
        val embeddedImageryEntries = embeddedImagery.listFiles()?.toList().orEmpty()
        check(
            sourceImageryEntries.all { it.isFile && !Files.isSymbolicLink(it.toPath()) } &&
                embeddedImageryEntries.all { it.isFile && !Files.isSymbolicLink(it.toPath()) }
        ) {
            "Freud imgeleme destesinde alt klasör veya bağlantı bulunamaz."
        }
        check(sourceCards.size == 24 && embeddedCards.size == 24) {
            "Freud imgeleme destesi tam 24 WebP kart içermeli."
        }
        val sourceImageryFiles = (sourceCards + sourceManifest).associateBy { it.name }
        val embeddedImageryFiles = (embeddedCards + embeddedManifest).associateBy { it.name }
        check(sourceImageryFiles.keys == embeddedImageryFiles.keys) {
            "Android Freud imgeleme destesi kaynakla aynı dosyaları içermiyor."
        }
        check(
            sourceImageryEntries.map { it.name }.toSet() == sourceImageryFiles.keys &&
                embeddedImageryEntries.map { it.name }.toSet() == embeddedImageryFiles.keys
        ) { "Freud imgeleme destesinde allowlist dışı dosya bulundu." }
        sourceImageryFiles.forEach { (name, source) ->
            val embedded = embeddedImageryFiles.getValue(name)
            check(source.readBytes().contentEquals(embedded.readBytes())) {
                "Android Freud imgeleme kartı güncel değil: $name"
            }
            if (name.endsWith(".webp")) {
                val header = source.inputStream().use { input -> ByteArray(12).also { input.read(it) } }
                check(
                    header.size == 12 &&
                        String(header, 0, 4, Charsets.US_ASCII) == "RIFF" &&
                        String(header, 8, 4, Charsets.US_ASCII) == "WEBP"
                ) { "Geçersiz WebP imgeleme kartı: $name" }
            }
        }
        val manifestText = sourceManifest.readText()
        check(Regex("\"card_count\"\\s*:\\s*24\\b").containsMatchIn(manifestText)) {
            "Freud imgeleme manifestindeki kart sayısı 24 değil."
        }

        val syncEngine = embeddedDivanRoot.resolve("sync_engine.py").readText()
        check(Regex("""(?m)^BATCH_VERSION\s*=\s*8\s*$""").containsMatchIn(syncEngine)) {
            "Android paketi cihaz eşitleme protokolü v8'i içermiyor."
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
            file.canonicalFile != embeddedTusCatalog.canonicalFile &&
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

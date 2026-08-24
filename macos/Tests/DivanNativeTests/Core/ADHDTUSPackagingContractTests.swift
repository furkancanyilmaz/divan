import CryptoKit
import Foundation
import XCTest
@testable import DivanNative

final class ADHDTUSPackagingContractTests: XCTestCase {
    private let catalogSHA256 =
        "88d868de90435a2cc38e1c41d35c25b20bddbaa6221b412715c4009735a12182"
    private let serverSHA256 =
        "e205b2e1efc92575cb99262ea85812e4d986369dc4635193bd9e508d31a4fe7b"
    private let indexSHA256 =
        "9c58ff43ae90febd61c4fe2066fd7ee7649fb232af44bd2a716dc287581672d0"
    private let catalogBytes = 3_780_233

    func testAuthoritativeCatalogIsPinnedMetadataOnlyV1() throws {
        let catalogURL = packageRoot().deletingLastPathComponent()
            .appendingPathComponent("freud-dev/assets/tus/catalog-v1.json")
        let data = try Data(contentsOf: catalogURL, options: .mappedIfSafe)
        XCTAssertEqual(data.count, catalogBytes)
        XCTAssertEqual(
            SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined(),
            catalogSHA256
        )

        let root = try XCTUnwrap(
            JSONSerialization.jsonObject(with: data) as? [String: Any]
        )
        XCTAssertEqual(root["protocol"] as? String, "divan_tus_catalog_v1")
        XCTAssertEqual(root["schema_version"] as? Int, 1)
        XCTAssertFalse(try XCTUnwrap(root["lessons"] as? [Any]).isEmpty)
        XCTAssertFalse(try XCTUnwrap(root["question_areas"] as? [Any]).isEmpty)
        XCTAssertFalse(try XCTUnwrap(root["reading_areas"] as? [Any]).isEmpty)
        XCTAssertFalse(containsRawContentKey(root))
    }

    func testPrepareAndVerifyPinCatalogInRuntimeManifestWithPrivateMode() throws {
        let prepare = try script("prepare_core.sh")
        let verify = try script("verify_package.sh")
        let runtime = try String(contentsOf: packageRoot()
            .appendingPathComponent("Sources/DivanNative/Core/CoreRuntime.swift"))

        for source in [prepare, verify, runtime] {
            XCTAssertTrue(source.contains("assets/tus/catalog-v1.json"))
            XCTAssertTrue(source.contains(catalogSHA256))
            XCTAssertTrue(source.contains(serverSHA256))
            XCTAssertTrue(source.contains(indexSHA256))
            XCTAssertTrue(source.contains("divan_tus_catalog_v1"))
            XCTAssertTrue(source.contains("question_text"))
            XCTAssertTrue(source.contains("sentence_text"))
        }
        XCTAssertTrue(prepare.contains("/usr/bin/install -m 600"))
        XCTAssertTrue(prepare.contains("/usr/bin/shasum -a 256 \"$TUS_CATALOG_RELATIVE\""))
        XCTAssertTrue(verify.contains("yalnız kullanıcıya açık (0600)"))
        XCTAssertTrue(verify.contains("assets/tus/catalog-v1.json\","))
        XCTAssertTrue(runtime.contains("runtimeFiles = Set(["))
        XCTAssertTrue(runtime.contains("containsRawTUSContentKey"))
    }

    func testSecretScanDoesNotMistakePCSKCatalogMetadataForAnAPIKey() throws {
        let prepare = try script("prepare_core.sh")
        let verify = try script("verify_package.sh")
        let pattern = #"(^|[^A-Za-z0-9])sk-(proj-)?[A-Za-z0-9_-]{20,}"#
        XCTAssertTrue(prepare.contains(pattern))
        XCTAssertTrue(verify.contains(pattern))

        let scanner = try NSRegularExpression(pattern: pattern)
        let catalogKey = "topic:pcsk-9-inhibitorleri-proprotein-konverta"
        XCTAssertNil(scanner.firstMatch(
            in: catalogKey,
            range: NSRange(catalogKey.startIndex..., in: catalogKey)
        ))
        let secret = #"token="sk-proj-abcdefghijklmnopqrstuvwxyz1234""#
        XCTAssertNotNil(scanner.firstMatch(
            in: secret,
            range: NSRange(secret.startIndex..., in: secret)
        ))
    }

    func testCandidateVersionIsReleaseElevenWithoutChangingPriorArtifacts() throws {
        let build = try script("build_preview_zip.sh")
        let verify = try script("verify_package.sh")
        for source in [build, verify] {
            XCTAssertTrue(source.contains("2026.08.22.14"))
            XCTAssertTrue(source.contains("2026082214"))
            XCTAssertFalse(source.contains("2026.08.22.10"))
            XCTAssertFalse(source.contains("2026082210"))
        }
    }

    private func script(_ name: String) throws -> String {
        try String(contentsOf: packageRoot()
            .appendingPathComponent("Scripts")
            .appendingPathComponent(name), encoding: .utf8)
    }

    private func packageRoot() -> URL {
        URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
    }

    private func containsRawContentKey(_ value: Any) -> Bool {
        let forbidden = Set([
            "answer", "answers", "choice", "choices", "content", "contents",
            "explanation", "explanations", "option", "options", "prompt",
            "question", "questions", "question_text", "raw", "sentence",
            "sentences", "sentence_text", "solution", "solutions", "stem", "text",
        ])
        if let dictionary = value as? [String: Any] {
            return dictionary.contains { key, child in
                forbidden.contains(key.lowercased()) || containsRawContentKey(child)
            }
        }
        if let array = value as? [Any] {
            return array.contains(where: containsRawContentKey)
        }
        return false
    }
}

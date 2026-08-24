import Foundation
import XCTest
@testable import DivanNative

final class CoreRuntimeTests: XCTestCase {
    func testInvalidCoreFailsBeforeLaunchingPython() async throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("divan-core-test-\(UUID().uuidString)", isDirectory: true)
        let data = FileManager.default.temporaryDirectory
            .appendingPathComponent("divan-data-test-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        try Data("print('not a server')".utf8).write(to: root.appendingPathComponent("server.py"))
        defer {
            try? FileManager.default.removeItem(at: root)
            try? FileManager.default.removeItem(at: data)
        }
        let runtime = CoreRuntime(configuration: RuntimeConfiguration(
            coreDirectory: root,
            dataDirectory: data
        ))
        do {
            _ = try await runtime.start()
            XCTFail("Eksik çekirdek başlamamalıydı")
        } catch let error as CoreRuntimeError {
            guard case .invalidCore("index.html") = error else {
                return XCTFail("Beklenmeyen hata: \(error)")
            }
        }
        if case .failed = await runtime.state {
            // expected
        } else {
            XCTFail("Çalışma zamanı hata durumuna geçmeliydi")
        }
    }

    func testPythonDiscoveryFindsSupportedSystemPython() throws {
        let python = try XCTUnwrap(CoreRuntime.discoverPython())
        XCTAssertTrue(FileManager.default.isExecutableFile(atPath: python.path))
    }

    func testMissingFreudImageryManifestFailsBeforeLaunchingPython() async throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("divan-core-imagery-test-\(UUID().uuidString)", isDirectory: true)
        let data = FileManager.default.temporaryDirectory
            .appendingPathComponent("divan-data-imagery-test-\(UUID().uuidString)", isDirectory: true)
        defer {
            try? FileManager.default.removeItem(at: root)
            try? FileManager.default.removeItem(at: data)
        }

        let presentFiles = [
            "server.py", "index.html", "secure_sync_transport.py",
            "sync_engine.py", "sync_service.py", "sync_qr.py",
            "qrcodegen.py", "macos_keychain.py",
            "assets/portraits/manifest.json",
        ]
        for relativePath in presentFiles {
            let file = root.appendingPathComponent(relativePath)
            try FileManager.default.createDirectory(
                at: file.deletingLastPathComponent(),
                withIntermediateDirectories: true
            )
            try Data("fixture".utf8).write(to: file)
        }

        let runtime = CoreRuntime(configuration: RuntimeConfiguration(
            coreDirectory: root,
            dataDirectory: data
        ))
        do {
            _ = try await runtime.start()
            XCTFail("Freud görsel desteği eksik çekirdek başlamamalıydı")
        } catch let error as CoreRuntimeError {
            guard case .invalidCore("assets/imagery/manifest.json") = error else {
                return XCTFail("Beklenmeyen hata: \(error)")
            }
        }
    }

    func testMismatchedSyncProtocolFailsBeforePrivateStoreLaunch() async throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("divan-core-contract-test-\(UUID().uuidString)", isDirectory: true)
        let data = FileManager.default.temporaryDirectory
            .appendingPathComponent("divan-data-contract-test-\(UUID().uuidString)", isDirectory: true)
        defer {
            try? FileManager.default.removeItem(at: root)
            try? FileManager.default.removeItem(at: data)
        }
        let files: [String: String] = [
            "server.py": """
                SCHEMA_PATH_VERSION = 4
                SCHEMA_PATH_V4_PROTOCOL = "schema_path_chat_v4"
                \"next_card\": next_card
                \"message_meta\": schema_message_meta_payload(
                \"interaction_policy\": schema_v4_interaction_policy(
                \"clinical_sync\": schema_clinical_sync_public(
                """,
            "index.html": "fixture",
            "secure_sync_transport.py": "fixture",
            "sync_engine.py": "BATCH_VERSION = 4",
            "sync_service.py": "fixture",
            "sync_qr.py": "fixture",
            "qrcodegen.py": "fixture",
            "macos_keychain.py": "fixture",
            "assets/portraits/manifest.json": "{}",
            "assets/imagery/manifest.json": "{}",
        ]
        for (relativePath, contents) in files {
            let file = root.appendingPathComponent(relativePath)
            try FileManager.default.createDirectory(
                at: file.deletingLastPathComponent(),
                withIntermediateDirectories: true
            )
            try Data(contents.utf8).write(to: file)
        }

        let runtime = CoreRuntime(configuration: RuntimeConfiguration(
            coreDirectory: root,
            dataDirectory: data
        ))
        do {
            _ = try await runtime.start()
            XCTFail("Uyumsuz eşitleme sözleşmesiyle çekirdek başlamamalıydı")
        } catch let error as CoreRuntimeError {
            guard case .invalidCore(let detail) = error else {
                return XCTFail("Beklenmeyen hata: \(error)")
            }
            XCTAssertTrue(detail.contains("v8"))
        }
        XCTAssertFalse(
            FileManager.default.fileExists(atPath: data.path),
            "Sözleşme doğrulanmadan özel veri klasörü oluşturulmamalı."
        )
    }

    func testMissingClinicalSyncV8SafetyContractFailsBeforeStoreLaunch() async throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent(
                "divan-core-sync-safety-test-\(UUID().uuidString)",
                isDirectory: true
            )
        let data = FileManager.default.temporaryDirectory
            .appendingPathComponent(
                "divan-data-sync-safety-test-\(UUID().uuidString)",
                isDirectory: true
            )
        defer {
            try? FileManager.default.removeItem(at: root)
            try? FileManager.default.removeItem(at: data)
        }
        let files: [String: String] = [
            "server.py": "fixture",
            "index.html": "fixture",
            "secure_sync_transport.py": "fixture",
            "sync_engine.py": "BATCH_VERSION = 8",
            "sync_service.py": "clinical_confirmation_required",
            "sync_qr.py": "fixture",
            "qrcodegen.py": "fixture",
            "macos_keychain.py": "fixture",
            "assets/portraits/manifest.json": "{}",
            "assets/imagery/manifest.json": "{}",
        ]
        for (relativePath, contents) in files {
            let file = root.appendingPathComponent(relativePath)
            try FileManager.default.createDirectory(
                at: file.deletingLastPathComponent(),
                withIntermediateDirectories: true
            )
            try Data(contents.utf8).write(to: file)
        }

        let runtime = CoreRuntime(configuration: RuntimeConfiguration(
            coreDirectory: root,
            dataDirectory: data
        ))
        do {
            _ = try await runtime.start()
            XCTFail("Klinik güvenlik alanları eksik v8 çekirdek başlamamalıydı")
        } catch let error as CoreRuntimeError {
            guard case .invalidCore(let detail) = error else {
                return XCTFail("Beklenmeyen hata: \(error)")
            }
            XCTAssertTrue(detail.contains("klinik eşitleme v8"))
        }
        XCTAssertFalse(
            FileManager.default.fileExists(atPath: data.path),
            "Klinik eşitleme sözleşmesi doğrulanmadan veri klasörü oluşmamalı."
        )
    }

    func testMissingChatOnlySchemaReducerFailsBeforeStoreLaunch() async throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent(
                "divan-core-chat-only-test-\(UUID().uuidString)",
                isDirectory: true
            )
        let data = FileManager.default.temporaryDirectory
            .appendingPathComponent(
                "divan-data-chat-only-test-\(UUID().uuidString)",
                isDirectory: true
            )
        defer {
            try? FileManager.default.removeItem(at: root)
            try? FileManager.default.removeItem(at: data)
        }
        let files: [String: String] = [
            "server.py": """
                SCHEMA_PATH_VERSION = 5
                SCHEMA_PATH_V5_PROTOCOL = "schema_path_chat_v5"
                "next_card": next_card
                "message_meta": schema_message_meta_payload(
                "interaction_policy": schema_v4_interaction_policy(
                "clinical_sync": schema_clinical_sync_public(
                def validate_schema_chat_binding(
                def validate_schema_v5_chat_binding(
                def schema_v5_prompt_delivery(
                def schema_v5_next_card(
                def schema_v5_plan_for_user_response(
                schema_binding_result
                schema_chat_only_step_data
                sync_import_control
                sync_import_resume_required
                schema_prompt_protocol
                schema_prompt_intent
                composer_allowed
                composer_mode
                "composer_surface": "ordinary_chat"
                "inline_controls_only": False
                "presentation": "chat_only"
                "accept_candidate_chat", "reject_candidate_chat"
                source_assistant_message_public_id
                meta_event_public_id
                clinical_generation
                checkpoint_public_id
                expected_checkpoint_seq
                """,
            "index.html": "fixture",
            "secure_sync_transport.py": """
                SYNC_PROTOCOL_VERSION = 8
                SYNC_CAPABILITY = "schema_checkpoint_v1"
                SCHEMA_PATH_V5_SYNC_CAPABILITY = "schema_path_chat_v5"
                SYNC_CAPABILITIES = (
                SYNC_PROTOCOL_ERROR_CODE = "sync_protocol_update_required"
                Her iki cihazdaki Divan’ı güncelleyin; sonra yeni QR oluşturun.
                """,
            "sync_engine.py": "BATCH_VERSION = 8",
            "sync_service.py": """
                clinical_confirmation_required
                pending_clinical_confirmation_conv_ids
                clinical_safety_pause
                clinical_safety_device
                clinical_safety_message
                """,
            "sync_qr.py": "fixture",
            "qrcodegen.py": "fixture",
            "macos_keychain.py": "fixture",
            "assets/portraits/manifest.json": "{}",
            "assets/imagery/manifest.json": "{}",
        ]
        for (relativePath, contents) in files {
            let file = root.appendingPathComponent(relativePath)
            try FileManager.default.createDirectory(
                at: file.deletingLastPathComponent(),
                withIntermediateDirectories: true
            )
            try Data(contents.utf8).write(to: file)
        }

        let runtime = CoreRuntime(configuration: RuntimeConfiguration(
            coreDirectory: root,
            dataDirectory: data
        ))
        do {
            _ = try await runtime.start()
            XCTFail("Chat-only reducerı eksik çekirdek başlamamalıydı")
        } catch let error as CoreRuntimeError {
            guard case .invalidCore(let detail) = error else {
                return XCTFail("Beklenmeyen hata: \(error)")
            }
            XCTAssertTrue(detail.contains("Şema çalışma sözleşmesi"))
        }
        XCTAssertFalse(
            FileManager.default.fileExists(atPath: data.path),
            "Chat-only sözleşmesi doğrulanmadan veri klasörü oluşmamalı."
        )
    }

    func testTamperedFrozenManifestFailsBeforePrivateStoreLaunch() async throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent(
                "divan-core-frozen-manifest-test-\(UUID().uuidString)",
                isDirectory: true
            )
        let data = FileManager.default.temporaryDirectory
            .appendingPathComponent(
                "divan-data-frozen-manifest-test-\(UUID().uuidString)",
                isDirectory: true
            )
        defer {
            try? FileManager.default.removeItem(at: root)
            try? FileManager.default.removeItem(at: data)
        }
        let runtimeFiles = [
            "server.py", "index.html", "secure_sync_transport.py",
            "sync_engine.py", "sync_service.py", "sync_qr.py",
            "qrcodegen.py", "macos_keychain.py",
        ]
        for relativePath in runtimeFiles + [
            "assets/portraits/manifest.json",
            "assets/imagery/manifest.json",
        ] {
            let file = root.appendingPathComponent(relativePath)
            try FileManager.default.createDirectory(
                at: file.deletingLastPathComponent(),
                withIntermediateDirectories: true
            )
            try Data("fixture".utf8).write(to: file)
        }
        let forged = runtimeFiles.map {
            String(repeating: "0", count: 64) + "  " + $0
        }.joined(separator: "\n") + "\n"
        try Data(forged.utf8).write(
            to: root.appendingPathComponent("runtime-source.sha256")
        )

        let runtime = CoreRuntime(configuration: RuntimeConfiguration(
            coreDirectory: root,
            dataDirectory: data
        ))
        do {
            _ = try await runtime.start()
            XCTFail("Değiştirilmiş paket manifestiyle çekirdek başlamamalıydı")
        } catch let error as CoreRuntimeError {
            guard case .invalidCore(let detail) = error else {
                return XCTFail("Beklenmeyen hata: \(error)")
            }
            XCTAssertTrue(detail.contains("runtime-source.sha256"))
        }
        XCTAssertFalse(
            FileManager.default.fileExists(atPath: data.path),
            "Manifest doğrulanmadan özel veri klasörü oluşmamalı."
        )
    }
}

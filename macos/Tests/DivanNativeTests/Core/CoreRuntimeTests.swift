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
}

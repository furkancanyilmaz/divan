import Foundation
import Security

actor CPythonServerBackend: PythonRuntimeBackend {
    private var currentEndpoint: RuntimeEndpoint?

    func start() async throws -> RuntimeEndpoint {
        if let currentEndpoint {
            return currentEndpoint
        }

        let supportDirectory = try Self.applicationSupportDirectory()
        let token = Self.randomToken()
        let endpointString = try await withCheckedThrowingContinuation {
            (continuation: CheckedContinuation<String, Error>) in
            DivanEmbeddedPythonRuntime.shared().start(
                withApplicationSupportPath: supportDirectory.path,
                token: token
            ) { endpoint, error in
                if let error {
                    continuation.resume(throwing: error)
                } else if let endpoint {
                    continuation.resume(returning: endpoint)
                } else {
                    continuation.resume(throwing: PythonRuntimeError.invalidEndpoint)
                }
            }
        }

        guard let baseURL = URL(string: endpointString),
              LoopbackURLPolicy.isLoopbackHTTP(baseURL) else {
            throw PythonRuntimeError.invalidEndpoint
        }
        let endpoint = RuntimeEndpoint(baseURL: baseURL)
        currentEndpoint = endpoint
        return endpoint
    }

    func stop() async {
        await withCheckedContinuation { continuation in
            DivanEmbeddedPythonRuntime.shared().stop {
                continuation.resume()
            }
        }
        currentEndpoint = nil
    }

    private static func applicationSupportDirectory() throws -> URL {
        let manager = FileManager.default
        let root = try manager.url(
            for: .applicationSupportDirectory,
            in: .userDomainMask,
            appropriateFor: nil,
            create: true
        )
        let directory = root.appendingPathComponent("Divan", isDirectory: true)
        try preparePrivateDirectory(
            directory,
            protection: .completeUntilFirstUserAuthentication
        )

        // The database must remain available to a response that was already
        // running when the screen locks. Backups have no background-runtime
        // requirement, so keep them under the stricter complete protection.
        try preparePrivateDirectory(
            directory.appendingPathComponent("yedekler", isDirectory: true),
            protection: .complete
        )
        return directory
    }

    private static func preparePrivateDirectory(
        _ directory: URL,
        protection: FileProtectionType
    ) throws {
        let manager = FileManager.default
        let directoryAttributes: [FileAttributeKey: Any] = [
            .protectionKey: protection,
            .posixPermissions: 0o700,
        ]
        try manager.createDirectory(
            at: directory,
            withIntermediateDirectories: true,
            attributes: directoryAttributes
        )

        // createDirectory does not update an already-existing directory. Apply
        // the policy on every launch so older installations are upgraded too.
        try manager.setAttributes(
            directoryAttributes,
            ofItemAtPath: directory.path
        )
        try excludeFromSystemBackup(directory)
        try protectExistingContents(
            of: directory,
            protection: protection
        )
    }

    private static func protectExistingContents(
        of directory: URL,
        protection: FileProtectionType
    ) throws {
        let manager = FileManager.default
        let keys: [URLResourceKey] = [.isDirectoryKey, .isSymbolicLinkKey]
        guard let enumerator = manager.enumerator(
            at: directory,
            includingPropertiesForKeys: keys,
            options: [.skipsPackageDescendants]
        ) else {
            return
        }

        for case let itemURL as URL in enumerator {
            let values = try itemURL.resourceValues(forKeys: Set(keys))
            if values.isSymbolicLink == true {
                enumerator.skipDescendants()
                continue
            }
            let isDirectory = values.isDirectory == true
            try manager.setAttributes(
                [
                    .protectionKey: protection,
                    .posixPermissions: isDirectory ? 0o700 : 0o600,
                ],
                ofItemAtPath: itemURL.path
            )
        }
    }

    private static func excludeFromSystemBackup(_ directory: URL) throws {
        var protectedURL = directory
        var values = URLResourceValues()
        values.isExcludedFromBackup = true
        try protectedURL.setResourceValues(values)
    }

    private static func randomToken() -> String {
        var bytes = [UInt8](repeating: 0, count: 32)
        let status = SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes)
        precondition(status == errSecSuccess, "Secure random generation failed")
        return Data(bytes)
            .base64EncodedString()
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
    }
}

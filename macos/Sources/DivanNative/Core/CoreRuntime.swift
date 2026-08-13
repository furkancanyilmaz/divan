import Darwin
import Foundation
import Security

public struct RuntimeEndpoint: Equatable, Sendable {
    public let baseURL: URL
    public let sessionToken: String
    public let processIdentifier: Int32

    public init(baseURL: URL, sessionToken: String, processIdentifier: Int32) {
        self.baseURL = baseURL
        self.sessionToken = sessionToken
        self.processIdentifier = processIdentifier
    }
}

public enum RuntimeState: Equatable, Sendable {
    case idle
    case starting
    case running(RuntimeEndpoint)
    case stopping
    case failed(String)
}

public struct RuntimeConfiguration: Sendable {
    public var coreDirectory: URL?
    public var dataDirectory: URL?
    public var pythonExecutable: URL?
    public var startupTimeout: TimeInterval
    public var extraEnvironment: [String: String]

    public init(
        coreDirectory: URL? = nil,
        dataDirectory: URL? = nil,
        pythonExecutable: URL? = nil,
        startupTimeout: TimeInterval = 20,
        extraEnvironment: [String: String] = [:]
    ) {
        self.coreDirectory = coreDirectory
        self.dataDirectory = dataDirectory
        self.pythonExecutable = pythonExecutable
        self.startupTimeout = max(3, min(startupTimeout, 120))
        self.extraEnvironment = extraEnvironment
    }
}

public enum CoreRuntimeError: LocalizedError, Equatable, Sendable {
    case coreNotFound
    case invalidCore(String)
    case pythonNotFound
    case privateDirectoryUnavailable(String)
    case alreadyRunning
    case launchFailed(String)
    case startupTimedOut
    case healthCheckFailed

    public var errorDescription: String? {
        switch self {
        case .coreNotFound:
            return "Divan çekirdek dosyaları bulunamadı."
        case .invalidCore(let file):
            return "Divan çekirdeğinde gerekli dosya eksik: \(file)"
        case .pythonNotFound:
            return "Python 3.9 veya daha yenisi bulunamadı."
        case .privateDirectoryUnavailable(let message):
            return "Özel veri klasörü hazırlanamadı: \(message)"
        case .alreadyRunning:
            return "Divan bu veri klasörüyle zaten çalışıyor."
        case .launchFailed(let message):
            return "Yerel Divan çalışma zamanı başlatılamadı: \(message)"
        case .startupTimedOut:
            return "Yerel Divan çalışma zamanı zamanında hazır olmadı."
        case .healthCheckFailed:
            return "Yerel Divan çalışma zamanı doğrulanamadı."
        }
    }
}

private struct RuntimeMetadata: Codable {
    let port: Int
    let token: String
    let pid: Int32
}

private final class ProcessOutputMonitor: @unchecked Sendable {
    private let lock = NSLock()
    private let logHandle: FileHandle
    private var buffer = ""
    private var portContinuation: AsyncStream<Int>.Continuation?
    let ports: AsyncStream<Int>

    init(logHandle: FileHandle) {
        self.logHandle = logHandle
        var captured: AsyncStream<Int>.Continuation?
        self.ports = AsyncStream { continuation in captured = continuation }
        self.portContinuation = captured
    }

    func consume(_ data: Data) {
        lock.lock()
        defer { lock.unlock() }
        if !data.isEmpty {
            do {
                try logHandle.write(contentsOf: data)
            } catch {
                // Logging must never stop the private runtime.
            }
            buffer += String(decoding: data, as: UTF8.self)
            if buffer.count > 16_384 {
                buffer = String(buffer.suffix(16_384))
            }
            if let port = Self.extractPort(buffer) {
                portContinuation?.yield(port)
                portContinuation?.finish()
                portContinuation = nil
            }
        } else {
            portContinuation?.finish()
            portContinuation = nil
            try? logHandle.synchronize()
        }
    }

    func finish() {
        lock.lock()
        defer { lock.unlock() }
        portContinuation?.finish()
        portContinuation = nil
        try? logHandle.synchronize()
    }

    private static func extractPort(_ text: String) -> Int? {
        let marker = "Divan hazır: http://127.0.0.1:"
        guard let range = text.range(of: marker, options: .backwards) else { return nil }
        let tail = text[range.upperBound...]
        let digits = tail.prefix { $0.isNumber }
        guard let port = Int(digits), (1...65_535).contains(port) else { return nil }
        return port
    }
}

/// Paketlenen Python çekirdeğinin süreç yaşam döngüsünü yönetir.
///
/// Sorumlulukları:
/// - Sistemde güvenli bir `python3` bulmak (Homebrew, `/usr/local`, `/usr/bin`
///   ve `PATH` sırayla, sembolik bağlantı oyunlarına karşı doğrulanarak).
/// - Çekirdeği `PORT=0` ile başlatmak: portu işletim sistemi seçer, böylece
///   sabit bir port çakışması veya tahmin edilebilir uç oluşmaz.
/// - 256 bitlik oturum anahtarı üretip yalnızca sürece devretmek.
/// - Veri klasörünü yalnız kullanıcıya açık izinlerle (0700) oluşturmak.
/// - Günlükleri döndürmek ve kapanışta süreci güvenle sonlandırmak.
///
/// Swift katmanı SQLite dosyasına asla doğrudan dokunmaz; tüm yazmalar
/// çekirdeğin denenmiş işlem sınırlarından geçer. Bu, native önizlemenin
/// kararlı Divan kurulumunun verisini bozmamasının da güvencesidir.
///
/// `actor` olması, başlatma/kapatma çağrılarının çakışmasını engeller.
public actor CoreRuntime {
    public private(set) var state: RuntimeState = .idle

    private let configuration: RuntimeConfiguration
    private var process: Process?
    private var outputPipe: Pipe?
    private var outputMonitor: ProcessOutputMonitor?
    private var logHandle: FileHandle?
    private var runtimeMetadataURL: URL?
    private var lockDescriptor: Int32 = -1

    public init(configuration: RuntimeConfiguration = RuntimeConfiguration()) {
        self.configuration = configuration
    }

    @discardableResult
    public func start() async throws -> RuntimeEndpoint {
        if case .running(let endpoint) = state { return endpoint }
        guard state == .idle || isFailedState else {
            throw CoreRuntimeError.alreadyRunning
        }
        state = .starting

        do {
            let coreDirectory = try locateCoreDirectory()
            try validateCoreDirectory(coreDirectory)
            let dataDirectory = try previewDataDirectory()
            try Self.preparePrivateDirectory(dataDirectory)
            let cacheDirectory = dataDirectory.appendingPathComponent("pycache", isDirectory: true)
            try Self.preparePrivateDirectory(cacheDirectory)
            try acquireRuntimeLock(in: dataDirectory)

            let metadataURL = dataDirectory.appendingPathComponent("runtime-native.json")
            runtimeMetadataURL = metadataURL
            try await retireVerifiedPreviousRuntime(metadataURL: metadataURL)

            let pythonURL: URL
            if let requested = configuration.pythonExecutable {
                guard Self.pythonIsUsable(requested) else {
                    throw CoreRuntimeError.pythonNotFound
                }
                pythonURL = requested
            } else if let found = Self.discoverPython() {
                pythonURL = found
            } else {
                throw CoreRuntimeError.pythonNotFound
            }

            let logURL = dataDirectory.appendingPathComponent("runtime-native.log")
            try Self.rotateLogIfNeeded(logURL)
            let handle = try Self.openPrivateLog(logURL)
            logHandle = handle

            let token = try Self.secureToken()
            let pipe = Pipe()
            let monitor = ProcessOutputMonitor(logHandle: handle)
            outputPipe = pipe
            outputMonitor = monitor
            pipe.fileHandleForReading.readabilityHandler = { file in
                monitor.consume(file.availableData)
            }

            let launched = Process()
            launched.executableURL = pythonURL
            launched.arguments = ["-u", coreDirectory.appendingPathComponent("server.py").path]
            launched.currentDirectoryURL = coreDirectory
            launched.standardInput = FileHandle.nullDevice
            launched.standardOutput = pipe
            launched.standardError = pipe
            launched.environment = Self.runtimeEnvironment(
                databaseURL: dataDirectory.appendingPathComponent("freud.db"),
                cacheDirectory: cacheDirectory,
                token: token,
                extra: configuration.extraEnvironment
            )
            launched.qualityOfService = .userInitiated
            do {
                try launched.run()
            } catch {
                throw CoreRuntimeError.launchFailed(error.localizedDescription)
            }
            process = launched

            guard let port = try await waitForPort(
                monitor.ports,
                process: launched,
                timeout: configuration.startupTimeout
            ) else {
                throw CoreRuntimeError.startupTimedOut
            }
            guard let baseURL = URL(string: "http://127.0.0.1:\(port)/") else {
                throw CoreRuntimeError.launchFailed("Geçersiz yerel bağlantı noktası.")
            }
            let endpoint = RuntimeEndpoint(
                baseURL: baseURL,
                sessionToken: token,
                processIdentifier: launched.processIdentifier
            )
            guard try await Self.healthCheck(endpoint) else {
                throw CoreRuntimeError.healthCheckFailed
            }
            let metadata = RuntimeMetadata(
                port: port,
                token: token,
                pid: launched.processIdentifier
            )
            try Self.writePrivateMetadata(metadata, to: metadataURL)
            state = .running(endpoint)
            return endpoint
        } catch {
            await cleanUpRuntime()
            state = .failed(error.localizedDescription)
            throw error
        }
    }

    public func stop() async {
        guard state != .idle else { return }
        state = .stopping
        await cleanUpRuntime()
        state = .idle
    }

    public func currentEndpoint() -> RuntimeEndpoint? {
        guard case .running(let endpoint) = state else { return nil }
        return endpoint
    }

    public static func discoverPython(
        environment: [String: String] = ProcessInfo.processInfo.environment
    ) -> URL? {
        var paths = [
            "/opt/homebrew/bin/python3",
            "/usr/local/bin/python3",
            "/usr/bin/python3",
        ]
        for directory in (environment["PATH"] ?? "").split(separator: ":") {
            let path = URL(fileURLWithPath: String(directory), isDirectory: true)
                .appendingPathComponent("python3").path
            if !paths.contains(path) { paths.append(path) }
        }
        for path in paths {
            let url = URL(fileURLWithPath: path)
            if pythonIsUsable(url) { return url }
        }
        return nil
    }

    private var isFailedState: Bool {
        if case .failed = state { return true }
        return false
    }

    private func locateCoreDirectory() throws -> URL {
        var candidates: [URL] = []
        if let configured = configuration.coreDirectory { candidates.append(configured) }
        if let environment = ProcessInfo.processInfo.environment["DIVAN_CORE_ROOT"],
           !environment.isEmpty {
            candidates.append(URL(fileURLWithPath: environment, isDirectory: true))
        }
        if let resources = Bundle.main.resourceURL {
            candidates.append(resources.appendingPathComponent("Divan", isDirectory: true))
        }
        let current = URL(
            fileURLWithPath: FileManager.default.currentDirectoryPath,
            isDirectory: true
        )
        candidates.append(current.appendingPathComponent("Resources/Divan", isDirectory: true))
        candidates.append(current.deletingLastPathComponent().appendingPathComponent("core", isDirectory: true))

        for candidate in candidates {
            let canonical = candidate.standardizedFileURL.resolvingSymlinksInPath()
            if FileManager.default.fileExists(
                atPath: canonical.appendingPathComponent("server.py").path
            ) {
                return canonical
            }
        }
        throw CoreRuntimeError.coreNotFound
    }

    private func validateCoreDirectory(_ directory: URL) throws {
        let required = [
            "server.py", "index.html", "secure_sync_transport.py",
            "sync_engine.py", "sync_service.py", "sync_qr.py",
            "qrcodegen.py", "macos_keychain.py",
            "assets/portraits/manifest.json",
        ]
        for relativePath in required {
            let file = directory.appendingPathComponent(relativePath)
            var isDirectory: ObjCBool = false
            guard FileManager.default.fileExists(atPath: file.path, isDirectory: &isDirectory),
                  !isDirectory.boolValue else {
                throw CoreRuntimeError.invalidCore(relativePath)
            }
        }
    }

    private func previewDataDirectory() throws -> URL {
        if let configured = configuration.dataDirectory { return configured }
        do {
            let root = try FileManager.default.url(
                for: .applicationSupportDirectory,
                in: .userDomainMask,
                appropriateFor: nil,
                create: true
            )
            return root.appendingPathComponent("Divan Native Preview", isDirectory: true)
        } catch {
            throw CoreRuntimeError.privateDirectoryUnavailable(error.localizedDescription)
        }
    }

    private func acquireRuntimeLock(in dataDirectory: URL) throws {
        let path = dataDirectory.appendingPathComponent("runtime-native.lock").path
        let descriptor = Darwin.open(
            path,
            O_CREAT | O_RDWR | O_CLOEXEC,
            S_IRUSR | S_IWUSR
        )
        guard descriptor >= 0 else { throw CoreRuntimeError.alreadyRunning }
        guard flock(descriptor, LOCK_EX | LOCK_NB) == 0 else {
            Darwin.close(descriptor)
            throw CoreRuntimeError.alreadyRunning
        }
        lockDescriptor = descriptor
        _ = chmod(path, S_IRUSR | S_IWUSR)
    }

    private func retireVerifiedPreviousRuntime(metadataURL: URL) async throws {
        guard let data = try? Data(contentsOf: metadataURL),
              let metadata = try? JSONDecoder().decode(RuntimeMetadata.self, from: data),
              metadata.pid > 1,
              kill(metadata.pid, 0) == 0,
              let baseURL = URL(string: "http://127.0.0.1:\(metadata.port)/") else {
            try? FileManager.default.removeItem(at: metadataURL)
            return
        }
        let endpoint = RuntimeEndpoint(
            baseURL: baseURL,
            sessionToken: metadata.token,
            processIdentifier: metadata.pid
        )
        guard (try? await Self.healthCheck(endpoint)) == true else {
            try? FileManager.default.removeItem(at: metadataURL)
            return
        }
        _ = kill(metadata.pid, SIGTERM)
        for _ in 0..<30 where kill(metadata.pid, 0) == 0 {
            try? await Task.sleep(for: .milliseconds(100))
        }
        if kill(metadata.pid, 0) == 0 {
            _ = kill(metadata.pid, SIGKILL)
            for _ in 0..<20 where kill(metadata.pid, 0) == 0 {
                try? await Task.sleep(for: .milliseconds(100))
            }
        }
        guard kill(metadata.pid, 0) != 0 else {
            throw CoreRuntimeError.launchFailed(
                "Önceki Divan çalışma zamanı güvenle kapatılamadı."
            )
        }
        try? FileManager.default.removeItem(at: metadataURL)
    }

    private func waitForPort(
        _ stream: AsyncStream<Int>,
        process: Process,
        timeout: TimeInterval
    ) async throws -> Int? {
        try await withThrowingTaskGroup(of: Int?.self) { group in
            group.addTask {
                for await port in stream { return port }
                return nil
            }
            group.addTask {
                try await Task.sleep(for: .seconds(timeout))
                return nil
            }
            while let result = try await group.next() {
                if let port = result {
                    group.cancelAll()
                    return port
                }
                if !process.isRunning {
                    group.cancelAll()
                    return nil
                }
                group.cancelAll()
                return nil
            }
            return nil
        }
    }

    private func cleanUpRuntime() async {
        outputPipe?.fileHandleForReading.readabilityHandler = nil
        outputMonitor?.finish()
        if let process, process.isRunning {
            process.terminate()
            for _ in 0..<30 where process.isRunning {
                try? await Task.sleep(for: .milliseconds(100))
            }
            if process.isRunning {
                _ = kill(process.processIdentifier, SIGKILL)
                process.waitUntilExit()
            }
        }
        process = nil
        try? outputPipe?.fileHandleForReading.close()
        try? outputPipe?.fileHandleForWriting.close()
        outputPipe = nil
        outputMonitor = nil
        try? logHandle?.synchronize()
        try? logHandle?.close()
        logHandle = nil
        if let runtimeMetadataURL {
            try? FileManager.default.removeItem(at: runtimeMetadataURL)
        }
        runtimeMetadataURL = nil
        if lockDescriptor >= 0 {
            _ = flock(lockDescriptor, LOCK_UN)
            Darwin.close(lockDescriptor)
            lockDescriptor = -1
        }
    }

    private static func pythonIsUsable(_ url: URL) -> Bool {
        guard FileManager.default.isExecutableFile(atPath: url.path) else { return false }
        let check = Process()
        check.executableURL = url
        check.arguments = [
            "-c",
            "import sqlite3, ssl, sys; assert sys.version_info >= (3, 9)",
        ]
        check.standardInput = FileHandle.nullDevice
        check.standardOutput = FileHandle.nullDevice
        check.standardError = FileHandle.nullDevice
        do {
            try check.run()
            check.waitUntilExit()
            return check.terminationStatus == 0
        } catch {
            return false
        }
    }

    private static func preparePrivateDirectory(_ directory: URL) throws {
        let manager = FileManager.default
        if manager.fileExists(atPath: directory.path) {
            let values = try directory.resourceValues(forKeys: [.isSymbolicLinkKey, .isDirectoryKey])
            guard values.isSymbolicLink != true, values.isDirectory == true else {
                throw CoreRuntimeError.privateDirectoryUnavailable(
                    "Klasör güvenli bir yerel dizin değil."
                )
            }
        } else {
            do {
                try manager.createDirectory(
                    at: directory,
                    withIntermediateDirectories: true,
                    attributes: [.posixPermissions: 0o700]
                )
            } catch {
                throw CoreRuntimeError.privateDirectoryUnavailable(error.localizedDescription)
            }
        }
        guard chmod(directory.path, S_IRWXU) == 0 else {
            throw CoreRuntimeError.privateDirectoryUnavailable("Klasör izinleri ayarlanamadı.")
        }
    }

    private static func openPrivateLog(_ url: URL) throws -> FileHandle {
        let manager = FileManager.default
        if !manager.fileExists(atPath: url.path) {
            guard manager.createFile(
                atPath: url.path,
                contents: nil,
                attributes: [.posixPermissions: 0o600]
            ) else {
                throw CoreRuntimeError.privateDirectoryUnavailable("Günlük oluşturulamadı.")
            }
        }
        _ = chmod(url.path, S_IRUSR | S_IWUSR)
        let handle = try FileHandle(forWritingTo: url)
        try handle.seekToEnd()
        return handle
    }

    private static func rotateLogIfNeeded(_ url: URL) throws {
        let manager = FileManager.default
        guard let attributes = try? manager.attributesOfItem(atPath: url.path),
              let size = attributes[.size] as? NSNumber,
              size.int64Value > 5 * 1024 * 1024 else { return }
        let previous = url.appendingPathExtension("1")
        try? manager.removeItem(at: previous)
        try manager.moveItem(at: url, to: previous)
        _ = chmod(previous.path, S_IRUSR | S_IWUSR)
    }

    private static func secureToken() throws -> String {
        var bytes = [UInt8](repeating: 0, count: 32)
        guard SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes) == errSecSuccess else {
            throw CoreRuntimeError.launchFailed("Güvenli oturum anahtarı üretilemedi.")
        }
        return bytes.map { String(format: "%02x", $0) }.joined()
    }

    private static func runtimeEnvironment(
        databaseURL: URL,
        cacheDirectory: URL,
        token: String,
        extra: [String: String]
    ) -> [String: String] {
        let inherited = ProcessInfo.processInfo.environment
        // Provider choice and secrets deliberately do not cross from the
        // launching shell/stable Divan installation into this Preview. Tests
        // and explicit callers may opt in through `extraEnvironment`.
        let inheritedKeys = [
            "HOME", "PATH", "LANG", "LC_ALL", "TMPDIR", "SSL_CERT_FILE",
            "REQUESTS_CA_BUNDLE",
        ]
        var environment: [String: String] = [:]
        for key in inheritedKeys {
            if let value = inherited[key] { environment[key] = value }
        }
        for (key, value) in extra where !key.isEmpty { environment[key] = value }
        environment["PORT"] = "0"
        environment["DIVAN_DB_PATH"] = databaseURL.path
        environment["PYTHONPYCACHEPREFIX"] = cacheDirectory.path
        environment["PYTHONUNBUFFERED"] = "1"
        environment["DIVAN_NO_BROWSER"] = "1"
        environment["DIVAN_SESSION_TOKEN"] = token
        environment["DIVAN_USE_KEYCHAIN"] = "1"
        environment["DIVAN_PRIVATE_FILES"] = "1"
        environment["DIVAN_PLATFORM"] = "macos_native_preview"
        environment["DIVAN_KEYCHAIN_SERVICE"] =
            "com.furkancanyilmaz.divan.native-preview.provider-credentials"
        return environment
    }

    private static func writePrivateMetadata(
        _ metadata: RuntimeMetadata,
        to url: URL
    ) throws {
        let data = try JSONEncoder().encode(metadata)
        try data.write(to: url, options: [.atomic])
        guard chmod(url.path, S_IRUSR | S_IWUSR) == 0 else {
            throw CoreRuntimeError.privateDirectoryUnavailable(
                "Çalışma bilgisi izinleri ayarlanamadı."
            )
        }
    }

    private static func healthCheck(_ endpoint: RuntimeEndpoint) async throws -> Bool {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = 3
        configuration.timeoutIntervalForResource = 5
        configuration.httpCookieAcceptPolicy = .always
        configuration.httpShouldSetCookies = true
        configuration.urlCache = nil
        let delegate = LoopbackRedirectDelegate(origin: endpoint.baseURL)
        let session = URLSession(
            configuration: configuration,
            delegate: delegate,
            delegateQueue: nil
        )
        defer { session.invalidateAndCancel() }

        var launch = URLComponents(url: endpoint.baseURL, resolvingAgainstBaseURL: false)
        launch?.queryItems = [
            URLQueryItem(name: "_divan_session", value: endpoint.sessionToken),
        ]
        guard let launchURL = launch?.url else { return false }
        let (_, launchResponse) = try await session.data(from: launchURL)
        guard let launchHTTP = launchResponse as? HTTPURLResponse,
              (200..<400).contains(launchHTTP.statusCode) else { return false }

        let healthURL = endpoint.baseURL.appendingPathComponent("api/v1/bootstrap")
        let (data, response) = try await session.data(from: healthURL)
        guard let http = response as? HTTPURLResponse,
              http.statusCode == 200,
              data.count <= 4 * 1024 * 1024,
              let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              object["api_contract_version"] is NSNumber else { return false }
        return true
    }
}

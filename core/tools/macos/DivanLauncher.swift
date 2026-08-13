import AppKit
import Darwin
import Foundation

private let processEnvironment = ProcessInfo.processInfo.environment
private let requestedPort: Int? = {
    if let value = processEnvironment["DIVAN_MAC_PORT"],
       let port = Int(value),
       (1...65535).contains(port) {
        return port
    }
    return nil
}()
private let suppressBrowserOpen = processEnvironment["DIVAN_MAC_NO_OPEN"] == "1"

private struct RuntimeMetadata: Codable {
    let version: String
    let port: Int
    let token: String
    let pid: Int32
}

private func launchURL(port: Int, token: String) -> URL? {
    var components = URLComponents()
    components.scheme = "http"
    components.host = "127.0.0.1"
    components.port = port
    components.path = "/"
    components.queryItems = [
        URLQueryItem(name: "_divan_session", value: token),
    ]
    return components.url
}

private func divanIsReady(_ url: URL) -> Bool {
    var request = URLRequest(url: url)
    request.timeoutInterval = 1
    request.cachePolicy = .reloadIgnoringLocalCacheData
    let semaphore = DispatchSemaphore(value: 0)
    var ready = false
    URLSession.shared.dataTask(with: request) { data, response, _ in
        defer { semaphore.signal() }
        guard let http = response as? HTTPURLResponse,
              http.statusCode == 200,
              let data,
              let page = String(data: data, encoding: .utf8) else { return }
        ready = page.contains("<title>Divan")
    }.resume()
    _ = semaphore.wait(timeout: .now() + 1.5)
    return ready
}

private func usablePython() -> String? {
    var candidates = [
        "/opt/homebrew/bin/python3",
        "/usr/local/bin/python3",
        "/usr/bin/python3",
    ]
    for directory in (processEnvironment["PATH"] ?? "")
            .split(separator: ":") {
        let candidate = URL(fileURLWithPath: String(directory))
            .appendingPathComponent("python3").path
        if !candidates.contains(candidate) { candidates.append(candidate) }
    }
    for path in candidates where FileManager.default.isExecutableFile(atPath: path) {
        let check = Process()
        check.executableURL = URL(fileURLWithPath: path)
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
            if check.terminationStatus == 0 { return path }
        } catch {
            continue
        }
    }
    return nil
}

private final class DivanAppDelegate: NSObject, NSApplicationDelegate {
    private let fileManager = FileManager.default
    private let version = Bundle.main.object(
        forInfoDictionaryKey: "CFBundleShortVersionString"
    ) as? String ?? "unknown"

    func applicationDidFinishLaunching(_ notification: Notification) {
        // Inherited by Python as well: newly created DB, WAL, snapshots and
        // metadata are private before any later chmod can run.
        _ = umask(0o077)
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            self?.startDivan()
        }
    }

    private func finishSuccess(_ url: URL) {
        DispatchQueue.main.async {
            if !suppressBrowserOpen {
                NSWorkspace.shared.open(url)
            }
            NSApp.terminate(nil)
        }
    }

    private func finishFailure(_ title: String, _ message: String) {
        DispatchQueue.main.async {
            NSApp.activate(ignoringOtherApps: true)
            let alert = NSAlert()
            alert.alertStyle = .critical
            alert.messageText = title
            alert.informativeText = message
            alert.addButton(withTitle: "Tamam")
            alert.runModal()
            NSApp.terminate(nil)
        }
    }

    private func startDivan() {
        guard let resourceRoot = Bundle.main.resourceURL?
                .appendingPathComponent("Divan", isDirectory: true) else {
            finishFailure("Divan başlatılamadı", "Uygulama dosyaları bulunamadı.")
            return
        }
        let serverURL = resourceRoot.appendingPathComponent("server.py")
        guard fileManager.fileExists(atPath: serverURL.path) else {
            finishFailure("Divan başlatılamadı", "server.py pakette bulunamadı.")
            return
        }
        guard let python = usablePython() else {
            finishFailure(
                "Python 3 gerekli",
                "Divan bu Mac’te Python 3.9 veya daha yenisini bulamadı. " +
                "python.org üzerinden Python 3 kurup Divan’ı yeniden açın."
            )
            return
        }

        let dataURL: URL
        if let override = processEnvironment["DIVAN_MAC_DATA_DIR"],
           !override.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            dataURL = URL(fileURLWithPath: override, isDirectory: true)
        } else {
            guard let applicationSupport = fileManager.urls(
                for: .applicationSupportDirectory,
                in: .userDomainMask
            ).first else {
                finishFailure(
                    "Divan başlatılamadı",
                    "Kullanıcı veri klasörü bulunamadı."
                )
                return
            }
            dataURL = applicationSupport.appendingPathComponent(
                "Divan",
                isDirectory: true
            )
        }
        let cacheURL = dataURL.appendingPathComponent("pycache", isDirectory: true)
        let databaseURL = dataURL.appendingPathComponent("freud.db")
        let logURL = dataURL.appendingPathComponent("server.log")
        let oldLogURL = dataURL.appendingPathComponent("server.log.1")
        let runtimeURL = dataURL.appendingPathComponent("runtime.json")
        let lockURL = dataURL.appendingPathComponent("launcher.lock")

        do {
            try fileManager.createDirectory(
                at: dataURL,
                withIntermediateDirectories: true,
                attributes: [.posixPermissions: 0o700]
            )
            try? fileManager.setAttributes(
                [.posixPermissions: 0o700], ofItemAtPath: dataURL.path)
            let lockDescriptor = Darwin.open(
                lockURL.path, O_CREAT | O_RDWR | O_CLOEXEC,
                S_IRUSR | S_IWUSR)
            guard lockDescriptor >= 0, flock(lockDescriptor, LOCK_EX) == 0 else {
                if lockDescriptor >= 0 { Darwin.close(lockDescriptor) }
                throw NSError(
                    domain: "DivanLauncher", code: 2,
                    userInfo: [NSLocalizedDescriptionKey:
                        "Başlatma kilidi oluşturulamadı."])
            }
            defer {
                _ = flock(lockDescriptor, LOCK_UN)
                Darwin.close(lockDescriptor)
            }
            try fileManager.createDirectory(
                at: cacheURL,
                withIntermediateDirectories: true,
                attributes: [.posixPermissions: 0o700]
            )
            try? fileManager.setAttributes(
                [.posixPermissions: 0o700], ofItemAtPath: cacheURL.path)
            try? fileManager.setAttributes(
                [.posixPermissions: 0o600], ofItemAtPath: lockURL.path)

            if let data = try? Data(contentsOf: runtimeURL),
               let prior = try? JSONDecoder().decode(
                    RuntimeMetadata.self, from: data),
               prior.port > 0,
               prior.pid > 0,
               kill(prior.pid, 0) == 0,
               let priorURL = launchURL(port: prior.port, token: prior.token),
               divanIsReady(priorURL) {
                if prior.version == version {
                    finishSuccess(priorURL)
                    return
                }
                // The token proves this is a Divan process we previously
                // started, so it is safe to retire it during an update.
                _ = kill(prior.pid, SIGTERM)
                for _ in 0..<20 where kill(prior.pid, 0) == 0 {
                    Thread.sleep(forTimeInterval: 0.1)
                }
                if kill(prior.pid, 0) == 0 {
                    throw NSError(
                        domain: "DivanLauncher", code: 3,
                        userInfo: [NSLocalizedDescriptionKey:
                            "Eski Divan sürümü güvenle kapatılamadı."])
                }
            }
            try? fileManager.removeItem(at: runtimeURL)

            if let attributes = try? fileManager.attributesOfItem(
                    atPath: logURL.path),
               let size = attributes[.size] as? NSNumber,
               size.int64Value > 5 * 1024 * 1024 {
                try? fileManager.removeItem(at: oldLogURL)
                try? fileManager.moveItem(at: logURL, to: oldLogURL)
            }
            if !fileManager.fileExists(atPath: logURL.path) {
                fileManager.createFile(
                    atPath: logURL.path,
                    contents: nil,
                    attributes: [.posixPermissions: 0o600]
                )
            }
            try? fileManager.setAttributes(
                [.posixPermissions: 0o600], ofItemAtPath: logURL.path)
            let log = try FileHandle(forWritingTo: logURL)
            try log.seekToEnd()

            let candidatePorts: [Int] = requestedPort.map { [$0] } ??
                (0..<5).map { _ in Int.random(in: 49152...65535) }
            for port in candidatePorts {
                let token = UUID().uuidString.replacingOccurrences(
                    of: "-", with: "") + UUID().uuidString.replacingOccurrences(
                    of: "-", with: "")
                guard let divanURL = launchURL(port: port, token: token) else {
                    continue
                }
                let server = Process()
                server.executableURL = URL(fileURLWithPath: python)
                server.arguments = [serverURL.path]
                server.currentDirectoryURL = resourceRoot
                server.standardInput = FileHandle.nullDevice
                server.standardOutput = log
                server.standardError = log
                var environment = ProcessInfo.processInfo.environment
                environment["PORT"] = String(port)
                environment["DIVAN_DB_PATH"] = databaseURL.path
                environment["PYTHONPYCACHEPREFIX"] = cacheURL.path
                environment["DIVAN_NO_BROWSER"] = "1"
                environment["DIVAN_SESSION_TOKEN"] = token
                environment["DIVAN_USE_KEYCHAIN"] = "1"
                environment["DIVAN_PRIVATE_FILES"] = "1"
                server.environment = environment
                try server.run()

                var ready = false
                for _ in 0..<60 {
                    Thread.sleep(forTimeInterval: 0.2)
                    if divanIsReady(divanURL) {
                        ready = true
                        break
                    }
                    if !server.isRunning { break }
                }
                if ready {
                    let metadata = RuntimeMetadata(
                        version: version,
                        port: port,
                        token: token,
                        pid: server.processIdentifier
                    )
                    let encoded = try JSONEncoder().encode(metadata)
                    try encoded.write(to: runtimeURL, options: .atomic)
                    try? fileManager.setAttributes(
                        [.posixPermissions: 0o600],
                        ofItemAtPath: runtimeURL.path)
                    if fileManager.fileExists(atPath: databaseURL.path) {
                        try? fileManager.setAttributes(
                            [.posixPermissions: 0o600],
                            ofItemAtPath: databaseURL.path)
                    }
                    try? log.close()
                    finishSuccess(divanURL)
                    return
                }
                if server.isRunning {
                    server.terminate()
                    server.waitUntilExit()
                }
            }
            try? log.close()
        } catch {
            finishFailure(
                "Divan başlatılamadı",
                "Yerel sunucu açılamadı. Ayrıntılar: \(logURL.path)\n\n\(error.localizedDescription)"
            )
            return
        }

        finishFailure(
            "Divan başlatılamadı",
            "Yerel sunucuya ulaşılamadı. Uygun bir yerel bağlantı " +
            "noktası bulunamadı veya sunucu erken kapandı.\n\n" +
            "Ayrıntılar: \(logURL.path)"
        )
    }
}

let application = NSApplication.shared
private let delegate = DivanAppDelegate()
application.delegate = delegate
application.setActivationPolicy(.accessory)
application.run()

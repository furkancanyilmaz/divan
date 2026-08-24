@preconcurrency import AVFoundation
import Foundation
import UIKit
import UniformTypeIdentifiers
import UserNotifications
import WebKit

private func bridgeFailure(_ code: String) -> [String: Any] {
    let message: String
    switch code {
    case "cancelled": message = "İşlem kullanıcı tarafından kapatıldı."
    case "permission_denied": message = "Gerekli sistem izni verilmedi."
    case "payload_too_large": message = "Seçilen içerik bu işlem için çok büyük."
    case "scanner_unavailable": message = "QR tarayıcı bu cihazda kullanılamıyor."
    case "scan_in_progress": message = "QR tarayıcı zaten açık."
    case "unsupported": message = "Bu işlem iOS uygulamasında desteklenmiyor."
    default: message = "Yerel uygulama işlemi tamamlanamadı."
    }
    return ["ok": false, "error": ["code": code, "message": message]]
}

@MainActor
final class DivanNativeBridge: NSObject, WKScriptMessageHandlerWithReply,
    UIDocumentPickerDelegate {

    static let handlerName = "divanNative"
    static let capabilities = [
        "setPendingWork",
        "showKeyboard",
        "hideKeyboard",
        "copyText",
        "saveText",
        "saveStoryImage",
        "shareStoryImages",
        "scanSyncQr",
        "completionNotifications",
        "haptic",
        "reminders",
    ]

    static var bootstrapScript: WKUserScript {
        let bootstrap: [String: Any] = [
            "version": 1,
            "platform": "ios",
            "deviceName": UIDevice.current.userInterfaceIdiom == .pad
                ? "iPad" : "iPhone",
            "capabilities": capabilities,
        ]
        let data = try! JSONSerialization.data(withJSONObject: bootstrap)
        let json = String(decoding: data, as: UTF8.self)
        return WKUserScript(
            source: "Object.defineProperty(window, '__DIVAN_NATIVE_BOOTSTRAP__', "
                + "{value:Object.freeze(\(json)),writable:false,configurable:false});",
            injectionTime: .atDocumentStart,
            forMainFrameOnly: true
        )
    }

    private static let maximumClipboardBytes = 256 * 1024
    private static let maximumTextBytes = 32 * 1024 * 1024
    private static let maximumDownloadedFileBytes: Int64 = 512 * 1024 * 1024
    private static let maximumStoryPages = 8
    private static let maximumStoryEncodedCharacters = 12 * 1024 * 1024
    private static let maximumStoryImageBytes = 8 * 1024 * 1024
    private static let maximumStoryTotalBytes = 40 * 1024 * 1024
    private static let pngDataPrefix = "data:image/png;base64,"
    private static let notificationPreferenceKey =
        "divan.reply-notifications-enabled"

    private weak var webView: WKWebView?
    private var endpoint: URL
    private var temporaryExportURLs = Set<URL>()
    private var backgroundTask: UIBackgroundTaskIdentifier = .invalid
    private var pendingWorkCount = 0
    private var qrScanner: DivanQRScannerViewController?
    private var qrReply: ((Any?, String?) -> Void)?

    init(endpoint: URL) {
        self.endpoint = endpoint
        super.init()
        purgeStaleTemporaryExports()
    }

    func attach(to webView: WKWebView) {
        self.webView = webView
    }

    func detach() {
        endBackgroundTask()
        qrScanner?.dismiss(animated: false)
        qrScanner = nil
        qrReply?(nil, "cancelled")
        qrReply = nil
        webView = nil
        cleanupTemporaryExports()
    }

    func updateEndpoint(_ endpoint: URL) {
        self.endpoint = endpoint
    }

    func userContentController(
        _ userContentController: WKUserContentController,
        didReceive message: WKScriptMessage,
        replyHandler: @escaping (Any?, String?) -> Void
    ) {
        guard message.name == Self.handlerName,
              message.frameInfo.isMainFrame,
              let sourceURL = message.frameInfo.request.url,
              LoopbackURLPolicy.isSameOrigin(sourceURL, as: endpoint),
              let envelope = message.body as? [String: Any],
              (envelope["version"] as? NSNumber)?.intValue == 1,
              let method = envelope["method"] as? String,
              method.count <= 64 else {
            replyHandler(bridgeFailure("invalid_request"), nil)
            return
        }
        let payload = envelope["payload"] as? [String: Any] ?? [:]

        switch method {
        case "copyText":
            copyText(payload, reply: replyHandler)
        case "saveText":
            saveText(payload, reply: replyHandler)
        case "saveStoryImage":
            saveStoryImage(payload, reply: replyHandler)
        case "shareStoryImages":
            shareStoryImages(payload, reply: replyHandler)
        case "scanSyncQr":
            scanSyncQR(reply: replyHandler)
        case "replyNotificationsEnabled":
            replyHandler(completionNotificationsEnabled(), nil)
        case "setReplyNotificationsEnabled":
            setCompletionNotifications(payload, reply: replyHandler)
        case "setPendingWork":
            setPendingWork(payload, reply: replyHandler)
        case "showKeyboard":
            // JavaScript focuses the actual textarea. The native side only
            // makes sure the web view can become the current responder.
            webView?.becomeFirstResponder()
            replyHandler(true, nil)
        case "hideKeyboard":
            webView?.endEditing(true)
            replyHandler(true, nil)
        case "haptic":
            performHaptic(style: payload["style"] as? String)
            replyHandler(true, nil)
        case "scheduleReminderNotification":
            scheduleReminderNotification(payload, reply: replyHandler)
        case "cancelReminderNotification":
            cancelReminderNotification(payload, reply: replyHandler)
        default:
            replyHandler(bridgeFailure("unsupported"), nil)
        }
    }

    private func copyText(
        _ payload: [String: Any],
        reply: @escaping (Any?, String?) -> Void
    ) {
        guard let text = payload["text"] as? String,
              text.lengthOfBytes(using: .utf8) <= Self.maximumClipboardBytes else {
            reply(bridgeFailure("payload_too_large"), nil)
            return
        }
        UIPasteboard.general.setItems(
            [[UTType.utf8PlainText.identifier: text]],
            options: [.expirationDate: Date().addingTimeInterval(10 * 60)]
        )
        reply(true, nil)
    }

    private func saveText(
        _ payload: [String: Any],
        reply: @escaping (Any?, String?) -> Void
    ) {
        guard let content = payload["content"] as? String,
              let data = content.data(using: .utf8),
              data.count <= Self.maximumTextBytes else {
            reply(bridgeFailure("payload_too_large"), nil)
            return
        }
        do {
            let url = try writeTemporary(
                data: data,
                requestedName: payload["fileName"] as? String ?? "divan.md",
                defaultExtension: "md"
            )
            guard presentDocumentExporter(url) else {
                cleanup([url])
                reply(bridgeFailure("unavailable"), nil)
                return
            }
            reply(true, nil)
        } catch {
            reply(bridgeFailure("save_failed"), nil)
        }
    }

    private func saveStoryImage(
        _ payload: [String: Any],
        reply: @escaping (Any?, String?) -> Void
    ) {
        guard let dataURL = payload["dataUrl"] as? String else {
            reply(bridgeFailure("invalid_request"), nil)
            return
        }
        do {
            let data = try decodeStoryPNG(dataURL)
            let url = try writeTemporary(
                data: data,
                requestedName: payload["fileName"] as? String ?? "divan.png",
                defaultExtension: "png"
            )
            guard presentDocumentExporter(url) else {
                cleanup([url])
                reply(bridgeFailure("unavailable"), nil)
                return
            }
            reply(true, nil)
        } catch let error as NativeBridgeError {
            reply(bridgeFailure(error.rawValue), nil)
        } catch {
            reply(bridgeFailure("save_failed"), nil)
        }
    }

    private func shareStoryImages(
        _ payload: [String: Any],
        reply: @escaping (Any?, String?) -> Void
    ) {
        guard let pages = payload["dataUrls"] as? [String],
              !pages.isEmpty,
              pages.count <= Self.maximumStoryPages else {
            reply(bridgeFailure("invalid_request"), nil)
            return
        }

        do {
            var totalBytes = 0
            var urls: [URL] = []
            for (index, dataURL) in pages.enumerated() {
                let data = try decodeStoryPNG(dataURL)
                totalBytes += data.count
                guard totalBytes <= Self.maximumStoryTotalBytes else {
                    throw NativeBridgeError.payloadTooLarge
                }
                let url = try writeTemporary(
                    data: data,
                    requestedName: String(format: "divan-hikaye-%02d.png", index + 1),
                    defaultExtension: "png"
                )
                urls.append(url)
            }

            guard let presenter = presentingViewController() else {
                cleanup(urls)
                reply(bridgeFailure("unavailable"), nil)
                return
            }
            let controller = UIActivityViewController(
                activityItems: urls,
                applicationActivities: nil
            )
            if let popover = controller.popoverPresentationController {
                popover.sourceView = webView
                popover.sourceRect = webView?.bounds ?? .zero
            }
            controller.completionWithItemsHandler = { [weak self] _, _, _, _ in
                Task { @MainActor in self?.cleanup(urls) }
            }
            presenter.present(controller, animated: true)
            reply(true, nil)
        } catch let error as NativeBridgeError {
            reply(bridgeFailure(error.rawValue), nil)
        } catch {
            reply(bridgeFailure("share_failed"), nil)
        }
    }

    private func scanSyncQR(reply: @escaping (Any?, String?) -> Void) {
        guard qrScanner == nil, qrReply == nil else {
            reply(bridgeFailure("scan_in_progress"), nil)
            return
        }
        guard UIImagePickerController.isSourceTypeAvailable(.camera),
              let presenter = presentingViewController() else {
            reply(bridgeFailure("scanner_unavailable"), nil)
            return
        }

        let presentScanner = { [weak self, weak presenter] in
            guard let self, let presenter else {
                reply(bridgeFailure("scanner_unavailable"), nil)
                return
            }
            let scanner = DivanQRScannerViewController()
            self.qrScanner = scanner
            self.qrReply = reply
            scanner.onResult = { [weak self] result in
                guard let self else { return }
                let completion = self.qrReply
                self.qrReply = nil
                self.qrScanner = nil
                switch result {
                case .success(let code): completion?(code, nil)
                case .failure(let error):
                    completion?(bridgeFailure(error.rawValue), nil)
                }
            }
            presenter.present(scanner, animated: true)
        }

        switch AVCaptureDevice.authorizationStatus(for: .video) {
        case .authorized:
            presentScanner()
        case .notDetermined:
            AVCaptureDevice.requestAccess(for: .video) { granted in
                Task { @MainActor in
                    granted
                        ? presentScanner()
                        : reply(bridgeFailure("permission_denied"), nil)
                }
            }
        default:
            reply(bridgeFailure("permission_denied"), nil)
        }
    }

    private func setCompletionNotifications(
        _ payload: [String: Any],
        reply: @escaping (Any?, String?) -> Void
    ) {
        let enabled = payload["enabled"] as? Bool ?? false
        if !enabled {
            UserDefaults.standard.set(false, forKey: Self.notificationPreferenceKey)
            UNUserNotificationCenter.current().removePendingNotificationRequests(
                withIdentifiers: ["divan-response-ready"]
            )
            reply(true, nil)
            return
        }

        UNUserNotificationCenter.current().requestAuthorization(
            options: [.alert, .sound]
        ) { granted, _ in
            Task { @MainActor in
                UserDefaults.standard.set(
                    granted,
                    forKey: Self.notificationPreferenceKey
                )
                granted
                    ? reply(true, nil)
                    : reply(bridgeFailure("permission_denied"), nil)
            }
        }
    }

    private func setPendingWork(
        _ payload: [String: Any],
        reply: @escaping (Any?, String?) -> Void
    ) {
        let previous = pendingWorkCount
        let count = max(0, (payload["count"] as? NSNumber)?.intValue ?? 0)
        pendingWorkCount = count
        if count > 0 {
            beginBackgroundTaskIfNeeded()
        } else {
            endBackgroundTask()
            if previous > 0,
               UIApplication.shared.applicationState != .active,
               completionNotificationsEnabled() {
                postCompletionNotification()
            }
        }
        reply(true, nil)
    }

    private func beginBackgroundTaskIfNeeded() {
        guard backgroundTask == .invalid else { return }
        backgroundTask = UIApplication.shared.beginBackgroundTask(
            withName: "Divan model yanıtı"
        ) { [weak self] in
            Task { @MainActor in self?.endBackgroundTask() }
        }
    }

    private func endBackgroundTask() {
        guard backgroundTask != .invalid else { return }
        UIApplication.shared.endBackgroundTask(backgroundTask)
        backgroundTask = .invalid
    }

    private func completionNotificationsEnabled() -> Bool {
        UserDefaults.standard.bool(forKey: Self.notificationPreferenceKey)
    }

    private func postCompletionNotification() {
        let content = UNMutableNotificationContent()
        content.title = "Divan"
        content.body = "Yanıt hazır."
        content.sound = .default
        let request = UNNotificationRequest(
            identifier: "divan-response-ready",
            content: content,
            trigger: nil
        )
        UNUserNotificationCenter.current().add(request)
    }

    // MARK: - ADHD koçu görev hatırlatıcıları

    private static let reminderNotificationPrefix = "divan-reminder-"
    private static let maximumReminderDelaySeconds: TimeInterval = 366 * 24 * 3600

    /// Gelecekteki bir ana sistem bildirimi kurar. Uygulama kapanmış olsa
    /// bile bildirim iOS tarafından zamanında gösterilir.
    private func scheduleReminderNotification(
        _ payload: [String: Any],
        reply: @escaping (Any?, String?) -> Void
    ) {
        let rawID = String(payload["id"] as? String ?? "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        let title = String(payload["title"] as? String ?? "Divan")
        let body = String(payload["body"] as? String ?? "")
        let rawDelay = (payload["afterSeconds"] as? NSNumber)?.doubleValue ?? 0
        guard !rawID.isEmpty, rawID.utf8.count <= 64,
              title.utf8.count <= 120,
              !body.isEmpty, body.utf8.count <= 500,
              rawDelay.isFinite, rawDelay > 0 else {
            reply(bridgeFailure("invalid_request"), nil)
            return
        }
        let delay = min(max(rawDelay, 1), Self.maximumReminderDelaySeconds)
        let identifier = Self.reminderNotificationPrefix + rawID
        let deliver = { (granted: Bool) in
            Task { @MainActor in
                guard granted else {
                    reply(bridgeFailure("permission_denied"), nil)
                    return
                }
                let content = UNMutableNotificationContent()
                content.title = title
                content.body = body
                content.sound = .default
                let trigger = UNTimeIntervalNotificationTrigger(
                    timeInterval: delay,
                    repeats: false
                )
                let request = UNNotificationRequest(
                    identifier: identifier,
                    content: content,
                    trigger: trigger
                )
                UNUserNotificationCenter.current().add(request)
                reply(true, nil)
            }
        }
        UNUserNotificationCenter.current().getNotificationSettings { settings in
            switch settings.authorizationStatus {
            case .notDetermined:
                UNUserNotificationCenter.current().requestAuthorization(
                    options: [.alert, .sound]
                ) { granted, _ in deliver(granted) }
            case .authorized, .provisional, .ephemeral:
                deliver(true)
            default:
                deliver(false)
            }
        }
    }

    /// Kurulmuş bir görev bildirimini kaldırır (görev silindi/yapıldı).
    private func cancelReminderNotification(
        _ payload: [String: Any],
        reply: @escaping (Any?, String?) -> Void
    ) {
        let rawID = String(payload["id"] as? String ?? "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        guard !rawID.isEmpty, rawID.utf8.count <= 64 else {
            reply(bridgeFailure("invalid_request"), nil)
            return
        }
        UNUserNotificationCenter.current().removePendingNotificationRequests(
            withIdentifiers: [Self.reminderNotificationPrefix + rawID]
        )
        reply(true, nil)
    }

    private func performHaptic(style: String?) {
        let feedbackStyle: UIImpactFeedbackGenerator.FeedbackStyle
        switch style {
        case "medium": feedbackStyle = .medium
        case "heavy": feedbackStyle = .heavy
        case "soft": feedbackStyle = .soft
        case "rigid": feedbackStyle = .rigid
        default: feedbackStyle = .light
        }
        UIImpactFeedbackGenerator(style: feedbackStyle).impactOccurred()
    }

    private func decodeStoryPNG(_ dataURL: String) throws -> Data {
        guard dataURL.hasPrefix(Self.pngDataPrefix) else {
            throw NativeBridgeError.invalidImage
        }
        let encoded = String(dataURL.dropFirst(Self.pngDataPrefix.count))
        guard !encoded.isEmpty,
              encoded.count <= Self.maximumStoryEncodedCharacters,
              let data = Data(base64Encoded: encoded, options: []),
              !data.isEmpty,
              data.count <= Self.maximumStoryImageBytes else {
            throw NativeBridgeError.payloadTooLarge
        }
        let pngSignature = Data([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A])
        guard data.starts(with: pngSignature) else {
            throw NativeBridgeError.invalidImage
        }
        return data
    }

    private func writeTemporary(
        data: Data,
        requestedName: String,
        defaultExtension: String
    ) throws -> URL {
        let directory = Self.exportDirectory
        let directoryAttributes: [FileAttributeKey: Any] = [
            .protectionKey: FileProtectionType.complete,
            .posixPermissions: 0o700,
        ]
        try FileManager.default.createDirectory(
            at: directory,
            withIntermediateDirectories: true,
            attributes: directoryAttributes
        )
        try FileManager.default.setAttributes(
            directoryAttributes,
            ofItemAtPath: directory.path
        )
        try Self.excludeFromBackup(directory)
        var name = safeFileName(requestedName)
        if URL(fileURLWithPath: name).pathExtension.isEmpty {
            name += ".\(defaultExtension)"
        }
        let url = directory.appendingPathComponent(
            UUID().uuidString + "-" + name,
            isDirectory: false
        )
        try data.write(to: url, options: [.atomic, .completeFileProtection])
        try FileManager.default.setAttributes(
            [
                .protectionKey: FileProtectionType.complete,
                .posixPermissions: 0o600,
            ],
            ofItemAtPath: url.path
        )
        temporaryExportURLs.insert(url)
        return url
    }

    func prepareDownloadDestination(
        response: URLResponse,
        suggestedFilename: String
    ) throws -> URL {
        guard let sourceURL = response.url,
              LoopbackURLPolicy.isSameOrigin(sourceURL, as: endpoint) else {
            throw NativeDownloadError.untrustedSource
        }
        if let httpResponse = response as? HTTPURLResponse,
           !(200 ..< 300).contains(httpResponse.statusCode) {
            throw NativeDownloadError.invalidResponse
        }
        let expectedLength = response.expectedContentLength
        guard expectedLength < 0
                || expectedLength <= Self.maximumDownloadedFileBytes else {
            throw NativeDownloadError.payloadTooLarge
        }

        let root = Self.exportDirectory
        let privateDirectoryAttributes: [FileAttributeKey: Any] = [
            .protectionKey: FileProtectionType.complete,
            .posixPermissions: 0o700,
        ]
        try FileManager.default.createDirectory(
            at: root,
            withIntermediateDirectories: true,
            attributes: privateDirectoryAttributes
        )
        try FileManager.default.setAttributes(
            privateDirectoryAttributes,
            ofItemAtPath: root.path
        )
        try Self.excludeFromBackup(root)
        let directory = root.appendingPathComponent(
            UUID().uuidString,
            isDirectory: true
        )
        try FileManager.default.createDirectory(
            at: directory,
            withIntermediateDirectories: true,
            attributes: privateDirectoryAttributes
        )

        var name = safeFileName(suggestedFilename)
        if URL(fileURLWithPath: name).pathExtension.isEmpty,
           let mimeType = response.mimeType,
           let preferredExtension = UTType(mimeType: mimeType)?.preferredFilenameExtension {
            name += ".\(preferredExtension)"
        }
        let destination = directory.appendingPathComponent(name, isDirectory: false)
        guard !FileManager.default.fileExists(atPath: destination.path) else {
            throw NativeDownloadError.invalidDestination
        }
        temporaryExportURLs.insert(destination)
        return destination
    }

    func presentDownloadedFile(_ url: URL) throws {
        guard temporaryExportURLs.contains(url),
              isManagedExportURL(url),
              FileManager.default.fileExists(atPath: url.path) else {
            throw NativeDownloadError.invalidDestination
        }
        let attributes = try FileManager.default.attributesOfItem(atPath: url.path)
        let size = (attributes[.size] as? NSNumber)?.int64Value ?? 0
        guard size > 0, size <= Self.maximumDownloadedFileBytes else {
            throw size > Self.maximumDownloadedFileBytes
                ? NativeDownloadError.payloadTooLarge
                : NativeDownloadError.invalidResponse
        }
        try FileManager.default.setAttributes(
            [
                .protectionKey: FileProtectionType.complete,
                .posixPermissions: 0o600,
            ],
            ofItemAtPath: url.path
        )
        guard let presenter = presentingViewController() else {
            throw NativeDownloadError.unavailable
        }

        let controller = UIActivityViewController(
            activityItems: [url],
            applicationActivities: nil
        )
        if let popover = controller.popoverPresentationController {
            popover.sourceView = webView
            popover.sourceRect = webView?.bounds ?? .zero
        }
        controller.completionWithItemsHandler = { [weak self] _, _, _, _ in
            Task { @MainActor in self?.cleanup([url]) }
        }
        presenter.present(controller, animated: true)
    }

    func discardTemporaryExport(_ url: URL) {
        cleanup([url])
    }

    func presentDownloadFailure(_ message: String) {
        guard let presenter = presentingViewController(),
              !(presenter is UIAlertController) else { return }
        let alert = UIAlertController(
            title: "Dosya kaydedilemedi",
            message: message,
            preferredStyle: .alert
        )
        alert.addAction(UIAlertAction(title: "Tamam", style: .default))
        presenter.present(alert, animated: true)
    }

    @discardableResult
    private func presentDocumentExporter(_ url: URL) -> Bool {
        guard let presenter = presentingViewController() else { return false }
        let picker = UIDocumentPickerViewController(forExporting: [url], asCopy: true)
        picker.delegate = self
        presenter.present(picker, animated: true)
        return true
    }

    func documentPickerWasCancelled(_ controller: UIDocumentPickerViewController) {
        cleanupTemporaryExports()
    }

    func documentPicker(
        _ controller: UIDocumentPickerViewController,
        didPickDocumentsAt urls: [URL]
    ) {
        cleanupTemporaryExports()
    }

    private func safeFileName(_ requested: String) -> String {
        let forbidden = CharacterSet(charactersIn: "\\/:*?\"<>|")
            .union(.controlCharacters)
        let parts = requested.components(separatedBy: forbidden)
        let joined = parts.joined(separator: "_")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        let safeName = joined.isEmpty || joined == "." || joined == ".."
            ? "divan-dosya" : joined
        return String(safeName.prefix(120))
    }

    private func presentingViewController() -> UIViewController? {
        var controller = webView?.window?.rootViewController
        while let presented = controller?.presentedViewController {
            controller = presented
        }
        return controller
    }

    private func cleanup(_ urls: [URL]) {
        for url in urls {
            try? FileManager.default.removeItem(at: url)
            temporaryExportURLs.remove(url)
            let parent = url.deletingLastPathComponent()
            if parent != Self.exportDirectory,
               isManagedExportURL(parent),
               (try? FileManager.default.contentsOfDirectory(
                at: parent,
                includingPropertiesForKeys: nil
               ).isEmpty) == true {
                try? FileManager.default.removeItem(at: parent)
            }
        }
    }

    private func isManagedExportURL(_ url: URL) -> Bool {
        let rootPath = Self.exportDirectory.standardizedFileURL.path + "/"
        return url.standardizedFileURL.path.hasPrefix(rootPath)
    }

    private func cleanupTemporaryExports() {
        cleanup(Array(temporaryExportURLs))
        try? FileManager.default.removeItem(at: Self.exportDirectory)
    }

    private static var exportDirectory: URL {
        FileManager.default.temporaryDirectory
            .appendingPathComponent("DivanExports", isDirectory: true)
    }

    private static func excludeFromBackup(_ directory: URL) throws {
        var protectedURL = directory
        var values = URLResourceValues()
        values.isExcludedFromBackup = true
        try protectedURL.setResourceValues(values)
    }

    private func purgeStaleTemporaryExports() {
        // iOS may terminate the process while a share sheet or document picker
        // is open. Remove exports from that previous process before the bridge
        // can create new ones.
        try? FileManager.default.removeItem(at: Self.exportDirectory)
        temporaryExportURLs.removeAll()
    }
}

@MainActor
final class WeakDivanNativeReplyHandler: NSObject, WKScriptMessageHandlerWithReply {
    weak var delegate: DivanNativeBridge?

    init(delegate: DivanNativeBridge) {
        self.delegate = delegate
    }

    func userContentController(
        _ userContentController: WKUserContentController,
        didReceive message: WKScriptMessage,
        replyHandler: @escaping (Any?, String?) -> Void
    ) {
        guard let delegate else {
            replyHandler(bridgeFailure("unavailable"), nil)
            return
        }
        delegate.userContentController(
            userContentController,
            didReceive: message,
            replyHandler: replyHandler
        )
    }
}

private enum NativeBridgeError: String, Error {
    case invalidImage = "invalid_image"
    case payloadTooLarge = "payload_too_large"
}

private enum NativeDownloadError: LocalizedError {
    case invalidDestination
    case invalidResponse
    case payloadTooLarge
    case unavailable
    case untrustedSource

    var errorDescription: String? {
        switch self {
        case .payloadTooLarge:
            return "Dosya güvenli indirme sınırını aşıyor."
        case .untrustedSource:
            return "Yalnızca Divan'ın yerel sunucusundaki dosyalar indirilebilir."
        case .unavailable:
            return "Paylaşma ekranı şu anda açılamıyor."
        case .invalidDestination, .invalidResponse:
            return "İndirilen dosya doğrulanamadı. Lütfen yeniden deneyin."
        }
    }
}

private enum QRScannerError: String, Error {
    case cancelled
    case permissionDenied = "permission_denied"
    case scannerUnavailable = "scanner_unavailable"
    case scanFailed = "scan_failed"
}

@MainActor
private final class DivanQRScannerViewController: UIViewController,
    @preconcurrency AVCaptureMetadataOutputObjectsDelegate {

    var onResult: ((Result<String, QRScannerError>) -> Void)?

    private let captureSession = AVCaptureSession()
    private var previewLayer: AVCaptureVideoPreviewLayer?
    private var completed = false

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .black

        let cancel = UIButton(type: .system)
        cancel.translatesAutoresizingMaskIntoConstraints = false
        var cancelConfiguration = UIButton.Configuration.filled()
        cancelConfiguration.title = "Vazgeç"
        cancelConfiguration.baseForegroundColor = .white
        cancelConfiguration.baseBackgroundColor = UIColor.black.withAlphaComponent(0.55)
        cancelConfiguration.contentInsets = NSDirectionalEdgeInsets(
            top: 9,
            leading: 16,
            bottom: 9,
            trailing: 16
        )
        cancel.configuration = cancelConfiguration
        cancel.titleLabel?.font = .preferredFont(forTextStyle: .headline)
        cancel.layer.cornerRadius = 18
        cancel.addTarget(self, action: #selector(cancelTapped), for: .touchUpInside)

        let instruction = UILabel()
        instruction.translatesAutoresizingMaskIntoConstraints = false
        instruction.text = "Divan eşitleme QR kodunu çerçeveye alın"
        instruction.textColor = .white
        instruction.textAlignment = .center
        instruction.numberOfLines = 0
        instruction.font = .preferredFont(forTextStyle: .headline)
        instruction.backgroundColor = UIColor.black.withAlphaComponent(0.55)
        instruction.layer.cornerRadius = 12
        instruction.clipsToBounds = true

        view.addSubview(instruction)
        view.addSubview(cancel)
        NSLayoutConstraint.activate([
            cancel.topAnchor.constraint(equalTo: view.safeAreaLayoutGuide.topAnchor, constant: 12),
            cancel.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -16),
            instruction.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 24),
            instruction.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -24),
            instruction.bottomAnchor.constraint(equalTo: view.safeAreaLayoutGuide.bottomAnchor, constant: -24),
            instruction.heightAnchor.constraint(greaterThanOrEqualToConstant: 54),
        ])

        configureCapture()
    }

    override func viewDidLayoutSubviews() {
        super.viewDidLayoutSubviews()
        previewLayer?.frame = view.bounds
    }

    override func viewWillDisappear(_ animated: Bool) {
        super.viewWillDisappear(animated)
        captureSession.stopRunning()
    }

    private func configureCapture() {
        guard let device = AVCaptureDevice.default(for: .video),
              let input = try? AVCaptureDeviceInput(device: device),
              captureSession.canAddInput(input) else {
            finish(.failure(.scannerUnavailable))
            return
        }
        captureSession.addInput(input)

        let output = AVCaptureMetadataOutput()
        guard captureSession.canAddOutput(output) else {
            finish(.failure(.scannerUnavailable))
            return
        }
        captureSession.addOutput(output)
        output.setMetadataObjectsDelegate(self, queue: .main)
        output.metadataObjectTypes = [.qr]

        let preview = AVCaptureVideoPreviewLayer(session: captureSession)
        preview.videoGravity = .resizeAspectFill
        view.layer.insertSublayer(preview, at: 0)
        previewLayer = preview

        DispatchQueue.global(qos: .userInitiated).async { [captureSession] in
            captureSession.startRunning()
        }
    }

    func metadataOutput(
        _ output: AVCaptureMetadataOutput,
        didOutput metadataObjects: [AVMetadataObject],
        from connection: AVCaptureConnection
    ) {
        guard let readable = metadataObjects.first as? AVMetadataMachineReadableCodeObject,
              let value = readable.stringValue,
              !value.isEmpty,
              value.utf8.count <= 64 * 1024 else { return }
        UINotificationFeedbackGenerator().notificationOccurred(.success)
        finish(.success(value))
    }

    @objc private func cancelTapped() {
        finish(.failure(.cancelled))
    }

    private func finish(_ result: Result<String, QRScannerError>) {
        guard !completed else { return }
        completed = true
        captureSession.stopRunning()
        dismiss(animated: true) { [onResult] in onResult?(result) }
    }
}

import SwiftUI
import UIKit
import WebKit

struct DivanWebView: UIViewRepresentable {
    let endpoint: RuntimeEndpoint

    func makeCoordinator() -> Coordinator {
        Coordinator(endpoint: endpoint.baseURL)
    }

    func makeUIView(context: Context) -> WKWebView {
        let contentController = WKUserContentController()
        contentController.addScriptMessageHandler(
            context.coordinator.nativeReplyHandler,
            contentWorld: .page,
            name: DivanNativeBridge.handlerName
        )
        contentController.addUserScript(DivanNativeBridge.bootstrapScript)

        let configuration = WKWebViewConfiguration()
        configuration.userContentController = contentController
        configuration.websiteDataStore = .default()
        configuration.preferences.javaScriptCanOpenWindowsAutomatically = false
        configuration.defaultWebpagePreferences.allowsContentJavaScript = true
        configuration.limitsNavigationsToAppBoundDomains = false

        let webView = SafeAreaReportingWebView(frame: .zero, configuration: configuration)
        webView.navigationDelegate = context.coordinator
        webView.uiDelegate = context.coordinator
        webView.allowsBackForwardNavigationGestures = false
        webView.allowsLinkPreview = false
        webView.scrollView.contentInsetAdjustmentBehavior = .never
        webView.scrollView.keyboardDismissMode = .interactive
        webView.inputAssistantItem.leadingBarButtonGroups = []
        webView.inputAssistantItem.trailingBarButtonGroups = []
        webView.isOpaque = true
        webView.backgroundColor = UIColor(red: 0.95, green: 0.92, blue: 0.85, alpha: 1)
        webView.scrollView.backgroundColor = webView.backgroundColor
        webView.customUserAgent = "Divan-iOS/1"

        #if DEBUG
        if #available(iOS 16.4, *) {
            webView.isInspectable = true
        }
        #endif

        context.coordinator.attach(to: webView)
        webView.safeAreaDidChange = { [weak coordinator = context.coordinator] in
            coordinator?.reportSafeArea($0)
        }
        context.coordinator.loadEndpointIfNeeded(in: webView)
        return webView
    }

    func updateUIView(_ webView: WKWebView, context: Context) {
        context.coordinator.updateEndpoint(endpoint.baseURL, in: webView)
        context.coordinator.reportSafeArea(webView.safeAreaInsets)
    }

    static func dismantleUIView(_ webView: WKWebView, coordinator: Coordinator) {
        coordinator.detach(from: webView)
        webView.configuration.userContentController.removeScriptMessageHandler(
            forName: DivanNativeBridge.handlerName,
            contentWorld: .page
        )
        webView.navigationDelegate = nil
        webView.uiDelegate = nil
    }

    @MainActor
    final class Coordinator: NSObject, WKNavigationDelegate, WKUIDelegate,
        WKDownloadDelegate {

        private weak var webView: WKWebView?
        let nativeBridge: DivanNativeBridge
        let nativeReplyHandler: WeakDivanNativeReplyHandler
        private var endpoint: URL
        private var loadedEndpoint: URL?
        private var keyboardObservers: [NSObjectProtocol] = []
        private var activeDownloads: [ObjectIdentifier: WKDownload] = [:]
        private var downloadDestinations: [ObjectIdentifier: URL] = [:]

        init(endpoint: URL) {
            self.endpoint = endpoint
            let nativeBridge = DivanNativeBridge(endpoint: endpoint)
            self.nativeBridge = nativeBridge
            nativeReplyHandler = WeakDivanNativeReplyHandler(delegate: nativeBridge)
        }

        func attach(to webView: WKWebView) {
            self.webView = webView
            nativeBridge.attach(to: webView)
            observeKeyboard()
        }

        func detach(from webView: WKWebView) {
            keyboardObservers.forEach(NotificationCenter.default.removeObserver)
            keyboardObservers.removeAll()
            for download in activeDownloads.values {
                download.delegate = nil
                download.cancel { _ in }
            }
            activeDownloads.removeAll()
            downloadDestinations.removeAll()
            if self.webView === webView {
                self.webView = nil
            }
            nativeBridge.detach()
        }

        func updateEndpoint(_ newEndpoint: URL, in webView: WKWebView) {
            guard endpoint != newEndpoint else { return }
            endpoint = newEndpoint
            nativeBridge.updateEndpoint(newEndpoint)
            loadedEndpoint = nil
            loadEndpointIfNeeded(in: webView)
        }

        func loadEndpointIfNeeded(in webView: WKWebView) {
            guard loadedEndpoint != endpoint,
                  LoopbackURLPolicy.isLoopbackHTTP(endpoint) else { return }
            loadedEndpoint = endpoint
            var request = URLRequest(url: endpoint)
            request.cachePolicy = .reloadRevalidatingCacheData
            request.timeoutInterval = 30
            webView.load(request)
        }

        func webView(
            _ webView: WKWebView,
            decidePolicyFor navigationAction: WKNavigationAction,
            decisionHandler: @escaping (WKNavigationActionPolicy) -> Void
        ) {
            guard let url = navigationAction.request.url else {
                decisionHandler(.cancel)
                return
            }

            if url.absoluteString == "about:blank" {
                decisionHandler(.allow)
                return
            }

            if LoopbackURLPolicy.isSameOrigin(url, as: endpoint) {
                decisionHandler(navigationAction.shouldPerformDownload ? .download : .allow)
                return
            }

            if navigationAction.navigationType == .linkActivated,
               LoopbackURLPolicy.isExternalWebURL(url) {
                UIApplication.shared.open(url, options: [:])
            }
            decisionHandler(.cancel)
        }

        func webView(
            _ webView: WKWebView,
            decidePolicyFor navigationResponse: WKNavigationResponse,
            decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void
        ) {
            guard let url = navigationResponse.response.url else {
                decisionHandler(.cancel)
                return
            }

            if url.absoluteString == "about:blank" {
                decisionHandler(.allow)
                return
            }

            guard LoopbackURLPolicy.isSameOrigin(url, as: endpoint) else {
                decisionHandler(.cancel)
                return
            }

            decisionHandler(isAttachment(navigationResponse.response) ? .download : .allow)
        }

        func webView(
            _ webView: WKWebView,
            navigationAction: WKNavigationAction,
            didBecome download: WKDownload
        ) {
            register(download)
        }

        func webView(
            _ webView: WKWebView,
            navigationResponse: WKNavigationResponse,
            didBecome download: WKDownload
        ) {
            register(download)
        }

        func download(
            _ download: WKDownload,
            decideDestinationUsing response: URLResponse,
            suggestedFilename: String,
            completionHandler: @escaping (URL?) -> Void
        ) {
            let identifier = ObjectIdentifier(download)
            guard activeDownloads[identifier] != nil else {
                completionHandler(nil)
                return
            }

            do {
                let destination = try nativeBridge.prepareDownloadDestination(
                    response: response,
                    suggestedFilename: suggestedFilename
                )
                downloadDestinations[identifier] = destination
                completionHandler(destination)
            } catch {
                activeDownloads.removeValue(forKey: identifier)
                downloadDestinations.removeValue(forKey: identifier)
                completionHandler(nil)
                nativeBridge.presentDownloadFailure(error.localizedDescription)
            }
        }

        func download(
            _ download: WKDownload,
            willPerformHTTPRedirection response: HTTPURLResponse,
            newRequest request: URLRequest,
            decisionHandler: @escaping (WKDownload.RedirectPolicy) -> Void
        ) {
            let identifier = ObjectIdentifier(download)
            guard activeDownloads[identifier] != nil,
                  let url = request.url,
                  LoopbackURLPolicy.isSameOrigin(url, as: endpoint) else {
                discardDownload(identifier)
                decisionHandler(.cancel)
                return
            }
            decisionHandler(.allow)
        }

        func downloadDidFinish(_ download: WKDownload) {
            let identifier = ObjectIdentifier(download)
            guard activeDownloads.removeValue(forKey: identifier) != nil,
                  let destination = downloadDestinations.removeValue(forKey: identifier) else {
                return
            }

            do {
                try nativeBridge.presentDownloadedFile(destination)
            } catch {
                nativeBridge.discardTemporaryExport(destination)
                nativeBridge.presentDownloadFailure(error.localizedDescription)
            }
        }

        func download(
            _ download: WKDownload,
            didFailWithError error: Error,
            resumeData: Data?
        ) {
            let identifier = ObjectIdentifier(download)
            guard activeDownloads.removeValue(forKey: identifier) != nil else { return }
            if let destination = downloadDestinations.removeValue(forKey: identifier) {
                nativeBridge.discardTemporaryExport(destination)
            }
            nativeBridge.presentDownloadFailure("Dosya indirilemedi. Lütfen yeniden deneyin.")
        }

        func webView(
            _ webView: WKWebView,
            createWebViewWith configuration: WKWebViewConfiguration,
            for navigationAction: WKNavigationAction,
            windowFeatures: WKWindowFeatures
        ) -> WKWebView? {
            guard let url = navigationAction.request.url else { return nil }
            if LoopbackURLPolicy.isSameOrigin(url, as: endpoint) {
                webView.load(navigationAction.request)
            } else if LoopbackURLPolicy.isExternalWebURL(url) {
                UIApplication.shared.open(url, options: [:])
            }
            return nil
        }

        func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
            webView.reload()
        }

        func webView(
            _ webView: WKWebView,
            didFail navigation: WKNavigation!,
            withError error: Error
        ) {
            sendNativeEvent(
                "runtime.error",
                detail: ["message": error.localizedDescription],
                in: webView
            )
        }

        func webView(
            _ webView: WKWebView,
            didFailProvisionalNavigation navigation: WKNavigation!,
            withError error: Error
        ) {
            sendNativeEvent(
                "runtime.error",
                detail: ["message": error.localizedDescription],
                in: webView
            )
        }

        func reportSafeArea(_ insets: UIEdgeInsets) {
            guard let webView else { return }
            sendNativeEvent(
                "safearea.change",
                detail: [
                    "top": insets.top,
                    "right": insets.right,
                    "bottom": insets.bottom,
                    "left": insets.left
                ],
                in: webView
            )
        }

        private func observeKeyboard() {
            guard keyboardObservers.isEmpty else { return }
            let center = NotificationCenter.default
            keyboardObservers = [
                center.addObserver(
                    forName: UIResponder.keyboardWillChangeFrameNotification,
                    object: nil,
                    queue: .main
                ) { [weak self] notification in
                    Task { @MainActor in
                        self?.reportKeyboard(notification)
                    }
                },
                center.addObserver(
                    forName: UIResponder.keyboardWillHideNotification,
                    object: nil,
                    queue: .main
                ) { [weak self] notification in
                    Task { @MainActor in
                        self?.reportKeyboard(notification, forcedHidden: true)
                    }
                }
            ]
        }

        private func register(_ download: WKDownload) {
            let identifier = ObjectIdentifier(download)
            activeDownloads[identifier] = download
            download.delegate = self
        }

        private func discardDownload(_ identifier: ObjectIdentifier) {
            guard activeDownloads.removeValue(forKey: identifier) != nil else { return }
            if let destination = downloadDestinations.removeValue(forKey: identifier) {
                nativeBridge.discardTemporaryExport(destination)
            }
        }

        private func isAttachment(_ response: URLResponse) -> Bool {
            guard let response = response as? HTTPURLResponse,
                  (200 ..< 300).contains(response.statusCode),
                  let disposition = response.value(
                    forHTTPHeaderField: "Content-Disposition"
                  )?.trimmingCharacters(in: .whitespacesAndNewlines)
                    .lowercased() else {
                return false
            }
            return disposition == "attachment" || disposition.hasPrefix("attachment;")
        }

        private func reportKeyboard(_ notification: Notification, forcedHidden: Bool = false) {
            guard let webView, let window = webView.window else { return }
            let userInfo = notification.userInfo ?? [:]
            let endFrame = (userInfo[UIResponder.keyboardFrameEndUserInfoKey] as? NSValue)?.cgRectValue ?? .zero
            let frameInWindow = window.convert(endFrame, from: nil)
            let overlap = forcedHidden ? 0 : max(0, window.bounds.maxY - frameInWindow.minY)
            let duration = userInfo[UIResponder.keyboardAnimationDurationUserInfoKey] as? Double ?? 0.25
            let curve = userInfo[UIResponder.keyboardAnimationCurveUserInfoKey] as? Int ?? 0

            sendNativeEvent(
                "keyboard.change",
                detail: [
                    "visible": overlap > 0,
                    "height": overlap,
                    "duration": duration,
                    "curve": curve
                ],
                in: webView
            )
        }

        private func sendNativeEvent(_ name: String, detail: [String: Any], in webView: WKWebView) {
            webView.callAsyncJavaScript(
                "window.dispatchEvent(new CustomEvent(eventName, { detail: eventDetail }));",
                arguments: ["eventName": name, "eventDetail": detail],
                in: nil,
                in: .page,
                completionHandler: nil
            )
        }
    }
}

private final class SafeAreaReportingWebView: WKWebView {
    var safeAreaDidChange: ((UIEdgeInsets) -> Void)?

    override func safeAreaInsetsDidChange() {
        super.safeAreaInsetsDidChange()
        safeAreaDidChange?(safeAreaInsets)
    }
}

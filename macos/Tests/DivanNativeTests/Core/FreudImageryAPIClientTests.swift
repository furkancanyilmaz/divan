import CryptoKit
import Foundation
import XCTest
@testable import DivanNative

private final class FreudImageryStubURLProtocol: URLProtocol {
    private static let lock = NSLock()
    private static var handler: ((URLRequest) throws -> (Int, [String: String], Data))?

    static func install(
        _ handler: @escaping (URLRequest) throws -> (Int, [String: String], Data)
    ) {
        lock.lock()
        self.handler = handler
        lock.unlock()
    }

    static func clear() {
        lock.lock()
        handler = nil
        lock.unlock()
    }

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        Self.lock.lock()
        let handler = Self.handler
        Self.lock.unlock()
        guard let handler else {
            client?.urlProtocol(self, didFailWithError: URLError(.badServerResponse))
            return
        }
        do {
            let (status, headers, data) = try handler(request)
            let url = try XCTUnwrap(request.url)
            let response = try XCTUnwrap(HTTPURLResponse(
                url: url,
                statusCode: status,
                httpVersion: "HTTP/1.1",
                headerFields: headers
            ))
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: data)
            client?.urlProtocolDidFinishLoading(self)
        } catch {
            client?.urlProtocol(self, didFailWithError: error)
        }
    }

    override func stopLoading() {}
}

private final class FreudImageryLockedBox<Value>: @unchecked Sendable {
    private let lock = NSLock()
    private var value: Value

    init(_ value: Value) { self.value = value }

    func withValue(_ action: (inout Value) -> Void) {
        lock.lock()
        defer { lock.unlock() }
        action(&value)
    }

    func get() -> Value {
        lock.lock()
        defer { lock.unlock() }
        return value
    }
}

final class FreudImageryAPIClientTests: XCTestCase {
    override func tearDown() {
        FreudImageryStubURLProtocol.clear()
        super.tearDown()
    }

    func testDeckGETDecodesExactLiteralContractAndCanonicalConversationQuery() async throws {
        FreudImageryStubURLProtocol.install { request in
            let url = try XCTUnwrap(request.url)
            if url.path == "/" { return (200, [:], Data("ok".utf8)) }
            XCTAssertEqual(url.path, "/api/freud-imagery")
            XCTAssertEqual(request.httpMethod, "GET")
            XCTAssertEqual(
                URLComponents(url: url, resolvingAgainstBaseURL: false)?
                    .queryItems?.first(where: { $0.name == "conv_id" })?.value,
                "42"
            )
            return (200, ["Content-Type": "application/json"], try Self.workspaceData())
        }

        let workspace = try await makeClient().freudImagery(conversationID: 42)

        XCTAssertTrue(workspace.available)
        XCTAssertEqual(workspace.cards.count, 24)
        XCTAssertEqual(workspace.cards.first?.title, "Görünen kart 1")
        XCTAssertEqual(workspace.cards.first?.description, "Yalnız görünen sahne 1.")
        XCTAssertEqual(workspace.session?.techniqueRunID, 77)
        XCTAssertEqual(workspace.session?.revision, 1)
        XCTAssertNil(workspace.selection)
        XCTAssertEqual(workspace.suggestions, [])
        XCTAssertTrue(workspace.capabilities.select)
    }

    func testConsentPostsOnlyExplicitFrameFields() async throws {
        let posted = FreudImageryLockedBox<[String: Any]>([:])
        FreudImageryStubURLProtocol.install { request in
            let path = try XCTUnwrap(request.url?.path)
            if path == "/" { return (200, [:], Data("ok".utf8)) }
            XCTAssertEqual(path, "/api/freud-imagery/selection")
            posted.withValue { $0 = (try? Self.body(request)) ?? [:] }
            return (200, ["Content-Type": "application/json"], try Self.mutationData())
        }

        _ = try await makeClient().mutateFreudImagerySelection(.consent(
            conversationID: 42,
            requestID: "freud-consent-0001",
            orientationConfirmed: true,
            frameConfirmed: true,
            realityConfirmed: true,
            stopSignal: "  Şimdi   dur  "
        ))

        let body = posted.get()
        XCTAssertEqual(Set(body.keys), Set([
            "action", "conv_id", "request_id", "orientation_confirmed",
            "frame_confirmed", "reality_confirmed", "stop_signal",
        ]))
        XCTAssertEqual(body["action"] as? String, "consent")
        XCTAssertEqual(body["conv_id"] as? Int, 42)
        XCTAssertEqual(body["request_id"] as? String, "freud-consent-0001")
        XCTAssertEqual(body["orientation_confirmed"] as? Bool, true)
        XCTAssertEqual(body["frame_confirmed"] as? Bool, true)
        XCTAssertEqual(body["reality_confirmed"] as? Bool, true)
        XCTAssertEqual(body["stop_signal"] as? String, "Şimdi dur")
    }

    func testSuggestionPostsExplicitModelConsentAndCannotReturnSelectedTrue() async throws {
        let posted = FreudImageryLockedBox<[String: Any]>([:])
        FreudImageryStubURLProtocol.install { request in
            let path = try XCTUnwrap(request.url?.path)
            if path == "/" { return (200, [:], Data("ok".utf8)) }
            posted.withValue { $0 = (try? Self.body(request)) ?? [:] }
            return (
                200,
                ["Content-Type": "application/json"],
                try Self.mutationData(selected: false, suggestionCount: 3)
            )
        }
        let response = try await makeClient().suggestFreudImagery(.init(
            conversationID: 42,
            requestID: "freud-suggest-0001",
            revision: 1,
            modelConsent: true
        ))

        XCTAssertEqual(Set(posted.get().keys), Set([
            "conv_id", "request_id", "revision", "model_consent",
        ]))
        XCTAssertEqual(posted.get()["model_consent"] as? Bool, true)
        XCTAssertNil(response.imagery.selection)
        XCTAssertEqual(response.imagery.suggestions.count, 3)
        XCTAssertEqual(response.selected, false)
    }

    func testMoreThanThreeSuggestionsFailsClosed() async throws {
        FreudImageryStubURLProtocol.install { request in
            if request.url?.path == "/" { return (200, [:], Data("ok".utf8)) }
            return (
                200,
                ["Content-Type": "application/json"],
                try Self.mutationData(selected: false, suggestionCount: 4)
            )
        }
        do {
            _ = try await makeClient().suggestFreudImagery(.init(
                conversationID: 42,
                requestID: "freud-suggest-0002",
                revision: 1,
                modelConsent: true
            ))
            XCTFail("Üçten fazla model önerisi kabul edilmemeliydi")
        } catch let error as DivanAPIError {
            XCTAssertEqual(error.errorCode, "invalid_freud_imagery")
        }
    }

    func testOffOriginCardURLIsRejectedBeforeAnyNetworkRequest() async throws {
        let requests = FreudImageryLockedBox(0)
        FreudImageryStubURLProtocol.install { _ in
            requests.withValue { $0 += 1 }
            return (500, [:], Data())
        }
        let card = Self.card(index: 1, url: "https://example.com/assets/imagery/card-01.webp?v=1")
        do {
            _ = try await makeClient().freudImageryCardData(card: card)
            XCTFail("Uzak kökenli kart URL'si kabul edilmemeliydi")
        } catch let error as DivanAPIError {
            XCTAssertEqual(error.errorCode, "invalid_imagery_url")
        }
        XCTAssertEqual(requests.get(), 0)
    }

    func testSameOriginCardLoaderChecksPathMIMEBytesAndDigest() async throws {
        let webp = Self.minimalWebP()
        let digest = SHA256.hash(data: webp)
            .map { String(format: "%02x", $0) }
            .joined()
        let card = FreudImageryCard(
            id: "card-01",
            file: "card-01.webp",
            category: "mekan",
            title: "Görünen kart",
            description: "Yalnız görünen sahne.",
            alt: "Yalnız görünen kart sahnesi.",
            sha256: digest,
            bytes: webp.count,
            url: "/assets/imagery/card-01.webp?v=2026.08.17.5"
        )
        let paths = FreudImageryLockedBox<[String]>([])
        FreudImageryStubURLProtocol.install { request in
            let url = try XCTUnwrap(request.url)
            paths.withValue { $0.append(url.path) }
            if url.path == "/" { return (200, [:], Data("ok".utf8)) }
            XCTAssertEqual(url.host, "127.0.0.1")
            XCTAssertEqual(url.port, 54321)
            XCTAssertEqual(url.query, "v=2026.08.17.5")
            XCTAssertEqual(request.value(forHTTPHeaderField: "Accept"), "image/webp")
            return (
                200,
                ["Content-Type": "image/webp", "Content-Length": String(webp.count)],
                webp
            )
        }

        let data = try await makeClient().freudImageryCardData(card: card)

        XCTAssertEqual(data, webp)
        XCTAssertEqual(paths.get(), ["/", "/assets/imagery/card-01.webp"])
    }

    private func makeClient() throws -> APIClient {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [FreudImageryStubURLProtocol.self]
        return try APIClient(
            baseURL: XCTUnwrap(URL(string: "http://127.0.0.1:54321/")),
            sessionToken: String(repeating: "f", count: 64),
            session: URLSession(configuration: configuration)
        )
    }

    private static func card(index: Int, url: String? = nil) -> FreudImageryCard {
        let id = String(format: "card-%02d", index)
        return FreudImageryCard(
            id: id,
            file: id + ".webp",
            category: "mekan",
            title: "Görünen kart \(index)",
            description: "Yalnız görünen sahne \(index).",
            alt: "Yalnız görünen kart sahnesi \(index).",
            sha256: String(repeating: "0", count: 64),
            bytes: 1_024 + index,
            url: url ?? "/assets/imagery/\(id).webp?v=2026.08.17.5"
        )
    }

    private static func cardObject(_ card: FreudImageryCard) -> [String: Any] {
        [
            "id": card.id,
            "file": card.file,
            "category": card.category,
            "title": card.title,
            "description": card.description,
            "alt": card.alt,
            "mime": card.mime,
            "sha256": card.sha256,
            "width": card.width,
            "height": card.height,
            "bytes": card.bytes,
            "url": card.url,
        ]
    }

    private static func workspaceObject(suggestionCount: Int = 0) -> [String: Any] {
        let cards = (1...24).map { card(index: $0) }
        return [
            "available": true,
            "blocked_reason": "",
            "method": [
                "id": "visual-free-association",
                "title": "Görsel Serbest Çağrışım",
                "description": "Kartlar yalnız görünen sahneyi sunar.",
            ],
            "cards": cards.map(cardObject),
            "session": [
                "id": 9,
                "technique_run_id": 77,
                "status": "active",
                "revision": 1,
                "orientation_confirmed": true,
                "frame_confirmed": true,
                "reality_confirmed": true,
                "stop_signal": "DUR",
                "consent_at": "2026-08-17 19:00",
            ],
            "selection": NSNull(),
            "suggestions": cards.prefix(suggestionCount).map(cardObject),
            "suggestion_question": suggestionCount > 0
                ? "Bu kartlardan biri sende ne çağrıştırıyor?" : "",
            "capabilities": [
                "consent": false, "suggest": true, "select": true,
                "clear": false, "undo": false, "stop": true,
            ],
            "safety_hold": false,
            "precheck_complete": true,
        ]
    }

    private static func workspaceData(suggestionCount: Int = 0) throws -> Data {
        try JSONSerialization.data(withJSONObject: [
            "imagery": workspaceObject(suggestionCount: suggestionCount),
        ])
    }

    private static func mutationData(
        selected: Bool? = nil,
        suggestionCount: Int = 0
    ) throws -> Data {
        var object: [String: Any] = [
            "ok": true,
            "duplicate": false,
            "imagery": workspaceObject(suggestionCount: suggestionCount),
        ]
        if let selected { object["selected"] = selected }
        return try JSONSerialization.data(withJSONObject: object)
    }

    private static func body(_ request: URLRequest) throws -> [String: Any] {
        let data: Data
        if let body = request.httpBody {
            data = body
        } else if let stream = request.httpBodyStream {
            stream.open()
            defer { stream.close() }
            var collected = Data()
            var buffer = [UInt8](repeating: 0, count: 4_096)
            while true {
                let count = stream.read(&buffer, maxLength: buffer.count)
                if count > 0 { collected.append(buffer, count: count) }
                else if count == 0 { break }
                else { throw stream.streamError ?? URLError(.cannotDecodeRawData) }
            }
            data = collected
        } else {
            throw URLError(.cannotDecodeRawData)
        }
        return try XCTUnwrap(
            JSONSerialization.jsonObject(with: data) as? [String: Any]
        )
    }

    private static func minimalWebP() -> Data {
        var bytes = Array("RIFF".utf8)
        bytes += [12, 0, 0, 0]
        bytes += Array("WEBP".utf8)
        bytes += Array("VP8 ".utf8)
        bytes += [0, 0, 0, 0]
        return Data(bytes)
    }
}

import Foundation
import XCTest
@testable import DivanNative

private final class StubURLProtocol: URLProtocol {
    private static let lock = NSLock()
    private static var requestHandler: ((URLRequest) throws -> (Int, [String: String], Data))?

    static func install(
        _ handler: @escaping (URLRequest) throws -> (Int, [String: String], Data)
    ) {
        lock.lock()
        requestHandler = handler
        lock.unlock()
    }

    static func clear() {
        lock.lock()
        requestHandler = nil
        lock.unlock()
    }

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        Self.lock.lock()
        let handler = Self.requestHandler
        Self.lock.unlock()
        guard let handler else {
            client?.urlProtocol(self, didFailWithError: URLError(.badServerResponse))
            return
        }
        do {
            let (status, headers, data) = try handler(request)
            guard let url = request.url,
                  let response = HTTPURLResponse(
                      url: url,
                      statusCode: status,
                      httpVersion: "HTTP/1.1",
                      headerFields: headers
                  ) else {
                throw URLError(.badServerResponse)
            }
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: data)
            client?.urlProtocolDidFinishLoading(self)
        } catch {
            client?.urlProtocol(self, didFailWithError: error)
        }
    }

    override func stopLoading() {}
}

private final class LockedBox<Value>: @unchecked Sendable {
    private let lock = NSLock()
    private var value: Value

    init(_ value: Value) {
        self.value = value
    }

    func set(_ value: Value) {
        lock.lock()
        defer { lock.unlock() }
        self.value = value
    }

    func get() -> Value {
        lock.lock()
        defer { lock.unlock() }
        return value
    }

    @discardableResult
    func mutate<Result>(_ body: (inout Value) -> Result) -> Result {
        lock.lock()
        defer { lock.unlock() }
        return body(&value)
    }
}

private func bodyData(from request: URLRequest) throws -> Data {
    if let body = request.httpBody { return body }
    guard let stream = request.httpBodyStream else {
        throw URLError(.cannotDecodeRawData)
    }
    stream.open()
    defer { stream.close() }
    var data = Data()
    var buffer = [UInt8](repeating: 0, count: 4_096)
    while true {
        let count = stream.read(&buffer, maxLength: buffer.count)
        if count > 0 {
            data.append(buffer, count: count)
        } else if count == 0 {
            return data
        } else {
            throw stream.streamError ?? URLError(.cannotDecodeRawData)
        }
    }
}

final class APIClientTests: XCTestCase {
    override func tearDown() {
        StubURLProtocol.clear()
        super.tearDown()
    }

    func testRejectsNonLoopbackEndpoint() {
        let session = makeSession()
        XCTAssertThrowsError(
            try APIClient(
                baseURL: XCTUnwrap(URL(string: "https://example.com/")),
                sessionToken: String(repeating: "a", count: 64),
                session: session
            )
        )
    }

    func testBootstrapMapsNativeContractAndLocalPortrait() async throws {
        StubURLProtocol.install { request in
            let path = try XCTUnwrap(request.url?.path)
            if path == "/" {
                return (200, ["Content-Type": "text/html"], Data("ok".utf8))
            }
            if path == "/api/settings" {
                return (200, ["Content-Type": "application/json"], Data(#"""
                {
                  "provider":"openai","providers":{"openai":{"label":"OpenAI","model":"gpt-test","key_set":true,"local":false}},
                  "context_window_tokens":131072,"context_window_options":[65536,131072],"privacy_seen":true,
                  "pin_set":false,"retention_days":0,"simple_mode":false,"credential_storage":"macos_keychain","version":"test"
                }
                """#.utf8))
            }
            XCTAssertEqual(path, "/api/v1/bootstrap")
            return (200, ["Content-Type": "application/json"], Data(#"""
            {
              "api_contract_version":1,"app_version":"test","capabilities":{"background_chat":true},
              "provider":{"id":"openai","label":"OpenAI","model":"gpt-test","key_set":true,"local":false},
              "therapists":[{"id":"freud","name":"Sigmund Freud","school":"Psikanaliz","sub":"Wien · 1856–1939","kind":"therapist","modes":["terapi","ders"],"portrait":{"url":"/assets/portraits/freud.jpg"}}],
              "philosophers":[{"id":"socrates","name":"Sokrates","school":"Sokratik sorgulama","sub":"Atina · MÖ 470–399","kind":"philosopher","modes":["ders"]}],
              "settings":{"context_window_tokens":131072,"privacy_seen":true,"pin_set":false,"retention_days":0,"simple_mode":false,"credential_storage":"macos_keychain"}
            }
            """#.utf8))
        }
        let client = try makeClient()
        let payload = try await client.bootstrap()
        XCTAssertEqual(payload.apiContractVersion, 1)
        XCTAssertEqual(payload.therapists.first?.school, "Psikanaliz")
        XCTAssertEqual(payload.therapists.first?.isLiving, false)
        XCTAssertEqual(payload.philosophers.first?.kind, .philosopher)
        XCTAssertEqual(payload.therapists.first?.portraitURL?.host, "127.0.0.1")
        XCTAssertEqual(payload.settings.selectedProviderID, "openai")
        XCTAssertTrue(payload.settings.providers.first?.keySet == true)
    }

    func testConversationPagingMapsSnakeCaseAndPreservesOrder() async throws {
        StubURLProtocol.install { request in
            let path = try XCTUnwrap(request.url?.path)
            if path == "/" {
                return (200, ["Content-Type": "text/html"], Data("ok".utf8))
            }
            XCTAssertEqual(path, "/api/conversation")
            let query = URLComponents(url: try XCTUnwrap(request.url), resolvingAgainstBaseURL: false)
            XCTAssertEqual(query?.queryItems?.first(where: { $0.name == "limit" })?.value, "80")
            XCTAssertEqual(query?.queryItems?.first(where: { $0.name == "before_id" })?.value, "42")
            return (200, ["Content-Type": "application/json"], Data(#"""
            {
              "conversation":{"id":7,"therapist":"jung","title":"Bir konuşma","mode":"terapi","submode":null,"created":"2026-01-01","updated":"2026-01-02","ended":0,"archived_at":null},
              "messages":[{"id":40,"role":"user","content":"İlk","created":"10:00","reply_to":null,"delivery_status":"completed"},{"id":41,"role":"assistant","content":"İkinci","created":"10:01","reply_to":40,"delivery_status":"completed"}],
              "message_count":100,"loaded_message_count":2,"has_more_messages":true,"oldest_message_id":40,"chat_request":null
            }
            """#.utf8))
        }
        let client = try makeClient()
        let page = try await client.conversation(id: 7, limit: 80, beforeID: 42)
        XCTAssertEqual(page.masterID, "jung")
        XCTAssertEqual(page.messages.map(\.id), [40, 41])
        XCTAssertEqual(page.messageCount, 100)
        XCTAssertTrue(page.hasMoreMessages)
        XCTAssertEqual(page.oldestMessageID, 40)
    }

    func testPortraitDataUsesAuthenticatedSessionAndAcceptsVersionQuery() async throws {
        let portrait = Data([0xff, 0xd8, 0xff, 0xd9])
        StubURLProtocol.install { request in
            let url = try XCTUnwrap(request.url)
            if url.path == "/" {
                return (200, ["Content-Type": "text/html"], Data("ok".utf8))
            }
            XCTAssertEqual(url.path, "/assets/portraits/freud.jpg")
            XCTAssertEqual(url.query, "v=2026.08.10.2")
            XCTAssertEqual(request.value(forHTTPHeaderField: "Accept"),
                           "image/webp,image/png,image/jpeg")
            return (200, [
                "Content-Type": "image/jpeg",
                "Content-Length": String(portrait.count),
            ], portrait)
        }
        let client = try makeClient()
        let url = try XCTUnwrap(URL(
            string: "http://127.0.0.1:54321/assets/portraits/freud.jpg?v=2026.08.10.2"
        ))
        let loaded = try await client.portraitData(url: url)
        XCTAssertEqual(loaded, portrait)
    }

    func testPortraitDataRejectsUnsafeURLBeforeTransport() async throws {
        let client = try makeClient()
        for raw in [
            "https://example.com/assets/portraits/freud.jpg?v=1",
            "http://127.0.0.1:54321/api/settings",
            "http://127.0.0.1:54321/assets/portraits/freud.jpg?v=1&token=x",
            "http://127.0.0.1:54321/assets/portraits/nested/freud.jpg?v=1",
        ] {
            do {
                _ = try await client.portraitData(url: XCTUnwrap(URL(string: raw)))
                XCTFail("Güvensiz portre adresi kabul edilmemeliydi: \(raw)")
            } catch let error as DivanAPIError {
                XCTAssertEqual(error.errorCode, "invalid_portrait_url")
            }
        }
    }

    func testPortraitDataRejectsWrongMIMEAndOversizedResponse() async throws {
        let mode = LockedBox("mime")
        StubURLProtocol.install { request in
            let path = try XCTUnwrap(request.url?.path)
            if path == "/" {
                return (200, ["Content-Type": "text/html"], Data("ok".utf8))
            }
            if mode.get() == "mime" {
                return (200, ["Content-Type": "text/plain"], Data("not image".utf8))
            }
            return (200, [
                "Content-Type": "image/jpeg",
                "Content-Length": String(10 * 1024 * 1024 + 1),
            ], Data([0xff]))
        }
        let client = try makeClient()
        let url = try XCTUnwrap(URL(
            string: "http://127.0.0.1:54321/assets/portraits/freud.jpg?v=1"
        ))
        do {
            _ = try await client.portraitData(url: url)
            XCTFail("Yanlış MIME kabul edilmemeliydi.")
        } catch let error as DivanAPIError {
            XCTAssertEqual(error.errorCode, "invalid_portrait_type")
        }
        mode.set("size")
        do {
            _ = try await client.portraitData(url: url)
            XCTFail("Büyük portre kabul edilmemeliydi.")
        } catch let error as DivanAPIError {
            XCTAssertEqual(error.errorCode, "portrait_too_large")
        }
    }

    func testActiveDuplicateChatPollsDurableStatusUntilTerminalCompletion() async throws {
        let statusCalls = LockedBox(0)
        StubURLProtocol.install { request in
            let url = try XCTUnwrap(request.url)
            switch url.path {
            case "/":
                return (200, ["Content-Type": "text/html"], Data("ok".utf8))
            case "/api/chat":
                return (202, ["Content-Type": "application/json"], Data(#"""
                {
                  "ok":true,"duplicate":true,"request_id":"server-request-1",
                  "status":"running","message":"Kısmi yanıt",
                  "user_message_id":31,"assistant_message_id":32
                }
                """#.utf8))
            case "/api/chat-status":
                let components = URLComponents(url: url, resolvingAgainstBaseURL: false)
                XCTAssertEqual(
                    components?.queryItems?.first(where: { $0.name == "request_id" })?.value,
                    "server-request-1"
                )
                let call = statusCalls.mutate { value in
                    value += 1
                    return value
                }
                if call == 1 {
                    return (200, ["Content-Type": "application/json"], Data(#"""
                    {"chat":{"request_id":"server-request-1","conv_id":7,
                    "status":"waiting_provider","content":"Kısmi yanıt",
                    "pending":true,"waiting_for_provider":true,"retryable":true}}
                    """#.utf8))
                }
                return (200, ["Content-Type": "application/json"], Data(#"""
                {"chat":{"request_id":"server-request-1","conv_id":7,
                "status":"completed","content":"Tam ve kalıcı yanıt",
                "pending":false,"waiting_for_provider":false,"retryable":false,
                "assistant_message_id":32}}
                """#.utf8))
            default:
                XCTFail("Beklenmeyen istek: \(url.path)")
                return (404, ["Content-Type": "application/json"], Data(#"{"error":"not found"}"#.utf8))
            }
        }

        let client = try makeClient()
        let stream = try await client.sendMessage(conversationID: 7, text: "Merhaba")
        var events: [ChatEvent] = []
        for try await event in stream { events.append(event) }

        XCTAssertGreaterThanOrEqual(statusCalls.get(), 2)
        XCTAssertFalse(events.contains {
            $0.kind == .done && ["queued", "running", "waiting_provider"].contains($0.status ?? "")
        })
        XCTAssertTrue(events.contains {
            $0.kind == .replace && $0.text == "Tam ve kalıcı yanıt"
        })
        XCTAssertEqual(events.last?.kind, .done)
        XCTAssertEqual(events.last?.status, "completed")
    }

    func testDurableChatRecoveryRetriesTransientStatusFailure() async throws {
        let statusCalls = LockedBox(0)
        StubURLProtocol.install { request in
            let url = try XCTUnwrap(request.url)
            switch url.path {
            case "/":
                return (200, ["Content-Type": "text/html"], Data("ok".utf8))
            case "/api/chat":
                return (202, ["Content-Type": "application/json"], Data(#"""
                {"ok":true,"duplicate":true,"request_id":"server-request-2",
                "status":"queued","message":""}
                """#.utf8))
            case "/api/chat-status":
                let call = statusCalls.mutate { value in
                    value += 1
                    return value
                }
                if call == 1 {
                    return (503, ["Content-Type": "application/json"], Data(#"""
                    {"error":"Durum geçici olarak okunamadı","retryable":true}
                    """#.utf8))
                }
                return (200, ["Content-Type": "application/json"], Data(#"""
                {"chat":{"request_id":"server-request-2","conv_id":7,
                "status":"completed","content":"Gecikse de geldi","pending":false,
                "waiting_for_provider":false,"retryable":false}}
                """#.utf8))
            default:
                return (404, ["Content-Type": "application/json"], Data(#"{"error":"not found"}"#.utf8))
            }
        }

        let client = try makeClient()
        let stream = try await client.sendMessage(conversationID: 7, text: "Bekle")
        var events: [ChatEvent] = []
        for try await event in stream { events.append(event) }

        XCTAssertGreaterThanOrEqual(statusCalls.get(), 2)
        XCTAssertTrue(events.contains { $0.kind == .replace && $0.text == "Gecikse de geldi" })
        XCTAssertEqual(events.last?.kind, .done)
        XCTAssertEqual(events.last?.status, "completed")
    }

    func testTerminalDuplicateFailureEmitsErrorInsteadOfDone() async throws {
        StubURLProtocol.install { request in
            let url = try XCTUnwrap(request.url)
            if url.path == "/" {
                return (200, ["Content-Type": "text/html"], Data("ok".utf8))
            }
            XCTAssertEqual(url.path, "/api/chat")
            return (200, ["Content-Type": "application/json"], Data(#"""
            {"ok":true,"duplicate":true,"request_id":"server-request-3",
            "status":"failed","message":"Sağlayıcı yanıt vermedi"}
            """#.utf8))
        }

        let client = try makeClient()
        let stream = try await client.sendMessage(conversationID: 7, text: "Merhaba")
        var events: [ChatEvent] = []
        for try await event in stream { events.append(event) }

        XCTAssertFalse(events.contains { $0.kind == .done })
        XCTAssertEqual(events.last?.kind, .error)
        XCTAssertEqual(events.last?.status, "failed")
    }

    func testNonterminalSSEDoneFallsBackToDurableStatusRecovery() async throws {
        let statusCalls = LockedBox(0)
        StubURLProtocol.install { request in
            let url = try XCTUnwrap(request.url)
            switch url.path {
            case "/":
                return (200, ["Content-Type": "text/html"], Data("ok".utf8))
            case "/api/chat":
                let body = #"""
                data: {"type":"accepted","request_id":"server-request-4","status":"running"}

                data: {"type":"done","request_id":"server-request-4","status":"running"}

                """#
                return (200, ["Content-Type": "text/event-stream"], Data(body.utf8))
            case "/api/chat-status":
                statusCalls.mutate { $0 += 1 }
                return (200, ["Content-Type": "application/json"], Data(#"""
                {"chat":{"request_id":"server-request-4","conv_id":7,
                "status":"completed","content":"Durable tamamlandı","pending":false,
                "waiting_for_provider":false,"retryable":false}}
                """#.utf8))
            default:
                return (404, ["Content-Type": "application/json"], Data(#"{"error":"not found"}"#.utf8))
            }
        }

        let client = try makeClient()
        let stream = try await client.sendMessage(conversationID: 7, text: "Merhaba")
        var events: [ChatEvent] = []
        for try await event in stream { events.append(event) }

        XCTAssertGreaterThanOrEqual(statusCalls.get(), 1)
        XCTAssertTrue(events.contains { $0.kind == .replace && $0.text == "Durable tamamlandı" })
        XCTAssertEqual(events.last?.kind, .done)
        XCTAssertEqual(events.last?.status, "completed")
    }

    func testSaveSettingsWritesSecretOnceWithoutReturningIt() async throws {
        let postedBody = LockedBox<[String: Any]>([:])
        StubURLProtocol.install { request in
            let path = try XCTUnwrap(request.url?.path)
            if path == "/" {
                return (200, ["Content-Type": "text/html"], Data("ok".utf8))
            }
            if request.httpMethod == "POST" {
                let data = try bodyData(from: request)
                let object = try XCTUnwrap(
                    JSONSerialization.jsonObject(with: data) as? [String: Any]
                )
                postedBody.set(object)
                return (200, ["Content-Type": "application/json"], Data(#"{"ok":true}"#.utf8))
            }
            return (200, ["Content-Type": "application/json"], Data(#"""
            {
              "provider":"openai","providers":{"openai":{"label":"OpenAI","model":"gpt-test","key_set":true,"local":false}},
              "context_window_tokens":65536,"context_window_options":[65536],"privacy_seen":false,
              "pin_set":false,"retention_days":0,"simple_mode":false,"credential_storage":"macos_keychain","version":"test"
            }
            """#.utf8))
        }
        let client = try makeClient()
        let settings = try await client.saveSettings(ProviderSettingsUpdate(
            providerID: "openai",
            modelID: "gpt-test",
            apiKey: "one-time-secret"
        ))
        let body = postedBody.get()
        XCTAssertEqual(body["provider"] as? String, "openai")
        XCTAssertEqual(body["openai_model"] as? String, "gpt-test")
        XCTAssertEqual(body["openai_api_key"] as? String, "one-time-secret")
        XCTAssertEqual(settings.selectedProviderID, "openai")
        XCTAssertFalse(String(describing: settings).contains("one-time-secret"))
    }

    private func makeSession() -> URLSession {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [StubURLProtocol.self]
        return URLSession(configuration: configuration)
    }

    private func makeClient() throws -> APIClient {
        try APIClient(
            baseURL: XCTUnwrap(URL(string: "http://127.0.0.1:54321/")),
            sessionToken: String(repeating: "a", count: 64),
            session: makeSession()
        )
    }
}

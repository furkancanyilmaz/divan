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
              "messages":[
                {"id":40,"public_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","role":"user","content":"İlk","created":"10:00","reply_to":null,"delivery_status":"completed",
                 "schema_binding_result":{"applied":false,"error_code":"stale_schema_revision","action":"record_present_transfer","path_id":9,"revision":22,"stage":"integrate","step":"present_transfer"}},
                {"id":41,"public_id":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","role":"assistant","content":"İkinci","created":"10:01","reply_to":40,"delivery_status":"completed",
                 "technique":"Değişken değiştirme","technique_phase":"current_impact","technique_rationale":"En ağır güncel etkiyi birlikte netleştirmek",
                 "meta_events":[{"id":51,"public_id":"meta-stable-51","kind":"progress","status":"active","message_id":41,"source_user_message_id":40,"source_assistant_message_id":41,"path_id":9,"path_public_id":"path-stable-9","stage":"listen","step":"current_impact","title":"Şema yolu","summary":"Güncel etki adımına geçildi.","payload":{},"actions":[],"created":"2026-08-22 10:01:00","updated":"2026-08-22 10:01:00"}]}
              ],
              "message_count":100,"loaded_message_count":2,"has_more_messages":true,"oldest_message_id":40,
              "chat_request":{"request_id":"schema-v5-process-0001","conv_id":7,"status":"running","pending":true,"schema_prompt_protocol":"schema_path_chat_v5","schema_prompt_intent":"variable_counterfactual"}
            }
            """#.utf8))
        }
        let client = try makeClient()
        let page = try await client.conversation(id: 7, limit: 80, beforeID: 42)
        XCTAssertEqual(page.masterID, "jung")
        XCTAssertEqual(page.messages.map(\.id), [40, 41])
        XCTAssertEqual(
            page.messages.map(\.publicID),
            [
                "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            ]
        )
        XCTAssertEqual(page.messageCount, 100)
        XCTAssertTrue(page.hasMoreMessages)
        XCTAssertEqual(page.oldestMessageID, 40)
        XCTAssertEqual(page.messages.last?.technique?.name, "Değişken değiştirme")
        XCTAssertEqual(page.messages.last?.technique?.phase, "current_impact")
        XCTAssertEqual(page.messages.last?.metaEvents.first?.id, "meta-stable-51")
        XCTAssertEqual(
            page.messages.first?.schemaBindingResult?.errorCode,
            "stale_schema_revision"
        )
        XCTAssertNotNil(page.messages.first?.schemaBindingResult?.failureMessage)
        XCTAssertNil(page.messages.last?.schemaBindingResult)
        XCTAssertEqual(
            page.latestChatRequest?.schemaPromptProtocol,
            "schema_path_chat_v5"
        )
        XCTAssertEqual(
            page.latestChatRequest?.schemaPromptIntent,
            "variable_counterfactual"
        )
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

    func testSchemaBoundChatPostsExactBindingAndMapsDoneEnvelope() async throws {
        let posted = LockedBox<[String: Any]>([:])
        StubURLProtocol.install { request in
            let path = try XCTUnwrap(request.url?.path)
            if path == "/" {
                return (200, ["Content-Type": "text/html"], Data("ok".utf8))
            }
            XCTAssertEqual(path, "/api/chat")
            posted.set(try XCTUnwrap(
                JSONSerialization.jsonObject(
                    with: try bodyData(from: request)
                ) as? [String: Any]
            ))
            let stream = #"""
            data: {"type":"accepted","request_id":"native-bound-1","status":"running","user_message_id":201}

            data: {"type":"done","request_id":"native-bound-1","status":"completed","assistant_message_id":202,"technique":"İmgeleme","technique_phase":"imagery_work","technique_rationale":"Kullanıcının bildirdiği anıyla çalışmak","message_meta":[{"id":61,"public_id":"meta-public-61","kind":"technique","status":"active","message_id":202,"source_user_message_id":201,"source_assistant_message_id":202,"path_id":9,"path_public_id":"33333333333333333333333333333333","stage":"depth","step":"imagery_work","title":"İmgeleme","summary":"Bir adım tamamlandı.","payload":{},"actions":[],"created":"2026-08-22 12:01:00","updated":"2026-08-22 12:01:00"}],"next_card":{"id":"schema-chat-imagery-r13","kind":"chat_prompt","presentation":"chat_only","status":"active","stage":"depth","step":"imagery_work","path_id":9,"path_public_id":"33333333333333333333333333333333","revision":13,"title":"","context_line":"","body":"Şimdi ne fark ediyorsunuz?","source":{"user_message_id":201,"user_message_public_id":"cccccccccccccccccccccccccccccccc","assistant_message_id":202,"assistant_message_public_id":"dddddddddddddddddddddddddddddddd","quote":""},"checkpoint":{"public_id":"77777777777777777777777777777777","seq":13,"prompt_key":"technique_turn","method_id":"young:method:imagery-rescripting","status":"active","can_backtrack":true,"backtrack_pending":false,"pending_target_public_id":null},"chat_binding":{"protocol":"schema_path_chat_v4","path_id":9,"path_public_id":"33333333333333333333333333333333","step_id":"imagery_work","expected_revision":13,"checkpoint_public_id":"77777777777777777777777777777777","expected_checkpoint_seq":13,"source_user_message_id":201,"source_user_message_public_id":"cccccccccccccccccccccccccccccccc","source_assistant_message_id":202,"source_assistant_message_public_id":"dddddddddddddddddddddddddddddddd","technique_link_id":5,"technique_link_public_id":"55555555555555555555555555555555","expected_technique_revision":4},"fields":[],"actions":[{"id":"technique-ground","action":"ground_chat_technique","label":"Şimdiye dön","style":"secondary","requires_confirm":false,"payload":{"step_id":"imagery_work","technique_link_id":5,"technique_link_public_id":"55555555555555555555555555555555","expected_technique_revision":4,"control_only":true}},{"id":"schema-pause","action":"pause","label":"Duraklat","style":"secondary","requires_confirm":false,"payload":{}},{"id":"schema-stop","action":"stop","label":"Çalışmayı bitir","style":"danger","requires_confirm":true,"payload":{}}],"progress":{"stage_number":2,"stage_total":3,"step_number":3,"step_total":7,"label":"İmgeleme"}},"schema_path":{"id":9,"public_id":"33333333333333333333333333333333","conv_id":7,"therapist":"young","claim_id":44,"phase":"work","status":"active","method_id":"young:method:imagery-rescripting","method":{"method_id":"young:method:imagery-rescripting","node_id":"young:method:imagery-rescripting","name":"İmgeleme ile yeniden senaryolama","requires_precheck":true},"technique_run_id":77,"technique_links":[{"id":5,"public_id":"55555555555555555555555555555555","step":"imagery_work","method_id":"young:method:imagery-rescripting","technique_run_id":77,"technique_revision":4,"status":"active","protocol":"imagery","current_stage":"work","requires_precheck":true}],"active_technique_link":{"id":5,"public_id":"55555555555555555555555555555555","step":"imagery_work","method_id":"young:method:imagery-rescripting","technique_run_id":77,"technique_revision":4,"status":"active","protocol":"imagery","current_stage":"work","requires_precheck":true},"records":{},"revision":13,"flow_version":4,"stage":"depth","step":"imagery_work"},"interaction_policy":{"requires_in_app":true,"remote_reply_allowed":false,"composer_binding_required":true,"composer_allowed":true,"composer_mode":"bound","composer_surface":"ordinary_chat","bound_step_id":"imagery_work","reason":"bound_schema_step"},"resume_state":{"required":false,"reason":"none","stage":"depth","step":"imagery_work","card_id":"schema-chat-imagery-r13"},"schema_binding_result":{"applied":true,"progressed":true,"followup_required":true,"missing":[],"error_code":null,"path_revision":13,"step":"imagery_work","checkpoint_public_id":"77777777777777777777777777777777","checkpoint_seq":13,"backtracked":false}}

            """#
            return (
                200,
                ["Content-Type": "text/event-stream"],
                Data(stream.utf8)
            )
        }

        let client = try makeClient()
        let binding = SchemaChatBinding(
            pathId: 9,
            pathPublicId: "33333333333333333333333333333333",
            stepId: "imagery_work",
            expectedRevision: 12,
            checkpointPublicId: String(repeating: "6", count: 32),
            expectedCheckpointSeq: 10,
            sourceUserMessageId: 199,
            sourceUserMessagePublicId: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            sourceAssistantMessageId: 200,
            sourceAssistantMessagePublicId: "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            techniqueLinkId: 5,
            techniqueLinkPublicId: "55555555555555555555555555555555",
            expectedTechniqueRevision: 3
        )
        let stream = try await client.sendMessage(
            conversationID: 7,
            text: "Göğsümde bir sıkışma fark ediyorum.",
            schemaBinding: binding
        )
        var events: [ChatEvent] = []
        for try await event in stream { events.append(event) }

        let body = posted.get()
        let postedBinding = try XCTUnwrap(body["schema_binding"] as? [String: Any])
        XCTAssertEqual(Set(postedBinding.keys), Set([
            "protocol", "path_id", "path_public_id", "step_id",
            "expected_revision", "checkpoint_public_id",
            "expected_checkpoint_seq", "source_user_message_id",
            "source_user_message_public_id", "source_assistant_message_id",
            "source_assistant_message_public_id",
            "technique_link_id", "technique_link_public_id",
            "expected_technique_revision",
        ]))
        XCTAssertEqual(postedBinding["protocol"] as? String, "schema_path_chat_v4")
        XCTAssertEqual(postedBinding["path_id"] as? Int, 9)
        XCTAssertEqual(postedBinding["path_public_id"] as? String, "33333333333333333333333333333333")
        XCTAssertEqual(postedBinding["step_id"] as? String, "imagery_work")
        XCTAssertEqual(postedBinding["expected_revision"] as? Int, 12)
        XCTAssertEqual(
            postedBinding["checkpoint_public_id"] as? String,
            String(repeating: "6", count: 32)
        )
        XCTAssertEqual(postedBinding["expected_checkpoint_seq"] as? Int, 10)
        XCTAssertEqual(postedBinding["expected_technique_revision"] as? Int, 3)
        XCTAssertEqual(
            postedBinding["technique_link_public_id"] as? String,
            "55555555555555555555555555555555"
        )
        XCTAssertNil(postedBinding["step_data"])
        XCTAssertEqual(postedBinding["source_user_message_id"] as? Int, 199)
        XCTAssertEqual(
            postedBinding["source_assistant_message_public_id"] as? String,
            "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        )
        let done = try XCTUnwrap(events.last)
        XCTAssertEqual(done.kind, .done)
        XCTAssertEqual(done.technique?.name, "İmgeleme")
        XCTAssertEqual(done.messageMeta.first?.id, "meta-public-61")
        XCTAssertEqual(done.nextCard?.source.assistantMessageId, 202)
        XCTAssertEqual(done.nextCard?.revision, 13)
        XCTAssertEqual(done.nextCard?.chatBinding?.pathPublicId, "33333333333333333333333333333333")
        XCTAssertEqual(
            done.nextCard?.chatBinding?.sourceAssistantMessagePublicId,
            "dddddddddddddddddddddddddddddddd"
        )
        XCTAssertTrue(done.nextCard?.isSupportedByNativeContract == true)
        XCTAssertEqual(done.schemaPath?.revision, 13)
        XCTAssertEqual(done.schemaPath?.methodId, "young:method:imagery-rescripting")
        XCTAssertEqual(done.interactionPolicy?.composerMode, .bound)
        XCTAssertEqual(done.resumeState?.cardId, "schema-chat-imagery-r13")
        XCTAssertEqual(done.schemaBindingResult?.applied, true)
        XCTAssertEqual(done.schemaBindingResult?.progressed, true)
        XCTAssertEqual(done.schemaBindingResult?.revision, 13)
    }

    func testSchemaV5BoundChatPostsExactPromptDeliveryIdentity()
        async throws {
        let posted = LockedBox<[String: Any]>([:])
        StubURLProtocol.install { request in
            let path = try XCTUnwrap(request.url?.path)
            if path == "/" {
                return (200, ["Content-Type": "text/html"], Data("ok".utf8))
            }
            XCTAssertEqual(path, "/api/chat")
            posted.set(try XCTUnwrap(
                JSONSerialization.jsonObject(
                    with: try bodyData(from: request)
                ) as? [String: Any]
            ))
            let stream = #"""
            data: {"type":"accepted","request_id":"native-v5-bound-1","status":"running","user_message_id":201}

            data: {"type":"replace","request_id":"native-v5-bound-1","text":"Birlikte bakalım."}

            data: {"type":"done","request_id":"native-v5-bound-1","status":"completed","assistant_message_id":202,"message_meta":[],"next_card":null,"schema_path":null,"interaction_policy":null,"resume_state":null,"schema_binding_result":{"applied":true,"progressed":true,"followup_required":true,"missing":[],"error_code":null,"path_revision":3,"step":"origin_sequence","checkpoint_public_id":"88888888888888888888888888888888","checkpoint_seq":2,"backtracked":false}}

            """#
            return (
                200,
                ["Content-Type": "text/event-stream"],
                Data(stream.utf8)
            )
        }

        let client = try makeClient()
        let binding = SchemaChatBinding(
            protocol: "schema_path_chat_v5",
            pathId: 9,
            pathPublicId: "33333333333333333333333333333333",
            stepId: "variable_explore",
            expectedRevision: 2,
            checkpointPublicId: "99999999999999999999999999999999",
            expectedCheckpointSeq: 1,
            promptRequestId: "schema-v5-prompt-0001",
            promptAssistantMessageId: 200,
            promptAssistantMessagePublicId:
                "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            sourceUserMessageId: 199,
            sourceUserMessagePublicId:
                "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            sourceAssistantMessageId: 200,
            sourceAssistantMessagePublicId:
                "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        )
        let stream = try await client.sendMessage(
            conversationID: 7,
            text: "Dün toplantıda sözüm kesildi.",
            schemaBinding: binding
        )
        var events: [ChatEvent] = []
        for try await event in stream { events.append(event) }

        let body = posted.get()
        let postedBinding = try XCTUnwrap(
            body["schema_binding"] as? [String: Any]
        )
        XCTAssertEqual(Set(postedBinding.keys), Set([
            "protocol", "path_id", "path_public_id", "step_id",
            "expected_revision", "checkpoint_public_id",
            "expected_checkpoint_seq", "prompt_request_id",
            "prompt_assistant_message_id",
            "prompt_assistant_message_public_id",
            "source_user_message_id", "source_user_message_public_id",
            "source_assistant_message_id",
            "source_assistant_message_public_id",
        ]))
        XCTAssertEqual(
            postedBinding["protocol"] as? String, "schema_path_chat_v5"
        )
        XCTAssertEqual(
            postedBinding["prompt_request_id"] as? String,
            "schema-v5-prompt-0001"
        )
        XCTAssertEqual(
            postedBinding["prompt_assistant_message_id"] as? Int, 200
        )
        XCTAssertEqual(events.last?.kind, .done)
        XCTAssertEqual(events.last?.schemaBindingResult?.step,
                       "origin_sequence")
    }

    func testSchemaV5BindingRejectsMissingOrMismatchedPromptIdentity()
        async throws {
        StubURLProtocol.install { request in
            if request.url?.path == "/" {
                return (200, ["Content-Type": "text/html"], Data("ok".utf8))
            }
            XCTFail("Geçersiz v5 bağı sohbet isteğine dönüşmemeli")
            return (500, [:], Data())
        }
        let client = try makeClient()
        let invalid = SchemaChatBinding(
            protocol: "schema_path_chat_v5",
            pathId: 9,
            pathPublicId: "33333333333333333333333333333333",
            stepId: "variable_explore",
            expectedRevision: 2,
            checkpointPublicId: "99999999999999999999999999999999",
            expectedCheckpointSeq: 1,
            promptRequestId: nil,
            promptAssistantMessageId: 201,
            promptAssistantMessagePublicId:
                "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            sourceUserMessageId: 199,
            sourceUserMessagePublicId:
                "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            sourceAssistantMessageId: 200,
            sourceAssistantMessagePublicId:
                "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        )

        do {
            _ = try await client.sendMessage(
                conversationID: 7,
                text: "Bu bağ gönderilmemeli.",
                schemaBinding: invalid
            )
            XCTFail("Eksik prompt isteği reddedilmeliydi")
        } catch let error as DivanAPIError {
            XCTAssertEqual(
                error.errorCode, "schema_prompt_delivery_incomplete"
            )
        }
    }

    func testSchemaV5ImportControlPostsMarkerAndExplicitNullPromptIdentity()
        async throws {
        let posted = LockedBox<[String: Any]>([:])
        StubURLProtocol.install { request in
            if request.url?.path == "/" {
                return (200, ["Content-Type": "text/html"], Data("ok".utf8))
            }
            XCTAssertEqual(request.url?.path, "/api/chat")
            posted.set(try XCTUnwrap(
                JSONSerialization.jsonObject(
                    with: try bodyData(from: request)
                ) as? [String: Any]
            ))
            let stream = #"""
            data: {"type":"accepted","request_id":"native-v5-import-1","status":"completed","user_message_id":201}

            data: {"type":"done","request_id":"native-v5-import-1","status":"completed","assistant_message_id":null,"message_meta":[],"next_card":null,"schema_path":null,"interaction_policy":null,"resume_state":null,"schema_binding_result":{"applied":true,"progressed":false,"followup_required":true,"missing":[],"error_code":null,"action":"pause","provider_called":false,"path_revision":7,"step":"variable_explore","checkpoint_public_id":"99999999999999999999999999999999","checkpoint_seq":1,"backtracked":false}}

            """#
            return (
                200,
                ["Content-Type": "text/event-stream"],
                Data(stream.utf8)
            )
        }

        let client = try makeClient()
        let binding = SchemaChatBinding(
            protocol: "schema_path_chat_v5",
            syncImportControl: true,
            pathId: 9,
            pathPublicId: "33333333333333333333333333333333",
            stepId: "variable_explore",
            expectedRevision: 7,
            checkpointPublicId: "99999999999999999999999999999999",
            expectedCheckpointSeq: 1,
            promptRequestId: nil,
            promptAssistantMessageId: nil,
            promptAssistantMessagePublicId: nil,
            sourceUserMessageId: 199,
            sourceUserMessagePublicId:
                "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            sourceAssistantMessageId: 200,
            sourceAssistantMessagePublicId:
                "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        )
        let stream = try await client.sendMessage(
            conversationID: 7,
            text: "Devam",
            schemaBinding: binding
        )
        for try await _ in stream {}

        let postedBinding = try XCTUnwrap(
            posted.get()["schema_binding"] as? [String: Any]
        )
        XCTAssertEqual(postedBinding["sync_import_control"] as? Bool, true)
        for key in [
            "prompt_request_id", "prompt_assistant_message_id",
            "prompt_assistant_message_public_id",
        ] {
            XCTAssertTrue(postedBinding.keys.contains(key))
            XCTAssertTrue(postedBinding[key] is NSNull, key)
        }
        XCTAssertEqual(Set(postedBinding.keys), Set([
            "protocol", "sync_import_control", "path_id",
            "path_public_id", "step_id", "expected_revision",
            "checkpoint_public_id", "expected_checkpoint_seq",
            "prompt_request_id", "prompt_assistant_message_id",
            "prompt_assistant_message_public_id",
            "source_user_message_id", "source_user_message_public_id",
            "source_assistant_message_id",
            "source_assistant_message_public_id",
        ]))
    }

    func testSchemaV5FalseImportMarkerFailsBeforeNetwork()
        async throws {
        StubURLProtocol.install { request in
            if request.url?.path == "/" {
                return (200, ["Content-Type": "text/html"], Data("ok".utf8))
            }
            XCTFail("False import marker must never reach chat")
            return (500, [:], Data())
        }
        let client = try makeClient()
        let binding = SchemaChatBinding(
            protocol: "schema_path_chat_v5",
            syncImportControl: false,
            pathId: 9,
            pathPublicId: "33333333333333333333333333333333",
            stepId: "variable_explore",
            expectedRevision: 7,
            checkpointPublicId: "99999999999999999999999999999999",
            expectedCheckpointSeq: 1,
            sourceUserMessageId: 199,
            sourceUserMessagePublicId:
                "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            sourceAssistantMessageId: 200,
            sourceAssistantMessagePublicId:
                "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        )

        do {
            _ = try await client.sendMessage(
                conversationID: 7,
                text: "Devam",
                schemaBinding: binding
            )
            XCTFail("False import marker should fail closed")
        } catch let error as DivanAPIError {
            XCTAssertEqual(
                error.errorCode, "schema_prompt_delivery_incomplete"
            )
        }
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

    func testSaveSettingsSendsOllamaBaseURLUnderOllamaKey() async throws {
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
              "provider":"ollama","providers":{"ollama":{"label":"Ollama","model":"llama3.1","key_set":false,"local":true,"base_url":"http://127.0.0.1:11434/v1"}},
              "context_window_tokens":65536,"context_window_options":[65536],"privacy_seen":false,
              "pin_set":false,"retention_days":0,"simple_mode":false,"credential_storage":"macos_keychain","version":"test"
            }
            """#.utf8))
        }
        let client = try makeClient()
        let settings = try await client.saveSettings(ProviderSettingsUpdate(
            providerID: "ollama",
            modelID: "llama3.1",
            localBaseURL: "http://127.0.0.1:11434/v1"
        ))
        let body = postedBody.get()
        XCTAssertEqual(body["provider"] as? String, "ollama")
        XCTAssertEqual(body["ollama_model"] as? String, "llama3.1")
        XCTAssertEqual(
            body["ollama_base_url"] as? String, "http://127.0.0.1:11434/v1")
        XCTAssertNil(body["lmstudio_base_url"])
        XCTAssertEqual(settings.selectedProviderID, "ollama")
    }

    func testScanLocalModelsDecodesDetectedServers() async throws {
        StubURLProtocol.install { request in
            let path = try XCTUnwrap(request.url?.path)
            if path == "/" {
                return (200, ["Content-Type": "text/html"], Data("ok".utf8))
            }
            XCTAssertEqual(path, "/api/provider/models")
            let data = try bodyData(from: request)
            let object = try XCTUnwrap(
                JSONSerialization.jsonObject(with: data) as? [String: Any]
            )
            XCTAssertEqual(object["scan_all"] as? Bool, true)
            return (200, ["Content-Type": "application/json"], Data(#"""
            {
              "ok":true,"models":["llama3.1"],
              "base_url":"http://127.0.0.1:11434/v1",
              "servers":[
                {"label":"Ollama","base_url":"http://127.0.0.1:11434/v1",
                 "models":["llama3.1"],"provider":"ollama"}
              ]
            }
            """#.utf8))
        }
        let client = try makeClient()
        let servers = try await client.scanLocalModels()
        XCTAssertEqual(servers.count, 1)
        XCTAssertEqual(servers[0].provider, "ollama")
        XCTAssertEqual(servers[0].baseUrl, "http://127.0.0.1:11434/v1")
        XCTAssertEqual(servers[0].models, ["llama3.1"])
    }

    func testSetGuestModePostsActiveAndReadsBackFlag() async throws {
        let postedBody = LockedBox<[String: Any]>([:])
        StubURLProtocol.install { request in
            let path = try XCTUnwrap(request.url?.path)
            if path == "/" {
                return (200, ["Content-Type": "text/html"], Data("ok".utf8))
            }
            if request.httpMethod == "POST" {
                XCTAssertEqual(path, "/api/guest-mode")
                let data = try bodyData(from: request)
                let object = try XCTUnwrap(
                    JSONSerialization.jsonObject(with: data) as? [String: Any]
                )
                postedBody.set(object)
                return (200, ["Content-Type": "application/json"], Data(#"""
                {"ok":true,"guest_mode":true,"deleted_guest_conversations":0}
                """#.utf8))
            }
            return (200, ["Content-Type": "application/json"], Data(#"""
            {
              "provider":"deepseek","providers":{"deepseek":{"label":"DeepSeek","model":"deepseek-chat","key_set":true,"local":false}},
              "context_window_tokens":65536,"context_window_options":[65536],"privacy_seen":false,
              "pin_set":false,"retention_days":0,"simple_mode":false,"guest_mode":true,
              "credential_storage":"macos_keychain","version":"test"
            }
            """#.utf8))
        }
        let client = try makeClient()
        let settings = try await client.setGuestMode(true)
        let body = postedBody.get()
        XCTAssertEqual(body["active"] as? Bool, true)
        XCTAssertTrue(settings.guestMode)
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

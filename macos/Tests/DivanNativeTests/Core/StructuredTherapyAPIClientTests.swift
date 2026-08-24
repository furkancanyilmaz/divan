import Foundation
import XCTest
@testable import DivanNative

private final class StructuredTherapyStubURLProtocol: URLProtocol {
    private static let lock = NSLock()
    private static var handler: ((URLRequest) throws -> (Int, Data))?

    static func install(_ handler: @escaping (URLRequest) throws -> (Int, Data)) {
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
            let (status, data) = try handler(request)
            let url = try XCTUnwrap(request.url)
            let response = try XCTUnwrap(HTTPURLResponse(
                url: url,
                statusCode: status,
                httpVersion: "HTTP/1.1",
                headerFields: ["Content-Type": "application/json"]
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

private final class StructuredTherapyLockedBox<Value>: @unchecked Sendable {
    private let lock = NSLock()
    private var value: Value

    init(_ value: Value) { self.value = value }

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
}

private func structuredTherapyBody(_ request: URLRequest) throws -> [String: Any] {
    let data: Data
    if let body = request.httpBody {
        data = body
    } else if let stream = request.httpBodyStream {
        stream.open()
        defer { stream.close() }
        var bytes = Data()
        var buffer = [UInt8](repeating: 0, count: 4_096)
        while true {
            let count = stream.read(&buffer, maxLength: buffer.count)
            if count > 0 {
                bytes.append(buffer, count: count)
            } else if count == 0 {
                break
            } else {
                throw stream.streamError ?? URLError(.cannotDecodeRawData)
            }
        }
        data = bytes
    } else {
        throw URLError(.cannotDecodeRawData)
    }
    return try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
}

final class StructuredTherapyAPIClientTests: XCTestCase {
    override func tearDown() {
        StructuredTherapyStubURLProtocol.clear()
        super.tearDown()
    }

    func testADHDDashboardDecodesTypedWorkspaceAndConversationQuery() async throws {
        StructuredTherapyStubURLProtocol.install { request in
            let url = try XCTUnwrap(request.url)
            if url.path == "/" { return (200, Data("ok".utf8)) }
            XCTAssertEqual(url.path, "/api/adhd/dashboard")
            XCTAssertEqual(request.httpMethod, "GET")
            let components = URLComponents(url: url, resolvingAgainstBaseURL: false)
            XCTAssertEqual(
                components?.queryItems?.first(where: { $0.name == "conv_id" })?.value,
                "12"
            )
            return (200, Data(#"""
            {
              "conversation_id":12,
              "default_target_per_week":2,
              "week_start":1786896000,
              "habits":[{
                "id":8,"source_conv":12,"title":"Defteri aç",
                "cue":"Kahveden sonra","tiny_action":"Tek satır yaz",
                "target_per_week":3,"preferred_days":[1,3,5],
                "reminder_local_time":null,"timezone":"Europe/Istanbul",
                "status":"active","review_due":true
              }],
              "events":[{
                "id":21,"habit":8,"scheduled_for":1786903200,
                "status":"scheduled","reminder_id":null
              }],
              "journal_entries":[{
                "id":31,"conv":12,"habit":8,"event":null,
                "entry_type":"daily_page","content":"Bugün bir satır yeterli.",
                "share_with_coach":false,"sensitive":true
              }],
              "week_counts":{"8":{"done":1,"partial":1,"skipped":0,"planned":2}},
              "review_due":[8],
              "notices":{
                "no_streak":"Seri yok.","no_shame":"Borç yok.",
                "not_diagnostic":"Tanı aracı değildir.",
                "monitoring":"Acil destek tarafından izlenmez.",
                "pause_available":"İstediğiniz an duraklatabilirsiniz."
              }
            }
            """#.utf8))
        }

        let client = try makeClient()
        let dashboard = try await client.adhdDashboard(conversationID: 12)

        XCTAssertEqual(dashboard.conversationID, 12)
        XCTAssertEqual(dashboard.defaultTargetPerWeek, 2)
        XCTAssertEqual(dashboard.habits.first?.tinyAction, "Tek satır yaz")
        XCTAssertEqual(dashboard.events.first?.habit, 8)
        XCTAssertTrue(try XCTUnwrap(dashboard.events.first).isOpen)
        XCTAssertTrue(try XCTUnwrap(dashboard.journalEntries.first).sensitive)
        XCTAssertEqual(dashboard.weekCounts["8"]?.partial, 1)
        XCTAssertEqual(dashboard.reviewDue, [8])
        XCTAssertEqual(dashboard.notices.noStreak, "Seri yok.")
    }

    func testADHDTUSPlannerDecodesExactMetadataOnlyPlanAndFilterQuery() async throws {
        StructuredTherapyStubURLProtocol.install { request in
            let url = try XCTUnwrap(request.url)
            if url.path == "/" { return (200, Data("ok".utf8)) }
            XCTAssertEqual(url.path, "/api/adhd/tus")
            XCTAssertEqual(request.httpMethod, "GET")
            let components = URLComponents(url: url, resolvingAgainstBaseURL: false)
            XCTAssertEqual(
                components?.queryItems?.first(where: { $0.name == "conv_id" })?.value,
                "12"
            )
            XCTAssertEqual(
                components?.queryItems?.first(where: { $0.name == "q" })?.value,
                "farma"
            )
            return (200, Self.adhdTUSActiveResponse)
        }

        let snapshot = try await makeClient().adhdTUSPlanner(
            conversationID: 12,
            query: " farma "
        )

        XCTAssertTrue(snapshot.contractIsSupported)
        XCTAssertEqual(snapshot.protocol, "adhd_tus_planner_v1")
        XCTAssertEqual(snapshot.revision, 8)
        XCTAssertEqual(snapshot.state, "active")
        XCTAssertEqual(snapshot.history.count, 6)
        XCTAssertNil(snapshot.question)
        XCTAssertEqual(snapshot.plan?.activity, "mixed")
        XCTAssertEqual(snapshot.plan?.lesson.name, "Farmakoloji")
        XCTAssertEqual(snapshot.plan?.readingArea?.source, "TümTUS Cümle")
        XCTAssertEqual(snapshot.plan?.readingArea?.availableCount, 120)
        XCTAssertEqual(snapshot.plan?.questionArea?.source, "TümTUS Soru")
        XCTAssertEqual(snapshot.plan?.questionArea?.availableCount, 40)
        XCTAssertEqual(snapshot.plan?.currentStep?.kind, "reading")
        XCTAssertEqual(snapshot.plan?.steps.filter(\.visible).count, 1)
        XCTAssertEqual(snapshot.catalog.questionCount, 11_438)
        XCTAssertEqual(snapshot.catalog.tusDefaultQuestionCount, 10_900)
        XCTAssertEqual(snapshot.catalog.sentenceCount, 39_100)
        XCTAssertEqual(snapshot.notices.localOnly, "Yalnız bu cihazda.")
    }

    func testADHDTUSPlannerRejectsProtocolConversationAndStateMismatch() async throws {
        let body = StructuredTherapyLockedBox(Self.adhdTUSActiveResponse)
        StructuredTherapyStubURLProtocol.install { request in
            if request.url?.path == "/" { return (200, Data("ok".utf8)) }
            return (200, body.get())
        }
        let client = try makeClient()

        for invalid in [
            Self.adhdTUSActiveJSON.replacingOccurrences(
                of: #""protocol":"adhd_tus_planner_v1""#,
                with: #""protocol":"adhd_tus_planner_v2""#
            ),
            Self.adhdTUSActiveJSON.replacingOccurrences(
                of: #""conv_id":12"#,
                with: #""conv_id":13"#
            ),
            Self.adhdTUSActiveJSON.replacingOccurrences(
                of: #""state":"active""#,
                with: #""state":"question""#
            ),
            Self.adhdTUSActiveJSON.replacingOccurrences(
                of: #""safety_hold":false"#,
                with: #""safety_hold":false,"ok":true,"duplicate":false,"action":"pause""#
            ),
        ] {
            body.set(Data(invalid.utf8))
            do {
                _ = try await client.adhdTUSPlanner(conversationID: 12)
                XCTFail("Tutarsız TUS sözleşmesi kabul edilmemeliydi.")
            } catch let error as DivanAPIError {
                XCTAssertEqual(error.errorCode, "invalid_request")
            }
        }
    }

    func testADHDTUSPlannerDropsRawQuestionAndSentenceFieldsFromTypedModel() async throws {
        let secret = "RAW-CONTENT-MUST-NOT-LEAK"
        StructuredTherapyStubURLProtocol.install { request in
            if request.url?.path == "/" { return (200, Data("ok".utf8)) }
            return (200, Data(#"""
            {
              "protocol":"adhd_tus_planner_v1","conv_id":12,"revision":2,
              "enabled":true,"state":"question","history":[],
              "question":{"id":"question_area","prompt":"Hangi alan?",
                "options":[{"id":"area-1","label":"Kardiyoloji",
                  "description":"40 soru","raw_question":"\#(secret)",
                  "sentence_text":"\#(secret)","choices":["\#(secret)"]}],
                "total_options":1,"filterable":true,"has_more":false},
              "plan":null,"allowed_actions":["answer","restart","set_mode"],
              "catalog":{"available":true,"error_code":null,
                "fingerprint":"sha256:\#(String(repeating: "b", count: 64))",
                "lessons":1,"question_areas":1,"reading_areas":1,
                "question_count":40,"sentence_count":20,
                "raw_questions":["\#(secret)"]},
              "catalog_changed":false,"notices":{},"safety_hold":false,
              "raw_question":"\#(secret)","sentence_text":"\#(secret)"
            }
            """#.utf8))
        }

        let snapshot = try await makeClient().adhdTUSPlanner(conversationID: 12)
        XCTAssertTrue(snapshot.contractIsSupported)
        XCTAssertEqual(snapshot.question?.options.first?.label, "Kardiyoloji")
        XCTAssertFalse(String(describing: snapshot).contains(secret))
    }

    func testADHDTUSAnswerPostsExactBindingAndAcceptsNextRevisionOnly() async throws {
        let posted = StructuredTherapyLockedBox<[String: Any]>([:])
        StructuredTherapyStubURLProtocol.install { request in
            if request.url?.path == "/" { return (200, Data("ok".utf8)) }
            XCTAssertEqual(request.url?.path, "/api/adhd/tus")
            XCTAssertEqual(request.httpMethod, "POST")
            posted.set(try structuredTherapyBody(request))
            return (200, Self.adhdTUSAnswerResponse)
        }

        let response = try await makeClient().mutateADHDTUS(.init(
            action: .answer,
            conversationID: 12,
            expectedRevision: 3,
            requestID: "native-adhd-tus-answer-0001",
            questionID: "activity",
            optionID: "questions"
        ))

        XCTAssertEqual(response.revision, 4)
        XCTAssertEqual(response.action, "answer")
        let body = posted.get()
        XCTAssertEqual(Set(body.keys), Set([
            "protocol", "conv_id", "action", "expected_revision", "request_id",
            "question_id", "option_id",
        ]))
        XCTAssertEqual(body["protocol"] as? String, "adhd_tus_planner_v1")
        XCTAssertEqual(body["conv_id"] as? Int, 12)
        XCTAssertEqual(body["action"] as? String, "answer")
        XCTAssertEqual(body["expected_revision"] as? Int, 3)
        XCTAssertEqual(body["request_id"] as? String, "native-adhd-tus-answer-0001")
        XCTAssertEqual(body["question_id"] as? String, "activity")
        XCTAssertEqual(body["option_id"] as? String, "questions")
        XCTAssertNil(body["custom_minutes"])
    }

    func testADHDTUSMutationRejectsRevisionRollbackAndActionMismatch() async throws {
        let response = StructuredTherapyLockedBox(Self.adhdTUSAnswerResponse)
        StructuredTherapyStubURLProtocol.install { request in
            if request.url?.path == "/" { return (200, Data("ok".utf8)) }
            return (200, response.get())
        }
        let client = try makeClient()
        let mutation = ADHDTUSMutation(
            action: .answer,
            conversationID: 12,
            expectedRevision: 3,
            requestID: "native-adhd-tus-stale-0001",
            questionID: "activity",
            optionID: "questions"
        )

        response.set(Data(Self.adhdTUSAnswerJSON.replacingOccurrences(
            of: #""revision":4"#,
            with: #""revision":3"#
        ).utf8))
        do {
            _ = try await client.mutateADHDTUS(mutation)
            XCTFail("Revizyon ilerlemeden dönen yanıt kabul edilmemeliydi.")
        } catch let error as DivanAPIError {
            XCTAssertEqual(error.errorCode, "invalid_request")
        }

        response.set(Data(Self.adhdTUSAnswerJSON.replacingOccurrences(
            of: #""action":"answer""#,
            with: #""action":"restart""#
        ).utf8))
        do {
            _ = try await client.mutateADHDTUS(mutation)
            XCTFail("Başka eyleme ait yanıt kabul edilmemeliydi.")
        } catch let error as DivanAPIError {
            XCTAssertEqual(error.errorCode, "invalid_request")
        }

        response.set(Data(Self.adhdTUSAnswerJSON.replacingOccurrences(
            of: ",\"duplicate\":false",
            with: ""
        ).utf8))
        do {
            _ = try await client.mutateADHDTUS(mutation)
            XCTFail("Eksik idempotency zarfı kabul edilmemeliydi.")
        } catch let error as DivanAPIError {
            XCTAssertEqual(error.errorCode, "invalid_request")
        }
    }

    func testADHDTUSInvalidQuestionAndPublicIDsFailBeforeNetwork() async throws {
        let requestCount = StructuredTherapyLockedBox(0)
        StructuredTherapyStubURLProtocol.install { _ in
            requestCount.set(requestCount.get() + 1)
            return (500, Data())
        }
        let client = try makeClient()

        let invalid = [
            ADHDTUSMutation(
                action: .answer, conversationID: 12, expectedRevision: 0,
                requestID: "native-adhd-tus-invalid-0001",
                questionID: "raw_question", optionID: "area-1"
            ),
            ADHDTUSMutation(
                action: .start, conversationID: 12, expectedRevision: 0,
                requestID: "native-adhd-tus-invalid-0002", planID: "plan-1"
            ),
            ADHDTUSMutation(
                action: .completeStep, conversationID: 12, expectedRevision: 0,
                requestID: "native-adhd-tus-invalid-0003",
                planID: String(repeating: "a", count: 32), stepID: "step-1"
            ),
            ADHDTUSMutation(
                action: .answer, conversationID: 12, expectedRevision: 0,
                requestID: "native-adhd-tus-invalid-0004",
                questionID: "activity", optionID: "15"
            ),
            ADHDTUSMutation(
                action: .answer, conversationID: 12, expectedRevision: 0,
                requestID: "native-adhd-tus-invalid-0005",
                questionID: "available_time", optionID: "normal"
            ),
            ADHDTUSMutation(
                action: .answer, conversationID: 12, expectedRevision: 0,
                requestID: "native-adhd-tus-invalid-0006",
                questionID: "start_friction", optionID: "questions"
            ),
            ADHDTUSMutation(
                action: .answer, conversationID: 12, expectedRevision: 0,
                requestID: "native-adhd-tus-invalid-0007",
                questionID: "lesson", optionID: "custom", customMinutes: 25
            ),
        ]
        for mutation in invalid {
            do {
                _ = try await client.mutateADHDTUS(mutation)
                XCTFail("Geçersiz TUS bağı ağdan önce reddedilmeliydi.")
            } catch let error as DivanAPIError {
                XCTAssertEqual(error.errorCode, "invalid_request")
            }
        }
        XCTAssertEqual(requestCount.get(), 0)
    }

    func testADHDTUSCatalogChangeKeepsExplicitRestartAndBlocksAnswer() async throws {
        StructuredTherapyStubURLProtocol.install { request in
            if request.url?.path == "/" { return (200, Data("ok".utf8)) }
            return (200, Data(#"""
            {
              "protocol":"adhd_tus_planner_v1","conv_id":12,"revision":7,
              "enabled":true,"state":"question",
              "history":[{"question_id":"activity","question":"Bugün nasıl çalışalım?","answer_id":"mixed","answer":"Karma ilerleyelim"}],
              "question":null,"plan":null,
              "allowed_actions":["restart","set_mode"],
              "catalog":{"available":true,"error_code":null,
                "fingerprint":"sha256:\#(String(repeating: "c", count: 64))",
                "lessons":13,"question_areas":4371,"reading_areas":3266,
                "question_count":11438,"tus_default_question_count":10900,
                "sentence_count":39100},
              "catalog_changed":true,"notices":{},"safety_hold":false
            }
            """#.utf8))
        }

        let snapshot = try await makeClient().adhdTUSPlanner(conversationID: 12)

        XCTAssertTrue(snapshot.contractIsSupported)
        XCTAssertNil(snapshot.question)
        XCTAssertEqual(Set(snapshot.allowedActions), ["restart", "set_mode"])
    }

    func testADHDTUSPauseAndResumePostCommonFieldsOnly() async throws {
        let posted = StructuredTherapyLockedBox<[[String: Any]]>([])
        let revision = StructuredTherapyLockedBox(8)
        StructuredTherapyStubURLProtocol.install { request in
            if request.url?.path == "/" { return (200, Data("ok".utf8)) }
            let body = try structuredTherapyBody(request)
            posted.set(posted.get() + [body])
            let action = try XCTUnwrap(body["action"] as? String)
            let next = revision.get() + 1
            revision.set(next)
            var json = Self.adhdTUSActiveJSON
                .replacingOccurrences(of: #""revision":8"#, with: #""revision":\#(next)"#)
            if action == "pause" {
                json = json
                    .replacingOccurrences(of: #""state":"active""#, with: #""state":"paused""#)
                    .replacingOccurrences(of: #""status":"active","activity""#, with: #""status":"paused","activity""#)
                    .replacingOccurrences(of: #""allowed_actions":["complete_step","pause","finish","cancel","set_mode"]"#, with: #""allowed_actions":["resume","finish","cancel","restart","set_mode"]"#)
            }
            json.removeLast()
            json += ", \"ok\":true,\"duplicate\":false,\"action\":\"\(action)\"}"
            return (200, Data(json.utf8))
        }
        let client = try makeClient()

        _ = try await client.mutateADHDTUS(.init(
            action: .pause, conversationID: 12, expectedRevision: 8,
            requestID: "native-adhd-tus-pause-0001"
        ))
        _ = try await client.mutateADHDTUS(.init(
            action: .resume, conversationID: 12, expectedRevision: 9,
            requestID: "native-adhd-tus-resume-0001"
        ))

        XCTAssertEqual(posted.get().count, 2)
        for body in posted.get() {
            XCTAssertEqual(Set(body.keys), Set([
                "protocol", "conv_id", "action", "expected_revision", "request_id",
            ]))
            XCTAssertNil(body["plan_id"])
            XCTAssertNil(body["step_id"])
        }
    }

    func testADHDStartNowPostsOnlyImmediateAttemptFieldsAndStableRequestID() async throws {
        let posted = StructuredTherapyLockedBox<[String: Any]>([:])
        StructuredTherapyStubURLProtocol.install { request in
            let path = try XCTUnwrap(request.url?.path)
            if path == "/" { return (200, Data("ok".utf8)) }
            XCTAssertEqual(path, "/api/adhd/habits")
            XCTAssertEqual(request.httpMethod, "POST")
            posted.set(try structuredTherapyBody(request))
            return (200, Data(#"""
            {
              "ok":true,"duplicate":false,
              "habit":{
                "id":8,"title":"Defteri aç","target_per_week":3,
                "preferred_days":[1,3,5],"status":"active","review_due":false
              },
              "event":{
                "id":22,"habit":8,"scheduled_for":1786903200,"status":"started"
              },
              "reminder":null
            }
            """#.utf8))
        }

        let client = try makeClient()
        let response = try await client.mutateADHDHabit(ADHDHabitMutation(
            action: .startNow,
            conversationID: 12,
            requestID: "adhd-start-0001",
            habitID: 8
        ))

        XCTAssertEqual(response.event?.status, "started")
        let body = posted.get()
        XCTAssertEqual(Set(body.keys), Set([
            "action", "conv_id", "request_id", "habit_id",
        ]))
        XCTAssertEqual(body["action"] as? String, "start_now")
        XCTAssertEqual(body["conv_id"] as? Int, 12)
        XCTAssertEqual(body["habit_id"] as? Int, 8)
        XCTAssertEqual(body["request_id"] as? String, "adhd-start-0001")
        XCTAssertNil(body["scheduled_for"])
        XCTAssertNil(body["reminder_local_time"])
        XCTAssertNil(body["timezone"])
    }

    func testADHDHabitUpdateClearsPreferredTimeWithEmptyStringNotNull() async throws {
        let posted = StructuredTherapyLockedBox<[String: Any]>([:])
        StructuredTherapyStubURLProtocol.install { request in
            let path = try XCTUnwrap(request.url?.path)
            if path == "/" { return (200, Data("ok".utf8)) }
            XCTAssertEqual(path, "/api/adhd/habits")
            posted.set(try structuredTherapyBody(request))
            return (200, Data(#"{"ok":true,"duplicate":false,"habit":{"id":8,"title":"Defteri aç","target_per_week":2,"preferred_days":[],"reminder_local_time":"","status":"active","review_due":false}}"#.utf8))
        }

        let client = try makeClient()
        _ = try await client.mutateADHDHabit(ADHDHabitMutation(
            action: .update,
            conversationID: 12,
            requestID: "adhd-update-0001",
            habitID: 8,
            reminderLocalTime: ""
        ))

        XCTAssertEqual(posted.get()["reminder_local_time"] as? String, "")
        XCTAssertFalse(posted.get()["reminder_local_time"] is NSNull)
    }

    func testADHDJournalRejectsSensitiveCoachSharingBeforeNetwork() async throws {
        let requestCount = StructuredTherapyLockedBox(0)
        StructuredTherapyStubURLProtocol.install { _ in
            requestCount.set(requestCount.get() + 1)
            return (500, Data())
        }
        let client = try makeClient()

        do {
            _ = try await client.mutateADHDJournal(ADHDJournalMutation(
                action: .create,
                conversationID: 12,
                requestID: "adhd-journal-0001",
                content: "Yalnızca bende kalacak not.",
                entryType: .freewrite,
                shareWithCoach: true,
                sensitive: true
            ))
            XCTFail("Hassas bir defter yazısı koçla paylaşılamamalıydı.")
        } catch let error as DivanAPIError {
            XCTAssertEqual(error.errorCode, "invalid_request")
            XCTAssertEqual(error.localizedDescription, "Hassas yazı koçla paylaşılamaz.")
        }
        XCTAssertEqual(requestCount.get(), 0)
    }

    func testSchemaEnhancedMethodPostsEveryExplicitPrecheckAnswerExactly() async throws {
        let posted = StructuredTherapyLockedBox<[String: Any]>([:])
        StructuredTherapyStubURLProtocol.install { request in
            let path = try XCTUnwrap(request.url?.path)
            if path == "/" { return (200, Data("ok".utf8)) }
            XCTAssertEqual(path, "/api/schema-path")
            XCTAssertEqual(request.httpMethod, "POST")
            posted.set(try structuredTherapyBody(request))
            return (200, Self.schemaMutationResponse)
        }

        let client = try makeClient()
        _ = try await client.mutateSchemaPath(SchemaPathMutation(
            action: .chooseMethod,
            conversationID: 12,
            requestID: "schema-method-0001",
            pathID: 44,
            methodID: "young:mode-chairs",
            confirmed: true,
            precheck: SchemaPathPrecheck(
                orientationConfirmed: true,
                realityClear: true,
                sleepActivationClear: true,
                intensity: 4,
                supportAvailable: false,
                stopSignal: "Şimdi dur"
            )
        ))

        let body = posted.get()
        XCTAssertEqual(Set(body.keys), Set([
            "action", "conv_id", "request_id", "path_id", "method_id",
            "confirmed", "precheck",
        ]))
        XCTAssertEqual(body["action"] as? String, "choose_method")
        XCTAssertEqual(body["method_id"] as? String, "young:mode-chairs")
        XCTAssertEqual(body["confirmed"] as? Bool, true)
        let precheck = try XCTUnwrap(body["precheck"] as? [String: Any])
        XCTAssertEqual(Set(precheck.keys), Set([
            "orientation_confirmed", "reality_clear", "sleep_activation_clear",
            "intensity", "support_available", "stop_signal",
        ]))
        XCTAssertEqual(precheck["orientation_confirmed"] as? Bool, true)
        XCTAssertEqual(precheck["reality_clear"] as? Bool, true)
        XCTAssertEqual(precheck["sleep_activation_clear"] as? Bool, true)
        XCTAssertEqual(precheck["intensity"] as? Int, 4)
        XCTAssertEqual(precheck["support_available"] as? Bool, false)
        XCTAssertEqual(precheck["stop_signal"] as? String, "Şimdi dur")
    }

    func testSchemaPracticePayloadContainsNoNotificationOrReminderKeys() async throws {
        let posted = StructuredTherapyLockedBox<[String: Any]>([:])
        StructuredTherapyStubURLProtocol.install { request in
            let path = try XCTUnwrap(request.url?.path)
            if path == "/" { return (200, Data("ok".utf8)) }
            XCTAssertEqual(path, "/api/schema-path")
            posted.set(try structuredTherapyBody(request))
            return (200, Self.schemaMutationResponse)
        }

        let client = try makeClient()
        _ = try await client.mutateSchemaPath(SchemaPathMutation(
            action: .assignPractice,
            conversationID: 12,
            requestID: "schema-practice-0001",
            pathID: 44,
            experiment: SchemaPractice(
                variable: "Bir kez yardım istemek",
                constant: "Aynı ekip toplantısı",
                prediction: "Yargılanacağım",
                action: "Tek bir net soru sormak",
                observableResult: "Verilen yanıtı not etmek",
                tinyVersion: "Soruyu taslakta yazmak",
                targetPerWeek: 2
            ),
            userConfirmed: true
        ))

        let body = posted.get()
        XCTAssertEqual(Set(body.keys), Set([
            "action", "conv_id", "request_id", "path_id", "experiment",
            "user_confirmed",
        ]))
        XCTAssertEqual(body["action"] as? String, "assign_practice")
        XCTAssertEqual(body["user_confirmed"] as? Bool, true)
        let experiment = try XCTUnwrap(body["experiment"] as? [String: Any])
        XCTAssertEqual(Set(experiment.keys), Set([
            "variable", "constant", "prediction", "action",
            "observable_result", "tiny_version", "target_per_week",
        ]))
        XCTAssertEqual(experiment["target_per_week"] as? Int, 2)

        let forbidden = Set([
            "notification", "notifications", "notify", "reminder",
            "reminder_id", "scheduled_for", "due_at",
        ])
        XCTAssertTrue(forbidden.isDisjoint(with: Set(body.keys)))
        XCTAssertTrue(forbidden.isDisjoint(with: Set(experiment.keys)))
    }

    func testSchemaPathDecodesFutureOnlyModeTurnProgressAndMessageEvidence() async throws {
        StructuredTherapyStubURLProtocol.install { request in
            let url = try XCTUnwrap(request.url)
            if url.path == "/" { return (200, Data("ok".utf8)) }
            XCTAssertEqual(url.path, "/api/schema-path")
            XCTAssertEqual(request.httpMethod, "GET")
            return (200, Data(#"""
            {
              "version":3,"active_path":null,
              "candidates":[{
                "id":91,"public_id":"claim-91","claim_type":"schema_hypothesis",
                "title":"Terk edilme olasılığı","statement":"Yakınlıkta kayıp beklentisi olabilir.",
                "status":"candidate","scope":"therapist","sensitive":false,
                "sources":[],"direct_user_evidence":[],"counterexamples":[],
                "evidence_summary":{"accepted":0,"pending":1,"reviewable":1},
                "approved_for_path":false,
                "schema":{"id":"schema_abandonment","label":"Terk edilme"},
                "mode":{"id":"vulnerable_child","label":"Kırılgan Çocuk"},
                "source_turn":{
                  "user_message_id":301,"assistant_message_id":302,
                  "user_excerpt":"Uzaklaşacak diye korktum.",
                  "assistant_excerpt":"Bunu birlikte yavaşça inceleyebiliriz.",
                  "completed":true
                },
                "decision_state":"pending",
                "available_decisions":["accept","defer","dismiss"],
                "deferred_for_next_session":false
              }],
              "queued_candidates":[],"queued_count":0,"active_path_notice":"",
              "methods":[],"notices":[],"allowed_actions":["review_candidate","start"],
              "completed_turns":4,"minimum_listening_turns":3,
              "schema_mode":{
                "enabled":true,"preference_enabled":true,
                "pending_device_confirmation":false,
                "pending_provider_confirmation":false,
                "can_enable":true,"reason":"","updated":"2026-08-17 21:00:00"
              },
              "turn_analysis":{
                "analysis_unit":"completed_user_assistant_turn","status":"succeeded",
                "processing":false,"eligible_turns":4,"analyzed_turns":1,
                "remaining_turns":3,"calls_remaining":3,
                "failed_turns":0,"safety_skipped_turns":0,
                "through_message_id":301,"target_message_id":307,"error_code":"",
                "analyzed_user_message_ids":[301],
                "processing_user_message_ids":[303],
                "failed_user_message_ids":[305],
                "provider":{"id":"lmstudio","label":"LM Studio","model":"local-model","local":true},
                "job":null
              },
              "focus":{
                "offer":{"id":7,"created":"2026-08-21 10:00","candidates":[{
                  "mode_key":"vulnerable_child","label":"Kırılgan Çocuk",
                  "chair_label":"Kırılgan yan","group":"child",
                  "coping_style":"surrender","recognize":"Yakınlık kaybı korkusu",
                  "question":"Bu anda bu yan mı öne çıkıyor?",
                  "evidence":"Uzaklaşacak diye korktum."
                }]},"chosen":null
              },
              "inline_suggestions":[{
                "suggestion_id":19,"assistant_message_id":302,
                "mode_key":"vulnerable_child","label":"Kırılgan Çocuk",
                "chair_label":"Kırılgan yan","group":"child",
                "coping_style":"surrender","recognize":"Yakınlık kaybı korkusu",
                "question":"Bunu konuşalım mı?","evidence":"Uzaklaşacak diye korktum."
              }],
              "focus_minimum_turns":3,
              "origin":{
                "recorded":true,"age":9,"age_range":"8–10",
                "scene":"Okul çıkışı","unmet_need":"Güven",
                "confidence":"reported","updated":"2026-08-21 10:02"
              },
              "growth":{
                "stages":[{"id":31,"seq":1,"age":9,"label":"",
                  "then_response":"Sustum","now_response":"Yardım istiyorum",
                  "difference":"Sesimi kullanıyorum","comparable":true}],
                "comparable_count":1,"max_stages":6
              },
              "healthy_adult":{
                "count":1,"recent":[{"evidence":"Sınır koyabildim",
                  "created":"2026-08-21 10:03"}]
              }
            }
            """#.utf8))
        }

        let value = try await makeClient().schemaPath(conversationID: 12)
        XCTAssertTrue(try XCTUnwrap(value.schemaMode).enabled)
        XCTAssertTrue(try XCTUnwrap(value.schemaMode).preferenceEnabled)
        XCTAssertFalse(try XCTUnwrap(value.schemaMode).pendingDeviceConfirmation)
        XCTAssertEqual(value.turnAnalysis?.analysisUnit, "completed_user_assistant_turn")
        XCTAssertEqual(value.turnAnalysis?.remainingTurns, 3)
        XCTAssertEqual(value.turnAnalysis?.callsRemaining, 3)
        XCTAssertEqual(value.turnAnalysis?.processingUserMessageIds, [303])
        XCTAssertEqual(value.turnAnalysis?.provider?.model, "local-model")
        XCTAssertEqual(value.candidates.first?.schema?.label, "Terk edilme")
        XCTAssertEqual(value.candidates.first?.mode?.id, "vulnerable_child")
        XCTAssertEqual(value.candidates.first?.sourceTurn?.userMessageId, 301)
        XCTAssertEqual(value.candidates.first?.availableDecisions, ["accept", "defer", "dismiss"])
        XCTAssertEqual(value.focus?.offer?.candidates.first?.modeKey, "vulnerable_child")
        XCTAssertEqual(value.inlineSuggestions?.first?.assistantMessageId, 302)
        XCTAssertEqual(value.origin?.age, 9)
        XCTAssertEqual(value.growth?.stages.first?.nowResponse, "Yardım istiyorum")
        XCTAssertEqual(value.healthyAdult?.recent.first?.evidence, "Sınır koyabildim")
    }

    func testSchemaFocusOriginGrowthAndHealthyAdultMutationsUseExactUserFields() async throws {
        let posted = StructuredTherapyLockedBox<[[String: Any]]>([])
        StructuredTherapyStubURLProtocol.install { request in
            if request.url?.path == "/" { return (200, Data("ok".utf8)) }
            var values = posted.get()
            values.append(try structuredTherapyBody(request))
            posted.set(values)
            return (200, Self.schemaMutationResponse)
        }
        let client = try makeClient()
        _ = try await client.mutateSchemaPath(.init(
            action: .chooseFocus, conversationID: 12,
            requestID: "schema-focus-choose-0001", pathID: 44,
            modeKey: "vulnerable_child"
        ))
        _ = try await client.mutateSchemaPath(.init(
            action: .recordOrigin, conversationID: 12,
            requestID: "schema-origin-record-0001", pathID: 44,
            authoredBy: "user", age: 9, ageRange: "8–10",
            scene: "Okul çıkışı", unmetNeed: "Güven", confidence: "reported"
        ))
        _ = try await client.mutateSchemaPath(.init(
            action: .addGrowthStage, conversationID: 12,
            requestID: "schema-growth-add-0001", pathID: 44,
            age: 12, label: "Ortaokul"
        ))
        _ = try await client.mutateSchemaPath(.init(
            action: .recordGrowth, conversationID: 12,
            requestID: "schema-growth-record-0001", pathID: 44,
            stageID: 31, thenResponse: "Sustum",
            nowResponse: "Yardım istiyorum", difference: "Sesimi kullanıyorum"
        ))
        _ = try await client.mutateSchemaPath(.init(
            action: .markHealthyAdult, conversationID: 12,
            requestID: "schema-healthy-adult-0001", pathID: 44,
            evidence: "Bugün gerçekçi bir sınır koydum."
        ))
        _ = try await client.mutateSchemaPath(.init(
            action: .acceptSuggestion, conversationID: 12,
            requestID: "schema-inline-accept-0001",
            suggestionID: 19
        ))

        let values = posted.get()
        XCTAssertEqual(values.map { $0["action"] as? String }, [
            "choose_focus", "record_origin", "add_growth_stage",
            "record_growth", "mark_healthy_adult", "accept_suggestion",
        ])
        XCTAssertEqual(values[0]["mode_key"] as? String, "vulnerable_child")
        XCTAssertEqual(values[1]["authored_by"] as? String, "user")
        XCTAssertEqual(values[1]["age"] as? Int, 9)
        XCTAssertEqual(values[1]["confidence"] as? String, "reported")
        XCTAssertEqual(values[2]["label"] as? String, "Ortaokul")
        XCTAssertEqual(values[3]["stage_id"] as? Int, 31)
        XCTAssertEqual(values[3]["now_response"] as? String, "Yardım istiyorum")
        XCTAssertEqual(values[4]["evidence"] as? String, "Bugün gerçekçi bir sınır koydum.")
        XCTAssertEqual(values[5]["suggestion_id"] as? Int, 19)
        XCTAssertNil(values[5]["path_id"])
    }

    func testSchemaTurnMutationsSendOnlyExplicitModeMessageAndHistoryScope() async throws {
        let posted = StructuredTherapyLockedBox<[[String: Any]]>([])
        StructuredTherapyStubURLProtocol.install { request in
            let path = try XCTUnwrap(request.url?.path)
            if path == "/" { return (200, Data("ok".utf8)) }
            XCTAssertEqual(path, "/api/schema-path")
            var values = posted.get()
            values.append(try structuredTherapyBody(request))
            posted.set(values)
            return (200, Data(#"{"ok":true,"processing":false}"#.utf8))
        }

        let client = try makeClient()
        _ = try await client.mutateSchemaTurnAnalysis(.init(
            action: .setMode,
            conversationID: 12,
            requestID: "schema-mode-0001",
            enabled: true,
            providerID: "lmstudio",
            modelID: "local-model"
        ))
        _ = try await client.mutateSchemaTurnAnalysis(.init(
            action: .analyzeTurn,
            conversationID: 12,
            requestID: "schema-turn-0001",
            userMessageID: 301,
            consent: true,
            providerID: "lmstudio",
            modelID: "local-model"
        ))
        _ = try await client.mutateSchemaTurnAnalysis(.init(
            action: .scanHistory,
            conversationID: 12,
            requestID: "schema-scan-0001",
            consent: true,
            providerID: "lmstudio",
            modelID: "local-model"
        ))

        let values = posted.get()
        XCTAssertEqual(values.count, 3)
        XCTAssertEqual(Set(values[0].keys), Set([
            "action", "conv_id", "request_id", "enabled",
            "provider_id", "model_id",
        ]))
        XCTAssertEqual(values[0]["action"] as? String, "set_mode")
        XCTAssertEqual(values[0]["enabled"] as? Bool, true)
        XCTAssertEqual(Set(values[1].keys), Set([
            "action", "conv_id", "request_id", "user_message_id",
            "consent", "provider_id", "model_id",
        ]))
        XCTAssertEqual(values[1]["user_message_id"] as? Int, 301)
        XCTAssertEqual(values[1]["consent"] as? Bool, true)
        XCTAssertEqual(Set(values[2].keys), Set([
            "action", "conv_id", "request_id", "consent",
            "provider_id", "model_id",
        ]))
        XCTAssertEqual(values[2]["consent"] as? Bool, true)
        XCTAssertEqual(values[2]["provider_id"] as? String, "lmstudio")
        XCTAssertEqual(values[2]["model_id"] as? String, "local-model")
    }

    func testSchemaModeKeepsSyncedPreferenceSeparateFromThisDeviceConsent() async throws {
        StructuredTherapyStubURLProtocol.install { request in
            if request.url?.path == "/" { return (200, Data("ok".utf8)) }
            return (200, Data(#"""
            {
              "version":1,"active_path":null,"candidates":[],
              "queued_candidates":[],"queued_count":0,"active_path_notice":"",
              "methods":[],"notices":[],"allowed_actions":["set_mode"],
              "completed_turns":0,"minimum_listening_turns":3,
              "schema_mode":{
                "enabled":false,"preference_enabled":true,
                "pending_device_confirmation":true,
                "pending_provider_confirmation":false,
                "can_enable":true,"reason":"device_confirmation_required",
                "updated":"2026-08-17 21:00:00"
              },
              "turn_analysis":null
            }
            """#.utf8))
        }

        let snapshot = try await makeClient().schemaPath(conversationID: 12)
        let mode = try XCTUnwrap(snapshot.schemaMode)
        XCTAssertFalse(mode.enabled)
        XCTAssertTrue(mode.preferenceEnabled)
        XCTAssertTrue(mode.pendingDeviceConfirmation)
        XCTAssertFalse(mode.pendingProviderConfirmation)
        XCTAssertEqual(mode.reason, "device_confirmation_required")
    }

    func testSchemaProviderConsentBoundariesFailBeforeNetwork() async throws {
        let schemaPosts = StructuredTherapyLockedBox<Int>(0)
        StructuredTherapyStubURLProtocol.install { request in
            if request.url?.path == "/api/schema-path" {
                schemaPosts.set(schemaPosts.get() + 1)
            }
            return (200, Data("ok".utf8))
        }
        let client = try makeClient()

        do {
            _ = try await client.mutateSchemaTurnAnalysis(.init(
                action: .setMode,
                conversationID: 12,
                requestID: "schema-mode-unpinned-0001",
                enabled: true
            ))
            XCTFail("Sağlayıcısız cihaz onayı ağa çıkmamalı.")
        } catch let error as DivanAPIError {
            XCTAssertEqual(error.errorCode, "invalid_request")
        }
        do {
            _ = try await client.mutateSchemaTurnAnalysis(.init(
                action: .analyzeTurn,
                conversationID: 12,
                requestID: "schema-turn-unconfirmed-0001",
                userMessageID: 301,
                providerID: "lmstudio",
                modelID: "local-model"
            ))
            XCTFail("Tek geçmiş tur açık onaysız ağa çıkmamalı.")
        } catch let error as DivanAPIError {
            XCTAssertEqual(error.errorCode, "invalid_request")
        }
        XCTAssertEqual(schemaPosts.get(), 0)
    }

    func testSchemaV4CardMutationPostsExactRevisionSourceAndTransferFields() async throws {
        let posted = StructuredTherapyLockedBox<[String: Any]>([:])
        StructuredTherapyStubURLProtocol.install { request in
            if request.url?.path == "/" { return (200, Data("ok".utf8)) }
            posted.set(try structuredTherapyBody(request))
            return (200, Self.schemaV4MutationResponse)
        }
        let client = try makeClient()
        let result = try await client.mutateSchemaCard(.init(
            action: .recordPresentTransfer,
            conversationID: 1,
            requestID: "schema-v4-transfer-0001",
            pathID: 9,
            pathPublicID: "33333333333333333333333333333333",
            expectedRevision: 21,
            sourceUserMessageID: 131,
            sourceAssistantMessageID: 132,
            values: [
                "trigger_source_user_message_id": .number(101),
                "trigger_source_assistant_message_id": .number(102),
                "trigger": .string("Konuşma gerildiğinde"),
                "healthy_adult_response": .string("Bir an durabilirim."),
                "planned_action": .string("Sınırımı söylemek"),
                "support_choice": .string("Ara vermek"),
                "predicted_result": .string("Seçim alanım olur."),
            ]
        ))

        XCTAssertEqual(result.version, 4)
        XCTAssertTrue(try XCTUnwrap(result.presentTransfer).recorded)
        XCTAssertEqual(
            result.snapshot.presentTransfer?.plannedAction,
            "Sınırımı söylemek"
        )
        let body = posted.get()
        XCTAssertEqual(body["action"] as? String, "record_present_transfer")
        XCTAssertEqual(body["path_id"] as? Int, 9)
        XCTAssertEqual(body["expected_revision"] as? Int, 21)
        XCTAssertEqual(body["source_user_message_id"] as? Int, 131)
        XCTAssertEqual(body["source_assistant_message_id"] as? Int, 132)
        XCTAssertEqual(
            body["trigger_source_assistant_message_id"] as? Int,
            102
        )
        XCTAssertEqual(body["planned_action"] as? String, "Sınırımı söylemek")
        XCTAssertNil(body["action_text"])
        XCTAssertNil(body["provider_id"])
        XCTAssertNil(body["model_id"])
    }

    func testSchemaV4PrepathStartPinsProtocolAndFlowVersionWithoutPathID() async throws {
        let posted = StructuredTherapyLockedBox<[String: Any]>([:])
        StructuredTherapyStubURLProtocol.install { request in
            if request.url?.path == "/" { return (200, Data("ok".utf8)) }
            posted.set(try structuredTherapyBody(request))
            return (200, Self.schemaV4MutationResponse)
        }
        _ = try await makeClient().mutateSchemaPath(.init(
            action: .start,
            conversationID: 1,
            requestID: "schema-v4-prepath-start-0001",
            schemaProtocol: "schema_path_chat_v4",
            flowVersion: 4,
            claimID: 41
        ))

        let body = posted.get()
        XCTAssertEqual(body["action"] as? String, "start")
        XCTAssertEqual(body["claim_id"] as? Int, 41)
        XCTAssertEqual(body["protocol"] as? String, "schema_path_chat_v4")
        XCTAssertEqual(body["flow_version"] as? Int, 4)
        XCTAssertNil(body["path_id"])
        XCTAssertNil(body["expected_revision"])
    }

    func testSchemaV4TechniqueCheckpointBindsStepClientEventAndBothRevisions() async throws {
        let posted = StructuredTherapyLockedBox<[String: Any]>([:])
        StructuredTherapyStubURLProtocol.install { request in
            if request.url?.path == "/" { return (200, Data("ok".utf8)) }
            posted.set(try structuredTherapyBody(request))
            return (200, Self.schemaV4MutationResponse)
        }
        _ = try await makeClient().mutateSchemaCard(.init(
            action: .submitChatTechnique,
            conversationID: 1,
            requestID: "schema-technique-step-0001",
            pathID: 9,
            pathPublicID: "33333333333333333333333333333333",
            expectedRevision: 12,
            stepID: "imagery_work",
            clientEventID: "schema-technique-event-0001",
            expectedTechniqueRevision: 3,
            values: [
                "technique_link_id": .number(5),
                "intensity": .number(4),
                "step_data": .object(["choice": .string("continue")]),
            ]
        ))

        let body = posted.get()
        XCTAssertEqual(body["step_id"] as? String, "imagery_work")
        XCTAssertEqual(body["client_event_id"] as? String, "schema-technique-event-0001")
        XCTAssertEqual(body["expected_revision"] as? Int, 12)
        XCTAssertEqual(body["expected_technique_revision"] as? Int, 3)
        XCTAssertEqual(body["technique_link_id"] as? Int, 5)
        XCTAssertNotNil(body["step_data"] as? [String: Any])
    }

    func testSchemaV4GroundingCompletionPostsExplicitSafetyFields() async throws {
        let posted = StructuredTherapyLockedBox<[String: Any]>([:])
        StructuredTherapyStubURLProtocol.install { request in
            if request.url?.path == "/" { return (200, Data("ok".utf8)) }
            posted.set(try structuredTherapyBody(request))
            return (200, Self.schemaV4MutationResponse)
        }
        _ = try await makeClient().mutateSchemaCard(.init(
            action: .completeChatTechnique,
            conversationID: 1,
            requestID: "schema-technique-complete-0001",
            pathID: 9,
            pathPublicID: "33333333333333333333333333333333",
            expectedRevision: 12,
            stepID: "imagery_work",
            clientEventID: "schema-technique-complete-event-0001",
            expectedTechniqueRevision: 3,
            values: [
                "technique_link_id": .number(5),
                "grounding_confirmed": .bool(true),
                "orientation_ok": .bool(true),
                "reality_clear": .bool(true),
                "intensity": .number(2),
            ]
        ))

        let body = posted.get()
        XCTAssertEqual(body["action"] as? String, "complete_chat_technique")
        XCTAssertEqual(body["grounding_confirmed"] as? Bool, true)
        XCTAssertEqual(body["orientation_ok"] as? Bool, true)
        XCTAssertEqual(body["reality_clear"] as? Bool, true)
        XCTAssertEqual(body["intensity"] as? Int, 2)
    }

    func testSchemaV4ChatOnlyGroundControlPreservesCurrentClinicalValues() async throws {
        let posted = StructuredTherapyLockedBox<[String: Any]>([:])
        StructuredTherapyStubURLProtocol.install { request in
            if request.url?.path == "/" { return (200, Data("ok".utf8)) }
            posted.set(try structuredTherapyBody(request))
            return (200, Self.schemaV4MutationResponse)
        }
        _ = try await makeClient().mutateSchemaCard(.init(
            action: .groundChatTechnique,
            conversationID: 1,
            requestID: "schema-technique-ground-control-0001",
            pathID: 9,
            pathPublicID: "33333333333333333333333333333333",
            expectedRevision: 12,
            stepID: "imagery_work",
            expectedTechniqueRevision: 3,
            values: [
                "technique_link_id": .number(5),
                "technique_link_public_id": .string(
                    "55555555555555555555555555555555"
                ),
                "control_only": .bool(true),
            ]
        ))

        let body = posted.get()
        XCTAssertEqual(body["action"] as? String, "ground_chat_technique")
        XCTAssertEqual(body["path_id"] as? Int, 9)
        XCTAssertEqual(
            body["path_public_id"] as? String,
            "33333333333333333333333333333333"
        )
        XCTAssertEqual(body["expected_revision"] as? Int, 12)
        XCTAssertEqual(body["control_only"] as? Bool, true)
        XCTAssertEqual(body["technique_link_id"] as? Int, 5)
        XCTAssertEqual(
            body["technique_link_public_id"] as? String,
            "55555555555555555555555555555555"
        )
        XCTAssertNil(body["intensity"])
        XCTAssertNil(body["orientation_ok"])
        XCTAssertNil(body["reality_clear"])
    }

    func testSchemaV4DirectControlsRejectForgedOrIncompletePayloadsBeforeNetwork()
        async throws {
        let postCount = StructuredTherapyLockedBox(0)
        StructuredTherapyStubURLProtocol.install { request in
            if request.url?.path == "/api/schema-path" {
                postCount.set(postCount.get() + 1)
            }
            return (200, Self.schemaV4MutationResponse)
        }
        let client = try makeClient()
        let mutations = [
            SchemaCardMutation(
                action: .pause,
                conversationID: 1,
                requestID: "schema-forged-pause-0001",
                pathID: 9,
                pathPublicID: "33333333333333333333333333333333",
                expectedRevision: 12,
                values: ["note": .string("forged")]
            ),
            SchemaCardMutation(
                action: .groundChatTechnique,
                conversationID: 1,
                requestID: "schema-missing-ground-0001",
                pathID: 9,
                pathPublicID: "33333333333333333333333333333333",
                expectedRevision: 12,
                stepID: "imagery_work",
                expectedTechniqueRevision: 3,
                values: [
                    "technique_link_id": .number(5),
                    "technique_link_public_id":
                        .string("55555555555555555555555555555555"),
                ]
            ),
        ]
        for mutation in mutations {
            do {
                _ = try await client.mutateSchemaCard(mutation)
                XCTFail("Sahte doğrudan kontrol ağa çıkmamalı.")
            } catch let error as DivanAPIError {
                XCTAssertEqual(error.errorCode, "invalid_request")
            }
        }
        XCTAssertEqual(postCount.get(), 0)
    }

    func testSchemaV4TransitionAndFlatPrecheckFieldsRemainServerOwned() async throws {
        let posts = StructuredTherapyLockedBox<[[String: Any]]>([])
        StructuredTherapyStubURLProtocol.install { request in
            if request.url?.path == "/" { return (200, Data("ok".utf8)) }
            posts.set(posts.get() + [try structuredTherapyBody(request)])
            return (200, Self.schemaV4MutationResponse)
        }
        let client = try makeClient()
        _ = try await client.mutateSchemaCard(.init(
            action: .rateCurrentSituation,
            conversationID: 1,
            requestID: "schema-transition-only-0001",
            pathID: 9,
            pathPublicID: "33333333333333333333333333333333",
            expectedRevision: 7,
            values: [
                "candidate_queue_id": .number(41),
                "transition_only": .bool(true),
            ]
        ))
        _ = try await client.mutateSchemaCard(.init(
            action: .startChatTechnique,
            conversationID: 1,
            requestID: "schema-flat-precheck-0001",
            pathID: 9,
            pathPublicID: "33333333333333333333333333333333",
            expectedRevision: 8,
            stepID: "imagery_precheck",
            values: [
                "method_id": .string("young:method:imagery-rescripting"),
                "orientation_confirmed": .bool(true),
                "reality_clear": .bool(true),
                "sleep_activation_clear": .bool(true),
                "intensity": .number(4),
                "support_available": .bool(true),
                "stop_signal": .string("DUR"),
            ]
        ))

        let bodies = posts.get()
        XCTAssertEqual(bodies.count, 2)
        XCTAssertEqual(bodies[0]["transition_only"] as? Bool, true)
        XCTAssertEqual(bodies[1]["step_id"] as? String, "imagery_precheck")
        XCTAssertEqual(bodies[1]["orientation_confirmed"] as? Bool, true)
        XCTAssertEqual(bodies[1]["reality_clear"] as? Bool, true)
        XCTAssertEqual(bodies[1]["sleep_activation_clear"] as? Bool, true)
        XCTAssertEqual(bodies[1]["intensity"] as? Int, 4)
        XCTAssertEqual(bodies[1]["support_available"] as? Bool, true)
        XCTAssertEqual(bodies[1]["stop_signal"] as? String, "DUR")
        XCTAssertNil(bodies[1]["precheck"])
    }

    func testSchemaV4FlatPracticeUsesNonCollidingPracticeActionField() async throws {
        let posted = StructuredTherapyLockedBox<[String: Any]>([:])
        StructuredTherapyStubURLProtocol.install { request in
            if request.url?.path == "/" { return (200, Data("ok".utf8)) }
            posted.set(try structuredTherapyBody(request))
            return (200, Self.schemaV4MutationResponse)
        }
        _ = try await makeClient().mutateSchemaCard(.init(
            action: .assignPractice,
            conversationID: 1,
            requestID: "schema-flat-practice-0001",
            pathID: 9,
            pathPublicID: "33333333333333333333333333333333",
            expectedRevision: 30,
            values: [
                "variable": .string("Yanıt vermeden önce durmak"),
                "constant": .string("Aynı konuşma bağlamı"),
                "prediction": .string("Yük bir puan azalır"),
                "practice_action": .string("Bir nefeslik ara"),
                "observable_result": .string("Yanıtımı seçebilirim"),
                "tiny_version": .string("Yalnız ayaklarımı hisset"),
                "target_per_week": .number(2),
                "user_confirmed": .bool(true),
            ]
        ))

        let body = posted.get()
        XCTAssertEqual(body["action"] as? String, "assign_practice")
        XCTAssertEqual(body["practice_action"] as? String, "Bir nefeslik ara")
        XCTAssertEqual(body["target_per_week"] as? Int, 2)
        XCTAssertNil(body["experiment"])
    }

    func testSchemaV4ProtectedBindingsCannotBeOverriddenByCardPayload() async throws {
        let postCount = StructuredTherapyLockedBox(0)
        StructuredTherapyStubURLProtocol.install { request in
            if request.url?.path == "/api/schema-path" {
                postCount.set(postCount.get() + 1)
            }
            return (200, Self.schemaV4MutationResponse)
        }
        do {
            _ = try await makeClient().mutateSchemaCard(.init(
                action: .rejectCandidate,
                conversationID: 1,
                requestID: "schema-protected-0001",
                pathID: 9,
                expectedRevision: 7,
                values: [
                    "path_id": .number(999),
                    "candidate_queue_id": .number(41),
                ]
            ))
            XCTFail("Kart payload'ı path bağını değiştirememeli.")
        } catch let error as DivanAPIError {
            XCTAssertEqual(error.errorCode, "invalid_request")
        }
        XCTAssertEqual(postCount.get(), 0)
    }

    func testSchemaV4PathlessMapMutationUsesGenerationAndExactSourcePair() async throws {
        let posted = StructuredTherapyLockedBox<[String: Any]>([:])
        StructuredTherapyStubURLProtocol.install { request in
            if request.url?.path == "/" { return (200, Data("ok".utf8)) }
            posted.set(try structuredTherapyBody(request))
            return (200, Self.schemaV4MutationResponse)
        }

        _ = try await makeClient().mutateSchemaCard(.init(
            action: .editMapUpdate,
            conversationID: 1,
            requestID: "schema-pathless-map-edit-0001",
            pathID: nil,
            expectedRevision: nil,
            sourceUserMessageID: 101,
            sourceAssistantMessageID: 102,
            values: [
                "meta_event_id": .number(51),
                "meta_event_public_id": .string(
                    "22222222222222222222222222222222"
                ),
                "clinical_generation": .number(2),
                "note": .string("Gerilimde geri çekilme döngüsü"),
            ]
        ))

        let body = posted.get()
        XCTAssertEqual(body["action"] as? String, "edit_map_update")
        XCTAssertEqual(body["meta_event_id"] as? Int, 51)
        XCTAssertEqual(
            body["meta_event_public_id"] as? String,
            "22222222222222222222222222222222"
        )
        XCTAssertEqual(body["clinical_generation"] as? Int, 2)
        XCTAssertEqual(body["source_user_message_id"] as? Int, 101)
        XCTAssertEqual(body["source_assistant_message_id"] as? Int, 102)
        XCTAssertNil(body["path_id"])
        XCTAssertNil(body["expected_revision"])
        XCTAssertNil(body["public_meta_event_id"])
    }

    func testSchemaClinicalSyncIsIndependentExplicitAndHasNoProviderFields() async throws {
        let posted = StructuredTherapyLockedBox<[String: Any]>([:])
        StructuredTherapyStubURLProtocol.install { request in
            if request.url?.path == "/" { return (200, Data("ok".utf8)) }
            posted.set(try structuredTherapyBody(request))
            return (200, Self.schemaV4MutationResponse)
        }
        let result = try await makeClient().mutateSchemaClinicalSync(.init(
            conversationID: 1,
            requestID: "schema-sync-enable-0001",
            enabled: true,
            confirmed: true
        ))
        XCTAssertTrue(try XCTUnwrap(result.clinicalSync).enabled)
        XCTAssertEqual(Set(posted.get().keys), Set([
            "action", "conv_id", "enabled", "confirmed", "request_id",
        ]))
        XCTAssertEqual(posted.get()["action"] as? String, "set_clinical_sync")
        XCTAssertEqual(posted.get()["confirmed"] as? Bool, true)
        XCTAssertNil(posted.get()["provider_id"])
        XCTAssertNil(posted.get()["expected_revision"])
    }

    private func makeClient() throws -> APIClient {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [StructuredTherapyStubURLProtocol.self]
        return try APIClient(
            baseURL: XCTUnwrap(URL(string: "http://127.0.0.1:54321/")),
            sessionToken: String(repeating: "a", count: 64),
            session: URLSession(configuration: configuration)
        )
    }

    private static let adhdTUSActiveResponse = Data(adhdTUSActiveJSON.utf8)
    private static let adhdTUSActiveJSON = #"""
    {
      "protocol":"adhd_tus_planner_v1","conv_id":12,"revision":8,
      "enabled":true,"state":"active",
      "history":[
        {"question_id":"activity","question":"Bugün nasıl çalışalım?","answer_id":"mixed","answer":"Karma ilerleyelim"},
        {"question_id":"lesson","question":"Hangi ders?","answer_id":"farmakoloji","answer":"Farmakoloji"},
        {"question_id":"reading_area","question":"Hangi kaynak ve konuyu okuyalım?","answer_id":"farma-okuma","answer":"Otonom sinir sistemi · TümTUS Cümle"},
        {"question_id":"question_area","question":"Hangi alandan soru çözelim?","answer_id":"farma-soru","answer":"Otonom sinir sistemi · TümTUS Soru"},
        {"question_id":"available_time","question":"Bugün kaç dakikan var?","answer_id":"15","answer":"15 dakika"},
        {"question_id":"start_friction","question":"Başlamak bugün nasıl geliyor?","answer_id":"hard","answer":"Başlamak zor"}
      ],
      "question":null,
      "plan":{
        "id":"11111111111111111111111111111111",
        "title":"Farmakoloji · 15 dakikalık karma tur",
        "summary":"Kısa okuma, hatırlama ve aynı dersten soru turu.",
        "status":"active","activity":"mixed",
        "lesson":{"key":"farmakoloji","name":"Farmakoloji"},
        "reading_area":{"key":"farma-okuma","name":"Otonom sinir sistemi","source":"TümTUS Cümle","available_count":120,"unit":"cümle"},
        "question_area":{"key":"farma-soru","name":"Otonom sinir sistemi","source":"TümTUS Soru","available_count":40,"unit":"soru"},
        "available_minutes":15,"start_friction":"hard",
        "progress":{"completed":1,"total":5},
        "current_step":{"id":"22222222222222222222222222222222","title":"Kısa okuma","detail":"Otonom sinir sistemi alanından 4 cümle oku.","kind":"reading","duration_minutes":4,"quantity":4,"unit":"cümle","status":"active","visible":true,"collapsed":false},
        "steps":[
          {"id":"33333333333333333333333333333333","title":"Yalnız başlangıcı aç","detail":"Kaynağı aç.","kind":"setup","duration_minutes":1,"quantity":1,"unit":"başlangıç","status":"completed","visible":false,"collapsed":true},
          {"id":"22222222222222222222222222222222","title":"Kısa okuma","detail":"Otonom sinir sistemi alanından 4 cümle oku.","kind":"reading","duration_minutes":4,"quantity":4,"unit":"cümle","status":"active","visible":true,"collapsed":false},
          {"id":"44444444444444444444444444444444","title":"Bakmadan hatırla","detail":null,"kind":"recall","duration_minutes":2,"quantity":null,"unit":null,"status":"pending","visible":false,"collapsed":true},
          {"id":"55555555555555555555555555555555","title":"Küçük soru bloğu","detail":"Otonom sinir sistemi alanından 3 soru çöz.","kind":"questions","duration_minutes":7,"quantity":3,"unit":"soru","status":"pending","visible":false,"collapsed":true},
          {"id":"66666666666666666666666666666666","title":"Kaldığın yeri bırak","detail":"Kaldığın yeri kaydet.","kind":"close","duration_minutes":1,"quantity":1,"unit":"kayıt","status":"pending","visible":false,"collapsed":true}
        ]
      },
      "allowed_actions":["complete_step","pause","finish","cancel","set_mode"],
      "catalog":{"available":true,"error_code":null,
        "fingerprint":"sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "lessons":12,"question_areas":707,"reading_areas":480,
        "question_count":11438,"tus_default_question_count":10900,"sentence_count":39100},
      "catalog_changed":false,
      "notices":{"no_streak":"Seri tutulmaz.","no_debt":"Borç yazılmaz.","local_only":"Yalnız bu cihazda.","content_boundary":"Yalnız metadata kullanılır."},
      "safety_hold":false
    }
    """#

    private static let adhdTUSAnswerResponse = Data(adhdTUSAnswerJSON.utf8)
    private static let adhdTUSAnswerJSON = #"""
    {
      "protocol":"adhd_tus_planner_v1","conv_id":12,"revision":4,
      "enabled":true,"state":"question",
      "history":[{"question_id":"activity","question":"Bugün nasıl çalışalım?","answer_id":"questions","answer":"Soru çözelim"}],
      "question":{"id":"lesson","prompt":"Hangi ders?","options":[{"id":"farmakoloji","label":"Farmakoloji","description":null}],"total_options":1,"filterable":true,"has_more":false},
      "plan":null,"allowed_actions":["answer","restart","set_mode"],
      "catalog":{"available":true,"error_code":null,
        "fingerprint":"sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "lessons":12,"question_areas":707,"reading_areas":480,
        "question_count":11438,"tus_default_question_count":10900,"sentence_count":39100},
      "catalog_changed":false,"notices":{},"safety_hold":false,
      "ok":true,"duplicate":false,"action":"answer"
    }
    """#

    private static let schemaMutationResponse = Data(#"""
    {
      "ok":true,"version":1,"active_path":null,
      "candidates":[],"methods":[],"notices":[],"allowed_actions":[],
      "completed_turns":3,"minimum_listening_turns":3
    }
    """#.utf8)

    private static let schemaV4MutationResponse = Data(#"""
    {
      "ok":true,"duplicate":false,
      "protocol":"schema_path_chat_v4","version":4,
      "stage":"listen","step":"candidate_review","revision":7,
      "progress":{"stage_number":1,"stage_total":3,"step_number":2,"step_total":5,"label":"Odak seçimi"},
      "next_card":null,"message_meta":[],
      "interaction_policy":{"requires_in_app":false,"remote_reply_allowed":true,"composer_binding_required":false,"bound_step_id":"","reason":"none"},
      "resume_state":{"required":false,"reason":"none","stage":"listen","step":"candidate_review","card_id":null},
      "clinical_sync":{"enabled":true,"can_enable":true,"reason":"enabled","notice":"Eşitleniyor."},
      "present_transfer":{"recorded":true,"id":81,"public_id":"77777777777777777777777777777777","source_user_message_id":131,"source_user_message_public_id":"eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee","source_assistant_message_id":132,"source_assistant_message_public_id":"ffffffffffffffffffffffffffffffff","trigger_source_user_message_id":101,"trigger_source_user_message_public_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","trigger_source_assistant_message_id":102,"trigger_source_assistant_message_public_id":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","trigger":"Konuşma gerildiğinde","healthy_adult_response":"Bir an durabilirim.","planned_action":"Sınırımı söylemek","support_choice":"Ara vermek","predicted_result":"Seçim alanım olur.","observed_result":""},
      "active_path":null,"candidates":[],"queued_candidates":[],"queued_count":0,
      "active_path_notice":"","methods":[],"notices":[],"allowed_actions":[],
      "completed_turns":3,"minimum_listening_turns":1
    }
    """#.utf8)
}

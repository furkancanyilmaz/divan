import Foundation
import XCTest
@testable import DivanNative

private final class AdvancedStubURLProtocol: URLProtocol {
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

private final class AdvancedLockedBox<Value>: @unchecked Sendable {
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

private func advancedBody(_ request: URLRequest) throws -> [String: Any] {
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
            if count > 0 { bytes.append(buffer, count: count) }
            else if count == 0 { break }
            else { throw stream.streamError ?? URLError(.cannotDecodeRawData) }
        }
        data = bytes
    } else {
        throw URLError(.cannotDecodeRawData)
    }
    return try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
}

final class AdvancedAPIClientTests: XCTestCase {
    override func tearDown() {
        AdvancedStubURLProtocol.clear()
        super.tearDown()
    }

    func testTechniqueCatalogPreservesDynamicChairAndReparentingProtocols() async throws {
        AdvancedStubURLProtocol.install { request in
            let url = try XCTUnwrap(request.url)
            if url.path == "/" { return (200, Data("ok".utf8)) }
            XCTAssertEqual(url.path, "/api/methods")
            let components = URLComponents(url: url, resolvingAgainstBaseURL: false)
            XCTAssertEqual(
                components?.queryItems?.first(where: { $0.name == "therapist" })?.value,
                "young"
            )
            XCTAssertEqual(
                components?.queryItems?.first(where: { $0.name == "conv_id" })?.value,
                "12"
            )
            return (200, Data(#"""
            {
              "intensity_limit":7,"safety_hold":false,
              "methods":[
                {"id":1,"key":"young:mode-chairs","node_id":"schema_mode_chairs","name":"Mod sandalyeleri","interaction_mode":"chair_work","requires_consent":true,
                 "chair_config":{"protocol":"schema_mode_chairs","protocol_version":2,"title":"Modlar","frame":"Çerçeve","allow_add":true,"min_participants":2,"max_participants":6,
                   "stages":[{"id":"map","label":"Harita","preferred_slots":["vulnerable_child"]}],
                   "participant_meta":{"vulnerable_child":{"purpose":"İhtiyaç","starter":"Şu an..."}},
                   "default_participants":[{"slot_key":"vulnerable_child","label":"Kırılgan Çocuk"},{"slot_key":"healthy_adult","label":"Sağlıklı Yetişkin"}]},
                 "process_tags":["modes"],"processes":[],"recommended":true},
                {"id":2,"key":"young:snrl-yeniden-ebeveynlik","node_id":"limited_reparenting","name":"Sınırlı yeniden ebeveynlik","interaction_mode":"imagery_work",
                 "imagery_config":{"protocol":"healthy_adult_reparenting","protocol_version":1,"title":"Yeniden ebeveynlik","frame":"Gerçek anı üretmez","stages":[{"id":"orientation","label":"Yönelim"}]}}
              ]
            }
            """#.utf8))
        }
        let client = try makeAdvancedClient()
        let catalog = try await client.techniqueCatalog(
            therapistID: "young", conversationID: 12
        )
        XCTAssertEqual(catalog.intensityLimit, 7)
        XCTAssertEqual(catalog.methods.count, 2)
        XCTAssertEqual(catalog.methods[0].chairConfiguration?.maximumParticipants, 6)
        XCTAssertEqual(catalog.methods[0].chairConfiguration?.defaultParticipants.count, 2)
        XCTAssertTrue(catalog.methods[1].isLimitedReparenting)
    }

    func testTechniqueConsentRequiresAndForwardsExplicitUserConfirmation() async throws {
        let client = try makeAdvancedClient()
        do {
            _ = try await client.mutateTechniqueRun(TechniqueRunMutation(
                conversationID: 12,
                action: .consent,
                runID: 4
            ))
            XCTFail("Consent without the user's current confirmation must fail.")
        } catch let error as DivanAPIError {
            XCTAssertEqual(error.errorCode, "invalid_request")
        }

        let posted = AdvancedLockedBox<[String: Any]>([:])
        AdvancedStubURLProtocol.install { request in
            let path = try XCTUnwrap(request.url?.path)
            if path == "/" { return (200, Data("ok".utf8)) }
            XCTAssertEqual(path, "/api/technique-run")
            posted.set(try advancedBody(request))
            return (200, Data(#"{"ok":true,"run":{"id":4,"conv":12,"status":"active","phase":"prepare"},"chairworks":[]}"#.utf8))
        }
        _ = try await client.mutateTechniqueRun(TechniqueRunMutation(
            conversationID: 12,
            action: .consent,
            runID: 4,
            consentConfirmed: true
        ))
        XCTAssertEqual(posted.get()["confirmed"] as? Bool, true)
    }

    func testEnhancedExperientialPrecheckPersistsBoundedAggregateBeforeConsent() async throws {
        let posted = AdvancedLockedBox<[String: Any]>([:])
        AdvancedStubURLProtocol.install { request in
            let path = try XCTUnwrap(request.url?.path)
            if path == "/" { return (200, Data("ok".utf8)) }
            XCTAssertEqual(path, "/api/session-meta")
            posted.set(try advancedBody(request))
            return (200, Data(#"{"ok":true}"#.utf8))
        }
        let client = try makeAdvancedClient()
        try await client.recordExperientialPrecheck(
            conversationID: 12,
            intensity: 4,
            intensityLimit: 10
        )
        let body = posted.get()
        XCTAssertEqual(body["conv_id"] as? Int, 12)
        XCTAssertEqual(body["precheck_done"] as? Bool, true)
        XCTAssertEqual(body["safety_ok"] as? Bool, true)
        XCTAssertEqual(body["anxiety_start"] as? Int, 4)
        XCTAssertEqual(body["intensity_limit"] as? Int, 7)
    }

    func testChairBeginSendsExplicitFrameAndMapsDynamicParticipants() async throws {
        let posted = AdvancedLockedBox<[String: Any]>([:])
        AdvancedStubURLProtocol.install { request in
            let path = try XCTUnwrap(request.url?.path)
            if path == "/" { return (200, Data("ok".utf8)) }
            XCTAssertEqual(path, "/api/chair-work")
            posted.set(try advancedBody(request))
            return (200, Data(#"""
            {"ok":true,"chairwork":{"id":9,"conv_id":12,"technique_run_id":4,"protocol":"schema_mode_chairs","status":"dialogue","revision":2,
              "participants":[
                {"id":1,"slot_key":"vulnerable_child","label":"Kırılgan Çocuk"},
                {"id":2,"slot_key":"angry_child","label":"Öfkeli Çocuk"},
                {"id":3,"slot_key":"critical_parent","label":"Eleştirel Ebeveyn"},
                {"id":4,"slot_key":"healthy_adult","label":"Sağlıklı Yetişkin"}
              ],"capabilities":{"speak":true}}}
            """#.utf8))
        }
        let client = try makeAdvancedClient()
        let result = try await client.mutateChairWork(ChairWorkMutation(
            conversationID: 12,
            chairRunID: 9,
            action: .begin,
            expectedRevision: 1,
            orientationOK: true,
            frameOK: true,
            stopSignal: "dur",
            goalText: "İç sesleri ayırt etmek"
        ))
        XCTAssertEqual(result.chairWork.participants.count, 4)
        XCTAssertEqual(posted.get()["orientation_ok"] as? Bool, true)
        XCTAssertEqual(posted.get()["frame_ok"] as? Bool, true)
        XCTAssertEqual(posted.get()["stop_signal"] as? String, "dur")
        XCTAssertEqual(posted.get()["goal_text"] as? String, "İç sesleri ayırt etmek")
    }

    func testChairLifecycleCheckpointUsesUserConfirmationNoteAndIntensity() async throws {
        let posted = AdvancedLockedBox<[String: Any]>([:])
        AdvancedStubURLProtocol.install { request in
            let path = try XCTUnwrap(request.url?.path)
            if path == "/" { return (200, Data("ok".utf8)) }
            XCTAssertEqual(path, "/api/chair-work")
            posted.set(try advancedBody(request))
            return (200, Data(#"{"ok":true,"chairwork":{"id":9,"conv_id":12,"technique_run_id":4,"status":"grounding","phase":"grounding","revision":3}}"#.utf8))
        }
        let client = try makeAdvancedClient()
        _ = try await client.mutateChairWork(ChairWorkMutation(
            conversationID: 12,
            chairRunID: 9,
            action: .ground,
            expectedRevision: 2,
            orientationOK: true,
            checkpointConfirmed: true,
            checkpointNote: "Odayı ve ayaklarımı fark ettim.",
            intensity: 3
        ))
        XCTAssertEqual(posted.get()["checkpoint_confirmed"] as? Bool, true)
        XCTAssertEqual(posted.get()["orientation_ok"] as? Bool, true)
        XCTAssertEqual(posted.get()["checkpoint_note"] as? String,
                       "Odayı ve ayaklarımı fark ettim.")
        XCTAssertEqual(posted.get()["intensity"] as? Int, 3)
    }

    func testChairResumeRequiresFreshGroundingOrientationAndIntensityOnWire() async throws {
        let client = try makeAdvancedClient()
        let invalid = [
            ChairWorkMutation(
                conversationID: 12,
                chairRunID: 9,
                action: .resume,
                orientationOK: true,
                intensity: 3
            ),
            ChairWorkMutation(
                conversationID: 12,
                chairRunID: 9,
                action: .resume,
                checkpointConfirmed: true,
                intensity: 3
            ),
            ChairWorkMutation(
                conversationID: 12,
                chairRunID: 9,
                action: .resume,
                orientationOK: true,
                checkpointConfirmed: true
            ),
            ChairWorkMutation(
                conversationID: 12,
                chairRunID: 9,
                action: .resume,
                orientationOK: true,
                checkpointConfirmed: true,
                intensity: 8
            ),
        ]
        for mutation in invalid {
            do {
                _ = try await client.mutateChairWork(mutation)
                XCTFail("Resume must reject missing or unsafe fresh confirmation.")
            } catch let error as DivanAPIError {
                XCTAssertEqual(error.errorCode, "invalid_request")
            }
        }

        let posted = AdvancedLockedBox<[String: Any]>([:])
        AdvancedStubURLProtocol.install { request in
            let path = try XCTUnwrap(request.url?.path)
            if path == "/" { return (200, Data("ok".utf8)) }
            XCTAssertEqual(path, "/api/chair-work")
            posted.set(try advancedBody(request))
            return (200, Data(#"{"ok":true,"chairwork":{"id":9,"conv_id":12,"technique_run_id":4,"status":"dialogue","phase":"work","revision":4}}"#.utf8))
        }
        _ = try await client.mutateChairWork(ChairWorkMutation(
            conversationID: 12,
            chairRunID: 9,
            action: .resume,
            expectedRevision: 3,
            orientationOK: true,
            checkpointConfirmed: true,
            intensity: 3
        ))
        XCTAssertEqual(posted.get()["action"] as? String, "resume")
        XCTAssertEqual(posted.get()["checkpoint_confirmed"] as? Bool, true)
        XCTAssertEqual(posted.get()["orientation_ok"] as? Bool, true)
        XCTAssertEqual(posted.get()["intensity"] as? Int, 3)
    }

    func testChairLifecycleValidationNeverInventsCheckpointConsent() async throws {
        let client = try makeAdvancedClient()
        do {
            _ = try await client.mutateChairWork(ChairWorkMutation(
                conversationID: 12,
                chairRunID: 9,
                action: .ground,
                orientationOK: true,
                intensity: 3
            ))
            XCTFail("Grounding without explicit checkpoint consent must fail.")
        } catch let error as DivanAPIError {
            XCTAssertEqual(error.errorCode, "invalid_request")
        }
        do {
            _ = try await client.mutateChairWork(ChairWorkMutation(
                conversationID: 12,
                chairRunID: 9,
                action: .reflect,
                checkpointConfirmed: true,
                checkpointNote: "   "
            ))
            XCTFail("Reflection without a user note must fail.")
        } catch let error as DivanAPIError {
            XCTAssertEqual(error.errorCode, "invalid_request")
        }
        do {
            _ = try await client.mutateChairWork(ChairWorkMutation(
                conversationID: 12,
                chairRunID: 9,
                action: .complete
            ))
            XCTFail("Completion without explicit checkpoint consent must fail.")
        } catch let error as DivanAPIError {
            XCTAssertEqual(error.errorCode, "invalid_request")
        }

        // Emergency stop intentionally has no checkpoint requirements. This
        // assertion exercises local validation only; no fake consent is added.
        _ = ChairWorkMutation(
            conversationID: 12,
            chairRunID: 9,
            action: .stop
        )
    }

    func testImageryConsentRequiresAllConfirmationsAndUsesWireKeys() async throws {
        let posted = AdvancedLockedBox<[String: Any]>([:])
        AdvancedStubURLProtocol.install { request in
            let path = try XCTUnwrap(request.url?.path)
            if path == "/" { return (200, Data("ok".utf8)) }
            posted.set(try advancedBody(request))
            return (200, Data(#"""
            {"ok":true,"imagerywork":{"id":5,"conv_id":12,"technique_run_id":3,"protocol":"healthy_adult_reparenting","status":"ready","consented":true,"consent_complete":true,"stop_signal":"dur","revision":1}}
            """#.utf8))
        }
        let client = try makeAdvancedClient()
        do {
            _ = try await client.mutateImageryWork(ImageryWorkMutation(
                conversationID: 12, action: .consent,
                imageryRunID: 5, orientationOK: true, frameOK: false,
                realityClear: true, stopSignal: "dur"
            ))
            XCTFail("Eksik açık onay gönderilmemeliydi.")
        } catch let error as DivanAPIError {
            XCTAssertEqual(error.errorCode, "invalid_request")
        }
        let result = try await client.mutateImageryWork(ImageryWorkMutation(
            conversationID: 12, action: .consent,
            imageryRunID: 5, orientationOK: true, frameOK: true,
            realityClear: true, stopSignal: "dur", sceneBoundary: "bugün"
        ))
        XCTAssertTrue(result.imageryWork.consentComplete)
        XCTAssertEqual(posted.get()["reality_clear"] as? Bool, true)
        XCTAssertEqual(posted.get()["scene_boundary"] as? String, "bugün")
    }

    func testImageryChoicesDecodeTypedActionsAndUseStableIDs() async throws {
        AdvancedStubURLProtocol.install { request in
            let path = try XCTUnwrap(request.url?.path)
            if path == "/" { return (200, Data("ok".utf8)) }
            XCTAssertEqual(path, "/api/imagery-work")
            return (200, Data(#"""
            {"ok":true,"imagerywork":{"id":5,"conv_id":12,
              "technique_run_id":3,"status":"active","phase":"work",
              "choice_descriptors":[
                {"id":"present_trigger:1","title":"Şimdiye dön","action":"advance"},
                {"id":"present_trigger:3","title":"Şimdiye dön","action":"ground"},
                {"id":"present_trigger:4","title":"Burada bırak","action":"stop"}
              ]}}
            """#.utf8))
        }
        let client = try makeAdvancedClient()
        let fetchedWork = try await client.imageryWork(conversationID: 12)
        let work = try XCTUnwrap(fetchedWork)
        XCTAssertEqual(
            work.choiceDescriptors.map(\.action),
            [.advance, .ground, .stop]
        )
        XCTAssertEqual(
            CoreAdvancedWorkspaceDataSource.imageryChoiceAction(
                choiceID: "present_trigger:3",
                descriptors: work.choiceDescriptors
            ),
            .ground
        )
        XCTAssertEqual(
            CoreAdvancedWorkspaceDataSource.imageryChoiceAction(
                choiceID: "present_trigger:1",
                descriptors: work.choiceDescriptors
            ),
            .advance,
            "Display text must never decide whether a choice grounds."
        )
        XCTAssertNil(
            CoreAdvancedWorkspaceDataSource.imageryChoiceAction(
                choiceID: "Şimdiye dön",
                descriptors: work.choiceDescriptors
            )
        )
    }

    func testLivingMapSummaryReviewAndGenerationAreTyped() async throws {
        let reviewBody = AdvancedLockedBox<[String: Any]>([:])
        AdvancedStubURLProtocol.install { request in
            let path = try XCTUnwrap(request.url?.path)
            if path == "/" { return (200, Data("ok".utf8)) }
            if path == "/api/living-map" {
                return (200, Data(#"""
                {"version":3,"pending":[{"id":7,"public_id":"insight-7","artifact_type":"insight","title":"Geri çekilme","statement":"Eleştiriyle geri çekilme","status":"developing","evidence_count":2}],
                 "pending_evidence_reviews":[],"sections":{"cycles":[],"values_needs":[],"strengths_exceptions":[],"goals_helpful":[]},"private":[],"pending_formulations":[],"generation_runs":[],"counts":{"pending":1},"disclaimer":"Hipotezdir"}
                """#.utf8))
            }
            if path == "/api/living-map/review" {
                reviewBody.set(try advancedBody(request))
                return (200, Data(#"""
                {"ok":true,"claim":{"id":7,"public_id":"insight-7","artifact_type":"insight","title":"Düzeltilen başlık","statement":"Yeni ifade"},"evidence":[],"history":[],"review_outcome":"edited"}
                """#.utf8))
            }
            XCTAssertEqual(path, "/api/living-map/generate")
            return (200, Data(#"{"ok":true,"processing":true,"job_id":88,"conv_id":12}"#.utf8))
        }
        let client = try makeAdvancedClient()
        let map = try await client.livingMap()
        XCTAssertEqual(map.version, 3)
        XCTAssertEqual(map.pending.first?.publicID, "insight-7")
        let detail = try await client.reviewLivingMap(LivingMapReviewRequest(
            claimReference: "insight-7", action: .edit,
            edits: LivingMapClaimEdits(
                title: "Düzeltilen başlık", statement: "Yeni ifade"
            )
        ))
        XCTAssertEqual(detail.reviewOutcome, "edited")
        XCTAssertEqual(reviewBody.get()["claim_id"] as? String, "insight-7")
        XCTAssertEqual(reviewBody.get()["title"] as? String, "Düzeltilen başlık")
        let accepted = try await client.generateLivingMap(conversationID: 12)
        XCTAssertEqual(accepted.jobID, 88)
    }

    func testSyncInvitationIsValidatedAndJoinNameMakesImmediateApplyExplicit() async throws {
        let joinBody = AdvancedLockedBox<[String: Any]>([:])
        AdvancedStubURLProtocol.install { request in
            let path = try XCTUnwrap(request.url?.path)
            if path == "/" { return (200, Data("ok".utf8)) }
            if path == "/api/sync/start" {
                return (200, Data(#"{"pairing_code":"secret-pairing-payload","qr_matrix":{"size":3,"rows":["010","111","010"]},"seconds_remaining":119}"#.utf8))
            }
            XCTAssertEqual(path, "/api/sync/join")
            joinBody.set(try advancedBody(request))
            return (200, Data(#"{"ok":true,"summary":{"sent":4,"received":7,"conflicts":1,"clinical_confirmation_required":true},"exact_equal":false,"clinical_confirmation_required":true,"clinical_confirmation_device":"this_device","clinical_confirmation_message":"Şema çalışma kayıtlarını bu cihazda onaylayın.","pending_clinical_confirmation_conv_ids":[12],"pending_clinical_confirmation_count":1,"last_sync_at":"2026-08-11 12:00","conflict_rows":[{"id":2,"record_type":"conversation","title":"A","reason":"İki tarafta değişti"}]}"#.utf8))
        }
        let client = try makeAdvancedClient()
        let invitation = try await client.startDeviceSyncHost()
        XCTAssertEqual(invitation.qrMatrix.rows.count, 3)
        let result = try await client.pairAndApplyDeviceSync(
            code: invitation.pairingCode,
            deviceName: "Furkan'ın iPhone'u",
            platform: "ios"
        )
        XCTAssertEqual(result.summary.received, 7)
        XCTAssertEqual(result.conflicts.first?.id, 2)
        XCTAssertTrue(result.clinicalConfirmationRequired)
        XCTAssertEqual(result.clinicalConfirmationDevice, "this_device")
        XCTAssertEqual(
            result.pendingClinicalConfirmationConversationIDs,
            [12]
        )
        XCTAssertEqual(result.pendingClinicalConfirmationCount, 1)
        XCTAssertEqual(joinBody.get()["code"] as? String, "secret-pairing-payload")
        XCTAssertEqual(joinBody.get()["device_name"] as? String, "Furkan'ın iPhone'u")
    }

    func testSyncV6StatusDecodesLocalClinicalConfirmationWithoutGenericConflict() async throws {
        AdvancedStubURLProtocol.install { request in
            if request.url?.path == "/" { return (200, Data("ok".utf8)) }
            XCTAssertEqual(request.url?.path, "/api/sync/status")
            return (200, Data(#"{"host_running":false,"busy":false,"seconds_remaining":0,"last_sync_at":"2026-08-22 12:00:00","last_peer_name":"Android","last_summary":{"sent":3,"received":4,"conflicts":0,"clinical_confirmation_required":true},"conflicts":[],"pending_clinical_confirmation_conv_ids":[12,19],"pending_clinical_confirmation_count":2,"scope":[],"secrets_excluded":true}"#.utf8))
        }
        let status = try await makeAdvancedClient().deviceSyncStatus()
        XCTAssertTrue(status.lastSummary.clinicalConfirmationRequired)
        XCTAssertEqual(
            status.pendingClinicalConfirmationConversationIDs,
            [12, 19]
        )
        XCTAssertEqual(status.pendingClinicalConfirmationCount, 2)
        XCTAssertTrue(status.conflicts.isEmpty)
    }

    func testSyncV6JoinDecodesClinicalSafetyPauseSeparatelyFromConsent() async throws {
        AdvancedStubURLProtocol.install { request in
            if request.url?.path == "/" { return (200, Data("ok".utf8)) }
            XCTAssertEqual(request.url?.path, "/api/sync/join")
            return (200, Data(#"{"ok":true,"summary":{"sent":2,"received":3,"conflicts":0,"clinical_confirmation_required":false,"clinical_safety_pause":true},"exact_equal":false,"clinical_confirmation_required":false,"clinical_safety_pause":true,"clinical_safety_device":"this_device","clinical_safety_message":"Bu cihazdaki güvenlik beklemesi sürerken Şema kayıtları alınmadı.","pending_clinical_confirmation_conv_ids":[],"pending_clinical_confirmation_count":0,"last_sync_at":"2026-08-22 12:10","conflict_rows":[]}"#.utf8))
        }
        let result = try await makeAdvancedClient().pairAndApplyDeviceSync(
            code: "fresh-safety-pause",
            deviceName: "Mac",
            platform: "macos"
        )
        XCTAssertTrue(result.clinicalSafetyPause)
        XCTAssertEqual(result.clinicalSafetyDevice, "this_device")
        XCTAssertTrue(
            result.clinicalSafetyMessage?.contains("güvenlik beklemesi")
                == true
        )
        XCTAssertFalse(result.clinicalConfirmationRequired)
        XCTAssertTrue(
            result.pendingClinicalConfirmationConversationIDs.isEmpty
        )
    }

    func testSyncV6StatusRecoversClinicalSafetyPauseFromSummary() async throws {
        AdvancedStubURLProtocol.install { request in
            if request.url?.path == "/" { return (200, Data("ok".utf8)) }
            XCTAssertEqual(request.url?.path, "/api/sync/status")
            return (200, Data(#"{"host_running":false,"busy":false,"seconds_remaining":0,"last_sync_at":"2026-08-22 12:10:00","last_peer_name":"Android","last_summary":{"sent":2,"received":3,"conflicts":0,"clinical_confirmation_required":false,"clinical_safety_pause":true,"clinical_safety_device":"computer","clinical_safety_message":"Bilgisayardaki güvenlik beklemesi sürüyor."},"conflicts":[],"pending_clinical_confirmation_conv_ids":[],"pending_clinical_confirmation_count":0,"scope":[],"secrets_excluded":true}"#.utf8))
        }
        let status = try await makeAdvancedClient().deviceSyncStatus()
        XCTAssertTrue(status.clinicalSafetyPause)
        XCTAssertEqual(status.clinicalSafetyDevice, "computer")
        XCTAssertEqual(
            status.clinicalSafetyMessage,
            "Bilgisayardaki güvenlik beklemesi sürüyor."
        )
        XCTAssertFalse(status.lastSummary.clinicalConfirmationRequired)
        XCTAssertTrue(
            status.pendingClinicalConfirmationConversationIDs.isEmpty
        )
    }

    func testSyncRejectsMalformedQRMatrix() async throws {
        AdvancedStubURLProtocol.install { request in
            if request.url?.path == "/" { return (200, Data("ok".utf8)) }
            return (200, Data(#"{"pairing_code":"secret","qr_matrix":{"size":3,"rows":["01","111","010"]},"seconds_remaining":119}"#.utf8))
        }
        let client = try makeAdvancedClient()
        do {
            _ = try await client.startDeviceSyncHost()
            XCTFail("Bozuk QR matrisi kabul edilmemeliydi.")
        } catch let error as DivanAPIError {
            XCTAssertEqual(error.errorCode, "invalid_request")
            XCTAssertFalse(error.localizedDescription.contains("secret"))
        }
    }

    private func makeAdvancedClient() throws -> APIClient {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [AdvancedStubURLProtocol.self]
        return try APIClient(
            baseURL: XCTUnwrap(URL(string: "http://127.0.0.1:54321/")),
            sessionToken: String(repeating: "a", count: 64),
            session: URLSession(configuration: configuration)
        )
    }
}

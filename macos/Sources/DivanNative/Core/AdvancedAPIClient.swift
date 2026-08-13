import Foundation

// These endpoints intentionally live beside the basic chat client. They use
// the same authenticated, loopback-only URLSession and never expose the
// embedded-session token or pairing secret through logs.
public extension APIClient {
    func techniqueCatalog(
        therapistID: String,
        conversationID: Int? = nil
    ) async throws -> TechniqueCatalog {
        let therapist = try Self.validIdentifier(
            therapistID, field: "Usta", maximum: 64
        )
        if let conversationID { try Self.requirePositive(conversationID, "Sohbet") }
        var query = [URLQueryItem(name: "therapist", value: therapist)]
        if let conversationID {
            query.append(URLQueryItem(name: "conv_id", value: String(conversationID)))
        }
        let response: TechniqueCatalogWire = try await get(
            "/api/methods", query: query
        )
        return response.model
    }

    func techniqueRuns(conversationID: Int) async throws -> TechniqueRunsSnapshot {
        try Self.requirePositive(conversationID, "Sohbet")
        let response: TechniqueRunsWire = try await get(
            "/api/technique-runs",
            query: [URLQueryItem(name: "conv_id", value: String(conversationID))]
        )
        return response.model
    }

    func mutateTechniqueRun(
        _ mutation: TechniqueRunMutation
    ) async throws -> TechniqueRunMutationResult {
        try Self.validate(mutation)
        var body: [String: JSONValue] = [
            "conv_id": .number(Double(mutation.conversationID)),
            "action": .string(mutation.action.rawValue),
        ]
        Self.put(mutation.runID, key: "id", into: &body)
        Self.put(mutation.methodKey, key: "method_key", into: &body)
        Self.put(mutation.methodID, key: "method_id", into: &body)
        Self.put(mutation.intensity, key: "intensity", into: &body)
        Self.put(mutation.consentConfirmed, key: "confirmed", into: &body)
        Self.put(mutation.checkpointConfirmed, key: "checkpoint_confirmed", into: &body)
        Self.put(mutation.checkpointNote, key: "checkpoint_note", into: &body)
        let response: TechniqueMutationWire = try await post(
            "/api/technique-run", body: body
        )
        return response.model
    }

    func chairWork(
        conversationID: Int,
        chairRunID: Int? = nil,
        includeFullHistory: Bool = false
    ) async throws -> ChairWorkCollection {
        try Self.requirePositive(conversationID, "Sohbet")
        if let chairRunID { try Self.requirePositive(chairRunID, "Sandalye çalışması") }
        var query = [URLQueryItem(name: "conv_id", value: String(conversationID))]
        if let chairRunID {
            query.append(URLQueryItem(name: "chair_run_id", value: String(chairRunID)))
        }
        if includeFullHistory {
            query.append(URLQueryItem(name: "full", value: "1"))
        }
        let response: ChairCollectionWire = try await get(
            "/api/chair-work", query: query
        )
        return response.model
    }

    func mutateChairWork(
        _ mutation: ChairWorkMutation
    ) async throws -> ChairWorkMutationResult {
        try Self.validate(mutation)
        var body: [String: JSONValue] = [
            "conv_id": .number(Double(mutation.conversationID)),
            "action": .string(mutation.action.rawValue),
        ]
        Self.put(mutation.chairRunID, key: "chair_run_id", into: &body)
        Self.put(mutation.expectedRevision, key: "expected_revision", into: &body)
        Self.put(mutation.participantID, key: "participant_id", into: &body)
        Self.put(mutation.label, key: "label", into: &body)
        Self.put(mutation.feedback, key: "fit", into: &body)
        Self.put(mutation.guidanceTurnID, key: "guidance_turn_id", into: &body)
        Self.put(mutation.orientationOK, key: "orientation_ok", into: &body)
        Self.put(mutation.frameOK, key: "frame_ok", into: &body)
        Self.put(mutation.stopSignal, key: "stop_signal", into: &body)
        Self.put(mutation.goalText, key: "goal_text", into: &body)
        Self.put(mutation.checkpointConfirmed, key: "checkpoint_confirmed", into: &body)
        Self.put(mutation.checkpointNote, key: "checkpoint_note", into: &body)
        Self.put(mutation.intensity, key: "intensity", into: &body)
        let response: ChairMutationWire = try await post(
            "/api/chair-work", body: body
        )
        return response.model
    }

    func addChairTurn(_ input: ChairTurnInput) async throws -> ChairTurnResult {
        try Self.requirePositive(input.conversationID, "Sohbet")
        if let id = input.chairRunID { try Self.requirePositive(id, "Sandalye çalışması") }
        if let id = input.participantID { try Self.requirePositive(id, "Sandalye") }
        let content = try Self.validText(input.content, field: "İfade", maximum: 3_000)
        try Self.validateIntensity(input.intensity)
        let eventID = try Self.eventIdentifier(
            input.clientEventID, prefix: "native-chair"
        )
        var body: [String: JSONValue] = [
            "conv_id": .number(Double(input.conversationID)),
            "content": .string(content),
            "client_event_id": .string(eventID),
        ]
        Self.put(input.chairRunID, key: "chair_run_id", into: &body)
        Self.put(input.participantID, key: "participant_id", into: &body)
        Self.put(input.intensity, key: "intensity", into: &body)
        Self.put(input.expectedRevision, key: "expected_revision", into: &body)
        Self.put(input.strategyID, key: "strategy_id", into: &body)
        let response: ChairTurnResultWire = try await post(
            "/api/chair-turn", body: body
        )
        return response.model
    }

    func requestChairGuidance(
        _ input: ChairGuidanceInput
    ) async throws -> ChairGuidanceResult {
        try Self.requirePositive(input.conversationID, "Sohbet")
        if let id = input.chairRunID { try Self.requirePositive(id, "Sandalye çalışması") }
        guard input.afterSequence >= 0, input.revision >= 0 else {
            throw Self.invalid("Sandalye çalışmasının sürümü geçersiz.")
        }
        let requestID = try Self.eventIdentifier(
            input.requestID, prefix: "native-chair-guide"
        )
        var body: [String: JSONValue] = [
            "conv_id": .number(Double(input.conversationID)),
            "after_seq": .number(Double(input.afterSequence)),
            "revision": .number(Double(input.revision)),
            "request_id": .string(requestID),
        ]
        Self.put(input.chairRunID, key: "chair_run_id", into: &body)
        let response: ChairGuidanceResultWire = try await post(
            "/api/chair-guidance", body: body, timeout: 180
        )
        return response.model
    }

    func imageryWork(conversationID: Int) async throws -> ImageryWork? {
        try Self.requirePositive(conversationID, "Sohbet")
        let response: ImageryEnvelopeWire = try await get(
            "/api/imagery-work",
            query: [URLQueryItem(name: "conv_id", value: String(conversationID))]
        )
        return response.imagerywork?.model
    }

    func mutateImageryWork(
        _ mutation: ImageryWorkMutation
    ) async throws -> ImageryWorkResult {
        try Self.validate(mutation)
        var body: [String: JSONValue] = [
            "conv_id": .number(Double(mutation.conversationID)),
            "action": .string(mutation.action.rawValue),
        ]
        Self.put(mutation.imageryRunID, key: "imagery_run_id", into: &body)
        Self.put(mutation.techniqueRunID, key: "technique_run_id", into: &body)
        Self.put(mutation.revision, key: "revision", into: &body)
        Self.put(mutation.orientationOK, key: "orientation_ok", into: &body)
        Self.put(mutation.frameOK, key: "frame_ok", into: &body)
        Self.put(mutation.realityClear, key: "reality_clear", into: &body)
        Self.put(mutation.stopSignal, key: "stop_signal", into: &body)
        Self.put(mutation.sceneBoundary, key: "scene_boundary", into: &body)
        Self.put(mutation.intensity, key: "intensity", into: &body)
        Self.put(mutation.groundingConfirmed, key: "grounding_confirmed", into: &body)
        Self.put(mutation.summary, key: "summary", into: &body)
        let response: ImageryMutationWire = try await post(
            "/api/imagery-work", body: body
        )
        return response.model
    }

    func addImageryTurn(_ input: ImageryTurnInput) async throws -> ImageryTurnResult {
        try Self.requirePositive(input.conversationID, "Sohbet")
        try Self.requirePositive(input.imageryRunID, "İmgelem çalışması")
        let content = try Self.validText(input.content, field: "İfade", maximum: 3_000)
        try Self.validateIntensity(input.intensity)
        guard input.orientationOK else {
            throw Self.invalid("İmgeleme devam etmeden önce bulunduğunuz ortamı doğrulayın.")
        }
        guard input.stepData.count <= 24,
              input.stepData.allSatisfy({ $0.key.count <= 64 && $0.value.count <= 2_000 }) else {
            throw Self.invalid("İmgelem adımı beklenenden büyük.")
        }
        let eventID = try Self.eventIdentifier(
            input.clientEventID, prefix: "native-imagery"
        )
        var body: [String: JSONValue] = [
            "conv_id": .number(Double(input.conversationID)),
            "imagery_run_id": .number(Double(input.imageryRunID)),
            "content": .string(content),
            "intensity": .number(Double(input.intensity)),
            "orientation_ok": .bool(input.orientationOK),
            "client_event_id": .string(eventID),
        ]
        Self.put(input.realityClear, key: "reality_clear", into: &body)
        Self.put(input.expectedRevision, key: "expected_revision", into: &body)
        if !input.stepData.isEmpty {
            body["step_data"] = .object(input.stepData.mapValues(JSONValue.string))
        }
        let response: ImageryTurnResultWire = try await post(
            "/api/imagery-turn", body: body
        )
        return response.model
    }

    func requestImageryGuidance(
        conversationID: Int,
        imageryRunID: Int,
        revision: Int? = nil
    ) async throws -> ImageryGuidanceResult {
        try Self.requirePositive(conversationID, "Sohbet")
        try Self.requirePositive(imageryRunID, "İmgelem çalışması")
        if let revision, revision < 0 { throw Self.invalid("Çalışma sürümü geçersiz.") }
        var body: [String: JSONValue] = [
            "conv_id": .number(Double(conversationID)),
            "imagery_run_id": .number(Double(imageryRunID)),
            "action": .string("guidance"),
        ]
        Self.put(revision, key: "revision", into: &body)
        let response: ImageryGuidanceWire = try await post(
            "/api/imagery-work", body: body, timeout: 180
        )
        return response.model
    }

    func livingMap(therapistID: String? = nil) async throws -> LivingMapSnapshot {
        var query: [URLQueryItem] = []
        if let therapistID {
            let therapist = try Self.validIdentifier(
                therapistID, field: "Usta", maximum: 64
            )
            query.append(URLQueryItem(name: "therapist", value: therapist))
        }
        let response: LivingMapWire = try await get("/api/living-map", query: query)
        return response.model
    }

    func sessionSummary(
        conversationID: Int
    ) async throws -> SessionSummaryRecord? {
        try Self.requirePositive(conversationID, "Görüşme")
        let response: SessionSummaryResponseWire = try await get(
            "/api/session-summary",
            query: [URLQueryItem(
                name: "id", value: String(conversationID))]
        )
        return response.model
    }

    func updateSessionSummary(
        conversationID: Int,
        action: SessionSummaryAction,
        content: String? = nil
    ) async throws -> SessionSummaryRecord? {
        try Self.requirePositive(conversationID, "Görüşme")
        var body: [String: JSONValue] = [
            "conv_id": .number(Double(conversationID)),
            "action": .string(action.rawValue),
        ]
        if let content {
            let text = try Self.validText(
                content, field: "Özet", maximum: 5_000
            )
            body["content"] = .string(text)
        }
        let response: SessionSummaryResponseWire = try await post(
            "/api/session-summary", body: body
        )
        return response.model
    }

    func livingMapDetail(reference: String) async throws -> LivingMapClaimDetail {
        let reference = try Self.validText(
            reference, field: "Harita kaydı", maximum: 160
        )
        let response: LivingDetailWire = try await get(
            "/api/living-map/detail",
            query: [URLQueryItem(name: "claim_id", value: reference)]
        )
        return response.model
    }

    func reviewLivingMap(
        _ request: LivingMapReviewRequest
    ) async throws -> LivingMapClaimDetail {
        let reference = try Self.validText(
            request.claimReference, field: "Harita kaydı", maximum: 160
        )
        if let scope = request.scope,
           !["therapist", "shared", "private", "excluded"].contains(scope) {
            throw Self.invalid("Harita görünürlük alanı geçersiz.")
        }
        var body: [String: JSONValue] = [
            "claim_id": .string(reference),
            "action": .string(request.action.rawValue),
        ]
        Self.put(request.scope, key: "scope", into: &body)
        Self.put(request.sensitive, key: "sensitive", into: &body)
        Self.put(request.excludedFromModel, key: "excluded_from_model", into: &body)
        try Self.add(request.edits.title, key: "title", maximum: 200, to: &body)
        try Self.add(request.edits.statement, key: "statement", maximum: 4_000, to: &body)
        try Self.add(request.edits.trigger, key: "trigger", maximum: 2_000, to: &body)
        try Self.add(request.edits.experience, key: "experience", maximum: 2_000, to: &body)
        try Self.add(request.edits.response, key: "response", maximum: 2_000, to: &body)
        try Self.add(request.edits.shortTermEffect, key: "short_term_effect", maximum: 2_000, to: &body)
        try Self.add(request.edits.longTermEffect, key: "long_term_effect", maximum: 2_000, to: &body)
        try Self.add(request.edits.need, key: "need", maximum: 2_000, to: &body)
        try Self.add(request.edits.counterexample, key: "counterexample", maximum: 2_000, to: &body)
        try Self.add(request.edits.context, key: "context", maximum: 2_000, to: &body)
        try Self.add(request.edits.note, key: "note", maximum: 2_000, to: &body)
        let response: LivingDetailWire = try await post(
            "/api/living-map/review", body: body
        )
        return response.model
    }

    func generateLivingMap(
        conversationID: Int
    ) async throws -> LivingMapGenerationAccepted {
        try Self.requirePositive(conversationID, "Sohbet")
        let response: LivingGenerationAcceptedWire = try await post(
            "/api/living-map/generate",
            body: ["conv_id": .number(Double(conversationID))]
        )
        return response.model
    }

    func deviceSyncStatus() async throws -> DeviceSyncStatus {
        let response: SyncStatusWire = try await get("/api/sync/status")
        return response.model
    }

    func startDeviceSyncHost() async throws -> DeviceSyncInvitation {
        let response: SyncInvitationWire = try await post("/api/sync/start", body: [:])
        let invitation = response.model
        try Self.validate(invitation)
        return invitation
    }

    func stopDeviceSyncHost() async throws -> DeviceSyncStatus {
        let response: SyncStatusWire = try await post("/api/sync/stop", body: [:])
        return response.model
    }

    func pairAndApplyDeviceSync(
        code: String,
        deviceName: String? = nil,
        platform: String? = nil
    ) async throws -> DeviceSyncApplyResult {
        // The pairing token is deliberately never interpolated into an error.
        let code = code.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !code.isEmpty, code.count <= 8_192 else {
            throw Self.invalid("Eşitleme kodu geçerli değil.")
        }
        var body: [String: JSONValue] = ["code": .string(code)]
        if let deviceName {
            let name = try Self.validText(deviceName, field: "Aygıt adı", maximum: 64)
            body["device_name"] = .string(name)
        }
        if let platform {
            let value = try Self.validText(platform, field: "Platform", maximum: 32)
            body["platform"] = .string(value)
        }
        let response: SyncApplyWire = try await post(
            "/api/sync/join", body: body, timeout: 600
        )
        return response.model
    }

    func resolveDeviceSyncConflict(
        id: Int,
        resolution: SyncConflictResolution
    ) async throws -> SyncConflictResolutionResult {
        try Self.requirePositive(id, "Çakışma")
        let response: SyncConflictResolutionWire = try await post(
            "/api/sync/conflict",
            body: [
                "id": .number(Double(id)),
                "resolution": .string(resolution.rawValue),
            ]
        )
        return response.model
    }
}

private extension APIClient {
    static func invalid(_ message: String) -> DivanAPIError {
        DivanAPIError(message: message, errorCode: "invalid_request")
    }

    static func requirePositive(_ value: Int, _ field: String) throws {
        guard value > 0 else { throw invalid("\(field) kimliği geçersiz.") }
    }

    static func validText(
        _ value: String,
        field: String,
        maximum: Int
    ) throws -> String {
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, trimmed.count <= maximum else {
            throw invalid("\(field) boş veya fazla uzun.")
        }
        return trimmed
    }

    static func validIdentifier(
        _ value: String,
        field: String,
        maximum: Int
    ) throws -> String {
        let value = try validText(value, field: field, maximum: maximum)
        guard value.unicodeScalars.allSatisfy({ scalar in
            (48...57).contains(scalar.value)
                || (65...90).contains(scalar.value)
                || (97...122).contains(scalar.value)
                || scalar == "_" || scalar == "-"
        }) else { throw invalid("\(field) kimliği geçersiz.") }
        return value
    }

    static func eventIdentifier(_ supplied: String?, prefix: String) throws -> String {
        let value = supplied?.trimmingCharacters(in: .whitespacesAndNewlines)
            ?? "\(prefix)-\(UUID().uuidString.lowercased())"
        guard !value.isEmpty, value.count <= 100,
              value.unicodeScalars.allSatisfy({ scalar in
                  (48...57).contains(scalar.value)
                      || (65...90).contains(scalar.value)
                      || (97...122).contains(scalar.value)
                      || scalar == "." || scalar == "_" || scalar == ":" || scalar == "-"
              }) else { throw invalid("İstek kimliği geçersiz.") }
        return value
    }

    static func validateIntensity(_ intensity: Int?) throws {
        guard let intensity else { return }
        guard (0...10).contains(intensity) else {
            throw invalid("Yoğunluk 0 ile 10 arasında olmalı.")
        }
    }

    static func validate(_ mutation: TechniqueRunMutation) throws {
        try requirePositive(mutation.conversationID, "Sohbet")
        if let id = mutation.runID { try requirePositive(id, "Çalışma") }
        try validateIntensity(mutation.intensity)
        if mutation.action == .propose {
            let key = mutation.methodKey?.trimmingCharacters(in: .whitespacesAndNewlines)
            guard (key?.isEmpty == false) || mutation.methodID != nil else {
                throw invalid("Başlatılacak yöntem katalogdan seçilmeli.")
            }
            if let key, key.count > 240 { throw invalid("Yöntem anahtarı fazla uzun.") }
        }
        if mutation.action == .consent, mutation.consentConfirmed != true {
            throw invalid("Tekniğe başlamak için kullanıcının açık onayı gerekli.")
        }
        if [.advance, .complete].contains(mutation.action),
           mutation.checkpointConfirmed != true {
            throw invalid("Bu adımı ilerletmek için açık onay gerekli.")
        }
        if let note = mutation.checkpointNote, note.count > 2_000 {
            throw invalid("Adım notu fazla uzun.")
        }
    }

    static func validate(_ mutation: ChairWorkMutation) throws {
        try requirePositive(mutation.conversationID, "Sohbet")
        if let id = mutation.chairRunID { try requirePositive(id, "Sandalye çalışması") }
        if let revision = mutation.expectedRevision, revision < 0 {
            throw invalid("Çalışma sürümü geçersiz.")
        }
        if [.select, .rename].contains(mutation.action) {
            guard let id = mutation.participantID, id > 0 else {
                throw invalid("Sandalye seçimi gerekli.")
            }
        }
        if [.rename, .add].contains(mutation.action) {
            _ = try validText(mutation.label ?? "", field: "Sandalye adı", maximum: 80)
        }
        if mutation.action == .feedback,
           !["fit", "partly", "missed", "stop"].contains(mutation.feedback ?? "") {
            throw invalid("Geri bildirim seçimi geçersiz.")
        }
        if mutation.action == .begin {
            guard mutation.orientationOK == true, mutation.frameOK == true else {
                throw invalid("Başlamadan önce yönelim ve çalışma çerçevesi onaylanmalı.")
            }
            _ = try validText(
                mutation.stopSignal ?? "", field: "Dur işareti", maximum: 80
            )
            _ = try validText(
                mutation.goalText ?? "", field: "Çalışma amacı", maximum: 500
            )
        }
        try validateIntensity(mutation.intensity)
        if let note = mutation.checkpointNote, note.count > 2_000 {
            throw invalid("Kontrol noktası notu fazla uzun.")
        }
        switch mutation.action {
        case .ground:
            guard mutation.checkpointConfirmed == true,
                  mutation.orientationOK == true,
                  mutation.intensity != nil else {
                throw invalid(
                    "Şimdiye dönüş için yönelim, yoğunluk ve açık onay gerekli."
                )
            }
        case .resume:
            guard mutation.checkpointConfirmed == true,
                  mutation.orientationOK == true,
                  let intensity = mutation.intensity,
                  intensity < 8 else {
                throw invalid(
                    "Devam için şimdi-burada yönelimi, topraklanma teyidi ve 8'in altında yoğunluk gerekli."
                )
            }
        case .reflect:
            guard mutation.checkpointConfirmed == true else {
                throw invalid("Değerlendirme aşaması için açık onay gerekli.")
            }
            _ = try validText(
                mutation.checkpointNote ?? "",
                field: "Değerlendirme notu",
                maximum: 2_000
            )
        case .complete:
            guard mutation.checkpointConfirmed == true else {
                throw invalid("Çalışmayı tamamlamak için açık onay gerekli.")
            }
        default:
            break
        }
    }

    static func validate(_ mutation: ImageryWorkMutation) throws {
        try requirePositive(mutation.conversationID, "Sohbet")
        if let id = mutation.imageryRunID { try requirePositive(id, "İmgelem çalışması") }
        if let id = mutation.techniqueRunID { try requirePositive(id, "Teknik çalışması") }
        if let revision = mutation.revision, revision < 0 {
            throw invalid("Çalışma sürümü geçersiz.")
        }
        try validateIntensity(mutation.intensity)
        switch mutation.action {
        case .create:
            guard mutation.techniqueRunID != nil else {
                throw invalid("İmgelem çalışması bir teknik kaydına bağlanmalı.")
            }
        case .consent:
            guard mutation.orientationOK == true,
                  mutation.frameOK == true,
                  mutation.realityClear == true else {
                throw invalid("İmgelem için dört parçalı açık onay tamamlanmalı.")
            }
            _ = try validText(
                mutation.stopSignal ?? "", field: "Dur işareti", maximum: 80
            )
        case .ground:
            guard mutation.orientationOK == true else {
                throw invalid("Topraklanma için bulunduğunuz ortamı doğrulayın.")
            }
        case .resume:
            guard mutation.orientationOK == true,
                  let intensity = mutation.intensity,
                  intensity < 8 else {
                throw invalid("Devam etmek için yönelim açık ve yoğunluk 8'in altında olmalı.")
            }
        case .complete:
            guard mutation.groundingConfirmed == true,
                  mutation.orientationOK == true,
                  mutation.realityClear == true,
                  let intensity = mutation.intensity,
                  intensity < 8 else {
                throw invalid("Bitirmeden önce topraklanma ve gerçeklik yönelimi tamamlanmalı.")
            }
        default:
            break
        }
    }

    static func validate(_ invitation: DeviceSyncInvitation) throws {
        guard !invitation.pairingCode.isEmpty,
              invitation.pairingCode.count <= 8_192 else {
            throw invalid("Eşitleme daveti okunamadı.")
        }
        let matrix = invitation.qrMatrix
        guard (1...177).contains(matrix.size),
              matrix.rows.count == matrix.size,
              matrix.rows.allSatisfy({ row in
                  row.count == matrix.size && row.allSatisfy({ $0 == "0" || $0 == "1" })
              }) else {
            throw invalid("Eşitleme QR verisi geçersiz.")
        }
    }

    static func put(
        _ value: Int?, key: String, into body: inout [String: JSONValue]
    ) {
        if let value { body[key] = .number(Double(value)) }
    }

    static func put(
        _ value: Bool?, key: String, into body: inout [String: JSONValue]
    ) {
        if let value { body[key] = .bool(value) }
    }

    static func put(
        _ value: String?, key: String, into body: inout [String: JSONValue]
    ) {
        if let value { body[key] = .string(value) }
    }

    static func add(
        _ value: String?,
        key: String,
        maximum: Int,
        to body: inout [String: JSONValue]
    ) throws {
        guard let value else { return }
        let validated = try validText(
            value, field: "Harita alanı", maximum: maximum
        )
        body[key] = .string(validated)
    }
}

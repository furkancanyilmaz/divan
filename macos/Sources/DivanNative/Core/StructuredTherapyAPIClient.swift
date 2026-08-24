import Foundation

/// Exact native bindings for the shared ADHD and Schema Path contracts.
///
/// Every mutation carries a bounded idempotency key.  Clinical decisions are
/// sent only from explicit user actions; this adapter never infers consent,
/// safety clearance, privacy sharing, or a candidate decision.
public extension APIClient {
    func adhdDashboard(conversationID: Int) async throws -> ADHDWorkspaceSnapshot {
        try Self.structuredPositive(conversationID, field: "ADHD görüşmesi")
        return try await get(
            "/api/adhd/dashboard",
            query: [URLQueryItem(name: "conv_id", value: String(conversationID))]
        )
    }

    func adhdTUSPlanner(
        conversationID: Int,
        query: String? = nil
    ) async throws -> ADHDTUSPlannerSnapshot {
        try Self.structuredPositive(conversationID, field: "ADHD görüşmesi")
        var items = [URLQueryItem(name: "conv_id", value: String(conversationID))]
        if let query = try Self.structuredText(
            query, field: "TUS alan araması", maximum: 80
        ), !query.isEmpty {
            items.append(URLQueryItem(name: "q", value: query))
        }
        let snapshot: ADHDTUSPlannerSnapshot = try await get(
            "/api/adhd/tus", query: items
        )
        guard snapshot.contractIsSupported,
              snapshot.conversationID == conversationID,
              snapshot.ok == nil,
              snapshot.duplicate == nil,
              snapshot.action == nil else {
            throw Self.structuredInvalid("TUS çalışma sözleşmesi doğrulanamadı.")
        }
        return snapshot
    }

    func mutateADHDTUS(
        _ mutation: ADHDTUSMutation
    ) async throws -> ADHDTUSPlannerSnapshot {
        try Self.validateStructured(mutation)
        var body: [String: JSONValue] = [
            "protocol": .string("adhd_tus_planner_v1"),
            "conv_id": .number(Double(mutation.conversationID)),
            "action": .string(mutation.action.rawValue),
            "expected_revision": .number(Double(mutation.expectedRevision)),
            "request_id": .string(try Self.structuredRequestID(
                mutation.requestID, prefix: "native-adhd-tus", maximum: 128
            )),
        ]
        Self.structuredPut(mutation.enabled, key: "enabled", into: &body)
        Self.structuredPut(mutation.questionID, key: "question_id", into: &body)
        Self.structuredPut(mutation.optionID, key: "option_id", into: &body)
        Self.structuredPut(mutation.customMinutes, key: "custom_minutes", into: &body)
        Self.structuredPut(mutation.planID, key: "plan_id", into: &body)
        Self.structuredPut(mutation.stepID, key: "step_id", into: &body)
        let snapshot: ADHDTUSPlannerSnapshot = try await post(
            "/api/adhd/tus", body: body
        )
        guard snapshot.contractIsSupported,
              snapshot.conversationID == mutation.conversationID,
              snapshot.ok == true,
              snapshot.duplicate != nil,
              snapshot.action == mutation.action.rawValue,
              snapshot.revision == mutation.expectedRevision + 1 else {
            throw Self.structuredInvalid("TUS çalışma sözleşmesi doğrulanamadı.")
        }
        return snapshot
    }

    func mutateADHDHabit(
        _ mutation: ADHDHabitMutation
    ) async throws -> ADHDHabitMutationResponse {
        try Self.validateStructured(mutation)
        var body: [String: JSONValue] = [
            "action": .string(mutation.action.rawValue),
            "conv_id": .number(Double(mutation.conversationID)),
            "request_id": .string(try Self.structuredRequestID(
                mutation.requestID, prefix: "native-adhd-habit", maximum: 128
            )),
        ]
        Self.structuredPut(mutation.habitID, key: "habit_id", into: &body)
        Self.structuredPut(mutation.title, key: "title", into: &body)
        Self.structuredPut(mutation.cue, key: "cue", into: &body)
        Self.structuredPut(mutation.tinyAction, key: "tiny_action", into: &body)
        Self.structuredPut(
            mutation.targetPerWeek, key: "target_per_week", into: &body
        )
        if let days = mutation.preferredDays {
            body["preferred_days"] = .array(days.map { .number(Double($0)) })
        }
        if let time = mutation.reminderLocalTime {
            // The server contract uses the empty string to clear this
            // preference; JSON null is not a valid local-time string.
            body["reminder_local_time"] = .string(time)
        }
        Self.structuredPut(mutation.timezone, key: "timezone", into: &body)
        Self.structuredPut(mutation.decision, key: "decision", into: &body)
        if let scheduledFor = mutation.scheduledFor {
            body["scheduled_for"] = .number(floor(scheduledFor))
        }
        return try await post("/api/adhd/habits", body: body)
    }

    func mutateADHDEvent(
        _ mutation: ADHDEventMutation
    ) async throws -> ADHDEventMutationResponse {
        try Self.validateStructured(mutation)
        var body: [String: JSONValue] = [
            "action": .string(mutation.action.rawValue),
            "conv_id": .number(Double(mutation.conversationID)),
            "event_id": .number(Double(mutation.eventID)),
            "request_id": .string(try Self.structuredRequestID(
                mutation.requestID, prefix: "native-adhd-event", maximum: 128
            )),
        ]
        Self.structuredPut(
            mutation.effortMinutes, key: "effort_minutes", into: &body
        )
        Self.structuredPut(mutation.friction, key: "friction", into: &body)
        Self.structuredPut(mutation.note, key: "note", into: &body)
        if let scheduledFor = mutation.scheduledFor {
            body["scheduled_for"] = .number(floor(scheduledFor))
        }
        return try await post("/api/adhd/events", body: body)
    }

    func mutateADHDJournal(
        _ mutation: ADHDJournalMutation
    ) async throws -> ADHDJournalMutationResponse {
        try Self.validateStructured(mutation)
        var body: [String: JSONValue] = [
            "action": .string(mutation.action.rawValue),
            "conv_id": .number(Double(mutation.conversationID)),
            "request_id": .string(try Self.structuredRequestID(
                mutation.requestID, prefix: "native-adhd-journal", maximum: 128
            )),
        ]
        Self.structuredPut(mutation.entryID, key: "entry_id", into: &body)
        Self.structuredPut(mutation.content, key: "content", into: &body)
        Self.structuredPut(
            mutation.entryType?.rawValue, key: "entry_type", into: &body
        )
        Self.structuredPut(
            mutation.shareWithCoach, key: "share_with_coach", into: &body
        )
        Self.structuredPut(mutation.sensitive, key: "sensitive", into: &body)
        Self.structuredPut(mutation.habitID, key: "habit_id", into: &body)
        Self.structuredPut(mutation.eventID, key: "event_id", into: &body)
        return try await post("/api/adhd/journal", body: body)
    }

    func schemaPath(conversationID: Int) async throws -> SchemaPathSnapshot {
        try Self.structuredPositive(conversationID, field: "Şema görüşmesi")
        return try await get(
            "/api/schema-path",
            query: [URLQueryItem(name: "conv_id", value: String(conversationID))]
        )
    }

    func mutateSchemaPath(
        _ mutation: SchemaPathMutation
    ) async throws -> SchemaPathMutationResponse {
        try Self.validateStructured(mutation)
        var body: [String: JSONValue] = [
            "action": .string(mutation.action.rawValue),
            "conv_id": .number(Double(mutation.conversationID)),
            "request_id": .string(try Self.structuredRequestID(
                mutation.requestID, prefix: "native-schema-path", maximum: 100
            )),
        ]
        Self.structuredPut(
            mutation.schemaProtocol, key: "protocol", into: &body
        )
        Self.structuredPut(mutation.flowVersion, key: "flow_version", into: &body)
        Self.structuredPut(mutation.pathID, key: "path_id", into: &body)
        Self.structuredPut(mutation.claimID, key: "claim_id", into: &body)
        Self.structuredPut(
            mutation.decision?.rawValue, key: "decision", into: &body
        )
        Self.structuredPut(mutation.context, key: "context", into: &body)
        Self.structuredPut(mutation.note, key: "note", into: &body)
        Self.structuredPut(mutation.kind, key: "kind", into: &body)
        Self.structuredPut(mutation.value, key: "value", into: &body)
        Self.structuredPut(mutation.toPhase, key: "to_phase", into: &body)
        Self.structuredPut(mutation.methodID, key: "method_id", into: &body)
        Self.structuredPut(mutation.confirmed, key: "confirmed", into: &body)
        Self.structuredPut(
            mutation.userConfirmed, key: "user_confirmed", into: &body
        )
        Self.structuredPut(
            mutation.techniqueRunID, key: "technique_run_id", into: &body
        )
        Self.structuredPut(mutation.reason, key: "reason", into: &body)
        Self.structuredPut(
            mutation.suggestionID, key: "suggestion_id", into: &body
        )
        Self.structuredPut(mutation.modeKey, key: "mode_key", into: &body)
        Self.structuredPut(
            mutation.authoredBy, key: "authored_by", into: &body
        )
        Self.structuredPut(mutation.age, key: "age", into: &body)
        Self.structuredPut(mutation.ageRange, key: "age_range", into: &body)
        Self.structuredPut(mutation.scene, key: "scene", into: &body)
        Self.structuredPut(
            mutation.unmetNeed, key: "unmet_need", into: &body
        )
        Self.structuredPut(
            mutation.confidence, key: "confidence", into: &body
        )
        Self.structuredPut(mutation.stageID, key: "stage_id", into: &body)
        Self.structuredPut(mutation.label, key: "label", into: &body)
        Self.structuredPut(
            mutation.thenResponse, key: "then_response", into: &body
        )
        Self.structuredPut(
            mutation.nowResponse, key: "now_response", into: &body
        )
        Self.structuredPut(
            mutation.difference, key: "difference", into: &body
        )
        Self.structuredPut(mutation.evidence, key: "evidence", into: &body)
        if let candidates = mutation.focusCandidates {
            body["candidates"] = .array(candidates.map { candidate in
                .object([
                    "mode_key": .string(candidate.modeKey),
                    "evidence": .string(candidate.evidence),
                ])
            })
        }
        if let precheck = mutation.precheck {
            body["precheck"] = .object([
                "orientation_confirmed": .bool(precheck.orientationConfirmed),
                "reality_clear": .bool(precheck.realityClear),
                "sleep_activation_clear": .bool(precheck.sleepActivationClear),
                "intensity": .number(Double(precheck.intensity)),
                "support_available": .bool(precheck.supportAvailable),
                "stop_signal": .string(precheck.stopSignal),
            ])
        }
        if let experiment = mutation.experiment {
            body["experiment"] = .object([
                "variable": .string(experiment.variable),
                "constant": .string(experiment.constant),
                "prediction": .string(experiment.prediction),
                "action": .string(experiment.action),
                "observable_result": .string(experiment.observableResult),
                "tiny_version": .string(experiment.tinyVersion),
                "target_per_week": .number(Double(experiment.targetPerWeek)),
            ])
        }
        return try await post("/api/schema-path", body: body)
    }

    /// Posts one server-declared Schema Path v4 card intent. Protected binding
    /// keys are never accepted from a card payload and therefore cannot be
    /// replaced by stale or model-authored JSON.
    func mutateSchemaCard(
        _ mutation: SchemaCardMutation
    ) async throws -> SchemaPathMutationResponse {
        try Self.validateSchemaCard(mutation)
        var body = mutation.values
        let protected = Self.schemaCardProtectedKeys
        guard protected.isDisjoint(with: body.keys) else {
            throw Self.structuredInvalid("Şema kartı bağlama alanlarını değiştiremez.")
        }
        body["action"] = .string(mutation.action.rawValue)
        body["conv_id"] = .number(Double(mutation.conversationID))
        body["request_id"] = .string(try Self.structuredRequestID(
            mutation.requestID, prefix: "native-schema-card", maximum: 100
        ))
        Self.structuredPut(mutation.pathID, key: "path_id", into: &body)
        Self.structuredPut(
            mutation.pathPublicID,
            key: "path_public_id",
            into: &body
        )
        Self.structuredPut(
            mutation.expectedRevision,
            key: "expected_revision",
            into: &body
        )
        Self.structuredPut(
            mutation.sourceUserMessageID,
            key: "source_user_message_id",
            into: &body
        )
        Self.structuredPut(
            mutation.sourceUserMessagePublicID,
            key: "source_user_message_public_id",
            into: &body
        )
        Self.structuredPut(
            mutation.sourceAssistantMessageID,
            key: "source_assistant_message_id",
            into: &body
        )
        Self.structuredPut(
            mutation.sourceAssistantMessagePublicID,
            key: "source_assistant_message_public_id",
            into: &body
        )
        Self.structuredPut(mutation.stepID, key: "step_id", into: &body)
        Self.structuredPut(
            mutation.clientEventID, key: "client_event_id", into: &body
        )
        Self.structuredPut(
            mutation.expectedTechniqueRevision,
            key: "expected_technique_revision",
            into: &body
        )
        return try await post("/api/schema-path", body: body, timeout: 180)
    }

    func mutateSchemaClinicalSync(
        _ mutation: SchemaClinicalSyncMutation
    ) async throws -> SchemaPathMutationResponse {
        try Self.structuredPositive(
            mutation.conversationID, field: "Şema görüşmesi"
        )
        guard mutation.confirmed else {
            throw Self.structuredInvalid(
                "Şema ve Yaşayan Harita eşitlemesi için açık onay gerekli."
            )
        }
        return try await post(
            "/api/schema-path",
            body: [
                "action": .string("set_clinical_sync"),
                "conv_id": .number(Double(mutation.conversationID)),
                "enabled": .bool(mutation.enabled),
                "confirmed": .bool(true),
                "request_id": .string(try Self.structuredRequestID(
                    mutation.requestID,
                    prefix: "native-schema-sync",
                    maximum: 100
                )),
            ]
        )
    }

    func mutateSchemaTurnAnalysis(
        _ mutation: SchemaTurnAnalysisMutation
    ) async throws -> SchemaTurnAnalysisMutationResponse {
        try Self.validateStructured(mutation)
        var body: [String: JSONValue] = [
            "action": .string(mutation.action.rawValue),
            "conv_id": .number(Double(mutation.conversationID)),
            "request_id": .string(try Self.structuredRequestID(
                mutation.requestID, prefix: "native-schema-turn", maximum: 100
            )),
        ]
        Self.structuredPut(mutation.enabled, key: "enabled", into: &body)
        Self.structuredPut(
            mutation.userMessageID, key: "user_message_id", into: &body
        )
        Self.structuredPut(mutation.consent, key: "consent", into: &body)
        Self.structuredPut(
            mutation.providerID, key: "provider_id", into: &body
        )
        Self.structuredPut(mutation.modelID, key: "model_id", into: &body)
        Self.structuredPut(mutation.jobID, key: "job_id", into: &body)
        return try await post("/api/schema-path", body: body, timeout: 180)
    }
}

private extension APIClient {
    static let schemaCardProtectedKeys: Set<String> = [
        "action", "conv_id", "request_id", "path_id", "path_public_id",
        "expected_revision",
        "source_user_message_id", "source_user_message_public_id",
        "source_assistant_message_id", "source_assistant_message_public_id", "step_id",
        "client_event_id", "expected_technique_revision",
    ]

    static let schemaCardValueKeys: Set<String> = [
        "claim_id", "candidate_public_id", "candidate_queue_id",
        "candidate_queue_public_id", "transition_only",
        "decision", "context",
        "note", "burden", "impact", "priority", "baseline_burden", "variable",
        "changed_scenario", "changed_burden", "fit", "confirmed", "reason",
        "method_id", "precheck", "orientation_confirmed", "reality_clear",
        "sleep_activation_clear", "support_available", "stop_signal",
        "orientation_ok", "grounding_confirmed", "participant_id",
        "strategy_id", "technique_link_id", "technique_link_public_id",
        "intensity", "choice",
        "step_data", "age", "age_range", "label", "scene", "unmet_need",
        "confidence", "authored_by", "stage_id", "then_response", "now_response",
        "difference", "evidence", "environment_before", "environment_rescripted",
        "healthy_adult_words", "trigger_source_user_message_id",
        "trigger_source_assistant_message_id", "trigger",
        "healthy_adult_response", "planned_action", "support_choice",
        "predicted_result", "observed_result", "experiment", "user_confirmed",
        "constant", "prediction", "observable_result", "tiny_version",
        "target_per_week", "practice_action", "meta_event_id",
        "meta_event_public_id", "clinical_generation", "control_only",
    ]

    static func validateSchemaCard(_ value: SchemaCardMutation) throws {
        try structuredPositive(value.conversationID, field: "Şema görüşmesi")
        let mapActions: Set<SchemaChatCardAction> = [
            .undoMapUpdate, .makeMapUpdatePrivate, .editMapUpdate,
        ]
        let candidateActions: Set<SchemaChatCardAction> = [
            .acceptCandidateChat, .rejectCandidateChat,
        ]
        if candidateActions.contains(value.action) {
            guard value.pathID == nil, value.pathPublicID == nil,
                  value.expectedRevision == nil else {
                throw structuredInvalid(
                    "Başlangıç seçimi çalışma yolu veya revizyon taşıyamaz."
                )
            }
        } else if mapActions.contains(value.action) {
            switch (value.pathID, value.expectedRevision) {
            case (nil, nil):
                guard value.pathPublicID == nil else {
                    throw structuredInvalid(
                        "Dinleme aşaması Harita kartı çalışma yolu kimliği taşıyamaz."
                    )
                }
                break
            case (.some(let pathID), .some(let revision)):
                try structuredPositive(pathID, field: "Çalışma yolu")
                try validateSchemaPathPublicID(value.pathPublicID)
                guard revision >= 0 else {
                    throw structuredInvalid("Şema çalışma revizyonu geçersiz.")
                }
            default:
                throw structuredInvalid(
                    "Yaşayan Harita çalışma yolu ve revizyonu birlikte bulunmalı."
                )
            }
        } else {
            guard let pathID = value.pathID,
                  let revision = value.expectedRevision else {
                throw structuredInvalid("Şema çalışma yolu bağı eksik.")
            }
            try structuredPositive(pathID, field: "Çalışma yolu")
            try validateSchemaPathPublicID(value.pathPublicID)
            guard revision >= 0 else {
                throw structuredInvalid("Şema çalışma revizyonu geçersiz.")
            }
        }
        _ = try structuredRequestID(
            value.requestID, prefix: "native-schema-card", maximum: 100
        )
        guard Set(value.values.keys).isSubset(of: schemaCardValueKeys) else {
            throw structuredInvalid("Şema kartında tanınmayan alan var.")
        }
        try validateSchemaCardJSON(.object(value.values), depth: 0)

        if candidateActions.contains(value.action) {
            guard case .number(let rawClaim)? = value.values["claim_id"],
                  rawClaim.isFinite, rawClaim.rounded() == rawClaim,
                  rawClaim > 0, rawClaim <= Double(Int.max),
                  case .string(let candidatePublicID)? =
                    value.values["candidate_public_id"],
                  SchemaPathCheckpoint.isPublicID(candidatePublicID),
                  let sourceUser = value.sourceUserMessageID, sourceUser > 0,
                  let sourceUserPublic = value.sourceUserMessagePublicID,
                  SchemaPathCheckpoint.isPublicID(sourceUserPublic),
                  let sourceAssistant = value.sourceAssistantMessageID,
                  sourceAssistant > 0,
                  let sourceAssistantPublic =
                    value.sourceAssistantMessagePublicID,
                  SchemaPathCheckpoint.isPublicID(
                    sourceAssistantPublic
                  ) else {
                throw structuredInvalid(
                    "Başlangıç seçiminin aday veya mesaj dayanağı geçersiz."
                )
            }
        }

        if mapActions.contains(value.action) {
            guard case .number(let rawMetaID)? = value.values["meta_event_id"],
                  rawMetaID.isFinite, rawMetaID.rounded() == rawMetaID,
                  rawMetaID > 0, rawMetaID <= Double(Int.max) else {
                throw structuredInvalid("Yaşayan Harita olay kimliği geçersiz.")
            }
            guard case .string(let rawPublicID)? =
                    value.values["meta_event_public_id"],
                  SchemaPathCheckpoint.isPublicID(rawPublicID) else {
                throw structuredInvalid("Yaşayan Harita ortak kimliği geçersiz.")
            }
            guard case .number(let generation)? =
                    value.values["clinical_generation"],
                  generation.isFinite, generation.rounded() == generation,
                  generation >= 0, generation <= Double(Int.max) else {
                throw structuredInvalid("Yaşayan Harita eşitleme nesli geçersiz.")
            }
        }

        let sourceActions: Set<SchemaChatCardAction> = [
            .recordOrigin, .recordGrowth, .markHealthyAdult,
            .recordEnvironmentRescript, .recordPresentTransfer,
            .undoMapUpdate, .makeMapUpdatePrivate, .editMapUpdate,
        ]
        if sourceActions.contains(value.action) {
            guard let user = value.sourceUserMessageID, user > 0,
                  let assistant = value.sourceAssistantMessageID,
                  assistant > 0 else {
                throw structuredInvalid(
                    "Bu kayıt için kullanıcı ve Kerem mesaj dayanağı gerekli."
                )
            }
        }

        let authoredTechniqueReplies: Set<SchemaChatCardAction> = [
            .submitChatTechnique, .completeChatTechnique,
        ]
        let directControls: Set<SchemaChatCardAction> = [
            .pause, .resumePath, .groundChatTechnique, .stop,
        ]
        if directControls.contains(value.action) {
            guard value.sourceUserMessageID == nil,
                  value.sourceUserMessagePublicID == nil,
                  value.sourceAssistantMessageID == nil,
                  value.sourceAssistantMessagePublicID == nil,
                  value.clientEventID == nil else {
                throw structuredInvalid(
                    "Şema güvenlik kontrolü mesaj dayanağı üretemez."
                )
            }
        }
        if [.pause, .resumePath, .stop].contains(value.action) {
            guard value.values.isEmpty,
                  value.stepID == nil,
                  value.expectedTechniqueRevision == nil else {
                throw structuredInvalid(
                    "Şema güvenlik kontrolünün ek alanları geçersiz."
                )
            }
        }
        if authoredTechniqueReplies.contains(value.action) {
            _ = try structuredText(
                value.stepID, field: "Şema adımı", maximum: 120, required: true
            )
            _ = try structuredRequestID(
                value.clientEventID, prefix: "native-schema-technique", maximum: 128
            )
            guard let revision = value.expectedTechniqueRevision, revision >= 0 else {
                throw structuredInvalid("Teknik çalışma revizyonu eksik.")
            }
        }
        if value.action == .groundChatTechnique {
            _ = try structuredText(
                value.stepID, field: "Şema adımı", maximum: 120, required: true
            )
            guard value.clientEventID == nil,
                  let revision = value.expectedTechniqueRevision,
                  revision >= 0,
                  case .number(let rawLink)? =
                    value.values["technique_link_id"],
                  rawLink.isFinite, rawLink.rounded() == rawLink,
                  rawLink > 0, rawLink <= Double(Int.max),
                  case .string(let publicLink)? =
                    value.values["technique_link_public_id"],
                  SchemaPathCheckpoint.isPublicID(publicLink),
                  value.values["control_only"] == .bool(true),
                  Set(value.values.keys) == Set([
                    "technique_link_id", "technique_link_public_id",
                    "control_only",
                  ]) else {
                throw structuredInvalid(
                    "Şimdiye dönüş kontrolünün teknik bağı geçersiz."
                )
            }
        }
        if value.action == .startChatTechnique {
            _ = try structuredText(
                value.stepID, field: "Şema adımı", maximum: 120, required: true
            )
        }
        if value.action == .submitChatTechnique,
           value.values["step_data"] == nil,
           value.values["choice"] == nil,
           value.values["intensity"] == nil {
            throw structuredInvalid("Teknik kontrol yanıtı eksik.")
        }
    }

    static func validateSchemaPathPublicID(_ value: String?) throws {
        guard let value,
              SchemaPathCheckpoint.isPublicID(value) else {
            throw structuredInvalid("Şema çalışma yolu genel kimliği geçersiz.")
        }
    }

    static func validateSchemaCardJSON(_ value: JSONValue, depth: Int) throws {
        guard depth <= 5 else {
            throw structuredInvalid("Şema kartı verisi fazla iç içe.")
        }
        switch value {
        case .string(let text):
            guard text.count <= 2_000,
                  !text.unicodeScalars.contains(where: {
                      CharacterSet.controlCharacters.contains($0)
                          && $0 != "\n" && $0 != "\t"
                  }) else {
                throw structuredInvalid("Şema kartı metni geçersiz.")
            }
        case .number(let number):
            guard number.isFinite else {
                throw structuredInvalid("Şema kartı sayısı geçersiz.")
            }
        case .array(let values):
            guard values.count <= 50 else {
                throw structuredInvalid("Şema kartı listesi fazla uzun.")
            }
            for child in values {
                try validateSchemaCardJSON(child, depth: depth + 1)
            }
        case .object(let values):
            guard values.count <= 50,
                  values.keys.allSatisfy({ !$0.isEmpty && $0.count <= 100 }) else {
                throw structuredInvalid("Şema kartı nesnesi geçersiz.")
            }
            for child in values.values {
                try validateSchemaCardJSON(child, depth: depth + 1)
            }
        case .bool, .null:
            break
        }
    }

    static func structuredInvalid(_ message: String) -> DivanAPIError {
        DivanAPIError(message: message, errorCode: "invalid_request")
    }

    static func structuredPositive(_ value: Int, field: String) throws {
        guard value > 0 else { throw structuredInvalid("\(field) kimliği geçersiz.") }
    }

    static func structuredText(
        _ value: String?, field: String, maximum: Int, required: Bool = false
    ) throws -> String? {
        guard let value else {
            if required { throw structuredInvalid("\(field) boş olamaz.") }
            return nil
        }
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        if required && trimmed.isEmpty {
            throw structuredInvalid("\(field) boş olamaz.")
        }
        guard trimmed.count <= maximum else {
            throw structuredInvalid("\(field) fazla uzun.")
        }
        return trimmed
    }

    static func structuredRequestID(
        _ supplied: String?, prefix: String, maximum: Int
    ) throws -> String {
        let value = supplied?.trimmingCharacters(in: .whitespacesAndNewlines)
            ?? "\(prefix)-\(UUID().uuidString.lowercased())"
        guard (12...maximum).contains(value.count),
              value.first?.isASCII == true,
              value.first?.isLetter == true || value.first?.isNumber == true,
              value.unicodeScalars.allSatisfy({ scalar in
                  (48...57).contains(scalar.value)
                      || (65...90).contains(scalar.value)
                      || (97...122).contains(scalar.value)
                      || scalar == "." || scalar == "_"
                      || scalar == ":" || scalar == "-"
              }) else {
            throw structuredInvalid("İşlem kimliği geçersiz.")
        }
        return value
    }

    static func validateStructured(_ value: ADHDHabitMutation) throws {
        try structuredPositive(value.conversationID, field: "ADHD görüşmesi")
        if let habitID = value.habitID {
            try structuredPositive(habitID, field: "Ritim")
        }
        if let target = value.targetPerWeek, !(1...7).contains(target) {
            throw structuredInvalid("Haftalık hedef 1–7 arasında olmalı.")
        }
        if let days = value.preferredDays,
           Set(days).count != days.count || !days.allSatisfy({ (0...6).contains($0) }) {
            throw structuredInvalid("Tercih edilen günler geçersiz.")
        }
        if let localTime = value.reminderLocalTime, !localTime.isEmpty,
           localTime.range(
               of: #"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$"#,
               options: .regularExpression
           ) == nil {
            throw structuredInvalid("Tercih saati SS:DD biçiminde olmalı.")
        }
        _ = try structuredText(value.title, field: "Ritim adı", maximum: 300,
                               required: value.action == .create)
        _ = try structuredText(value.cue, field: "Başlangıç ipucu", maximum: 500)
        _ = try structuredText(value.tinyAction, field: "Küçük hareket", maximum: 500)
        _ = try structuredText(value.timezone, field: "Saat dilimi", maximum: 64)
        if let timezone = value.timezone, !timezone.isEmpty,
           timezone.range(
               of: #"^[A-Za-z0-9_+\-/]{1,64}$"#,
               options: .regularExpression
           ) == nil {
            throw structuredInvalid("Saat dilimi geçersiz.")
        }

        if value.action != .create, value.habitID == nil {
            throw structuredInvalid("Ritim seçilmedi.")
        }
        if value.action == .update,
           value.title == nil && value.cue == nil && value.tinyAction == nil
            && value.targetPerWeek == nil && value.preferredDays == nil
            && value.reminderLocalTime == nil && value.timezone == nil {
            throw structuredInvalid("Güncellenecek ritim alanı yok.")
        }
        if value.action == .review,
           !["keep", "smaller", "increase", "decrease", "pause"]
            .contains(value.decision ?? "") {
            throw structuredInvalid("Ritim değerlendirmesi seçilmedi.")
        }
        if value.action == .schedule {
            guard let date = value.scheduledFor, date.isFinite,
                  date >= Date().timeIntervalSince1970 + 20,
                  date <= Date().timeIntervalSince1970 + 366 * 86_400 else {
                throw structuredInvalid("Hatırlatıcı 20 saniye–1 yıl sonrasına kurulmalı.")
            }
        }
    }

    static func validateStructured(_ value: ADHDTUSMutation) throws {
        try structuredPositive(value.conversationID, field: "ADHD görüşmesi")
        guard (0..<Int.max).contains(value.expectedRevision) else {
            throw structuredInvalid("TUS çalışma sürümü geçersiz.")
        }
        _ = try structuredRequestID(
            value.requestID, prefix: "native-adhd-tus", maximum: 128
        )
        let questionID = try structuredText(
            value.questionID, field: "TUS sorusu", maximum: 100
        )
        let optionID = try structuredText(
            value.optionID, field: "TUS yanıtı", maximum: 128
        )
        let planID = try structuredText(
            value.planID, field: "TUS planı", maximum: 64
        )
        let stepID = try structuredText(
            value.stepID, field: "TUS adımı", maximum: 64
        )
        switch value.action {
        case .setMode:
            guard value.enabled != nil,
                  questionID == nil, optionID == nil,
                  value.customMinutes == nil, planID == nil, stepID == nil else {
                throw structuredInvalid("TUS modu isteği geçersiz.")
            }
        case .answer:
            guard let questionID, !questionID.isEmpty,
                  ADHDTUSPlannerSnapshot.questionIDs.contains(questionID),
                  let optionID, !optionID.isEmpty,
                  ADHDTUSOption.isCatalogKey(optionID),
                  value.enabled == nil, planID == nil, stepID == nil else {
                throw structuredInvalid("TUS yanıtı eksik veya geçersiz.")
            }
            let fixedOptions: [String: Set<String>] = [
                "activity": ["read", "questions", "mixed", "choose"],
                "available_time": ["5", "15", "25", "45", "custom"],
                "start_friction": ["hard", "normal", "default"],
            ]
            if let allowed = fixedOptions[questionID],
               !allowed.contains(optionID) {
                throw structuredInvalid("TUS yanıtı bu soruya ait değil.")
            }
            if optionID == "custom" {
                guard questionID == "available_time",
                      let minutes = value.customMinutes,
                      (5...180).contains(minutes) else {
                    throw structuredInvalid("Özel süre 5–180 dakika arasında olmalı.")
                }
            } else if value.customMinutes != nil {
                throw structuredInvalid("Bu TUS yanıtı özel süre kabul etmiyor.")
            }
        case .start:
            guard value.enabled == nil, questionID == nil, optionID == nil,
                  value.customMinutes == nil, let planID,
                  ADHDTUSPlan.isPublicID(planID),
                  stepID == nil else {
                throw structuredInvalid("Başlatılacak TUS planı geçersiz.")
            }
        case .completeStep:
            guard value.enabled == nil, questionID == nil, optionID == nil,
                  value.customMinutes == nil,
                  let planID, ADHDTUSPlan.isPublicID(planID),
                  let stepID, ADHDTUSPlan.isPublicID(stepID) else {
                throw structuredInvalid("Tamamlanacak TUS adımı geçersiz.")
            }
        case .finish:
            guard value.enabled == nil, questionID == nil, optionID == nil,
                  value.customMinutes == nil, let planID,
                  ADHDTUSPlan.isPublicID(planID),
                  stepID == nil else {
                throw structuredInvalid("Bitirilecek TUS planı geçersiz.")
            }
        case .cancel:
            guard value.enabled == nil, questionID == nil, optionID == nil,
                  value.customMinutes == nil,
                  planID.map(ADHDTUSPlan.isPublicID) ?? true,
                  stepID == nil else {
                throw structuredInvalid("İptal edilecek TUS planı geçersiz.")
            }
        case .restart, .pause, .resume:
            guard value.enabled == nil, questionID == nil, optionID == nil,
                  value.customMinutes == nil, planID == nil, stepID == nil else {
                throw structuredInvalid("TUS çalışma eylemi geçersiz.")
            }
        }
    }

    static func validateStructured(_ value: ADHDEventMutation) throws {
        try structuredPositive(value.conversationID, field: "ADHD görüşmesi")
        try structuredPositive(value.eventID, field: "Ritim denemesi")
        if let effort = value.effortMinutes, !(0...1_440).contains(effort) {
            throw structuredInvalid("Harcanan süre 0–1440 dakika arasında olmalı.")
        }
        let frictions = Set([
            "", "start", "decision", "sustain", "finish", "emotion", "environment",
        ])
        if let friction = value.friction, !frictions.contains(friction) {
            throw structuredInvalid("Sürtünme alanı geçersiz.")
        }
        _ = try structuredText(value.note, field: "Deneme notu", maximum: 2_000)
        if value.action == .reschedule {
            guard let date = value.scheduledFor, date.isFinite,
                  date >= Date().timeIntervalSince1970 + 20,
                  date <= Date().timeIntervalSince1970 + 366 * 86_400 else {
                throw structuredInvalid("Hatırlatıcı 20 saniye–1 yıl sonrasına kurulmalı.")
            }
        }
    }

    static func validateStructured(_ value: ADHDJournalMutation) throws {
        try structuredPositive(value.conversationID, field: "ADHD görüşmesi")
        if let entryID = value.entryID {
            try structuredPositive(entryID, field: "Defter yazısı")
        }
        if value.action != .create, value.entryID == nil {
            throw structuredInvalid("Defter yazısı seçilmedi.")
        }
        _ = try structuredText(
            value.content, field: "Defter yazısı", maximum: 8_000,
            required: value.action == .create
        )
        if value.sensitive == true && value.shareWithCoach == true {
            throw structuredInvalid("Hassas yazı koçla paylaşılamaz.")
        }
    }

    static func validateStructured(_ value: SchemaPathMutation) throws {
        try structuredPositive(value.conversationID, field: "Şema görüşmesi")
        if value.schemaProtocol != nil || value.flowVersion != nil {
            guard value.action == .start,
                  value.schemaProtocol == "schema_path_chat_v4",
                  value.flowVersion == 4 else {
                throw structuredInvalid("Şema sohbet protokolü geçersiz.")
            }
        }
        if let pathID = value.pathID { try structuredPositive(pathID, field: "Çalışma yolu") }
        let pathActions: Set<SchemaPathAction> = [
            .record, .advance, .offerFocus, .chooseFocus, .declineFocus,
            .recordOrigin, .addGrowthStage, .recordGrowth, .markHealthyAdult,
            .chooseMethod, .assignPractice, .linkTechnique, .pause, .resume,
            .stop, .close,
        ]
        if pathActions.contains(value.action), value.pathID == nil {
            throw structuredInvalid("Çalışma yolu seçilmedi.")
        }
        switch value.action {
        case .reviewCandidate:
            guard let claimID = value.claimID, claimID > 0,
                  let decision = value.decision else {
                throw structuredInvalid("Şema olasılığı kararı eksik.")
            }
            if decision == .contextual {
                _ = try structuredText(
                    value.context, field: "Bağlam", maximum: 300, required: true
                )
            }
            _ = try structuredText(value.note, field: "İnceleme notu", maximum: 700)
        case .start:
            guard let claimID = value.claimID, claimID > 0 else {
                throw structuredInvalid("Şema olasılığı seçilmedi.")
            }
        case .record:
            let kinds = Set([
                "current_trigger", "need", "earlier_echo", "skip_origin",
                "exception", "alternative", "good_enough", "followup",
                "skip_practice",
            ])
            guard let kind = value.kind, kinds.contains(kind) else {
                throw structuredInvalid("Çalışma notu türü geçersiz.")
            }
            _ = try structuredText(
                value.value, field: "Çalışma notu", maximum: 2_000, required: true
            )
        case .advance:
            guard ["focus", "method", "practice", "followup"].contains(value.toPhase ?? "") else {
                throw structuredInvalid("Sonraki çalışma aşaması geçersiz.")
            }
        case .offerFocus:
            guard let candidates = value.focusCandidates,
                  (1...3).contains(candidates.count),
                  Set(candidates.map(\.modeKey)).count == candidates.count else {
                throw structuredInvalid("Birbirinden farklı 1–3 odak adayı gerekli.")
            }
            for candidate in candidates {
                _ = try structuredText(
                    candidate.modeKey, field: "Odak modu", maximum: 80,
                    required: true
                )
                _ = try structuredText(
                    candidate.evidence, field: "Odak dayanağı", maximum: 2_000
                )
            }
        case .chooseFocus:
            _ = try structuredText(
                value.modeKey, field: "Odak modu", maximum: 80, required: true
            )
        case .declineFocus:
            break
        case .dismissSuggestion, .acceptSuggestion:
            guard let suggestionID = value.suggestionID, suggestionID > 0 else {
                throw structuredInvalid("Sohbet içi mod önerisi seçilmedi.")
            }
        case .recordOrigin:
            guard ["reported", "uncertain", "unknown"]
                .contains(value.confidence ?? "") else {
                throw structuredInvalid("Köken kesinliği seçilmedi.")
            }
            guard value.authoredBy == "user" else {
                throw structuredInvalid(
                    "Köken yalnız kullanıcının kendi anlatımından kaydedilebilir."
                )
            }
            if let age = value.age, !(0...120).contains(age) {
                throw structuredInvalid("Köken yaşı geçersiz.")
            }
            _ = try structuredText(
                value.ageRange, field: "Yaş aralığı", maximum: 40
            )
            _ = try structuredText(
                value.scene, field: "Köken sahnesi", maximum: 2_000
            )
            _ = try structuredText(
                value.unmetNeed, field: "Karşılanmayan ihtiyaç", maximum: 2_000
            )
        case .addGrowthStage:
            if let age = value.age, !(0...120).contains(age) {
                throw structuredInvalid("Büyütme basamağı yaşı geçersiz.")
            }
            let label = try structuredText(
                value.label, field: "Büyütme basamağı", maximum: 80
            ) ?? ""
            if value.age == nil && label.isEmpty {
                throw structuredInvalid("Basamak için yaş veya kısa ad gerekli.")
            }
        case .recordGrowth:
            guard let stageID = value.stageID, stageID > 0 else {
                throw structuredInvalid("Büyütme basamağı seçilmedi.")
            }
            guard value.thenResponse != nil || value.nowResponse != nil
                    || value.difference != nil else {
                throw structuredInvalid("Kaydedilecek büyütme yanıtı yok.")
            }
            _ = try structuredText(
                value.thenResponse, field: "O zamanki yanıt", maximum: 2_000
            )
            _ = try structuredText(
                value.nowResponse, field: "Bugünkü yanıt", maximum: 2_000
            )
            _ = try structuredText(
                value.difference, field: "Fark", maximum: 2_000
            )
        case .markHealthyAdult:
            _ = try structuredText(
                value.evidence, field: "Sağlıklı Yetişkin kanıtı",
                maximum: 2_000, required: true
            )
        case .chooseMethod:
            _ = try structuredText(
                value.methodID, field: "Yöntem", maximum: 240, required: true
            )
            guard value.confirmed == true else {
                throw structuredInvalid("Yöntem için açık onay gerekli.")
            }
            if let precheck = value.precheck {
                guard precheck.orientationConfirmed, precheck.realityClear,
                      precheck.sleepActivationClear, (0...7).contains(precheck.intensity) else {
                    throw structuredInvalid("Başlangıç güvenlik kontrolü tamamlanmadı.")
                }
                _ = try structuredText(
                    precheck.stopSignal, field: "Durma işareti", maximum: 120,
                    required: true
                )
            }
        case .assignPractice:
            guard value.userConfirmed == true, let practice = value.experiment else {
                throw structuredInvalid("Küçük deney için açık kullanıcı onayı gerekli.")
            }
            for (field, text) in [
                ("Tek değişken", practice.variable),
                ("Sabit bağlam", practice.constant),
                ("Tahmin", practice.prediction),
                ("Eylem", practice.action),
                ("Gözlenebilir sonuç", practice.observableResult),
                ("En küçük biçim", practice.tinyVersion),
            ] {
                _ = try structuredText(text, field: field, maximum: 500, required: true)
            }
            guard (1...5).contains(practice.targetPerWeek) else {
                throw structuredInvalid("Haftalık küçük deney hedefi 1–5 olmalı.")
            }
        case .linkTechnique:
            guard let runID = value.techniqueRunID, runID > 0 else {
                throw structuredInvalid("Bağlanacak teknik çalışması seçilmedi.")
            }
        case .pause, .resume, .close:
            break
        case .stop:
            _ = try structuredText(value.reason, field: "Durdurma notu", maximum: 500)
        }
    }

    static func validateStructured(
        _ value: SchemaTurnAnalysisMutation
    ) throws {
        try structuredPositive(value.conversationID, field: "Şema görüşmesi")
        switch value.action {
        case .setMode:
            guard let enabled = value.enabled else {
                throw structuredInvalid("Şema terapisi modu seçimi gerekli.")
            }
            if enabled {
                _ = try structuredText(
                    value.providerID, field: "Sağlayıcı", maximum: 64,
                    required: true
                )
                _ = try structuredText(
                    value.modelID, field: "Model", maximum: 200,
                    required: true
                )
            }
        case .analyzeTurn:
            guard let messageID = value.userMessageID, messageID > 0 else {
                throw structuredInvalid("İncelenecek kullanıcı mesajı geçersiz.")
            }
            guard value.consent == true else {
                throw structuredInvalid("Bu tamamlanmış mesaj çifti için açık onay gerekli.")
            }
            _ = try structuredText(
                value.providerID, field: "Sağlayıcı", maximum: 64,
                required: true
            )
            _ = try structuredText(
                value.modelID, field: "Model", maximum: 200,
                required: true
            )
        case .scanHistory:
            guard value.consent == true else {
                throw structuredInvalid("Geçmiş mesaj çiftleri için açık onay gerekli.")
            }
            _ = try structuredText(
                value.providerID, field: "Sağlayıcı", maximum: 64,
                required: true
            )
            _ = try structuredText(
                value.modelID, field: "Model", maximum: 200,
                required: true
            )
        case .retryScan:
            guard let jobID = value.jobID, jobID > 0 else {
                throw structuredInvalid("Yeniden denenecek tarama bulunamadı.")
            }
        }
    }

    static func structuredPut(
        _ value: Int?, key: String, into body: inout [String: JSONValue]
    ) {
        if let value { body[key] = .number(Double(value)) }
    }

    static func structuredPut(
        _ value: Bool?, key: String, into body: inout [String: JSONValue]
    ) {
        if let value { body[key] = .bool(value) }
    }

    static func structuredPut(
        _ value: String?, key: String, into body: inout [String: JSONValue]
    ) {
        if let value { body[key] = .string(value) }
    }
}

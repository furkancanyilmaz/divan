import Foundation
import XCTest
@testable import DivanNative

private enum StructuredTherapyTestFailure: LocalizedError {
    case retryable

    var errorDescription: String? { "Geçici hata" }
}

private actor StructuredTherapyViewModelDataSource: StructuredTherapyDataSource {
    private var startNowRequests: [ADHDHabitMutation] = []
    private var shouldFailFirstStartNow = true
    private var dashboardFailuresRemaining = 0
    private var schemaAnalysisRequests: [SchemaTurnAnalysisMutation] = []
    private var schemaPathRequests: [SchemaPathMutation] = []
    private var configuredSchemaSnapshot: SchemaPathSnapshot?
    private var tusRequests: [ADHDTUSMutation] = []
    private var tusLoadSnapshot = StructuredTherapyViewModelDataSource
        .tusQuestionSnapshot(revision: 3)
    private var tusMutationSnapshot = StructuredTherapyViewModelDataSource
        .tusQuestionSnapshot(
        revision: 4,
        questionID: "lesson",
        optionID: "farmakoloji",
        optionLabel: "Farmakoloji",
        action: "answer",
        ok: true
    )
    private var tusMutationFailuresRemaining = 0
    private var nextTUSMutationAPIError: DivanAPIError?

    func freudImagery(conversationID: Int) async throws -> FreudImageryWorkspace {
        throw StructuredTherapyTestFailure.retryable
    }

    func mutateFreudImagerySelection(
        _ mutation: FreudImagerySelectionMutation
    ) async throws -> FreudImageryMutationResponse {
        throw StructuredTherapyTestFailure.retryable
    }

    func suggestFreudImagery(
        _ mutation: FreudImagerySuggestionMutation
    ) async throws -> FreudImageryMutationResponse {
        throw StructuredTherapyTestFailure.retryable
    }

    func freudImageryCardData(card: FreudImageryCard) async throws -> Data {
        throw StructuredTherapyTestFailure.retryable
    }

    func adhdDashboard(conversationID: Int) async throws -> ADHDWorkspaceSnapshot {
        if dashboardFailuresRemaining > 0 {
            dashboardFailuresRemaining -= 1
            throw StructuredTherapyTestFailure.retryable
        }
        return ADHDWorkspaceSnapshot(
            conversationID: conversationID,
            defaultTargetPerWeek: 2,
            weekStart: 1_786_896_000,
            habits: [Self.habit],
            events: [],
            journalEntries: [],
            weekCounts: [:],
            reviewDue: [],
            notices: ADHDWorkspaceNotices(
                noStreak: nil,
                noShame: nil,
                notDiagnostic: nil,
                monitoring: nil,
                pauseAvailable: nil
            )
        )
    }

    func mutateADHDHabit(
        _ mutation: ADHDHabitMutation
    ) async throws -> ADHDHabitMutationResponse {
        if mutation.action == .startNow {
            startNowRequests.append(mutation)
            if shouldFailFirstStartNow {
                shouldFailFirstStartNow = false
                throw StructuredTherapyTestFailure.retryable
            }
        }
        return ADHDHabitMutationResponse(
            ok: true,
            duplicate: false,
            habit: Self.habit,
            event: nil,
            reminder: nil,
            notices: nil
        )
    }

    func mutateADHDEvent(
        _ mutation: ADHDEventMutation
    ) async throws -> ADHDEventMutationResponse {
        throw StructuredTherapyTestFailure.retryable
    }

    func mutateADHDJournal(
        _ mutation: ADHDJournalMutation
    ) async throws -> ADHDJournalMutationResponse {
        throw StructuredTherapyTestFailure.retryable
    }

    func adhdTUSPlanner(
        conversationID: Int,
        query: String?
    ) async throws -> ADHDTUSPlannerSnapshot {
        tusLoadSnapshot
    }

    func mutateADHDTUS(
        _ mutation: ADHDTUSMutation
    ) async throws -> ADHDTUSPlannerSnapshot {
        tusRequests.append(mutation)
        if let error = nextTUSMutationAPIError {
            nextTUSMutationAPIError = nil
            throw error
        }
        if tusMutationFailuresRemaining > 0 {
            tusMutationFailuresRemaining -= 1
            throw StructuredTherapyTestFailure.retryable
        }
        return tusMutationSnapshot
    }

    func schemaPath(conversationID: Int) async throws -> SchemaPathSnapshot {
        if let configuredSchemaSnapshot { return configuredSchemaSnapshot }
        return SchemaPathSnapshot(
            version: 1,
            activePath: nil,
            candidates: [],
            methods: [],
            notices: [],
            allowedActions: [],
            completedTurns: 0,
            minimumListeningTurns: 3,
            turnAnalysis: SchemaTurnAnalysisState(
                analysisUnit: "completed_user_assistant_turn",
                status: "idle",
                processing: false,
                eligibleTurns: 0,
                analyzedTurns: 0,
                remainingTurns: 0,
                callsRemaining: 0,
                failedTurns: 0,
                safetySkippedTurns: 0,
                throughMessageId: 0,
                targetMessageId: 0,
                analyzedUserMessageIds: [],
                processingUserMessageIds: [],
                failedUserMessageIds: [],
                errorCode: nil,
                provider: SchemaTurnAnalysisProvider(
                    id: "lmstudio",
                    label: "LM Studio / Yerel",
                    model: "local-model",
                    local: true
                ),
                job: nil
            )
        )
    }

    func mutateSchemaPath(
        _ mutation: SchemaPathMutation
    ) async throws -> SchemaPathMutationResponse {
        schemaPathRequests.append(mutation)
        let value: SchemaPathSnapshot
        if let configuredSchemaSnapshot {
            value = configuredSchemaSnapshot
        } else {
            value = try await schemaPath(conversationID: mutation.conversationID)
        }
        return SchemaPathMutationResponse(
            ok: true,
            duplicate: false,
            version: value.version,
            protocol: value.protocol,
            presentation: value.presentation,
            stage: value.stage,
            step: value.step,
            revision: value.revision,
            progress: value.progress,
            nextCard: value.nextCard,
            messageMeta: value.messageMeta,
            interactionPolicy: value.interactionPolicy,
            resumeState: value.resumeState,
            clinicalSync: value.clinicalSync,
            activePath: value.activePath,
            candidates: value.candidates,
            queuedCandidates: value.queuedCandidates,
            queuedCount: value.queuedCount,
            activePathNotice: value.activePathNotice,
            methods: value.methods,
            notices: value.notices,
            allowedActions: value.allowedActions,
            completedTurns: value.completedTurns,
            minimumListeningTurns: value.minimumListeningTurns,
            schemaMode: value.schemaMode,
            turnAnalysis: value.turnAnalysis,
            candidate: nil,
            focus: value.focus,
            inlineSuggestions: value.inlineSuggestions,
            focusMinimumTurns: value.focusMinimumTurns,
            origin: value.origin,
            growth: value.growth,
            healthyAdult: value.healthyAdult
        )
    }

    func mutateSchemaTurnAnalysis(
        _ mutation: SchemaTurnAnalysisMutation
    ) async throws -> SchemaTurnAnalysisMutationResponse {
        schemaAnalysisRequests.append(mutation)
        return SchemaTurnAnalysisMutationResponse(
            ok: true,
            processing: false,
            queued: false,
            alreadyAnalyzed: false,
            jobId: nil,
            userMessageId: mutation.userMessageID,
            message: nil,
            turnAnalysis: nil,
            schemaMode: nil
        )
    }

    func capturedStartNowRequests() -> [ADHDHabitMutation] { startNowRequests }
    func capturedSchemaAnalysisRequests() -> [SchemaTurnAnalysisMutation] {
        schemaAnalysisRequests
    }
    func capturedSchemaPathRequests() -> [SchemaPathMutation] {
        schemaPathRequests
    }
    func capturedTUSRequests() -> [ADHDTUSMutation] { tusRequests }
    func setSchemaSnapshot(_ value: SchemaPathSnapshot) {
        configuredSchemaSnapshot = value
    }
    func failNextDashboard() { dashboardFailuresRemaining += 1 }
    func failNextTUSMutation() { tusMutationFailuresRemaining += 1 }
    func failNextTUSMutation(with error: DivanAPIError) {
        nextTUSMutationAPIError = error
    }
    func setTUSLoadSnapshot(_ value: ADHDTUSPlannerSnapshot) {
        tusLoadSnapshot = value
    }
    func setTUSMutationSnapshot(_ value: ADHDTUSPlannerSnapshot) {
        tusMutationSnapshot = value
    }

    static func tusQuestionSnapshot(
        revision: Int,
        questionID: String = "activity",
        optionID: String = "questions",
        optionLabel: String = "Soru çözelim",
        allowedActions: [String] = ["answer", "restart", "set_mode"],
        action: String? = nil,
        ok: Bool? = nil
    ) -> ADHDTUSPlannerSnapshot {
        var options = [ADHDTUSOption(
            id: optionID,
            label: optionLabel,
            description: nil
        )]
        if questionID == "activity" && optionID != "choose" {
            options.append(ADHDTUSOption(
                id: "choose",
                label: "Sen seç",
                description: nil
            ))
        }
        return ADHDTUSPlannerSnapshot(
            protocol: "adhd_tus_planner_v1",
            conversationID: 12,
            revision: revision,
            enabled: true,
            state: "question",
            history: [],
            question: ADHDTUSQuestion(
                id: questionID,
                prompt: questionID == "activity" ? "Bugün nasıl çalışalım?" : "Hangi ders?",
                options: options,
                totalOptions: options.count,
                filterable: ["lesson", "reading_area", "question_area"]
                    .contains(questionID),
                hasMore: false
            ),
            plan: nil,
            allowedActions: allowedActions,
            catalog: ADHDTUSCatalogSummary(
                available: true,
                errorCode: nil,
                fingerprint: "sha256:" + String(repeating: "a", count: 64),
                lessons: 12,
                questionAreas: 707,
                readingAreas: 480,
                questionCount: 11_438,
                tusDefaultQuestionCount: 10_900,
                sentenceCount: 39_100
            ),
            catalogChanged: false,
            notices: ADHDTUSNotices(
                noStreak: "Seri yok.",
                noDebt: "Borç yok.",
                localOnly: "Yalnız bu cihazda.",
                contentBoundary: "Yalnız metadata."
            ),
            safetyHold: false,
            ok: ok,
            duplicate: ok.map { _ in false },
            action: action
        )
    }

    static let habit = ADHDHabit(
        id: 8,
        sourceConv: 12,
        title: "Defteri aç",
        cue: "Kahveden sonra",
        tinyAction: "Tek satır yaz",
        targetPerWeek: 3,
        preferredDays: [1, 3, 5],
        reminderLocalTime: nil,
        timezone: "Europe/Istanbul",
        status: "active",
        reviewAfter: nil,
        reviewDue: false,
        lastReviewedAt: nil,
        isGuest: false,
        created: nil,
        updated: nil
    )
}

@MainActor
final class StructuredTherapyViewModelTests: XCTestCase {
    func testADHDStartNowRetainsRequestIDUntilMutationAndRefreshBothSucceed() async throws {
        let source = StructuredTherapyViewModelDataSource()
        let model = ADHDWorkspaceViewModel(dataSource: source, conversationID: 12)
        let habit = StructuredTherapyViewModelDataSource.habit

        await model.startNow(habit)
        XCTAssertEqual(model.failure?.message, "Geçici hata")

        await source.failNextDashboard()
        await model.startNow(habit)
        XCTAssertEqual(model.failure?.title, "Kaydedildi; görünüm yenilenemedi")

        await model.startNow(habit)
        XCTAssertNil(model.failure)
        XCTAssertEqual(model.statusMessage, "Deneme başladı. Bildirim kurulmadı.")

        await model.startNow(habit)
        let requests = await source.capturedStartNowRequests()
        XCTAssertEqual(requests.count, 4)
        let firstID = try XCTUnwrap(requests[0].requestID)
        XCTAssertEqual(requests[1].requestID, firstID)
        XCTAssertEqual(requests[2].requestID, firstID)
        XCTAssertNotEqual(requests[3].requestID, firstID)
        XCTAssertTrue(requests.allSatisfy { $0.action == .startNow })
        XCTAssertTrue(requests.allSatisfy { $0.scheduledFor == nil })
    }

    func testADHDTUSAnswerBindsVisibleQuestionRevisionAndStableRetryID() async throws {
        let source = StructuredTherapyViewModelDataSource()
        await source.failNextTUSMutation()
        let model = ADHDWorkspaceViewModel(dataSource: source, conversationID: 12)
        await model.reloadTUS()
        let question = try XCTUnwrap(model.tusSnapshot?.question)
        let option = try XCTUnwrap(question.options.first)

        await model.answerTUS(question, option: option)
        XCTAssertEqual(model.failure?.message, "Geçici hata")
        XCTAssertEqual(model.tusSnapshot?.revision, 3)

        await model.answerTUS(question, option: option)
        XCTAssertNil(model.failure)
        XCTAssertEqual(model.tusSnapshot?.revision, 4)
        XCTAssertEqual(model.tusSnapshot?.question?.id, "lesson")

        let requests = await source.capturedTUSRequests()
        XCTAssertEqual(requests.count, 2)
        XCTAssertEqual(requests[0].action, .answer)
        XCTAssertEqual(requests[0].expectedRevision, 3)
        XCTAssertEqual(requests[0].questionID, "activity")
        XCTAssertEqual(requests[0].optionID, "questions")
        XCTAssertEqual(requests[1].requestID, requests[0].requestID)
    }

    func testADHDTUSRejectsHiddenActionAndStaleQuestionBeforeDataSource() async throws {
        let source = StructuredTherapyViewModelDataSource()
        let model = ADHDWorkspaceViewModel(dataSource: source, conversationID: 12)
        await model.reloadTUS()
        let current = try XCTUnwrap(model.tusSnapshot?.question)

        await model.pauseTUS()
        XCTAssertEqual(model.failure?.title, "TUS işlemi artık kullanılamıyor")
        var requests = await source.capturedTUSRequests()
        XCTAssertTrue(requests.isEmpty)

        let forged = ADHDTUSQuestion(
            id: current.id,
            prompt: current.prompt,
            options: [ADHDTUSOption(
                id: "read", label: "Konu okuyalım", description: nil
            )],
            totalOptions: 1,
            filterable: false,
            hasMore: false
        )
        await model.answerTUS(forged, option: forged.options[0])
        XCTAssertEqual(model.failure?.title, "TUS sorusu güncel değil")
        requests = await source.capturedTUSRequests()
        XCTAssertTrue(requests.isEmpty)
    }

    func testADHDTUSStaleMutationResponseFailsClosedUntilReload() async throws {
        let source = StructuredTherapyViewModelDataSource()
        await source.setTUSMutationSnapshot(StructuredTherapyViewModelDataSource.tusQuestionSnapshot(
            revision: 3,
            action: "answer",
            ok: true
        ))
        let model = ADHDWorkspaceViewModel(dataSource: source, conversationID: 12)
        await model.reloadTUS()
        let question = try XCTUnwrap(model.tusSnapshot?.question)
        let option = try XCTUnwrap(question.options.first)

        await model.answerTUS(question, option: option)

        XCTAssertNil(model.tusSnapshot)
        XCTAssertEqual(model.failure?.title, "TUS işlemi tamamlanamadı")
        XCTAssertEqual(model.failure?.message, "TUS çalışma yanıtı güncel değil.")
        await model.loadTUSIfNeeded()
        XCTAssertEqual(model.tusSnapshot?.revision, 3)
    }

    func testADHDTUSConflictAndCatalogMismatchFailClosedUntilReload() async throws {
        let failures = [
            DivanAPIError(
                message: "Adım artık güncel değil.",
                statusCode: 409,
                errorCode: "tus_step_mismatch"
            ),
            DivanAPIError(
                message: "Katalog kullanılamıyor.",
                statusCode: 503,
                errorCode: "tus_catalog_unavailable"
            ),
        ]

        for error in failures {
            let source = StructuredTherapyViewModelDataSource()
            let model = ADHDWorkspaceViewModel(dataSource: source, conversationID: 12)
            await model.reloadTUS()
            let question = try XCTUnwrap(model.tusSnapshot?.question)
            let option = try XCTUnwrap(question.options.first)
            await source.failNextTUSMutation(with: error)

            await model.answerTUS(question, option: option)

            XCTAssertNil(model.tusSnapshot)
            XCTAssertEqual(model.failure?.title, "TUS işlemi tamamlanamadı")
            await model.loadTUSIfNeeded()
            XCTAssertEqual(model.tusSnapshot?.revision, 3)
        }
    }

    func testJournalPrivacyControlsRemainMutuallyExclusive() {
        let source = StructuredTherapyViewModelDataSource()
        let model = ADHDWorkspaceViewModel(dataSource: source, conversationID: 12)

        XCTAssertTrue(model.journalSensitive)
        XCTAssertFalse(model.journalShareWithCoach)

        model.setJournalSharing(true)
        XCTAssertTrue(model.journalShareWithCoach)
        XCTAssertFalse(model.journalSensitive)

        model.setJournalSensitive(true)
        XCTAssertTrue(model.journalSensitive)
        XCTAssertFalse(model.journalShareWithCoach)
    }

    func testSchemaModeNeverEnablesWithoutFreshExplicitFutureTurnConsent() async {
        let source = StructuredTherapyViewModelDataSource()
        let model = SchemaPathViewModel(dataSource: source, conversationID: 12)
        await model.reload()

        await model.setSchemaMode(enabled: true)
        XCTAssertEqual(model.failure?.title, "Açık onay gerekli")
        let requestsBeforeConsent = await source.capturedSchemaAnalysisRequests()
        XCTAssertTrue(requestsBeforeConsent.isEmpty)

        model.modeEnableConfirmed = true
        await model.setSchemaMode(enabled: true)
        let requests = await source.capturedSchemaAnalysisRequests()
        XCTAssertEqual(requests.count, 1)
        XCTAssertEqual(requests.first?.action, .setMode)
        XCTAssertEqual(requests.first?.enabled, true)
        XCTAssertEqual(requests.first?.providerID, "lmstudio")
        XCTAssertEqual(requests.first?.modelID, "local-model")
        XCTAssertNil(requests.first?.consent)
        XCTAssertFalse(model.modeEnableConfirmed)
        XCTAssertEqual(
            model.statusMessage,
            "Bu cihaz için Şema terapisi modu onaylandı. Yalnız bundan sonra tamamlanan mesaj çiftleri incelenecek."
        )
    }

    func testExplorationAdvancesThroughExplicitFocusBeforeMethod() async throws {
        let source = StructuredTherapyViewModelDataSource()
        await source.setSchemaSnapshot(Self.schemaSnapshot(
            phase: "explore",
            allowedActions: ["record", "advance"]
        ))
        let model = SchemaPathViewModel(dataSource: source, conversationID: 12)
        await model.reload()
        model.currentTrigger = "Birinin uzaklaşması"
        model.need = "Güven ve açıklık"

        await model.saveExploration()

        XCTAssertNil(model.failure)
        let requests = await source.capturedSchemaPathRequests()
        XCTAssertEqual(requests.map(\.action), [.record, .record, .advance])
        XCTAssertEqual(requests.last?.toPhase, "focus")
        XCTAssertFalse(requests.contains { $0.toPhase == "method" })
    }

    func testOriginIsAlwaysUserAuthoredAndUnknownNeedsNoInventedAge() async {
        let source = StructuredTherapyViewModelDataSource()
        await source.setSchemaSnapshot(Self.schemaSnapshot(
            phase: "focus",
            allowedActions: ["record_origin"]
        ))
        let model = SchemaPathViewModel(dataSource: source, conversationID: 12)
        await model.reload()
        model.originConfidence = "unknown"
        model.originScene = "Yalnız hatırladığım kadarı"

        await model.saveOrigin()

        XCTAssertNil(model.failure)
        let request = await source.capturedSchemaPathRequests().last
        XCTAssertEqual(request?.action, .recordOrigin)
        XCTAssertEqual(request?.authoredBy, "user")
        XCTAssertNil(request?.age)
        XCTAssertEqual(request?.confidence, "unknown")
    }

    private static func schemaSnapshot(
        phase: String,
        allowedActions: [String]
    ) -> SchemaPathSnapshot {
        SchemaPathSnapshot(
            version: 3,
            activePath: SchemaPath(
                id: 44,
                convId: 12,
                therapist: "young",
                claimId: 91,
                candidate: nil,
                phase: phase,
                status: "active",
                methodId: nil,
                method: nil,
                techniqueRunId: nil,
                practice: nil,
                records: [:],
                revision: 1,
                created: nil,
                updated: nil,
                closedAt: nil
            ),
            candidates: [],
            methods: [],
            notices: [],
            allowedActions: allowedActions,
            completedTurns: 3,
            minimumListeningTurns: 1,
            focus: SchemaFocusState(offer: nil, chosen: nil),
            focusMinimumTurns: 3,
            origin: SchemaOriginState(
                recorded: false,
                status: nil,
                age: nil,
                ageRange: "",
                scene: "",
                unmetNeed: "",
                confidence: "unknown",
                updated: nil
            ),
            growth: SchemaGrowthState(
                stages: [], comparableCount: 0, maxStages: 6
            ),
            healthyAdult: SchemaHealthyAdultState(count: 0, recent: [])
        )
    }
}

import Foundation
import XCTest
@testable import DivanNative

@MainActor
final class AdvancedWorkspaceSafetyTests: XCTestCase {
    func testChairStartValidationIsVisibleAndNeverCallsAdapter() async {
        let source = AdvancedSafetyDataSource()
        let model = makeModel(source)
        await model.reloadWorkspace()

        await model.startChairWork()

        XCTAssertEqual(model.failure?.title, "Devam etmek için")
        XCTAssertEqual(
            model.failure?.message,
            AdvancedWorkspaceValidationError.explicitConsentRequired.localizedDescription
        )
        let callCount = await source.chairStartCallCount()
        XCTAssertEqual(callCount, 0)

        model.chairOrientationConfirmed = true
        model.chairFrameConfirmed = true
        await model.startChairWork()

        XCTAssertEqual(model.failure?.title, "Devam etmek için")
        XCTAssertEqual(
            model.failure?.message,
            AdvancedWorkspaceValidationError.emptyResponse.localizedDescription
        )
        let countAfterIncompleteForm = await source.chairStartCallCount()
        XCTAssertEqual(countAfterIncompleteForm, 0)
    }

    func testValidChairStartForwardsEveryUserAuthoredField() async throws {
        let source = AdvancedSafetyDataSource()
        let model = makeModel(source)
        await model.reloadWorkspace()

        model.chairGoalText = "  Eleştirel ses ile incinmiş yanımı ayırmak  "
        model.chairStopSignal = "  Şimdi dur  "
        model.chairParticipantTitles = [
            "  İncinmiş çocuğum  ",
            "  Talepkâr ebeveyn sesi  ",
        ]
        model.chairIntensity = 4
        model.chairOrientationConfirmed = true
        model.chairFrameConfirmed = true

        await model.startChairWork()

        let captured = await source.capturedChairStart()
        let startCalls = await source.chairStartCallCount()
        let request = try XCTUnwrap(captured)
        XCTAssertEqual(startCalls, 1)
        XCTAssertEqual(request.conversationID, 12)
        XCTAssertEqual(request.goalText, "Eleştirel ses ile incinmiş yanımı ayırmak")
        XCTAssertEqual(request.stopSignal, "Şimdi dur")
        XCTAssertEqual(
            request.participantTitles,
            ["İncinmiş çocuğum", "Talepkâr ebeveyn sesi"]
        )
        XCTAssertEqual(request.startingParticipantIndex, 0)
        XCTAssertEqual(request.intensity, 4)
        XCTAssertTrue(request.orientationConfirmed)
        XCTAssertTrue(request.frameConfirmed)
        XCTAssertEqual(model.chairSession?.phase, .active)
        XCTAssertNil(model.failure)
        XCTAssertFalse(model.chairOrientationConfirmed)
        XCTAssertFalse(model.chairFrameConfirmed)
    }

    func testValidChairStartAdapterFailureBecomesVisibleState() async {
        let source = AdvancedSafetyDataSource(failingStart: .chair)
        let model = makeModel(source)
        await model.reloadWorkspace()

        model.chairGoalText = "Eleştirel ses ile incinmiş yanımı ayırmak"
        model.chairStopSignal = "Şimdi dur"
        model.chairParticipantTitles = ["İncinmiş çocuğum", "Eleştirel ses"]
        model.chairIntensity = 4
        model.chairOrientationConfirmed = true
        model.chairFrameConfirmed = true

        await model.startChairWork()

        let calls = await source.chairStartCallCount()
        XCTAssertEqual(calls, 1)
        XCTAssertNil(model.chairSession)
        XCTAssertEqual(model.failure?.title, "İşlem tamamlanamadı")
        XCTAssertEqual(model.failure?.message, "Sandalye çalışması başlatılamadı.")
        XCTAssertTrue(model.chairOrientationConfirmed)
        XCTAssertTrue(model.chairFrameConfirmed)
    }

    func testImageryStartValidationIsVisibleAndNeverCallsAdapter() async {
        let source = AdvancedSafetyDataSource()
        let model = makeModel(source)
        await model.reloadWorkspace()
        model.selectModule(.reparenting)

        await model.startImagery()

        XCTAssertEqual(model.failure?.title, "Devam etmek için")
        XCTAssertEqual(
            model.failure?.message,
            AdvancedWorkspaceValidationError.explicitConsentRequired.localizedDescription
        )
        let callCount = await source.imageryStartCallCount()
        XCTAssertEqual(callCount, 0)

        model.imageryOrientationConfirmed = true
        model.imageryFrameConfirmed = true
        model.imageryRealityConfirmed = true
        await model.startImagery()

        XCTAssertEqual(model.failure?.title, "Devam etmek için")
        XCTAssertEqual(
            model.failure?.message,
            AdvancedWorkspaceValidationError.emptyResponse.localizedDescription
        )
        let countAfterIncompleteForm = await source.imageryStartCallCount()
        XCTAssertEqual(countAfterIncompleteForm, 0)
    }

    func testValidImageryStartForwardsEveryFreshConfirmationAndBoundary() async throws {
        let source = AdvancedSafetyDataSource()
        let model = makeModel(source)
        await model.reloadWorkspace()
        model.selectModule(.reparenting)

        model.imageryIntention = "  Bugün görülme ihtiyacıma yaklaşmak  "
        model.imageryStopSignal = "  Burada dur  "
        model.imagerySceneBoundary = "  Odayı fark ederek uzaktan izleyeceğim  "
        model.imageryIntensity = 5
        model.imageryOrientationConfirmed = true
        model.imageryFrameConfirmed = true
        model.imageryRealityConfirmed = true

        await model.startImagery()

        let captured = await source.capturedImageryStart()
        let startCalls = await source.imageryStartCallCount()
        let request = try XCTUnwrap(captured)
        XCTAssertEqual(startCalls, 1)
        XCTAssertEqual(request.conversationID, 12)
        XCTAssertEqual(request.intention, "Bugün görülme ihtiyacıma yaklaşmak")
        XCTAssertEqual(request.stopSignal, "Burada dur")
        XCTAssertEqual(
            request.sceneBoundary,
            "Odayı fark ederek uzaktan izleyeceğim"
        )
        XCTAssertEqual(request.intensity, 5)
        XCTAssertTrue(request.orientationConfirmed)
        XCTAssertTrue(request.frameConfirmed)
        XCTAssertTrue(request.realityConfirmed)
        XCTAssertEqual(model.imagerySession?.phase, .active)
        XCTAssertNil(model.failure)
        XCTAssertFalse(model.imageryOrientationConfirmed)
        XCTAssertFalse(model.imageryFrameConfirmed)
        XCTAssertFalse(model.imageryRealityConfirmed)
    }

    func testValidImageryStartAdapterFailureBecomesVisibleState() async {
        let source = AdvancedSafetyDataSource(failingStart: .imagery)
        let model = makeModel(source)
        await model.reloadWorkspace()
        model.selectModule(.reparenting)

        model.imageryIntention = "Bugün görülme ihtiyacıma yaklaşmak"
        model.imageryStopSignal = "Burada dur"
        model.imagerySceneBoundary = "Odayı fark ederek uzaktan izleyeceğim"
        model.imageryIntensity = 5
        model.imageryOrientationConfirmed = true
        model.imageryFrameConfirmed = true
        model.imageryRealityConfirmed = true

        await model.startImagery()

        let calls = await source.imageryStartCallCount()
        XCTAssertEqual(calls, 1)
        XCTAssertNil(model.imagerySession)
        XCTAssertEqual(model.failure?.title, "İşlem tamamlanamadı")
        XCTAssertEqual(model.failure?.message, "İmgeleme çalışması başlatılamadı.")
        XCTAssertTrue(model.imageryOrientationConfirmed)
        XCTAssertTrue(model.imageryFrameConfirmed)
        XCTAssertTrue(model.imageryRealityConfirmed)
    }

    func testChairResumeForwardsFreshUserConfirmationsAndIntensity() async throws {
        let paused = makeChairSession(phase: .paused, intensity: 6, limit: 7)
        let source = AdvancedSafetyDataSource(chair: paused)
        let model = makeModel(source)
        await model.reloadWorkspace()

        model.chairResumeOrientationConfirmed = true
        model.chairResumeGroundingConfirmed = true
        model.chairIntensity = 3
        await model.resumeChairWork()

        let capturedResume = await source.capturedChairResume()
        let request = try XCTUnwrap(capturedResume)
        XCTAssertEqual(request.sessionID, paused.id)
        XCTAssertTrue(request.orientationConfirmed)
        XCTAssertTrue(request.groundingConfirmed)
        XCTAssertEqual(request.currentIntensity, 3)
        XCTAssertEqual(model.chairSession?.phase, .active)
        XCTAssertFalse(model.chairResumeOrientationConfirmed)
        XCTAssertFalse(model.chairResumeGroundingConfirmed)
    }

    func testChairGroundForwardsExplicitCheckpointOrientationAndIntensity() async throws {
        let active = makeChairSession(phase: .active, intensity: 5, limit: 7)
        let source = AdvancedSafetyDataSource(chair: active)
        let model = makeModel(source)
        await model.reloadWorkspace()

        model.chairClosureAction = .ground
        model.chairClosureCheckpointConfirmed = true
        model.chairClosureOrientationConfirmed = true
        model.chairIntensity = 2
        await model.advanceChairClosure()

        let capturedClosure = await source.capturedChairClosure()
        let request = try XCTUnwrap(capturedClosure)
        XCTAssertEqual(request.sessionID, active.id)
        XCTAssertEqual(request.action, .ground)
        XCTAssertTrue(request.checkpointConfirmed)
        XCTAssertTrue(request.orientationConfirmed)
        XCTAssertEqual(request.currentIntensity, 2)
        XCTAssertEqual(model.chairSession?.phase, .paused)
    }

    func testChairStopPreemptsBusyGuidanceAndStaleResultCannotReopenWork() async {
        let active = makeChairSession(phase: .active)
        let source = AdvancedSafetyDataSource(chair: active)
        await source.suspendNextChairGuidance()
        let model = makeModel(source)
        await model.reloadWorkspace()

        let guidance = Task { await model.requestChairGuidance() }
        await source.waitUntilChairGuidanceStarted()
        XCTAssertTrue(model.isPerformingAction)

        await model.stopChairWork()
        XCTAssertEqual(model.chairSession?.phase, .completed)
        let chairStopCount = await source.chairStopCallCount()
        XCTAssertEqual(chairStopCount, 1)

        await source.releaseChairGuidance()
        await guidance.value
        XCTAssertEqual(
            model.chairSession?.phase,
            .completed,
            "A late guidance response must never overwrite a terminal stop."
        )
    }

    func testImageryStopPreemptsBusyResumeAndStaleResultCannotReopenWork() async {
        let paused = makeImagerySession(phase: .paused)
        let source = AdvancedSafetyDataSource(imagery: paused)
        await source.suspendNextImageryResume()
        let model = makeModel(source)
        await model.reloadWorkspace()

        model.imageryResumeOrientationConfirmed = true
        model.imageryIntensity = 3
        let resume = Task { await model.resumeImagery() }
        await source.waitUntilImageryResumeStarted()
        XCTAssertTrue(model.isPerformingAction)

        await model.stopImagery()
        XCTAssertEqual(model.imagerySession?.phase, .completed)
        let imageryStopCount = await source.imageryStopCallCount()
        XCTAssertEqual(imageryStopCount, 1)

        await source.releaseImageryResume()
        await resume.value
        XCTAssertEqual(
            model.imagerySession?.phase,
            .completed,
            "A late imagery response must never overwrite a terminal stop."
        )
    }

    private func makeModel(
        _ source: AdvancedSafetyDataSource
    ) -> AdvancedWorkspaceViewModel {
        AdvancedWorkspaceViewModel(
            dataSource: source,
            context: AdvancedWorkspaceContext(
                conversationID: 12,
                masterID: "young",
                masterName: "Jeffrey Young",
                allowsClinicalWork: true
            )
        )
    }
}

actor AdvancedSafetyDataSource: AdvancedWorkspaceDataSource {
    private let initialChair: WorkspaceChairSession?
    private let initialImagery: WorkspaceImagerySession?
    private let failingStart: AdvancedStartFailure?
    private let chairIsAvailable: Bool
    private let chairReason: String?
    private let imageryIsAvailable: Bool
    private let imageryReason: String?
    private var lastChairStart: WorkspaceChairStartRequest?
    private var lastImageryStart: WorkspaceImageryStartRequest?
    private var chairStarts = 0
    private var imageryStarts = 0
    private var lastChairResume: WorkspaceChairResumeRequest?
    private var lastChairClosure: WorkspaceChairClosureRequest?
    private var chairStops = 0
    private var imageryStops = 0

    private var holdChairGuidance = false
    private var chairGuidanceStarted = false
    private var chairGuidanceContinuation: CheckedContinuation<Void, Never>?
    private var holdImageryResume = false
    private var imageryResumeStarted = false
    private var imageryResumeContinuation: CheckedContinuation<Void, Never>?

    init(
        chair: WorkspaceChairSession? = nil,
        imagery: WorkspaceImagerySession? = nil,
        failingStart: AdvancedStartFailure? = nil,
        chairAvailable: Bool = true,
        chairUnavailableReason: String? = nil,
        imageryAvailable: Bool = true,
        imageryUnavailableReason: String? = nil
    ) {
        initialChair = chair
        initialImagery = imagery
        self.failingStart = failingStart
        chairIsAvailable = chairAvailable
        chairReason = chairUnavailableReason
        imageryIsAvailable = imageryAvailable
        imageryReason = imageryUnavailableReason
    }

    func capturedChairResume() -> WorkspaceChairResumeRequest? { lastChairResume }
    func capturedChairClosure() -> WorkspaceChairClosureRequest? { lastChairClosure }
    func capturedChairStart() -> WorkspaceChairStartRequest? { lastChairStart }
    func capturedImageryStart() -> WorkspaceImageryStartRequest? { lastImageryStart }
    func chairStartCallCount() -> Int { chairStarts }
    func imageryStartCallCount() -> Int { imageryStarts }
    func chairStopCallCount() -> Int { chairStops }
    func imageryStopCallCount() -> Int { imageryStops }

    func suspendNextChairGuidance() { holdChairGuidance = true }
    func waitUntilChairGuidanceStarted() async {
        while !chairGuidanceStarted { await Task.yield() }
    }
    func releaseChairGuidance() {
        holdChairGuidance = false
        chairGuidanceContinuation?.resume()
        chairGuidanceContinuation = nil
    }

    func suspendNextImageryResume() { holdImageryResume = true }
    func waitUntilImageryResumeStarted() async {
        while !imageryResumeStarted { await Task.yield() }
    }
    func releaseImageryResume() {
        holdImageryResume = false
        imageryResumeContinuation?.resume()
        imageryResumeContinuation = nil
    }

    func advancedWorkspaceSnapshot(
        context: AdvancedWorkspaceContext
    ) async throws -> AdvancedWorkspaceSnapshot {
        AdvancedWorkspaceSnapshot(
            clinicalIntensityLimit: 7,
            chairAvailable: chairIsAvailable,
            chairUnavailableReason: chairReason,
            imageryAvailable: imageryIsAvailable,
            imageryUnavailableReason: imageryReason,
            chairSession: initialChair,
            imagerySession: initialImagery
        )
    }

    func startChairWork(
        request: WorkspaceChairStartRequest
    ) async throws -> WorkspaceChairSession {
        chairStarts += 1
        lastChairStart = request
        if failingStart == .chair {
            throw AdvancedSafetyTestError.chairStartFailed
        }
        return makeChairSession(phase: .active, intensity: request.intensity)
    }

    func addChairTurn(
        sessionID: String,
        chairID: String,
        content: String,
        intensity: Int
    ) async throws -> WorkspaceChairSession {
        makeChairSession(phase: .active, intensity: intensity)
    }

    func selectChair(
        sessionID: String,
        chairID: String
    ) async throws -> WorkspaceChairSession {
        makeChairSession(phase: .active)
    }

    func addChairParticipant(
        sessionID: String,
        title: String
    ) async throws -> WorkspaceChairSession {
        makeChairSession(phase: .active)
    }

    func requestChairGuidance(
        sessionID: String
    ) async throws -> WorkspaceChairSession {
        if holdChairGuidance {
            chairGuidanceStarted = true
            await withCheckedContinuation { continuation in
                chairGuidanceContinuation = continuation
            }
        }
        return makeChairSession(phase: .active)
    }

    func resumeChairWork(
        request: WorkspaceChairResumeRequest
    ) async throws -> WorkspaceChairSession {
        lastChairResume = request
        return makeChairSession(
            phase: .active,
            intensity: request.currentIntensity
        )
    }

    func advanceChairClosure(
        request: WorkspaceChairClosureRequest
    ) async throws -> WorkspaceChairSession {
        lastChairClosure = request
        let phase: WorkspaceWorkPhase = request.action == .complete
            ? .completed : .paused
        return makeChairSession(
            phase: phase,
            intensity: request.currentIntensity
        )
    }

    func stopChairWork(
        sessionID: String
    ) async throws -> WorkspaceChairSession {
        chairStops += 1
        return makeChairSession(phase: .completed)
    }

    func startImagery(
        request: WorkspaceImageryStartRequest
    ) async throws -> WorkspaceImagerySession {
        imageryStarts += 1
        lastImageryStart = request
        if failingStart == .imagery {
            throw AdvancedSafetyTestError.imageryStartFailed
        }
        return makeImagerySession(phase: .active, intensity: request.intensity)
    }

    func respondToImageryCheckpoint(
        response: WorkspaceImageryCheckpointResponse
    ) async throws -> WorkspaceImagerySession {
        makeImagerySession(phase: .active, intensity: response.currentIntensity)
    }

    func groundImagery(
        request: WorkspaceImageryGroundRequest
    ) async throws -> WorkspaceImagerySession {
        makeImagerySession(phase: .paused, intensity: request.currentIntensity)
    }

    func pauseImagery(
        sessionID: String
    ) async throws -> WorkspaceImagerySession {
        makeImagerySession(phase: .paused)
    }

    func resumeImagery(
        request: WorkspaceImageryResumeRequest
    ) async throws -> WorkspaceImagerySession {
        if holdImageryResume {
            imageryResumeStarted = true
            await withCheckedContinuation { continuation in
                imageryResumeContinuation = continuation
            }
        }
        return makeImagerySession(
            phase: .active,
            intensity: request.currentIntensity
        )
    }

    func finishImagery(
        request: WorkspaceImageryFinishRequest
    ) async throws -> WorkspaceImagerySession {
        makeImagerySession(
            phase: .completed,
            intensity: request.currentIntensity
        )
    }

    func stopImagery(
        sessionID: String
    ) async throws -> WorkspaceImagerySession {
        imageryStops += 1
        return makeImagerySession(phase: .completed)
    }

    func livingMap(
        conversationID: Int?
    ) async throws -> [WorkspaceLivingMapCard] { [] }

    func reviewLivingMap(
        cardID: String,
        action: WorkspaceLivingMapReviewAction,
        note: String
    ) async throws -> WorkspaceLivingMapCard {
        throw AdvancedSafetyTestError.unexpectedCall
    }

    func wifiSyncStatus() async throws -> WorkspaceWiFiSyncStatus { .idle }
    func createWiFiSyncOffer() async throws -> WorkspaceWiFiSyncStatus { .idle }
    func joinWiFiSync(
        code: String,
        deviceName: String
    ) async throws -> WorkspaceWiFiSyncStatus { .idle }
    func cancelWiFiSync() async throws -> WorkspaceWiFiSyncStatus { .idle }
    func resolveWiFiSyncConflict(
        conflictID: String,
        resolution: WorkspaceSyncConflictResolution
    ) async throws -> WorkspaceWiFiSyncStatus { .idle }
}

enum AdvancedStartFailure: Sendable {
    case chair
    case imagery
}

enum AdvancedSafetyTestError: LocalizedError {
    case unexpectedCall
    case chairStartFailed
    case imageryStartFailed

    var errorDescription: String? {
        switch self {
        case .unexpectedCall: return "Beklenmeyen test çağrısı."
        case .chairStartFailed: return "Sandalye çalışması başlatılamadı."
        case .imageryStartFailed: return "İmgeleme çalışması başlatılamadı."
        }
    }
}

func makeChairSession(
    phase: WorkspaceWorkPhase,
    intensity: Int = 3,
    limit: Int = 7
) -> WorkspaceChairSession {
    let participants = [
        WorkspaceChairIdentity(
            id: "1",
            title: "İhtiyacı olan parçam",
            prompt: "Ne söylemek istiyor?",
            sortOrder: 0
        ),
        WorkspaceChairIdentity(
            id: "2",
            title: "Koruyan parçam",
            prompt: "Neyi koruyor?",
            sortOrder: 1
        ),
    ]
    return WorkspaceChairSession(
        id: "chair-1",
        title: "İki sandalye",
        frame: "Sözler kullanıcıya aittir.",
        goalText: "İki yanı ayırt etmek",
        stopSignal: "DUR",
        participants: participants,
        minimumParticipants: 2,
        maximumParticipants: 6,
        allowsAddingParticipants: true,
        orientationConfirmed: true,
        frameConfirmed: true,
        activeChairID: participants[0].id,
        phase: phase,
        intensity: intensity,
        intensityLimit: limit,
        updatedAt: Date()
    )
}

func makeImagerySession(
    phase: WorkspaceWorkPhase,
    intensity: Int = 3,
    limit: Int = 7
) -> WorkspaceImagerySession {
    let stage = WorkspaceProtocolStage(
        id: "present_trigger",
        label: "Şimdiki tetikleyici",
        aim: "Bugünkü ihtiyacı fark etmek",
        prompt: "Şu anda neye ihtiyacınız var?"
    )
    return WorkspaceImagerySession(
        id: "imagery-1",
        phase: phase,
        title: "Sınırlı yeniden ebeveynlik",
        frame: "İmge tarihsel kanıt değildir.",
        stages: [stage],
        currentStageID: stage.id,
        currentStageIndex: 0,
        checkpoint: WorkspaceImageryCheckpoint(
            id: "checkpoint-1",
            stageID: stage.id,
            title: stage.label,
            prompt: stage.prompt,
            safetyNote: "İstediğiniz anda durabilirsiniz.",
            choices: [
                WorkspaceImageryChoice(id: "continue", title: "Devam et")
            ]
        ),
        sceneBoundary: "Odada kalacağım.",
        stopSignal: "DUR",
        orientationConfirmed: true,
        frameConfirmed: true,
        realityConfirmed: true,
        intensity: intensity,
        intensityLimit: limit,
        updatedAt: Date()
    )
}

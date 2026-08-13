import Foundation
import SwiftUI

@MainActor
public final class AdvancedWorkspaceViewModel: ObservableObject {
    public let context: AdvancedWorkspaceContext

    @Published public var selectedModule: AdvancedModule
    @Published public private(set) var chairConfiguration: WorkspaceChairConfiguration = .twoPartDefault
    @Published public private(set) var clinicalIntensityLimit = 10
    @Published public private(set) var clinicalSafetyHold = false
    @Published public private(set) var chairAvailable = false
    @Published public private(set) var chairUnavailableReason: String?
    @Published public private(set) var imageryAvailable = false
    @Published public private(set) var imageryUnavailableReason: String?
    @Published public private(set) var chairSession: WorkspaceChairSession?
    @Published public private(set) var imagerySession: WorkspaceImagerySession?
    @Published public private(set) var livingMapCards: [WorkspaceLivingMapCard] = []
    @Published public private(set) var syncStatus: WorkspaceWiFiSyncStatus = .idle
    @Published public private(set) var isLoading = false
    @Published public private(set) var operationDescription = ""
    @Published public var failure: AdvancedWorkspaceFailure?

    @Published public var chairGoalText = ""
    @Published public var chairStopSignal = "Dur"
    @Published public var chairParticipantTitles = WorkspaceChairConfiguration.twoPartDefault.defaultParticipantTitles
    @Published public var chairNewParticipantTitle = ""
    @Published public var chairIntensity = 3
    @Published public var chairOrientationConfirmed = false
    @Published public var chairFrameConfirmed = false
    @Published public var chairTurnDraft = ""
    @Published public var chairClosureAction: WorkspaceChairClosureAction = .ground
    @Published public var chairClosureCheckpointConfirmed = false
    @Published public var chairClosureOrientationConfirmed = false
    @Published public var chairClosureNote = ""
    @Published public var chairResumeOrientationConfirmed = false
    @Published public var chairResumeGroundingConfirmed = false
    @Published public private(set) var isChairStopInFlight = false

    @Published public var imageryIntention = ""
    @Published public var imageryIntensity = 3

    /// Kullanıcının seçtiği yoğunluk, açık imgelem oturumunun klinik
    /// sınırını aşıyor mu? Eşik tek kaynaktan (`WorkspaceSafety`) gelir.
    public var imageryIntensityBlocksResume: Bool {
        WorkspaceSafety.intensityBlocksResume(
            intensity: imageryIntensity,
            limit: imagerySession?.intensityLimit ?? WorkspaceSafety.resumeCeiling
        )
    }

    /// Sandalye çalışması için aynı kural.
    public var chairIntensityBlocksResume: Bool {
        WorkspaceSafety.intensityBlocksResume(
            intensity: chairIntensity,
            limit: chairSession?.intensityLimit ?? WorkspaceSafety.resumeCeiling
        )
    }
    @Published public var imageryOrientationConfirmed = false
    @Published public var imageryFrameConfirmed = false
    @Published public var imageryRealityConfirmed = false
    @Published public var imageryStopSignal = "Dur"
    @Published public var imagerySceneBoundary = "Sahneyi uzaktan, bulunduğum odanın farkında kalarak izleyeceğim."
    @Published public var imageryCheckpointConfirmed = false
    @Published public var imageryCheckpointOrientationConfirmed = false
    @Published public var imageryCheckpointRealityConfirmed = false
    @Published public var imageryGroundOrientationConfirmed = false
    @Published public var imageryResumeOrientationConfirmed = false
    @Published public var imageryFinishGroundingConfirmed = false
    @Published public var imageryFinishOrientationConfirmed = false
    @Published public var imageryFinishRealityConfirmed = false
    @Published public var imageryChoiceID = ""
    @Published public var imageryNote = ""
    @Published public private(set) var isImageryStopInFlight = false

    @Published public var livingMapDomain: WorkspaceLivingMapDomain?
    @Published public var livingMapReviewNotes: [String: String] = [:]

    @Published public var syncPairingCode = ""
    @Published public var syncDeviceName = Host.current().localizedName ?? "Bu Mac"
    @Published public var syncJoinConfirmed = false

    private let dataSource: any AdvancedWorkspaceDataSource
    private var hasLoaded = false
    private var syncPollToken = UUID()
    private var uiOperationToken = UUID()
    private var chairOperationToken = UUID()
    private var imageryOperationToken = UUID()

    public init(
        dataSource: any AdvancedWorkspaceDataSource,
        context: AdvancedWorkspaceContext,
        initialModule: AdvancedModule = .chairWork
    ) {
        self.dataSource = dataSource
        self.context = context
        self.selectedModule = context.allowsClinicalWork ? initialModule : .wifiSync
    }

    public var isPerformingAction: Bool { !operationDescription.isEmpty }

    public var imageryConsentComplete: Bool {
        imageryOrientationConfirmed && imageryFrameConfirmed && imageryRealityConfirmed
    }

    public var chairConsentComplete: Bool {
        chairOrientationConfirmed && chairFrameConfirmed
    }

    public var selectedImageryChoice: WorkspaceImageryChoice? {
        imagerySession?.checkpoint.choices.first(where: { $0.id == imageryChoiceID })
    }

    public var filteredLivingMapCards: [WorkspaceLivingMapCard] {
        guard let livingMapDomain else { return livingMapCards }
        return livingMapCards.filter { $0.domain == livingMapDomain }
    }

    public func loadIfNeeded() async {
        guard !hasLoaded else { return }
        await reloadWorkspace()
    }

    public func reloadWorkspace() async {
        guard !isPerformingAction else { return }
        isLoading = true
        failure = nil
        do {
            let isFirstSuccessfulLoad = !hasLoaded
            let snapshot = try await dataSource.advancedWorkspaceSnapshot(context: context)
            clinicalIntensityLimit = snapshot.clinicalIntensityLimit
            clinicalSafetyHold = snapshot.clinicalSafetyHold
            // An existing durable work record must remain reviewable even if
            // its method later disappears from the currently published
            // catalog.  In particular, a proposed record still needs to expose
            // the user's explicit “Onayla ve başlat” gate.
            chairAvailable = snapshot.chairAvailable || snapshot.chairSession != nil
            chairUnavailableReason = snapshot.chairUnavailableReason
            imageryAvailable = snapshot.imageryAvailable
            imageryUnavailableReason = snapshot.imageryUnavailableReason
            chairConfiguration = snapshot.chairConfiguration
            chairSession = snapshot.chairSession
            imagerySession = snapshot.imagerySession
            livingMapCards = snapshot.livingMap
            setSyncStatus(snapshot.syncStatus)
            if snapshot.chairSession == nil, isFirstSuccessfulLoad {
                chairParticipantTitles = normalizedDefaultParticipantTitles(snapshot.chairConfiguration)
            }
            chairIntensity = min(chairIntensity, snapshot.clinicalIntensityLimit)
            imageryIntensity = min(imageryIntensity, snapshot.clinicalIntensityLimit)
            if let chairSession = snapshot.chairSession {
                chairIntensity = min(chairSession.intensity, chairSession.intensityLimit)
                resetChairResumeInput()
                if chairSession.phase == .notStarted, isFirstSuccessfulLoad {
                    configureChairStartInput(
                        for: chairSession,
                        configuration: snapshot.chairConfiguration
                    )
                }
            }
            if let imagerySession = snapshot.imagerySession {
                configureImageryInput(for: imagerySession)
            }
            if snapshot.chairSession != nil, isFirstSuccessfulLoad {
                resetChairClosureInput()
            }
            normalizeSelectedModuleAfterLoad()
            hasLoaded = true
        } catch {
            failure = makeFailure(
                title: "Çalışma alanı açılamadı",
                error: error,
                retry: .loadWorkspace
            )
        }
        isLoading = false
    }

    public func selectModule(_ module: AdvancedModule) {
        guard moduleIsAvailable(module) else {
            failure = AdvancedWorkspaceFailure(
                title: "Bu çalışma kullanılamıyor",
                message: unavailableReason(for: module)
                    ?? AdvancedWorkspaceValidationError.clinicalWorkUnavailable.localizedDescription
            )
            return
        }
        selectedModule = module
    }

    public func retryFailure() async {
        let action = failure?.retryAction
        failure = nil
        switch action {
        case .loadWorkspace:
            await reloadWorkspace()
        case .loadLivingMap:
            await refreshLivingMap()
        case .refreshSync:
            await refreshSyncStatus()
        case nil:
            break
        }
    }

    public func dismissFailure() {
        failure = nil
    }

    // MARK: Chair work

    public func startChairWork() async {
        guard context.allowsClinicalWork else {
            presentValidation(.clinicalWorkUnavailable)
            return
        }
        guard chairAvailable else {
            presentUnavailable(
                chairUnavailableReason,
                fallback: "Bu ustanın yayımlanmış yöntem kataloğunda sandalye çalışması bulunmuyor."
            )
            return
        }
        guard !clinicalSafetyHold else {
            presentValidation(.clinicalSafetyHold)
            return
        }
        guard chairConsentComplete else {
            presentValidation(.explicitConsentRequired)
            return
        }

        let goal = chairGoalText.trimmingCharacters(in: .whitespacesAndNewlines)
        let stopSignal = chairStopSignal.trimmingCharacters(in: .whitespacesAndNewlines)
        let participantTitles = chairParticipantTitles.map {
            $0.trimmingCharacters(in: .whitespacesAndNewlines)
        }
        guard !goal.isEmpty,
              !stopSignal.isEmpty,
              !participantTitles.contains(where: \.isEmpty),
              participantTitles.count >= chairConfiguration.minimumParticipants,
              participantTitles.count <= chairConfiguration.maximumParticipants else {
            presentValidation(.emptyResponse)
            return
        }

        await performChair("Sandalye çalışması başlatılıyor…") {
            try await dataSource.startChairWork(
                request: WorkspaceChairStartRequest(
                    conversationID: context.conversationID,
                    goalText: goal,
                    stopSignal: stopSignal,
                    participantTitles: participantTitles,
                    startingParticipantIndex: 0,
                    intensity: chairIntensity,
                    orientationConfirmed: chairOrientationConfirmed,
                    frameConfirmed: chairFrameConfirmed
                )
            )
        } onSuccess: { session in
            chairIntensity = min(session.intensity, session.intensityLimit)
            chairOrientationConfirmed = false
            chairFrameConfirmed = false
            resetChairResumeInput()
        }
    }

    /// Leaves a completed record intact on the server while returning the UI
    /// to a fresh, explicitly confirmed start form.  No new work is created
    /// until the user completes that form and presses the start action.
    public func prepareNewChairWork() {
        guard chairSession?.phase == .completed,
              chairAvailable,
              !isPerformingAction else { return }
        chairSession = nil
        chairGoalText = ""
        chairStopSignal = "Dur"
        chairParticipantTitles = normalizedDefaultParticipantTitles(chairConfiguration)
        chairIntensity = min(3, clinicalIntensityLimit)
        chairOrientationConfirmed = false
        chairFrameConfirmed = false
        chairNewParticipantTitle = ""
        failure = nil
        resetChairClosureInput()
        resetChairResumeInput()
    }

    public func submitChairTurn() async {
        guard let session = chairSession else { return }
        guard !clinicalSafetyHold else {
            presentValidation(.clinicalSafetyHold)
            return
        }
        let content = chairTurnDraft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !content.isEmpty else {
            presentValidation(.emptyResponse)
            return
        }

        await performChair("Sözünüz kaydediliyor…") {
            try await dataSource.addChairTurn(
                sessionID: session.id,
                chairID: session.activeChairID,
                content: content,
                intensity: chairIntensity
            )
        } onSuccess: { _ in
            chairTurnDraft = ""
        }
    }

    public func selectChair(_ chair: WorkspaceChairIdentity) async {
        guard !clinicalSafetyHold else {
            presentValidation(.clinicalSafetyHold)
            return
        }
        guard let session = chairSession,
              session.activeChairID != chair.id,
              session.phase == .active else { return }
        await performChair("Diğer sandalyeye geçiliyor…") {
            try await dataSource.selectChair(
                sessionID: session.id,
                chairID: chair.id
            )
        }
    }

    public func addChairParticipant() async {
        guard !clinicalSafetyHold else {
            presentValidation(.clinicalSafetyHold)
            return
        }
        guard let session = chairSession,
              session.allowsAddingParticipants,
              session.participants.count < session.maximumParticipants else { return }
        let title = chairNewParticipantTitle.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !title.isEmpty else {
            presentValidation(.emptyResponse)
            return
        }
        await performChair("Yeni sandalye ekleniyor…") {
            try await dataSource.addChairParticipant(
                sessionID: session.id,
                title: title
            )
        } onSuccess: { _ in
            chairNewParticipantTitle = ""
        }
    }

    public func requestChairGuidance() async {
        guard !clinicalSafetyHold else {
            presentValidation(.clinicalSafetyHold)
            return
        }
        guard let session = chairSession, session.phase == .active else { return }
        await performChair("Terapist yönergesi hazırlanıyor…") {
            try await dataSource.requestChairGuidance(sessionID: session.id)
        }
    }

    public func resumeChairWork() async {
        guard let session = chairSession, session.phase == .paused else { return }
        guard !clinicalSafetyHold else {
            presentValidation(.clinicalSafetyHold)
            return
        }
        guard chairResumeOrientationConfirmed else {
            presentValidation(.orientationConfirmationRequired)
            return
        }
        guard chairResumeGroundingConfirmed else {
            presentValidation(.groundingConfirmationRequired)
            return
        }
        guard chairIntensity >= 0, chairIntensity <= session.intensityLimit else {
            presentValidation(.intensityExceedsSessionLimit)
            return
        }
        guard chairIntensity < 8 else {
            presentValidation(.resumeIntensityTooHigh)
            return
        }

        let request = WorkspaceChairResumeRequest(
            sessionID: session.id,
            orientationConfirmed: chairResumeOrientationConfirmed,
            groundingConfirmed: chairResumeGroundingConfirmed,
            currentIntensity: chairIntensity
        )
        await performChair("Sandalye çalışmasına dönülüyor…") {
            try await dataSource.resumeChairWork(request: request)
        } onSuccess: { _ in
            resetChairResumeInput()
        }
    }

    public func advanceChairClosure() async {
        guard let session = chairSession, session.phase != .completed else { return }
        guard chairClosureCheckpointConfirmed else {
            presentValidation(.closureCheckpointRequired)
            return
        }
        if [.ground, .complete].contains(chairClosureAction),
           !chairClosureOrientationConfirmed {
            presentValidation(.orientationConfirmationRequired)
            return
        }
        let note = chairClosureNote.trimmingCharacters(in: .whitespacesAndNewlines)
        if chairClosureAction == .reflect, note.isEmpty {
            presentValidation(.emptyResponse)
            return
        }
        if chairClosureAction == .complete,
           !session.completedClosureActions.isSuperset(of: [.ground, .reflect]) {
            presentValidation(.closureSequenceIncomplete)
            return
        }
        await performChair("Kapanış adımı kaydediliyor…") {
            try await dataSource.advanceChairClosure(
                request: WorkspaceChairClosureRequest(
                    sessionID: session.id,
                    action: chairClosureAction,
                    checkpointConfirmed: chairClosureCheckpointConfirmed,
                    orientationConfirmed: chairClosureOrientationConfirmed,
                    note: note,
                    currentIntensity: chairIntensity
                )
            )
        } onSuccess: { _ in
            resetChairClosureInput()
        }
    }

    public func stopChairWork() async {
        guard let session = chairSession, session.phase != .completed else { return }
        guard !isChairStopInFlight else { return }

        let stopToken = UUID()
        chairOperationToken = stopToken
        uiOperationToken = stopToken
        isChairStopInFlight = true
        operationDescription = "Sandalye çalışması kapatılıyor…"
        failure = nil
        defer {
            isChairStopInFlight = false
            if uiOperationToken == stopToken {
                operationDescription = ""
            }
        }

        do {
            let stopped = try await dataSource.stopChairWork(sessionID: session.id)
            guard chairOperationToken == stopToken else { return }
            chairSession = stopped
            chairTurnDraft = ""
            resetChairClosureInput()
            resetChairResumeInput()
        } catch {
            guard chairOperationToken == stopToken else { return }
            failure = makeFailure(title: "Çalışma kapatılamadı", error: error, retry: nil)
        }
    }

    // MARK: Imagery

    public func startImagery() async {
        guard context.allowsClinicalWork else {
            presentValidation(.clinicalWorkUnavailable)
            return
        }
        guard imageryAvailable else {
            presentUnavailable(
                imageryUnavailableReason,
                fallback: "Bu ustanın yayımlanmış yöntem kataloğunda sınırlı yeniden ebeveynlik-imgeleme çalışması bulunmuyor."
            )
            return
        }
        guard !clinicalSafetyHold else {
            presentValidation(.clinicalSafetyHold)
            return
        }
        guard imageryConsentComplete else {
            presentValidation(.explicitConsentRequired)
            return
        }
        let intention = imageryIntention.trimmingCharacters(in: .whitespacesAndNewlines)
        let stopSignal = imageryStopSignal.trimmingCharacters(in: .whitespacesAndNewlines)
        let sceneBoundary = imagerySceneBoundary.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !intention.isEmpty, !stopSignal.isEmpty, !sceneBoundary.isEmpty else {
            presentValidation(.emptyResponse)
            return
        }

        await performImagery("Güvenli başlangıç hazırlanıyor…") {
            try await dataSource.startImagery(
                request: WorkspaceImageryStartRequest(
                    conversationID: context.conversationID,
                    intention: intention,
                    intensity: imageryIntensity,
                    orientationConfirmed: imageryOrientationConfirmed,
                    frameConfirmed: imageryFrameConfirmed,
                    realityConfirmed: imageryRealityConfirmed,
                    stopSignal: stopSignal,
                    sceneBoundary: sceneBoundary
                )
            )
        } onSuccess: { _ in
            imageryOrientationConfirmed = false
            imageryFrameConfirmed = false
            imageryRealityConfirmed = false
            resetImageryCheckpointInput()
        }
    }

    public func submitImageryCheckpoint() async {
        guard let session = imagerySession else { return }
        guard !clinicalSafetyHold else {
            presentValidation(.clinicalSafetyHold)
            return
        }
        guard let choice = selectedImageryChoice else {
            presentValidation(.emptyResponse)
            return
        }
        guard imageryCheckpointConfirmed else {
            presentValidation(.checkpointConfirmationRequired)
            return
        }
        guard imageryCheckpointOrientationConfirmed else {
            presentValidation(.orientationConfirmationRequired)
            return
        }
        guard imageryCheckpointRealityConfirmed else {
            presentValidation(.realityConfirmationRequired)
            return
        }

        await performImagery("Seçiminiz uygulanıyor…") {
            try await dataSource.respondToImageryCheckpoint(
                response: WorkspaceImageryCheckpointResponse(
                    sessionID: session.id,
                    checkpointID: session.checkpoint.id,
                    choiceID: choice.id,
                    note: imageryNote.trimmingCharacters(in: .whitespacesAndNewlines),
                    currentIntensity: imageryIntensity,
                    confirmed: imageryCheckpointConfirmed,
                    orientationConfirmed: imageryCheckpointOrientationConfirmed,
                    realityConfirmed: imageryCheckpointRealityConfirmed
                )
            )
        } onSuccess: { _ in
            resetImageryCheckpointInput()
        }
    }

    public func groundImagery() async {
        guard let session = imagerySession, session.phase != .completed else { return }
        guard imageryGroundOrientationConfirmed else {
            presentValidation(.orientationConfirmationRequired)
            return
        }
        await performImagery("Şimdiye dönme adımı açılıyor…") {
            try await dataSource.groundImagery(
                request: WorkspaceImageryGroundRequest(
                    sessionID: session.id,
                    currentIntensity: imageryIntensity,
                    roomOrientationConfirmed: imageryGroundOrientationConfirmed
                )
            )
        } onSuccess: { _ in
            resetImageryCheckpointInput()
        }
    }

    public func resumeImagery() async {
        guard let session = imagerySession, session.phase == .paused else { return }
        guard !clinicalSafetyHold else {
            presentValidation(.clinicalSafetyHold)
            return
        }
        guard imageryResumeOrientationConfirmed else {
            presentValidation(.orientationConfirmationRequired)
            return
        }
        guard imageryIntensity < 8 else {
            presentValidation(.resumeIntensityTooHigh)
            return
        }
        await performImagery("İmgelemeye dönülüyor…") {
            try await dataSource.resumeImagery(
                request: WorkspaceImageryResumeRequest(
                    sessionID: session.id,
                    currentIntensity: imageryIntensity,
                    orientationConfirmed: imageryResumeOrientationConfirmed
                )
            )
        } onSuccess: { _ in
            imageryResumeOrientationConfirmed = false
            resetImageryCheckpointInput()
        }
    }

    public func finishImagery() async {
        guard let session = imagerySession, session.phase != .completed else { return }
        guard imageryFinishGroundingConfirmed else {
            presentValidation(.groundingConfirmationRequired)
            return
        }
        guard imageryFinishOrientationConfirmed else {
            presentValidation(.orientationConfirmationRequired)
            return
        }
        guard imageryFinishRealityConfirmed else {
            presentValidation(.realityConfirmationRequired)
            return
        }
        guard imageryIntensity < 8 else {
            presentValidation(.completionIntensityTooHigh)
            return
        }
        await performImagery("Çalışma kapatılıyor…") {
            try await dataSource.finishImagery(
                request: WorkspaceImageryFinishRequest(
                    sessionID: session.id,
                    currentIntensity: imageryIntensity,
                    groundingConfirmed: imageryFinishGroundingConfirmed,
                    orientationConfirmed: imageryFinishOrientationConfirmed,
                    realityConfirmed: imageryFinishRealityConfirmed
                )
            )
        } onSuccess: { _ in
            resetImageryFinishInput()
            resetImageryCheckpointInput()
        }
    }

    public func stopImagery() async {
        guard let session = imagerySession, session.phase != .completed else { return }
        guard !isImageryStopInFlight else { return }

        let stopToken = UUID()
        imageryOperationToken = stopToken
        uiOperationToken = stopToken
        isImageryStopInFlight = true
        operationDescription = "İmgeleme çalışması kapatılıyor…"
        failure = nil
        defer {
            isImageryStopInFlight = false
            if uiOperationToken == stopToken {
                operationDescription = ""
            }
        }

        do {
            let stopped = try await dataSource.stopImagery(sessionID: session.id)
            guard imageryOperationToken == stopToken else { return }
            imagerySession = stopped
            resetImageryFinishInput()
            resetImageryCheckpointInput()
        } catch {
            guard imageryOperationToken == stopToken else { return }
            failure = makeFailure(title: "İmgeleme kapatılamadı", error: error, retry: nil)
        }
    }

    // MARK: Living map

    public func refreshLivingMap() async {
        guard context.allowsClinicalWork else {
            presentValidation(.clinicalWorkUnavailable)
            return
        }
        await perform("Yaşayan harita yenileniyor…", retry: .loadLivingMap) {
            livingMapCards = try await dataSource.livingMap(
                conversationID: context.conversationID
            )
        }
    }

    public func reviewLivingMap(
        cardID: String,
        action: WorkspaceLivingMapReviewAction
    ) async {
        let note = livingMapReviewNotes[cardID, default: ""]
            .trimmingCharacters(in: .whitespacesAndNewlines)
        await perform("Değerlendirmeniz kaydediliyor…") {
            let card = try await dataSource.reviewLivingMap(
                cardID: cardID,
                action: action,
                note: note
            )
            replaceLivingMapCard(card)
            livingMapReviewNotes[cardID] = ""
        }
    }

    // MARK: Wi-Fi sync

    public func refreshSyncStatus() async {
        guard !isPerformingAction else { return }
        await perform("Eşitleme durumu yenileniyor…", retry: .refreshSync) {
            setSyncStatus(try await dataSource.wifiSyncStatus())
        }
    }

    public func createSyncOffer() async {
        await perform("Tek kullanımlık QR kod hazırlanıyor…", retry: .refreshSync) {
            setSyncStatus(try await dataSource.createWiFiSyncOffer())
        }
    }

    public func joinSync() async {
        guard syncJoinConfirmed else {
            presentValidation(.explicitConsentRequired)
            return
        }
        let code = syncPairingCode.trimmingCharacters(in: .whitespacesAndNewlines)
        let deviceName = syncDeviceName.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !code.isEmpty, !deviceName.isEmpty else {
            presentValidation(.emptyResponse)
            return
        }
        await perform("Diğer cihazın eşitlemesine katılınıyor…", retry: .refreshSync) {
            setSyncStatus(
                try await dataSource.joinWiFiSync(code: code, deviceName: deviceName)
            )
            syncPairingCode = ""
            syncJoinConfirmed = false
        }
    }

    public func cancelSync() async {
        syncPollToken = UUID()
        await perform("Eşitleme iptal ediliyor…") {
            setSyncStatus(try await dataSource.cancelWiFiSync())
        }
    }

    public func resolveSyncConflict(
        conflictID: String,
        resolution: WorkspaceSyncConflictResolution
    ) async {
        await perform("Çakışma tercihiniz uygulanıyor…") {
            setSyncStatus(
                try await dataSource.resolveWiFiSyncConflict(
                    conflictID: conflictID,
                    resolution: resolution
                )
            )
        }
    }

    // MARK: Helpers

    public func moduleIsAvailable(_ module: AdvancedModule) -> Bool {
        guard context.allowsClinicalWork || !module.isClinical else { return false }
        return switch module {
        case .chairWork: chairAvailable
        case .reparenting: imageryAvailable
        case .livingMap, .wifiSync: true
        }
    }

    public func unavailableReason(for module: AdvancedModule) -> String? {
        guard context.allowsClinicalWork || !module.isClinical else {
            return AdvancedWorkspaceValidationError.clinicalWorkUnavailable.localizedDescription
        }
        return switch module {
        case .chairWork:
            chairAvailable ? nil : chairUnavailableReason
                ?? "Bu ustanın yayımlanmış yöntem kataloğunda sandalye çalışması bulunmuyor."
        case .reparenting:
            imageryAvailable ? nil : imageryUnavailableReason
                ?? "Bu ustanın yayımlanmış yöntem kataloğunda sınırlı yeniden ebeveynlik-imgeleme çalışması bulunmuyor."
        case .livingMap, .wifiSync:
            nil
        }
    }

    private func performChair(
        _ description: String,
        action: () async throws -> WorkspaceChairSession,
        onSuccess: (WorkspaceChairSession) -> Void = { _ in }
    ) async {
        guard !isPerformingAction, !isChairStopInFlight else { return }
        let token = UUID()
        chairOperationToken = token
        uiOperationToken = token
        operationDescription = description
        failure = nil
        defer {
            if uiOperationToken == token {
                operationDescription = ""
            }
        }

        do {
            let updated = try await action()
            guard chairOperationToken == token else { return }
            chairSession = updated
            onSuccess(updated)
        } catch {
            guard chairOperationToken == token else { return }
            failure = makeFailure(title: "İşlem tamamlanamadı", error: error, retry: nil)
        }
    }

    private func performImagery(
        _ description: String,
        action: () async throws -> WorkspaceImagerySession,
        onSuccess: (WorkspaceImagerySession) -> Void = { _ in }
    ) async {
        guard !isPerformingAction, !isImageryStopInFlight else { return }
        let token = UUID()
        imageryOperationToken = token
        uiOperationToken = token
        operationDescription = description
        failure = nil
        defer {
            if uiOperationToken == token {
                operationDescription = ""
            }
        }

        do {
            let updated = try await action()
            guard imageryOperationToken == token else { return }
            imagerySession = updated
            onSuccess(updated)
        } catch {
            guard imageryOperationToken == token else { return }
            failure = makeFailure(title: "İşlem tamamlanamadı", error: error, retry: nil)
        }
    }

    private func perform(
        _ description: String,
        retry: AdvancedRetryAction? = nil,
        action: () async throws -> Void
    ) async {
        guard !isPerformingAction else { return }
        let token = UUID()
        uiOperationToken = token
        operationDescription = description
        failure = nil
        defer {
            if uiOperationToken == token {
                operationDescription = ""
            }
        }
        do {
            try await action()
        } catch {
            if uiOperationToken == token {
                failure = makeFailure(title: "İşlem tamamlanamadı", error: error, retry: retry)
            }
        }
    }

    private func presentValidation(_ error: AdvancedWorkspaceValidationError) {
        failure = AdvancedWorkspaceFailure(
            title: "Devam etmek için",
            message: error.localizedDescription
        )
    }

    private func presentUnavailable(_ reason: String?, fallback: String) {
        failure = AdvancedWorkspaceFailure(
            title: "Bu çalışma bu ustada bulunmuyor",
            message: reason ?? fallback
        )
    }

    private func normalizeSelectedModuleAfterLoad() {
        guard !moduleIsAvailable(selectedModule) else { return }
        let requestedModule = selectedModule
        let reason = unavailableReason(for: requestedModule)
            ?? "Bu çalışma seçili usta ve görüşme bağlamında kullanılamıyor."
        let experientialFallback: AdvancedModule? = switch requestedModule {
        case .chairWork where imageryAvailable: .reparenting
        case .reparenting where chairAvailable: .chairWork
        default: nil
        }
        if let experientialFallback {
            selectedModule = experientialFallback
        }
        let direction: String
        if let experientialFallback {
            direction = "Aynı seanstaki kullanılabilir \(experientialFallback.title.lowercased()) alanı açıldı."
        } else if requestedModule == .chairWork {
            direction = "Perls veya Young gibi sandalye protokolü yayımlanmış bir terapistin seansını seçin."
        } else if requestedModule == .reparenting {
            direction = "Young veya Arntz gibi imgeleme-yeniden ebeveynlik protokolü yayımlanmış bir terapistin seansını seçin."
        } else {
            direction = "Uygun bir terapi görüşmesi seçin."
        }
        failure = AdvancedWorkspaceFailure(
            title: "Bu usta bu çalışmayı sunmuyor",
            message: "\(reason) \(direction)"
        )
    }

    private func makeFailure(
        title: String,
        error: Error,
        retry: AdvancedRetryAction?
    ) -> AdvancedWorkspaceFailure {
        let message = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
        return AdvancedWorkspaceFailure(
            title: title,
            message: message.isEmpty ? "Beklenmeyen bir sorun oluştu." : message,
            retryAction: retry
        )
    }

    private func resetImageryCheckpointInput() {
        imageryCheckpointConfirmed = false
        imageryCheckpointOrientationConfirmed = false
        imageryCheckpointRealityConfirmed = false
        imageryGroundOrientationConfirmed = false
        imageryNote = ""
        if let session = imagerySession {
            configureImageryInput(for: session)
        }
    }

    private func configureImageryInput(for session: WorkspaceImagerySession) {
        imageryIntensity = min(session.intensity, session.intensityLimit)
        imageryChoiceID = session.checkpoint.choices.first?.id ?? ""
        imageryCheckpointConfirmed = false
        imageryCheckpointOrientationConfirmed = false
        imageryCheckpointRealityConfirmed = false
        imageryGroundOrientationConfirmed = false
        imageryResumeOrientationConfirmed = false
    }

    private func resetImageryFinishInput() {
        imageryFinishGroundingConfirmed = false
        imageryFinishOrientationConfirmed = false
        imageryFinishRealityConfirmed = false
    }

    private func resetChairClosureInput() {
        chairClosureCheckpointConfirmed = false
        chairClosureOrientationConfirmed = false
        chairClosureNote = ""
        if let session = chairSession,
           let next = session.availableClosureActions.first(where: {
               !session.completedClosureActions.contains($0)
           }) {
            chairClosureAction = next
        } else {
            chairClosureAction = .ground
        }
    }

    private func resetChairResumeInput() {
        chairResumeOrientationConfirmed = false
        chairResumeGroundingConfirmed = false
    }

    private func configureChairStartInput(
        for session: WorkspaceChairSession,
        configuration: WorkspaceChairConfiguration
    ) {
        chairGoalText = session.goalText
        let proposedStopSignal = session.stopSignal.trimmingCharacters(
            in: .whitespacesAndNewlines
        )
        chairStopSignal = proposedStopSignal.isEmpty ? "Dur" : proposedStopSignal

        var proposedTitles = session.participants
            .sorted { $0.sortOrder < $1.sortOrder }
            .map(\.title)
            .filter { !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
        let defaults = normalizedDefaultParticipantTitles(configuration)
        while proposedTitles.count < configuration.minimumParticipants {
            let index = proposedTitles.count
            proposedTitles.append(
                defaults.indices.contains(index) ? defaults[index] : "Parça \(index + 1)"
            )
        }
        chairParticipantTitles = Array(
            proposedTitles.prefix(configuration.maximumParticipants)
        )
        chairIntensity = min(session.intensity, session.intensityLimit)

        // Consent is deliberately fresh on every presentation.  Stored or
        // partially stored booleans are never treated as a current click.
        chairOrientationConfirmed = false
        chairFrameConfirmed = false
    }

    private func normalizedDefaultParticipantTitles(
        _ configuration: WorkspaceChairConfiguration
    ) -> [String] {
        var titles = Array(configuration.defaultParticipantTitles.prefix(configuration.maximumParticipants))
        while titles.count < configuration.minimumParticipants {
            titles.append("Parça \(titles.count + 1)")
        }
        return titles
    }

    private func replaceLivingMapCard(_ updated: WorkspaceLivingMapCard) {
        if let index = livingMapCards.firstIndex(where: { $0.id == updated.id }) {
            livingMapCards[index] = updated
        } else {
            livingMapCards.append(updated)
        }
    }

    private func setSyncStatus(_ status: WorkspaceWiFiSyncStatus) {
        syncStatus = status
        if status.phase.isInProgress {
            beginSyncPolling()
        } else {
            syncPollToken = UUID()
        }
    }

    private func beginSyncPolling() {
        let token = UUID()
        syncPollToken = token
        Task { [weak self] in
            for _ in 0..<300 {
                do {
                    try await Task.sleep(nanoseconds: 2_000_000_000)
                } catch {
                    return
                }
                guard let self,
                      self.syncPollToken == token,
                      self.syncStatus.phase.isInProgress else { return }
                do {
                    let next = try await self.dataSource.wifiSyncStatus()
                    guard self.syncPollToken == token else { return }
                    self.syncStatus = next
                    if !next.phase.isInProgress {
                        self.syncPollToken = UUID()
                        return
                    }
                } catch {
                    guard self.syncPollToken == token else { return }
                    self.failure = self.makeFailure(
                        title: "Eşitleme durumu alınamadı",
                        error: error,
                        retry: .refreshSync
                    )
                    self.syncPollToken = UUID()
                    return
                }
            }
            guard let self, self.syncPollToken == token else { return }
            self.syncPollToken = UUID()
            self.failure = AdvancedWorkspaceFailure(
                title: "Eşitleme hâlâ sürüyor",
                message: "Durum otomatik olarak doğrulanamadı. Aktarımı silmeden yeniden kontrol edebilirsiniz.",
                retryAction: .refreshSync
            )
        }
    }
}

import Foundation

public protocol DivanService: Sendable {
    func bootstrap() async throws -> BootstrapPayload
    func masters(kind: MasterKind) async throws -> [MasterSummary]
    func portraitData(url: URL) async throws -> Data
    func conversations(archived: Bool) async throws -> [ConversationSummary]
    func conversation(
        id: Int,
        limit: Int,
        beforeID: Int?
    ) async throws -> ConversationPage
    func createConversation(
        masterID: String,
        mode: String,
        submode: String?
    ) async throws -> NewConversation
    func setArchived(_ archived: Bool, id: Int) async throws
    func setPinned(_ pinned: Bool, id: Int) async throws
    func deleteConversation(id: Int) async throws
    func endConversation(id: Int) async throws
    func settings() async throws -> PublicSettings
    func saveSettings(_ update: ProviderSettingsUpdate) async throws -> PublicSettings
    func sendMessage(
        conversationID: Int,
        text: String,
        replyTo: Int?
    ) async throws -> AsyncThrowingStream<ChatEvent, Error>
    func chatStatus(requestID: String) async throws -> ChatRequestStatus
    func cancelChat(requestID: String) async throws -> ChatRequestStatus
    func retryChat(requestID: String) async throws -> ChatRequestStatus

    // Structured techniques and experiential workspaces
    func techniqueCatalog(
        therapistID: String,
        conversationID: Int?
    ) async throws -> TechniqueCatalog
    func techniqueRuns(conversationID: Int) async throws -> TechniqueRunsSnapshot
    func mutateTechniqueRun(
        _ mutation: TechniqueRunMutation
    ) async throws -> TechniqueRunMutationResult
    func chairWork(
        conversationID: Int,
        chairRunID: Int?,
        includeFullHistory: Bool
    ) async throws -> ChairWorkCollection
    func mutateChairWork(
        _ mutation: ChairWorkMutation
    ) async throws -> ChairWorkMutationResult
    func addChairTurn(_ input: ChairTurnInput) async throws -> ChairTurnResult
    func requestChairGuidance(
        _ input: ChairGuidanceInput
    ) async throws -> ChairGuidanceResult
    func imageryWork(conversationID: Int) async throws -> ImageryWork?
    func mutateImageryWork(
        _ mutation: ImageryWorkMutation
    ) async throws -> ImageryWorkResult
    func addImageryTurn(_ input: ImageryTurnInput) async throws -> ImageryTurnResult
    func requestImageryGuidance(
        conversationID: Int,
        imageryRunID: Int,
        revision: Int?
    ) async throws -> ImageryGuidanceResult

    // Longitudinal living map
    func livingMap(therapistID: String?) async throws -> LivingMapSnapshot
    func livingMapDetail(reference: String) async throws -> LivingMapClaimDetail
    func reviewLivingMap(
        _ request: LivingMapReviewRequest
    ) async throws -> LivingMapClaimDetail
    func generateLivingMap(
        conversationID: Int
    ) async throws -> LivingMapGenerationAccepted

    // Explicit same-Wi-Fi pairing. Joining immediately applies the merge.
    func deviceSyncStatus() async throws -> DeviceSyncStatus
    func startDeviceSyncHost() async throws -> DeviceSyncInvitation
    func stopDeviceSyncHost() async throws -> DeviceSyncStatus
    func pairAndApplyDeviceSync(
        code: String,
        deviceName: String?,
        platform: String?
    ) async throws -> DeviceSyncApplyResult
    func resolveDeviceSyncConflict(
        id: Int,
        resolution: SyncConflictResolution
    ) async throws -> SyncConflictResolutionResult
}

public extension DivanService {
    func conversation(id: Int, limit: Int = 80) async throws -> ConversationPage {
        try await conversation(id: id, limit: limit, beforeID: nil)
    }

    func techniqueCatalog(therapistID: String) async throws -> TechniqueCatalog {
        try await techniqueCatalog(therapistID: therapistID, conversationID: nil)
    }

    func chairWork(
        conversationID: Int,
        chairRunID: Int? = nil
    ) async throws -> ChairWorkCollection {
        try await chairWork(
            conversationID: conversationID,
            chairRunID: chairRunID,
            includeFullHistory: false
        )
    }

    func requestImageryGuidance(
        conversationID: Int,
        imageryRunID: Int
    ) async throws -> ImageryGuidanceResult {
        try await requestImageryGuidance(
            conversationID: conversationID,
            imageryRunID: imageryRunID,
            revision: nil
        )
    }

    func livingMap() async throws -> LivingMapSnapshot {
        try await livingMap(therapistID: nil)
    }
}

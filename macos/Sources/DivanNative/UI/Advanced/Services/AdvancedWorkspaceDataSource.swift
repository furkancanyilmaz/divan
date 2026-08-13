import Foundation

/// UI-facing boundary for advanced native modules.
///
/// Core adapters must preserve the explicit `confirmed` fields and must not
/// advance an experiential exercise after a rejected or missing checkpoint.
public protocol AdvancedWorkspaceDataSource: Sendable {
    func advancedWorkspaceSnapshot(
        context: AdvancedWorkspaceContext
    ) async throws -> AdvancedWorkspaceSnapshot

    func startChairWork(
        request: WorkspaceChairStartRequest
    ) async throws -> WorkspaceChairSession

    func addChairTurn(
        sessionID: String,
        chairID: String,
        content: String,
        intensity: Int
    ) async throws -> WorkspaceChairSession

    func selectChair(
        sessionID: String,
        chairID: String
    ) async throws -> WorkspaceChairSession

    func addChairParticipant(
        sessionID: String,
        title: String
    ) async throws -> WorkspaceChairSession

    func requestChairGuidance(
        sessionID: String
    ) async throws -> WorkspaceChairSession

    func resumeChairWork(
        request: WorkspaceChairResumeRequest
    ) async throws -> WorkspaceChairSession

    func advanceChairClosure(
        request: WorkspaceChairClosureRequest
    ) async throws -> WorkspaceChairSession

    func stopChairWork(
        sessionID: String
    ) async throws -> WorkspaceChairSession

    func startImagery(
        request: WorkspaceImageryStartRequest
    ) async throws -> WorkspaceImagerySession

    func respondToImageryCheckpoint(
        response: WorkspaceImageryCheckpointResponse
    ) async throws -> WorkspaceImagerySession

    func groundImagery(
        request: WorkspaceImageryGroundRequest
    ) async throws -> WorkspaceImagerySession

    func resumeImagery(
        request: WorkspaceImageryResumeRequest
    ) async throws -> WorkspaceImagerySession

    func finishImagery(
        request: WorkspaceImageryFinishRequest
    ) async throws -> WorkspaceImagerySession

    func stopImagery(
        sessionID: String
    ) async throws -> WorkspaceImagerySession

    func livingMap(
        conversationID: Int?
    ) async throws -> [WorkspaceLivingMapCard]

    func reviewLivingMap(
        cardID: String,
        action: WorkspaceLivingMapReviewAction,
        note: String
    ) async throws -> WorkspaceLivingMapCard

    func wifiSyncStatus() async throws -> WorkspaceWiFiSyncStatus
    func createWiFiSyncOffer() async throws -> WorkspaceWiFiSyncStatus

    func joinWiFiSync(
        code: String,
        deviceName: String
    ) async throws -> WorkspaceWiFiSyncStatus

    func cancelWiFiSync() async throws -> WorkspaceWiFiSyncStatus

    func resolveWiFiSyncConflict(
        conflictID: String,
        resolution: WorkspaceSyncConflictResolution
    ) async throws -> WorkspaceWiFiSyncStatus
}

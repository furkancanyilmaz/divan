import Foundation

// Bu dosya `AdvancedAPIPayloads.swift`'ten ayrıldı: 1214 satırlık
// tek dosya, alan sınırları zaten `// MARK` ile çizilmiş 53 tel
// tipini barındırıyordu. Tipler değişmedi, yalnızca yerleşimleri
// alanlarına göre ayrıldı.
// Aynı Wi-Fi eşitleme tel biçimleri.

// MARK: Sync wire payloads

struct SyncSummaryWire: Decodable {
    let sent: Int?
    let received: Int?
    let conflicts: Int?
    let clinicalConfirmationRequired: Bool?
    let clinicalSafetyPause: Bool?
    let clinicalSafetyDevice: String?
    let clinicalSafetyMessage: String?

    var model: SyncSummary {
        SyncSummary(
            sent: sent ?? 0, received: received ?? 0,
            conflicts: conflicts ?? 0,
            clinicalConfirmationRequired:
                clinicalConfirmationRequired ?? false,
            clinicalSafetyPause: clinicalSafetyPause ?? false,
            clinicalSafetyDevice: clinicalSafetyDevice,
            clinicalSafetyMessage: clinicalSafetyMessage
        )
    }
}

struct SyncConflictWire: Decodable {
    let id: Int?
    let recordType: String?
    let title: String?
    let summary: String?
    let reason: String?
    let createdAt: String?

    var model: SyncConflict {
        SyncConflict(
            id: id ?? 0, recordType: recordType ?? "", title: title ?? "",
            summary: summary ?? "", reason: reason ?? "",
            createdAt: createdAt ?? ""
        )
    }
}

struct SyncStatusWire: Decodable {
    let hostRunning: Bool?
    let busy: Bool?
    let secondsRemaining: Int?
    let lastSyncAt: String?
    let lastPeerName: String?
    let lastSummary: SyncSummaryWire?
    let conflicts: [SyncConflictWire]?
    let pendingClinicalConfirmationConvIds: [Int]?
    let pendingClinicalConfirmationCount: Int?
    let clinicalSafetyPause: Bool?
    let clinicalSafetyDevice: String?
    let clinicalSafetyMessage: String?
    let scope: [String]?
    let secretsExcluded: Bool?

    var model: DeviceSyncStatus {
        DeviceSyncStatus(
            hostRunning: hostRunning ?? false, busy: busy ?? false,
            secondsRemaining: secondsRemaining ?? 0,
            lastSyncAt: lastSyncAt, lastPeerName: lastPeerName,
            lastSummary: lastSummary?.model ?? SyncSummary(
                sent: 0, received: 0, conflicts: 0
            ),
            conflicts: (conflicts ?? []).map(\.model),
            pendingClinicalConfirmationConversationIDs:
                pendingClinicalConfirmationConvIds ?? [],
            pendingClinicalConfirmationCount:
                pendingClinicalConfirmationCount
                    ?? pendingClinicalConfirmationConvIds?.count ?? 0,
            clinicalSafetyPause:
                clinicalSafetyPause
                    ?? lastSummary?.clinicalSafetyPause ?? false,
            clinicalSafetyDevice:
                clinicalSafetyDevice
                    ?? lastSummary?.clinicalSafetyDevice,
            clinicalSafetyMessage:
                clinicalSafetyMessage
                    ?? lastSummary?.clinicalSafetyMessage,
            scope: scope ?? [],
            secretsExcluded: secretsExcluded ?? true
        )
    }
}

struct SyncQRWire: Decodable {
    let size: Int?
    let rows: [String]?

    var model: SyncQRMatrix {
        SyncQRMatrix(size: size ?? 0, rows: rows ?? [])
    }
}

struct SyncInvitationWire: Decodable {
    let pairingCode: String?
    let qrMatrix: SyncQRWire?
    let secondsRemaining: Int?

    var model: DeviceSyncInvitation {
        DeviceSyncInvitation(
            pairingCode: pairingCode ?? "",
            qrMatrix: qrMatrix?.model ?? SyncQRMatrix(size: 0, rows: []),
            secondsRemaining: secondsRemaining ?? 0
        )
    }
}

struct SyncApplyWire: Decodable {
    let summary: SyncSummaryWire?
    let lastSyncAt: String?
    let conflictRows: [SyncConflictWire]?
    let exactEqual: Bool?
    let clinicalConfirmationRequired: Bool?
    let clinicalConfirmationDevice: String?
    let clinicalConfirmationMessage: String?
    let pendingClinicalConfirmationConvIds: [Int]?
    let pendingClinicalConfirmationCount: Int?
    let clinicalSafetyPause: Bool?
    let clinicalSafetyDevice: String?
    let clinicalSafetyMessage: String?

    var model: DeviceSyncApplyResult {
        DeviceSyncApplyResult(
            summary: summary?.model ?? SyncSummary(
                sent: 0, received: 0, conflicts: 0
            ),
            lastSyncAt: lastSyncAt ?? "",
            conflicts: (conflictRows ?? []).map(\.model),
            exactEqual: exactEqual ?? false,
            clinicalConfirmationRequired:
                clinicalConfirmationRequired ?? false,
            clinicalConfirmationDevice: clinicalConfirmationDevice,
            clinicalConfirmationMessage: clinicalConfirmationMessage,
            pendingClinicalConfirmationConversationIDs:
                pendingClinicalConfirmationConvIds ?? [],
            pendingClinicalConfirmationCount:
                pendingClinicalConfirmationCount
                    ?? pendingClinicalConfirmationConvIds?.count ?? 0,
            clinicalSafetyPause:
                clinicalSafetyPause
                    ?? summary?.clinicalSafetyPause ?? false,
            clinicalSafetyDevice:
                clinicalSafetyDevice
                    ?? summary?.clinicalSafetyDevice,
            clinicalSafetyMessage:
                clinicalSafetyMessage
                    ?? summary?.clinicalSafetyMessage
        )
    }
}

struct SyncConflictResolutionWire: Decodable {
    let conflicts: [SyncConflictWire]?

    var model: SyncConflictResolutionResult {
        SyncConflictResolutionResult(
            conflicts: (conflicts ?? []).map(\.model)
        )
    }
}

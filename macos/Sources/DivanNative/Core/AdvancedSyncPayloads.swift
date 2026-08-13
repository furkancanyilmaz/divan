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

    var model: SyncSummary {
        SyncSummary(
            sent: sent ?? 0, received: received ?? 0,
            conflicts: conflicts ?? 0
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
            conflicts: (conflicts ?? []).map(\.model), scope: scope ?? [],
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

    var model: DeviceSyncApplyResult {
        DeviceSyncApplyResult(
            summary: summary?.model ?? SyncSummary(
                sent: 0, received: 0, conflicts: 0
            ),
            lastSyncAt: lastSyncAt ?? "",
            conflicts: (conflictRows ?? []).map(\.model)
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

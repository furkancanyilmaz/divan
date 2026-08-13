import Foundation

// Bu dosya `AdvancedAPIPayloads.swift`'ten ayrıldı: 1214 satırlık
// tek dosya, alan sınırları zaten `// MARK` ile çizilmiş 53 tel
// tipini barındırıyordu. Tipler değişmedi, yalnızca yerleşimleri
// alanlarına göre ayrıldı.
// Sandalye çalışması tel biçimleri.

// MARK: Chair wire payloads

struct SchemaStrategyWire: Decodable {
    let id: String?
    let label: String?
    let group: String?
    let chairLabel: String?
    let slotKeys: [String]?
    let stageIds: [String]?
    let recognize: String?
    let understand: String?
    let question: String?
    let steps: [String]?
    let healthyAdultBridge: String?
    let realWorldBridge: String?
    let avoid: String?
    let relevant: Bool?

    var model: SchemaStrategy {
        SchemaStrategy(
            id: id ?? "", label: label ?? "", group: group ?? "",
            chairLabel: chairLabel ?? "", slotKeys: slotKeys ?? [],
            stageIDs: stageIds ?? [], recognize: recognize ?? "",
            understand: understand ?? "", question: question ?? "",
            steps: steps ?? [], healthyAdultBridge: healthyAdultBridge ?? "",
            realWorldBridge: realWorldBridge ?? "", avoid: avoid ?? "",
            relevant: relevant ?? false
        )
    }
}

struct StageProgressWire: Decodable {
    let completed: Int?
    let total: Int?
    let currentIndex: Int?

    var model: StageProgress {
        StageProgress(
            completed: completed ?? 0,
            total: total ?? 0,
            currentIndex: currentIndex ?? 0
        )
    }
}

struct ChairParticipantWire: Decodable {
    let id: Int?
    let slotKey: String?
    let label: String?
    let sortOrder: Int?
    let source: String?
    let purpose: String?
    let starter: String?
    let turnCount: Int?
    let hasSpoken: Bool?
    let lastIntensity: Int?
    let created: String?
    let updated: String?

    var model: ChairParticipant {
        ChairParticipant(
            id: id ?? 0, slotKey: slotKey ?? "", label: label ?? "",
            sortOrder: sortOrder ?? 0, source: source ?? "",
            purpose: purpose ?? "", starter: starter ?? "",
            turnCount: turnCount ?? 0, hasSpoken: hasSpoken ?? false,
            lastIntensity: lastIntensity, createdAt: created ?? "",
            updatedAt: updated ?? ""
        )
    }
}

struct WorkGuidanceWire: Decodable {
    let observation: String?
    let instruction: String?
    let checkIn: String?

    var model: WorkGuidance {
        WorkGuidance(
            observation: observation ?? "", instruction: instruction ?? "",
            checkIn: checkIn ?? ""
        )
    }
}

struct ChairTurnWire: Decodable {
    let id: Int?
    let seq: Int?
    let actorKind: String?
    let participantId: Int?
    let participantLabel: String?
    let authoredBy: String?
    let turnKind: String?
    let content: String?
    let guidance: WorkGuidanceWire?
    let intensity: Int?
    let payload: [String: JSONValue]?
    let source: String?
    let revertedAt: String?
    let created: String?

    var model: ChairTurn {
        ChairTurn(
            id: id ?? 0, sequence: seq ?? 0,
            actorKind: actorKind ?? "", participantID: participantId,
            participantLabel: participantLabel, authoredBy: authoredBy ?? "",
            turnKind: turnKind ?? "", content: content ?? "",
            guidance: guidance?.model, intensity: intensity,
            payload: payload ?? [:], source: source ?? "",
            revertedAt: revertedAt, createdAt: created ?? ""
        )
    }
}

struct ChairCapabilitiesWire: Decodable {
    let begin: Bool?
    let speak: Bool?
    let guide: Bool?
    let select: Bool?
    let rename: Bool?
    let add: Bool?
    let ground: Bool?
    let resume: Bool?
    let reflect: Bool?
    let complete: Bool?
    let nextStage: Bool?
    let previousStage: Bool?
    let feedback: Bool?

    var model: ChairCapabilities {
        ChairCapabilities(
            begin: begin ?? false, speak: speak ?? false,
            guide: guide ?? false, select: select ?? false,
            rename: rename ?? false, add: add ?? false,
            ground: ground ?? false, resume: resume ?? false,
            reflect: reflect ?? false, complete: complete ?? false,
            nextStage: nextStage ?? false,
            previousStage: previousStage ?? false,
            feedback: feedback ?? false
        )
    }
}

struct ChairWorkWire: Decodable {
    let id: Int?
    let convId: Int?
    let techniqueRunId: Int?
    let therapist: String?
    let methodNodeId: String?
    let methodName: String?
    let `protocol`: String?
    let protocolVersion: Int?
    let title: String?
    let frame: String?
    let status: String?
    let techniqueStatus: String?
    let phase: String?
    let revision: Int?
    let activeParticipantId: Int?
    let guidanceMode: String?
    let participants: [ChairParticipantWire]?
    let turns: [ChairTurnWire]?
    let stageDefs: [ProtocolStageWire]?
    let stages: [ProtocolStageWire]?
    let currentStage: String?
    let currentStageIndex: Int?
    let stageIndex: Int?
    let completedStageIds: [String]?
    let stageProgress: StageProgressWire?
    let roundNo: Int?
    let suggestedNextParticipantId: Int?
    let latestGuidance: ChairTurnWire?
    let latestFeedback: ChairTurnWire?
    let feedbackOptions: [String]?
    let schemaStrategyVersion: Int?
    let schemaStrategies: [SchemaStrategyWire]?
    let stopSignal: String?
    let goalText: String?
    let orientationConfirmed: Bool?
    let frameConfirmed: Bool?
    let consentComplete: Bool?
    let lastSeq: Int?
    let turnCount: Int?
    let conversationTurnCount: Int?
    let created: String?
    let updated: String?
    let canUndo: Bool?
    let safetyHold: Bool?
    let intensity: Int?
    let intensityLimit: Int?
    let capabilities: ChairCapabilitiesWire?

    var model: ChairWork {
        let publicStages = stageDefs ?? stages ?? []
        return ChairWork(
            id: id ?? 0, conversationID: convId ?? 0,
            techniqueRunID: techniqueRunId ?? 0,
            therapistID: therapist ?? "", methodNodeID: methodNodeId ?? "",
            methodName: methodName ?? "", protocolID: `protocol` ?? "",
            protocolVersion: protocolVersion ?? 0, title: title ?? "",
            frame: frame ?? "", status: status ?? "",
            techniqueStatus: techniqueStatus ?? "", phase: phase ?? "",
            revision: revision ?? 0, activeParticipantID: activeParticipantId,
            guidanceMode: guidanceMode ?? "",
            participants: (participants ?? []).map(\.model),
            turns: (turns ?? []).map(\.model),
            stages: publicStages.map(\.model), currentStage: currentStage ?? "",
            currentStageIndex: currentStageIndex ?? stageIndex ?? 0,
            completedStageIDs: completedStageIds ?? [],
            stageProgress: stageProgress?.model ?? StageProgress(
                completed: 0, total: publicStages.count,
                currentIndex: currentStageIndex ?? stageIndex ?? 0
            ),
            roundNumber: roundNo ?? 0,
            suggestedNextParticipantID: suggestedNextParticipantId,
            latestGuidance: latestGuidance?.model,
            latestFeedback: latestFeedback?.model,
            feedbackOptions: feedbackOptions ?? [],
            schemaStrategyVersion: schemaStrategyVersion,
            schemaStrategies: (schemaStrategies ?? []).map(\.model),
            stopSignal: stopSignal ?? "", goalText: goalText ?? "",
            orientationConfirmed: orientationConfirmed ?? false,
            frameConfirmed: frameConfirmed ?? false,
            consentComplete: consentComplete ?? false,
            lastSequence: lastSeq ?? 0, turnCount: turnCount ?? 0,
            conversationTurnCount: conversationTurnCount ?? 0,
            createdAt: created ?? "", updatedAt: updated ?? "",
            canUndo: canUndo ?? false, safetyHold: safetyHold ?? false,
            intensity: intensity, intensityLimit: intensityLimit ?? 10,
            capabilities: capabilities?.model ?? ChairCapabilities(
                begin: false, speak: false, guide: false, select: false,
                rename: false, add: false, ground: false, resume: false,
                reflect: false, complete: false, nextStage: false,
                previousStage: false, feedback: false
            )
        )
    }
}

struct ChairCollectionWire: Decodable {
    let chairwork: ChairWorkWire?
    let chairworks: [ChairWorkWire]?

    var model: ChairWorkCollection {
        ChairWorkCollection(
            chairWork: chairwork?.model,
            chairWorks: (chairworks ?? []).map(\.model)
        )
    }
}

struct ChairMutationWire: Decodable {
    let chairwork: ChairWorkWire
    var model: ChairWorkMutationResult {
        ChairWorkMutationResult(chairWork: chairwork.model)
    }
}

struct ChairTurnResultWire: Decodable {
    let duplicate: Bool?
    let turn: ChairTurnWire?
    let chairwork: ChairWorkWire
    let crisis: Bool?
    let pausedForIntensity: Bool?
    let safetyHold: Bool?
    let message: String?

    var model: ChairTurnResult {
        ChairTurnResult(
            duplicate: duplicate ?? false, turn: turn?.model,
            chairWork: chairwork.model, crisis: crisis ?? false,
            pausedForIntensity: pausedForIntensity ?? false,
            safetyHold: safetyHold ?? false, message: message
        )
    }
}

struct ChairGuidanceResultWire: Decodable {
    let duplicate: Bool?
    let turn: ChairTurnWire
    let chairwork: ChairWorkWire

    var model: ChairGuidanceResult {
        ChairGuidanceResult(
            duplicate: duplicate ?? false, turn: turn.model,
            chairWork: chairwork.model
        )
    }
}

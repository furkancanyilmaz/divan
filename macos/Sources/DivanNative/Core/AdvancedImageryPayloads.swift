import Foundation

// Bu dosya `AdvancedAPIPayloads.swift`'ten ayrıldı: 1214 satırlık
// tek dosya, alan sınırları zaten `// MARK` ile çizilmiş 53 tel
// tipini barındırıyordu. Tipler değişmedi, yalnızca yerleşimleri
// alanlarına göre ayrıldı.
// Güvenli imgeleme tel biçimleri.

// MARK: Imagery wire payloads

struct ImageryStepWire: Decodable {
    let id: Int?
    let seq: Int?
    let stage: String?
    let content: String?
    let intensity: Int?
    let orientationOk: Bool?
    let realityClear: Bool?
    let stopRequested: Bool?
    let authoredBy: String?
    let source: String?
    let turnKind: String?
    let observation: String?
    let instruction: String?
    let checkIn: String?
    let stepData: [String: String]?
    let created: String?
    let revertedAt: String?

    var model: ImageryStep {
        ImageryStep(
            id: id ?? 0, sequence: seq ?? 0, stage: stage ?? "",
            content: content ?? "", intensity: intensity,
            orientationOK: orientationOk, realityClear: realityClear,
            stopRequested: stopRequested ?? false,
            authoredBy: authoredBy ?? "", source: source ?? "",
            turnKind: turnKind ?? "", observation: observation,
            instruction: instruction, checkIn: checkIn,
            stepData: stepData ?? [:], createdAt: created ?? "",
            revertedAt: revertedAt
        )
    }
}

struct ImageryCapabilitiesWire: Decodable {
    let begin: Bool?
    let write: Bool?
    let advance: Bool?
    let ground: Bool?
    let resume: Bool?
    let complete: Bool?
    let stop: Bool?
    let undo: Bool?
    let guidance: Bool?

    var model: ImageryCapabilities {
        ImageryCapabilities(
            begin: begin ?? false, write: write ?? false,
            advance: advance ?? false, ground: ground ?? false,
            resume: resume ?? false, complete: complete ?? false,
            stop: stop ?? false, undo: undo ?? false,
            guidance: guidance ?? false
        )
    }
}

struct ImageryChoiceDescriptorWire: Decodable {
    let id: String?
    let title: String?
    let action: String?

    var model: ImageryChoiceDescriptor? {
        guard let id, !id.isEmpty,
              let title, !title.isEmpty,
              let rawAction = action,
              let action = ImageryChoiceAction(rawValue: rawAction) else {
            return nil
        }
        return ImageryChoiceDescriptor(id: id, title: title, action: action)
    }
}

struct ImageryWorkWire: Decodable {
    let id: Int?
    let convId: Int?
    let techniqueRunId: Int?
    let methodNodeId: String?
    let `protocol`: String?
    let protocolVersion: Int?
    let title: String?
    let frame: String?
    let status: String?
    let currentStage: String?
    let currentStageIndex: Int?
    let stageIndex: Int?
    let stageDefs: [ProtocolStageWire]?
    let completedStageIds: [String]?
    let stageProgress: StageProgressWire?
    let choices: [String]?
    let choiceDescriptors: [ImageryChoiceDescriptorWire]?
    let summary: JSONValue?
    let schemaStrategyVersion: Int?
    let schemaStrategies: [SchemaStrategyWire]?
    let techniqueStatus: String?
    let phase: String?
    let consented: Bool?
    let sceneBoundary: String?
    let stopSignal: String?
    let resumeStage: String?
    let orientationConfirmed: Bool?
    let frameConfirmed: Bool?
    let realityConfirmed: Bool?
    let consentComplete: Bool?
    let revision: Int?
    let intensity: Int?
    let intensityLimit: Int?
    let safetyHold: Bool?
    let steps: [ImageryStepWire]?
    let turns: [ImageryStepWire]?
    let capabilities: ImageryCapabilitiesWire?
    let safetyNote: String?

    var model: ImageryWork {
        let stageModels = (stageDefs ?? []).map(\.model)
        return ImageryWork(
            id: id ?? 0, conversationID: convId ?? 0,
            techniqueRunID: techniqueRunId ?? 0,
            methodNodeID: methodNodeId ?? "", protocolID: `protocol` ?? "",
            protocolVersion: protocolVersion ?? 0, title: title ?? "",
            frame: frame ?? "", status: status ?? "",
            currentStage: currentStage ?? "",
            currentStageIndex: currentStageIndex ?? stageIndex ?? 0,
            stages: stageModels, completedStageIDs: completedStageIds ?? [],
            stageProgress: stageProgress?.model ?? StageProgress(
                completed: 0, total: stageModels.count,
                currentIndex: currentStageIndex ?? stageIndex ?? 0
            ),
            choices: choices ?? [],
            choiceDescriptors: (choiceDescriptors ?? []).compactMap(\.model),
            summary: summary ?? .null,
            schemaStrategyVersion: schemaStrategyVersion,
            schemaStrategies: (schemaStrategies ?? []).map(\.model),
            techniqueStatus: techniqueStatus ?? "", phase: phase ?? "",
            consented: consented ?? false, sceneBoundary: sceneBoundary ?? "",
            stopSignal: stopSignal ?? "", resumeStage: resumeStage ?? "",
            orientationConfirmed: orientationConfirmed ?? false,
            frameConfirmed: frameConfirmed ?? false,
            realityConfirmed: realityConfirmed ?? false,
            consentComplete: consentComplete ?? false,
            revision: revision ?? 0, intensity: intensity,
            intensityLimit: intensityLimit ?? 10,
            safetyHold: safetyHold ?? false,
            steps: (steps ?? turns ?? []).map(\.model),
            capabilities: capabilities?.model ?? ImageryCapabilities(
                begin: false, write: false, advance: false, ground: false,
                resume: false, complete: false, stop: false, undo: false,
                guidance: false
            ),
            safetyNote: safetyNote ?? ""
        )
    }
}

struct ImageryEnvelopeWire: Decodable {
    let imagerywork: ImageryWorkWire?
}

struct ImageryMutationWire: Decodable {
    let imagerywork: ImageryWorkWire
    let pausedForIntensity: Bool?

    var model: ImageryWorkResult {
        ImageryWorkResult(
            imageryWork: imagerywork.model,
            pausedForIntensity: pausedForIntensity ?? false
        )
    }
}

struct ImageryTurnResultWire: Decodable {
    let duplicate: Bool?
    let imagerywork: ImageryWorkWire
    let pausedForIntensity: Bool?
    let crisis: Bool?
    let safetyHold: Bool?
    let message: String?

    var model: ImageryTurnResult {
        ImageryTurnResult(
            duplicate: duplicate ?? false, imageryWork: imagerywork.model,
            pausedForIntensity: pausedForIntensity ?? false,
            crisis: crisis ?? false, safetyHold: safetyHold ?? false,
            message: message
        )
    }
}

struct ImageryGuidanceWire: Decodable {
    let duplicate: Bool?
    let turn: ImageryStepWire
    let guidance: WorkGuidanceWire?
    let imagerywork: ImageryWorkWire

    var model: ImageryGuidanceResult {
        ImageryGuidanceResult(
            duplicate: duplicate ?? false, turn: turn.model,
            guidance: guidance?.model ?? WorkGuidance(
                observation: turn.observation ?? "",
                instruction: turn.instruction ?? "",
                checkIn: turn.checkIn ?? ""
            ),
            imageryWork: imagerywork.model
        )
    }
}

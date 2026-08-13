import Foundation

// Bu dosya `AdvancedAPIPayloads.swift`'ten ayrıldı: 1214 satırlık
// tek dosya, alan sınırları zaten `// MARK` ile çizilmiş 53 tel
// tipini barındırıyordu. Tipler değişmedi, yalnızca yerleşimleri
// alanlarına göre ayrıldı.
// Yöntem kataloğu ve teknik çalışma tel biçimleri.


// Wire DTOs deliberately use `Id`/`Ok` spellings because the shared decoder
// converts `snake_case` to ordinary camel case. Public models keep idiomatic
// Swift `ID`/`OK` names at this boundary.

struct ProtocolStageWire: Decodable {
    let id: String?
    let label: String?
    let aim: String?
    let prompt: String?
    let preferredSlots: [String]?
    let choices: [String]?

    var model: ProtocolStage {
        ProtocolStage(
            id: id ?? "", label: label ?? "", aim: aim ?? "",
            prompt: prompt ?? "", preferredSlots: preferredSlots ?? [],
            choices: choices ?? []
        )
    }
}

struct TechniqueProcessWire: Decodable {
    let id: String?
    let name: String?
    let description: String?

    var model: TechniqueProcess {
        TechniqueProcess(
            id: id ?? "", name: name ?? "", description: description ?? ""
        )
    }
}

struct ParticipantTemplateWire: Decodable {
    let slotKey: String?
    let label: String?

    var model: TechniqueParticipantTemplate {
        TechniqueParticipantTemplate(slotKey: slotKey ?? "", label: label ?? "")
    }
}

struct ParticipantMetadataWire: Decodable {
    let purpose: String?
    let starter: String?

    var model: TechniqueParticipantMetadata {
        TechniqueParticipantMetadata(
            purpose: purpose ?? "", starter: starter ?? ""
        )
    }
}

struct ChairTechniqueConfigurationWire: Decodable {
    let `protocol`: String?
    let protocolVersion: Int?
    let title: String?
    let frame: String?
    let stages: [ProtocolStageWire]?
    let participantMeta: [String: ParticipantMetadataWire]?
    let allowAdd: Bool?
    let minParticipants: Int?
    let maxParticipants: Int?
    let defaultParticipants: [ParticipantTemplateWire]?

    var model: ChairTechniqueConfiguration {
        ChairTechniqueConfiguration(
            protocolID: `protocol` ?? "",
            protocolVersion: protocolVersion ?? 0,
            title: title ?? "",
            frame: frame ?? "",
            stages: (stages ?? []).map(\.model),
            participantMetadata: (participantMeta ?? [:]).mapValues(\.model),
            allowsAddingParticipants: allowAdd ?? false,
            minimumParticipants: minParticipants ?? 0,
            maximumParticipants: maxParticipants ?? 0,
            defaultParticipants: (defaultParticipants ?? []).map(\.model)
        )
    }
}

struct ImageryTechniqueConfigurationWire: Decodable {
    let `protocol`: String?
    let protocolVersion: Int?
    let title: String?
    let frame: String?
    let stages: [ProtocolStageWire]?

    var model: ImageryTechniqueConfiguration {
        ImageryTechniqueConfiguration(
            protocolID: `protocol` ?? "",
            protocolVersion: protocolVersion ?? 0,
            title: title ?? "",
            frame: frame ?? "",
            stages: (stages ?? []).map(\.model)
        )
    }
}

struct TechniqueMethodWire: Decodable {
    let id: Int?
    let key: String?
    let nodeId: String?
    let name: String?
    let description: String?
    let riskLevel: String?
    let requiresConsent: Bool?
    let interactionMode: String?
    let workflowKind: String?
    let workflowNotice: String?
    let chairConfig: ChairTechniqueConfigurationWire?
    let imageryConfig: ImageryTechniqueConfigurationWire?
    let processTags: [String]?
    let processes: [TechniqueProcessWire]?
    let recommended: Bool?
    let reason: String?
    let caution: String?

    var model: TechniqueMethod {
        TechniqueMethod(
            id: id ?? 0,
            key: key ?? "",
            nodeID: nodeId ?? "",
            name: name ?? "",
            description: description ?? "",
            riskLevel: riskLevel ?? "standard",
            requiresConsent: requiresConsent ?? true,
            interactionMode: interactionMode ?? "chat",
            workflowKind: workflowKind ?? "user_confirmed_checkpoints",
            workflowNotice: workflowNotice ?? "",
            chairConfiguration: chairConfig?.model,
            imageryConfiguration: imageryConfig?.model,
            processTags: processTags ?? [],
            processes: (processes ?? []).map(\.model),
            recommended: recommended ?? false,
            reason: reason ?? "",
            caution: caution ?? ""
        )
    }
}

struct TechniqueCatalogWire: Decodable {
    let methods: [TechniqueMethodWire]?
    let intensityLimit: Int?
    let safetyHold: Bool?

    var model: TechniqueCatalog {
        TechniqueCatalog(
            methods: (methods ?? []).map(\.model),
            intensityLimit: intensityLimit ?? 10,
            safetyHold: safetyHold ?? false
        )
    }
}

struct TechniqueRunWire: Decodable {
    let id: Int?
    let conv: Int?
    let therapist: String?
    let methodKey: String?
    let methodName: String?
    let phase: String?
    let status: String?
    let intensityStart: Int?
    let intensityCurrent: Int?
    let consentAt: String?
    let stateJson: String?
    let created: String?
    let updated: String?
    let interactionMode: String?
    let workflowKind: String?
    let workflowNotice: String?
    let chairConfig: ChairTechniqueConfigurationWire?
    let imageryConfig: ImageryTechniqueConfigurationWire?

    var model: TechniqueRun {
        TechniqueRun(
            id: id ?? 0,
            conversationID: conv ?? 0,
            therapistID: therapist ?? "",
            methodKey: methodKey ?? "",
            methodName: methodName ?? "",
            phase: phase ?? "",
            status: status ?? "",
            intensityStart: intensityStart,
            intensityCurrent: intensityCurrent,
            consentAt: consentAt,
            state: Self.decodeState(stateJson),
            createdAt: created ?? "",
            updatedAt: updated ?? "",
            interactionMode: interactionMode ?? "chat",
            workflowKind: workflowKind ?? "user_confirmed_checkpoints",
            workflowNotice: workflowNotice ?? "",
            chairConfiguration: chairConfig?.model,
            imageryConfiguration: imageryConfig?.model
        )
    }

    private static func decodeState(_ text: String?) -> [String: JSONValue] {
        guard let data = text?.data(using: .utf8),
              let value = try? JSONDecoder().decode(
                  [String: JSONValue].self, from: data
              ) else { return [:] }
        return value
    }
}

struct TechniqueRunsWire: Decodable {
    let runs: [TechniqueRunWire]?
    let intensityLimit: Int?
    let safetyHold: Bool?
    let chairwork: ChairWorkWire?
    let chairworks: [ChairWorkWire]?

    var model: TechniqueRunsSnapshot {
        TechniqueRunsSnapshot(
            runs: (runs ?? []).map(\.model),
            intensityLimit: intensityLimit ?? 10,
            safetyHold: safetyHold ?? false,
            chairWork: chairwork?.model,
            chairWorks: (chairworks ?? []).map(\.model)
        )
    }
}

struct TechniqueMutationWire: Decodable {
    let run: TechniqueRunWire
    let chairwork: ChairWorkWire?
    let chairworks: [ChairWorkWire]?

    var model: TechniqueRunMutationResult {
        TechniqueRunMutationResult(
            run: run.model,
            chairWork: chairwork?.model,
            chairWorks: (chairworks ?? []).map(\.model)
        )
    }
}

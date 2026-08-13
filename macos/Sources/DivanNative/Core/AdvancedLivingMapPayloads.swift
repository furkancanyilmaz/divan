import Foundation

// Bu dosya `AdvancedAPIPayloads.swift`'ten ayrıldı: 1214 satırlık
// tek dosya, alan sınırları zaten `// MARK` ile çizilmiş 53 tel
// tipini barındırıyordu. Tipler değişmedi, yalnızca yerleşimleri
// alanlarına göre ayrıldı.
// Yaşayan harita tel biçimleri.

// MARK: Living map wire payloads

struct LivingClaimWire: Decodable {
    let artifactType: String?
    let id: Int?
    let publicId: String?
    let sourceConv: Int?
    let therapist: String?
    let lens: String?
    let claimType: String?
    let title: String?
    let statement: String?
    let trigger: String?
    let triggerContext: String?
    let response: String?
    let experience: String?
    let shortTermEffect: String?
    let longTermEffect: String?
    let need: String?
    let counterexample: String?
    let context: String?
    let reviewNote: String?
    let status: String?
    let scope: String?
    let sensitive: Bool?
    let userEdited: Bool?
    let firstSeen: String?
    let lastSeen: String?
    let reviewedAt: String?
    let created: String?
    let updated: String?
    let evidenceCount: Int?
    let counterexampleCount: Int?
    let sourceCount: Int?
    let pendingEvidenceCount: Int?
    let hasPendingEvidence: Bool?
    let promptEligible: Bool?
    let excludedFromModel: Bool?
    let pending: Bool?
    let reviewKind: String?
    let reviewActions: [String]?
    let reviewPrompt: String?
    let revision: Int?
    let stale: Bool?

    var model: LivingMapClaim {
        LivingMapClaim(
            artifactType: artifactType ?? "insight", id: id ?? 0,
            publicID: publicId ?? String(id ?? 0),
            sourceConversationID: sourceConv, therapistID: therapist ?? "",
            lens: lens ?? "", claimType: claimType ?? "",
            title: title ?? "", statement: statement ?? "",
            trigger: trigger ?? triggerContext ?? "", response: response ?? "",
            experience: experience ?? "",
            shortTermEffect: shortTermEffect ?? "",
            longTermEffect: longTermEffect ?? "", need: need ?? "",
            counterexample: counterexample ?? "", context: context ?? "",
            reviewNote: reviewNote ?? "", status: status ?? "",
            scope: scope ?? "", sensitive: sensitive ?? false,
            userEdited: userEdited ?? false, firstSeen: firstSeen,
            lastSeen: lastSeen, reviewedAt: reviewedAt,
            createdAt: created ?? "", updatedAt: updated ?? "",
            evidenceCount: evidenceCount ?? 0,
            counterexampleCount: counterexampleCount ?? 0,
            sourceCount: sourceCount ?? 0,
            pendingEvidenceCount: pendingEvidenceCount ?? 0,
            hasPendingEvidence: hasPendingEvidence ?? false,
            promptEligible: promptEligible ?? false,
            excludedFromModel: excludedFromModel ?? false,
            pending: pending ?? false, reviewKind: reviewKind,
            reviewActions: reviewActions ?? [], reviewPrompt: reviewPrompt,
            revision: revision, stale: stale ?? false
        )
    }
}

struct LivingSectionsWire: Decodable {
    let cycles: [LivingClaimWire]?
    let valuesNeeds: [LivingClaimWire]?
    let strengthsExceptions: [LivingClaimWire]?
    let goalsHelpful: [LivingClaimWire]?

    var model: LivingMapSections {
        LivingMapSections(
            cycles: (cycles ?? []).map(\.model),
            valuesAndNeeds: (valuesNeeds ?? []).map(\.model),
            strengthsAndExceptions: (strengthsExceptions ?? []).map(\.model),
            goalsAndHelpfulPatterns: (goalsHelpful ?? []).map(\.model)
        )
    }
}

struct LivingCountsWire: Decodable {
    let pending: Int?
    let pendingInsights: Int?
    let pendingEvidenceReviews: Int?
    let pendingFormulations: Int?
    let developingPatterns: Int?
    let retired: Int?
    let hidden: Int?

    var model: LivingMapCounts {
        LivingMapCounts(
            pending: pending ?? 0, pendingInsights: pendingInsights ?? 0,
            pendingEvidenceReviews: pendingEvidenceReviews ?? 0,
            pendingFormulations: pendingFormulations ?? 0,
            developingPatterns: developingPatterns ?? 0,
            retired: retired ?? 0, hidden: hidden ?? 0
        )
    }
}

struct JobWire: Decodable {
    let id: Int?
    let status: String?
    let stage: String?
    let progress: Int?
    let errorCode: String?
    let created: String?
    let started: String?
    let finished: String?
    let updated: String?

    var model: BackgroundJobSummary {
        BackgroundJobSummary(
            id: id ?? 0, status: status ?? "", stage: stage ?? "",
            progress: progress ?? 0, errorCode: errorCode ?? "",
            createdAt: created, startedAt: started, finishedAt: finished,
            updatedAt: updated
        )
    }
}

struct LivingProviderWire: Decodable {
    let id: String?
    let label: String?
    let model: String?
    let local: Bool?

    var modelValue: LivingMapProvider {
        LivingMapProvider(
            id: id ?? "", label: label ?? "", model: model ?? "",
            isLocal: local ?? false
        )
    }
}

struct LivingHistoricalWire: Decodable {
    let eligibleCount: Int?
    let coveredCount: Int?
    let remainingCount: Int?
    let busyCount: Int?
    let failedCount: Int?
    let activeCount: Int?
    let endedCount: Int?
    let archivedCount: Int?
    let safetySkippedCount: Int?
    let includesActive: Bool?
    let includesEnded: Bool?
    let includesArchived: Bool?
    let provider: LivingProviderWire?
    let processing: Bool?
    let job: JobWire?

    var model: LivingMapHistoricalAnalysis {
        LivingMapHistoricalAnalysis(
            eligibleCount: eligibleCount ?? 0, coveredCount: coveredCount ?? 0,
            remainingCount: remainingCount ?? 0, busyCount: busyCount ?? 0,
            failedCount: failedCount ?? 0, activeCount: activeCount ?? 0,
            endedCount: endedCount ?? 0, archivedCount: archivedCount ?? 0,
            safetySkippedCount: safetySkippedCount ?? 0,
            includesActive: includesActive ?? true,
            includesEnded: includesEnded ?? true,
            includesArchived: includesArchived ?? true,
            provider: provider?.modelValue ?? LivingMapProvider(
                id: "", label: "", model: "", isLocal: false
            ),
            processing: processing ?? false, job: job?.model
        )
    }
}

struct LivingGenerationRunWire: Decodable {
    let conv: Int?
    let status: String?
    let provider: String?
    let model: String?
    let candidateCount: Int?
    let throughMessageId: Int?
    let errorCode: String?
    let created: String?
    let started: String?
    let finished: String?
    let updated: String?

    var modelValue: LivingMapGenerationRun {
        LivingMapGenerationRun(
            conversationID: conv ?? 0, status: status ?? "",
            provider: provider ?? "", model: model ?? "",
            candidateCount: candidateCount ?? 0,
            throughMessageID: throughMessageId ?? 0,
            errorCode: errorCode ?? "", createdAt: created ?? "",
            startedAt: started, finishedAt: finished, updatedAt: updated ?? ""
        )
    }
}

struct LivingMapWire: Decodable {
    let version: Int?
    let pending: [LivingClaimWire]?
    let pendingEvidenceReviews: [LivingClaimWire]?
    let sections: LivingSectionsWire?
    let `private`: [LivingClaimWire]?
    let pendingFormulations: [LivingClaimWire]?
    let generationRuns: [LivingGenerationRunWire]?
    let historicalAnalysis: LivingHistoricalWire?
    let counts: LivingCountsWire?
    let disclaimer: String?

    var model: LivingMapSnapshot {
        LivingMapSnapshot(
            version: version ?? 0, pending: (pending ?? []).map(\.model),
            pendingEvidenceReviews: (pendingEvidenceReviews ?? []).map(\.model),
            sections: sections?.model ?? LivingMapSections(
                cycles: [], valuesAndNeeds: [], strengthsAndExceptions: [],
                goalsAndHelpfulPatterns: []
            ),
            privateClaims: (`private` ?? []).map(\.model),
            pendingFormulations: (pendingFormulations ?? []).map(\.model),
            generationRuns: (generationRuns ?? []).map(\.modelValue),
            historicalAnalysis: historicalAnalysis?.model
                ?? LivingHistoricalWire.empty.model,
            counts: counts?.model ?? LivingCountsWire.empty.model,
            disclaimer: disclaimer ?? ""
        )
    }
}

private extension LivingHistoricalWire {
    static var empty: LivingHistoricalWire {
        LivingHistoricalWire(
            eligibleCount: nil, coveredCount: nil, remainingCount: nil,
            busyCount: nil, failedCount: nil, activeCount: nil,
            endedCount: nil, archivedCount: nil, safetySkippedCount: nil,
            includesActive: nil, includesEnded: nil, includesArchived: nil,
            provider: nil, processing: nil, job: nil
        )
    }
}

private extension LivingCountsWire {
    static var empty: LivingCountsWire {
        LivingCountsWire(
            pending: nil, pendingInsights: nil, pendingEvidenceReviews: nil,
            pendingFormulations: nil, developingPatterns: nil, retired: nil,
            hidden: nil
        )
    }
}

struct LivingEvidenceWire: Decodable {
    let id: Int?
    let relation: String?
    let reviewStatus: String?
    let pending: Bool?
    let reviewed: Bool?
    let observationId: Int?
    let convId: Int?
    let conversationTitle: String?
    let therapist: String?
    let messageId: Int?
    let created: String?
    let observedAt: String?
    let authoredBy: String?
    let role: String?
    let sourceLabel: String?
    let excerpt: String?
    let snippet: String?

    var model: LivingMapEvidence {
        LivingMapEvidence(
            id: id ?? 0, relation: relation ?? "", reviewStatus: reviewStatus,
            pending: pending ?? false, reviewed: reviewed ?? false,
            observationID: observationId, conversationID: convId ?? 0,
            conversationTitle: conversationTitle ?? "",
            therapistID: therapist ?? "", messageID: messageId,
            createdAt: created ?? "", observedAt: observedAt ?? created ?? "",
            authoredBy: authoredBy ?? "", role: role ?? "",
            sourceLabel: sourceLabel ?? "", excerpt: excerpt ?? snippet ?? ""
        )
    }
}

struct LivingHistoryWire: Decodable {
    let id: Int?
    let action: String?
    let source: String?
    let created: String?

    var model: LivingMapHistoryEvent {
        LivingMapHistoryEvent(
            id: id ?? 0, action: action ?? "", source: source,
            createdAt: created ?? ""
        )
    }
}

struct LivingDetailWire: Decodable {
    let claim: LivingClaimWire
    let evidence: [LivingEvidenceWire]?
    let history: [LivingHistoryWire]?
    let reviewOutcome: String?
    let formulation: [String: JSONValue]?

    var model: LivingMapClaimDetail {
        LivingMapClaimDetail(
            claim: claim.model, evidence: (evidence ?? []).map(\.model),
            history: (history ?? []).map(\.model),
            reviewOutcome: reviewOutcome, formulation: formulation
        )
    }
}

struct LivingGenerationAcceptedWire: Decodable {
    let processing: Bool?
    let jobId: Int?
    let convId: Int?

    var model: LivingMapGenerationAccepted {
        LivingMapGenerationAccepted(
            processing: processing ?? false, jobID: jobId ?? 0,
            conversationID: convId ?? 0
        )
    }
}

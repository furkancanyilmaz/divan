import Foundation

// MARK: - Technique catalogue and lifecycle

public struct ProtocolStage: Identifiable, Codable, Equatable, Sendable {
    public let id: String
    public let label: String
    public let aim: String
    public let prompt: String
    public let preferredSlots: [String]
    public let choices: [String]
}

public struct TechniqueProcess: Identifiable, Codable, Equatable, Sendable {
    public let id: String
    public let name: String
    public let description: String
}

public struct TechniqueParticipantTemplate: Codable, Equatable, Sendable {
    public let slotKey: String
    public let label: String
}

public struct TechniqueParticipantMetadata: Codable, Equatable, Sendable {
    public let purpose: String
    public let starter: String
}

public struct ChairTechniqueConfiguration: Codable, Equatable, Sendable {
    public let protocolID: String
    public let protocolVersion: Int
    public let title: String
    public let frame: String
    public let stages: [ProtocolStage]
    public let participantMetadata: [String: TechniqueParticipantMetadata]
    public let allowsAddingParticipants: Bool
    public let minimumParticipants: Int
    public let maximumParticipants: Int
    public let defaultParticipants: [TechniqueParticipantTemplate]
}

public struct ImageryTechniqueConfiguration: Codable, Equatable, Sendable {
    public let protocolID: String
    public let protocolVersion: Int
    public let title: String
    public let frame: String
    public let stages: [ProtocolStage]
}

public struct TechniqueMethod: Identifiable, Codable, Equatable, Sendable {
    public let id: Int
    public let key: String
    public let nodeID: String
    public let name: String
    public let description: String
    public let riskLevel: String
    public let requiresConsent: Bool
    public let interactionMode: String
    public let workflowKind: String
    public let workflowNotice: String
    public let chairConfiguration: ChairTechniqueConfiguration?
    public let imageryConfiguration: ImageryTechniqueConfiguration?
    public let processTags: [String]
    public let processes: [TechniqueProcess]
    public let recommended: Bool
    public let reason: String
    public let caution: String

    public var isChairWork: Bool { interactionMode == "chair_work" }
    public var isImageryWork: Bool { interactionMode == "imagery_work" }
    public var isLimitedReparenting: Bool {
        imageryConfiguration?.protocolID == "healthy_adult_reparenting"
    }
}

public struct TechniqueCatalog: Codable, Equatable, Sendable {
    public let methods: [TechniqueMethod]
    public let intensityLimit: Int
    public let safetyHold: Bool
}

public struct TechniqueRun: Identifiable, Codable, Equatable, Sendable {
    public let id: Int
    public let conversationID: Int
    public let therapistID: String
    public let methodKey: String
    public let methodName: String
    public let phase: String
    public let status: String
    public let intensityStart: Int?
    public let intensityCurrent: Int?
    public let consentAt: String?
    public let state: [String: JSONValue]
    public let createdAt: String
    public let updatedAt: String
    public let interactionMode: String
    public let workflowKind: String
    public let workflowNotice: String
    public let chairConfiguration: ChairTechniqueConfiguration?
    public let imageryConfiguration: ImageryTechniqueConfiguration?

    public var isOpen: Bool {
        ["proposed", "active", "paused"].contains(status)
    }
}

public struct TechniqueRunsSnapshot: Codable, Equatable, Sendable {
    public let runs: [TechniqueRun]
    public let intensityLimit: Int
    public let safetyHold: Bool
    public let chairWork: ChairWork?
    public let chairWorks: [ChairWork]
}

public enum TechniqueRunAction: String, Codable, CaseIterable, Sendable {
    case propose
    case consent
    case intensity
    case advance
    case pause
    case resume
    case stop
    case complete
}

public struct TechniqueRunMutation: Codable, Equatable, Sendable {
    public let conversationID: Int
    public let action: TechniqueRunAction
    public let runID: Int?
    public let methodKey: String?
    public let methodID: Int?
    public let intensity: Int?
    /// Evidence that the user actively accepted the proposed technique.
    public let consentConfirmed: Bool?
    public let checkpointConfirmed: Bool?
    public let checkpointNote: String?

    public init(
        conversationID: Int,
        action: TechniqueRunAction,
        runID: Int? = nil,
        methodKey: String? = nil,
        methodID: Int? = nil,
        intensity: Int? = nil,
        consentConfirmed: Bool? = nil,
        checkpointConfirmed: Bool? = nil,
        checkpointNote: String? = nil
    ) {
        self.conversationID = conversationID
        self.action = action
        self.runID = runID
        self.methodKey = methodKey
        self.methodID = methodID
        self.intensity = intensity
        self.consentConfirmed = consentConfirmed
        self.checkpointConfirmed = checkpointConfirmed
        self.checkpointNote = checkpointNote
    }
}

public struct TechniqueRunMutationResult: Codable, Equatable, Sendable {
    public let run: TechniqueRun
    public let chairWork: ChairWork?
    public let chairWorks: [ChairWork]
}

// MARK: - Chair work

public struct SchemaStrategy: Identifiable, Codable, Equatable, Sendable {
    public let id: String
    public let label: String
    public let group: String
    public let chairLabel: String
    public let slotKeys: [String]
    public let stageIDs: [String]
    public let recognize: String
    public let understand: String
    public let question: String
    public let steps: [String]
    public let healthyAdultBridge: String
    public let realWorldBridge: String
    public let avoid: String
    public let relevant: Bool
}

public struct StageProgress: Codable, Equatable, Sendable {
    public let completed: Int
    public let total: Int
    public let currentIndex: Int
}

public struct ChairParticipant: Identifiable, Codable, Equatable, Sendable {
    public let id: Int
    public let slotKey: String
    public let label: String
    public let sortOrder: Int
    public let source: String
    public let purpose: String
    public let starter: String
    public let turnCount: Int
    public let hasSpoken: Bool
    public let lastIntensity: Int?
    public let createdAt: String
    public let updatedAt: String
}

public struct WorkGuidance: Codable, Equatable, Sendable {
    public let observation: String
    public let instruction: String
    public let checkIn: String
}

public struct ChairTurn: Identifiable, Codable, Equatable, Sendable {
    public let id: Int
    public let sequence: Int
    public let actorKind: String
    public let participantID: Int?
    public let participantLabel: String?
    public let authoredBy: String
    public let turnKind: String
    public let content: String
    public let guidance: WorkGuidance?
    public let intensity: Int?
    public let payload: [String: JSONValue]
    public let source: String
    public let revertedAt: String?
    public let createdAt: String
}

public struct ChairCapabilities: Codable, Equatable, Sendable {
    public let begin: Bool
    public let speak: Bool
    public let guide: Bool
    public let select: Bool
    public let rename: Bool
    public let add: Bool
    public let ground: Bool
    public let resume: Bool
    public let reflect: Bool
    public let complete: Bool
    public let nextStage: Bool
    public let previousStage: Bool
    public let feedback: Bool
}

public struct ChairWork: Identifiable, Codable, Equatable, Sendable {
    public let id: Int
    public let conversationID: Int
    public let techniqueRunID: Int
    public let therapistID: String
    public let methodNodeID: String
    public let methodName: String
    public let protocolID: String
    public let protocolVersion: Int
    public let title: String
    public let frame: String
    public let status: String
    public let techniqueStatus: String
    public let phase: String
    public let revision: Int
    public let activeParticipantID: Int?
    public let guidanceMode: String
    public let participants: [ChairParticipant]
    public let turns: [ChairTurn]
    public let stages: [ProtocolStage]
    public let currentStage: String
    public let currentStageIndex: Int
    public let completedStageIDs: [String]
    public let stageProgress: StageProgress
    public let roundNumber: Int
    public let suggestedNextParticipantID: Int?
    public let latestGuidance: ChairTurn?
    public let latestFeedback: ChairTurn?
    public let feedbackOptions: [String]
    public let schemaStrategyVersion: Int?
    public let schemaStrategies: [SchemaStrategy]
    public let stopSignal: String
    public let goalText: String
    public let orientationConfirmed: Bool
    public let frameConfirmed: Bool
    public let consentComplete: Bool
    public let lastSequence: Int
    public let turnCount: Int
    public let conversationTurnCount: Int
    public let createdAt: String
    public let updatedAt: String
    public let canUndo: Bool
    public let safetyHold: Bool
    public let intensity: Int?
    public let intensityLimit: Int
    public let capabilities: ChairCapabilities
}

public struct ChairWorkCollection: Codable, Equatable, Sendable {
    public let chairWork: ChairWork?
    public let chairWorks: [ChairWork]
}

public enum ChairWorkAction: String, Codable, CaseIterable, Sendable {
    case begin
    case select
    case rename
    case add
    case ground
    case resume
    case reflect
    case complete
    case undo
    case nextStage = "next_stage"
    case previousStage = "previous_stage"
    case feedback
    case stop
}

public struct ChairWorkMutation: Codable, Equatable, Sendable {
    public let conversationID: Int
    public let chairRunID: Int?
    public let action: ChairWorkAction
    public let expectedRevision: Int?
    public let participantID: Int?
    public let label: String?
    public let feedback: String?
    public let guidanceTurnID: Int?
    /// Explicit confirmations required when beginning an enhanced chair protocol.
    public let orientationOK: Bool?
    public let frameOK: Bool?
    public let stopSignal: String?
    public let goalText: String?
    /// User-authored checkpoint data for the ground/reflect/complete lifecycle.
    /// These values are intentionally optional because emergency `stop` must
    /// remain available without completing a form.
    public let checkpointConfirmed: Bool?
    public let checkpointNote: String?
    public let intensity: Int?

    public init(
        conversationID: Int,
        chairRunID: Int? = nil,
        action: ChairWorkAction,
        expectedRevision: Int? = nil,
        participantID: Int? = nil,
        label: String? = nil,
        feedback: String? = nil,
        guidanceTurnID: Int? = nil,
        orientationOK: Bool? = nil,
        frameOK: Bool? = nil,
        stopSignal: String? = nil,
        goalText: String? = nil,
        checkpointConfirmed: Bool? = nil,
        checkpointNote: String? = nil,
        intensity: Int? = nil
    ) {
        self.conversationID = conversationID
        self.chairRunID = chairRunID
        self.action = action
        self.expectedRevision = expectedRevision
        self.participantID = participantID
        self.label = label
        self.feedback = feedback
        self.guidanceTurnID = guidanceTurnID
        self.orientationOK = orientationOK
        self.frameOK = frameOK
        self.stopSignal = stopSignal
        self.goalText = goalText
        self.checkpointConfirmed = checkpointConfirmed
        self.checkpointNote = checkpointNote
        self.intensity = intensity
    }
}

public struct ChairWorkMutationResult: Codable, Equatable, Sendable {
    public let chairWork: ChairWork
}

public struct ChairTurnInput: Codable, Equatable, Sendable {
    public let conversationID: Int
    public let chairRunID: Int?
    public let participantID: Int?
    public let content: String
    public let intensity: Int?
    public let expectedRevision: Int?
    public let strategyID: String?
    public let clientEventID: String?

    public init(
        conversationID: Int,
        chairRunID: Int? = nil,
        participantID: Int? = nil,
        content: String,
        intensity: Int? = nil,
        expectedRevision: Int? = nil,
        strategyID: String? = nil,
        clientEventID: String? = nil
    ) {
        self.conversationID = conversationID
        self.chairRunID = chairRunID
        self.participantID = participantID
        self.content = content
        self.intensity = intensity
        self.expectedRevision = expectedRevision
        self.strategyID = strategyID
        self.clientEventID = clientEventID
    }
}

public struct ChairTurnResult: Codable, Equatable, Sendable {
    public let duplicate: Bool
    /// Nil when the user's exact personal stop signal closed the run without
    /// recording the signal as an experiential utterance.
    public let turn: ChairTurn?
    public let chairWork: ChairWork
    public let crisis: Bool
    public let pausedForIntensity: Bool
    public let safetyHold: Bool
    public let message: String?
}

public struct ChairGuidanceInput: Codable, Equatable, Sendable {
    public let conversationID: Int
    public let chairRunID: Int?
    public let afterSequence: Int
    public let revision: Int
    public let requestID: String?

    public init(
        conversationID: Int,
        chairRunID: Int? = nil,
        afterSequence: Int,
        revision: Int,
        requestID: String? = nil
    ) {
        self.conversationID = conversationID
        self.chairRunID = chairRunID
        self.afterSequence = afterSequence
        self.revision = revision
        self.requestID = requestID
    }
}

public struct ChairGuidanceResult: Codable, Equatable, Sendable {
    public let duplicate: Bool
    public let turn: ChairTurn
    public let chairWork: ChairWork
}

// MARK: - Imagery and limited reparenting

public struct ImageryStep: Identifiable, Codable, Equatable, Sendable {
    public let id: Int
    public let sequence: Int
    public let stage: String
    public let content: String
    public let intensity: Int?
    public let orientationOK: Bool?
    public let realityClear: Bool?
    public let stopRequested: Bool
    public let authoredBy: String
    public let source: String
    public let turnKind: String
    public let observation: String?
    public let instruction: String?
    public let checkIn: String?
    public let stepData: [String: String]
    public let createdAt: String
    public let revertedAt: String?
}

public struct ImageryCapabilities: Codable, Equatable, Sendable {
    public let begin: Bool
    public let write: Bool
    public let advance: Bool
    public let ground: Bool
    public let resume: Bool
    public let complete: Bool
    public let stop: Bool
    public let undo: Bool
    public let guidance: Bool
}

public struct ImageryWork: Identifiable, Codable, Equatable, Sendable {
    public let id: Int
    public let conversationID: Int
    public let techniqueRunID: Int
    public let methodNodeID: String
    public let protocolID: String
    public let protocolVersion: Int
    public let title: String
    public let frame: String
    public let status: String
    public let currentStage: String
    public let currentStageIndex: Int
    public let stages: [ProtocolStage]
    public let completedStageIDs: [String]
    public let stageProgress: StageProgress
    public let choices: [String]
    public let choiceDescriptors: [ImageryChoiceDescriptor]
    public let summary: JSONValue
    public let schemaStrategyVersion: Int?
    public let schemaStrategies: [SchemaStrategy]
    public let techniqueStatus: String
    public let phase: String
    public let consented: Bool
    public let sceneBoundary: String
    public let stopSignal: String
    public let resumeStage: String
    public let orientationConfirmed: Bool
    public let frameConfirmed: Bool
    public let realityConfirmed: Bool
    public let consentComplete: Bool
    public let revision: Int
    public let intensity: Int?
    public let intensityLimit: Int
    public let safetyHold: Bool
    public let steps: [ImageryStep]
    public let capabilities: ImageryCapabilities
    public let safetyNote: String

    public var isLimitedReparenting: Bool {
        protocolID == "healthy_adult_reparenting"
    }
}

public enum ImageryChoiceAction: String, Codable, CaseIterable, Sendable {
    case advance
    case ground
    case stop
}

public struct ImageryChoiceDescriptor: Identifiable, Codable, Equatable, Sendable {
    public let id: String
    public let title: String
    public let action: ImageryChoiceAction

    public init(id: String, title: String, action: ImageryChoiceAction) {
        self.id = id
        self.title = title
        self.action = action
    }
}

public enum ImageryWorkAction: String, Codable, CaseIterable, Sendable {
    case create
    case consent
    case begin
    case stop
    case ground
    case resume
    case complete
    case advance
    case undo
}

public struct ImageryWorkMutation: Codable, Equatable, Sendable {
    public let conversationID: Int
    public let action: ImageryWorkAction
    public let imageryRunID: Int?
    public let techniqueRunID: Int?
    public let revision: Int?
    public let orientationOK: Bool?
    public let frameOK: Bool?
    public let realityClear: Bool?
    public let stopSignal: String?
    public let sceneBoundary: String?
    public let intensity: Int?
    public let groundingConfirmed: Bool?
    public let summary: String?

    public init(
        conversationID: Int,
        action: ImageryWorkAction,
        imageryRunID: Int? = nil,
        techniqueRunID: Int? = nil,
        revision: Int? = nil,
        orientationOK: Bool? = nil,
        frameOK: Bool? = nil,
        realityClear: Bool? = nil,
        stopSignal: String? = nil,
        sceneBoundary: String? = nil,
        intensity: Int? = nil,
        groundingConfirmed: Bool? = nil,
        summary: String? = nil
    ) {
        self.conversationID = conversationID
        self.action = action
        self.imageryRunID = imageryRunID
        self.techniqueRunID = techniqueRunID
        self.revision = revision
        self.orientationOK = orientationOK
        self.frameOK = frameOK
        self.realityClear = realityClear
        self.stopSignal = stopSignal
        self.sceneBoundary = sceneBoundary
        self.intensity = intensity
        self.groundingConfirmed = groundingConfirmed
        self.summary = summary
    }
}

public struct ImageryWorkResult: Codable, Equatable, Sendable {
    public let imageryWork: ImageryWork
    public let pausedForIntensity: Bool
}

public struct ImageryTurnInput: Codable, Equatable, Sendable {
    public let conversationID: Int
    public let imageryRunID: Int
    public let content: String
    public let intensity: Int
    public let orientationOK: Bool
    public let realityClear: Bool?
    public let expectedRevision: Int?
    public let stepData: [String: String]
    public let clientEventID: String?

    public init(
        conversationID: Int,
        imageryRunID: Int,
        content: String,
        intensity: Int,
        orientationOK: Bool,
        realityClear: Bool? = nil,
        expectedRevision: Int? = nil,
        stepData: [String: String] = [:],
        clientEventID: String? = nil
    ) {
        self.conversationID = conversationID
        self.imageryRunID = imageryRunID
        self.content = content
        self.intensity = intensity
        self.orientationOK = orientationOK
        self.realityClear = realityClear
        self.expectedRevision = expectedRevision
        self.stepData = stepData
        self.clientEventID = clientEventID
    }
}

public struct ImageryTurnResult: Codable, Equatable, Sendable {
    public let duplicate: Bool
    public let imageryWork: ImageryWork
    public let pausedForIntensity: Bool
    public let crisis: Bool
    public let safetyHold: Bool
    public let message: String?
}

public struct ImageryGuidanceResult: Codable, Equatable, Sendable {
    public let duplicate: Bool
    public let turn: ImageryStep
    public let guidance: WorkGuidance
    public let imageryWork: ImageryWork
}

// MARK: - Living map

public struct LivingMapClaim: Identifiable, Codable, Equatable, Sendable {
    public let artifactType: String
    public let id: Int
    public let publicID: String
    public let sourceConversationID: Int?
    public let therapistID: String
    public let lens: String
    public let claimType: String
    public let title: String
    public let statement: String
    public let trigger: String
    public let response: String
    public let experience: String
    public let shortTermEffect: String
    public let longTermEffect: String
    public let need: String
    public let counterexample: String
    public let context: String
    public let reviewNote: String
    public let status: String
    public let scope: String
    public let sensitive: Bool
    public let userEdited: Bool
    public let firstSeen: String?
    public let lastSeen: String?
    public let reviewedAt: String?
    public let createdAt: String
    public let updatedAt: String
    public let evidenceCount: Int
    public let counterexampleCount: Int
    public let sourceCount: Int
    public let pendingEvidenceCount: Int
    public let hasPendingEvidence: Bool
    public let promptEligible: Bool
    public let excludedFromModel: Bool
    public let pending: Bool
    public let reviewKind: String?
    public let reviewActions: [String]
    public let reviewPrompt: String?
    public let revision: Int?
    public let stale: Bool
}

public struct LivingMapSections: Codable, Equatable, Sendable {
    public let cycles: [LivingMapClaim]
    public let valuesAndNeeds: [LivingMapClaim]
    public let strengthsAndExceptions: [LivingMapClaim]
    public let goalsAndHelpfulPatterns: [LivingMapClaim]
}

public struct LivingMapCounts: Codable, Equatable, Sendable {
    public let pending: Int
    public let pendingInsights: Int
    public let pendingEvidenceReviews: Int
    public let pendingFormulations: Int
    public let developingPatterns: Int
    public let retired: Int
    public let hidden: Int
}

public struct BackgroundJobSummary: Identifiable, Codable, Equatable, Sendable {
    public let id: Int
    public let status: String
    public let stage: String
    public let progress: Int
    public let errorCode: String
    public let createdAt: String?
    public let startedAt: String?
    public let finishedAt: String?
    public let updatedAt: String?
}

public struct LivingMapProvider: Codable, Equatable, Sendable {
    public let id: String
    public let label: String
    public let model: String
    public let isLocal: Bool
}

public struct LivingMapHistoricalAnalysis: Codable, Equatable, Sendable {
    public let eligibleCount: Int
    public let coveredCount: Int
    public let remainingCount: Int
    public let busyCount: Int
    public let failedCount: Int
    public let activeCount: Int
    public let endedCount: Int
    public let archivedCount: Int
    public let safetySkippedCount: Int
    public let includesActive: Bool
    public let includesEnded: Bool
    public let includesArchived: Bool
    public let provider: LivingMapProvider
    public let processing: Bool
    public let job: BackgroundJobSummary?
}

public struct LivingMapGenerationRun: Codable, Equatable, Sendable {
    public let conversationID: Int
    public let status: String
    public let provider: String
    public let model: String
    public let candidateCount: Int
    public let throughMessageID: Int
    public let errorCode: String
    public let createdAt: String
    public let startedAt: String?
    public let finishedAt: String?
    public let updatedAt: String
}

public struct LivingMapSnapshot: Codable, Equatable, Sendable {
    public let version: Int
    public let pending: [LivingMapClaim]
    public let pendingEvidenceReviews: [LivingMapClaim]
    public let sections: LivingMapSections
    public let privateClaims: [LivingMapClaim]
    public let pendingFormulations: [LivingMapClaim]
    public let generationRuns: [LivingMapGenerationRun]
    public let historicalAnalysis: LivingMapHistoricalAnalysis
    public let counts: LivingMapCounts
    public let disclaimer: String
}

public struct LivingMapEvidence: Identifiable, Codable, Equatable, Sendable {
    public let id: Int
    public let relation: String
    public let reviewStatus: String?
    public let pending: Bool
    public let reviewed: Bool
    public let observationID: Int?
    public let conversationID: Int
    public let conversationTitle: String
    public let therapistID: String
    public let messageID: Int?
    public let createdAt: String
    public let observedAt: String
    public let authoredBy: String
    public let role: String
    public let sourceLabel: String
    public let excerpt: String
}

public struct LivingMapHistoryEvent: Identifiable, Codable, Equatable, Sendable {
    public let id: Int
    public let action: String
    public let source: String?
    public let createdAt: String
}

public struct LivingMapClaimDetail: Codable, Equatable, Sendable {
    public let claim: LivingMapClaim
    public let evidence: [LivingMapEvidence]
    public let history: [LivingMapHistoryEvent]
    public let reviewOutcome: String?
    public let formulation: [String: JSONValue]?
}

public enum LivingMapReviewAction: String, Codable, CaseIterable, Sendable {
    case confirm
    case partial
    case context
    case reject
    case retire
    case rejectEvidence = "reject_evidence"
    case makePrivate = "private"
    case exclude
    case edit
}

public struct LivingMapClaimEdits: Codable, Equatable, Sendable {
    public var title: String?
    public var statement: String?
    public var trigger: String?
    public var experience: String?
    public var response: String?
    public var shortTermEffect: String?
    public var longTermEffect: String?
    public var need: String?
    public var counterexample: String?
    public var context: String?
    public var note: String?

    public init(
        title: String? = nil,
        statement: String? = nil,
        trigger: String? = nil,
        experience: String? = nil,
        response: String? = nil,
        shortTermEffect: String? = nil,
        longTermEffect: String? = nil,
        need: String? = nil,
        counterexample: String? = nil,
        context: String? = nil,
        note: String? = nil
    ) {
        self.title = title
        self.statement = statement
        self.trigger = trigger
        self.experience = experience
        self.response = response
        self.shortTermEffect = shortTermEffect
        self.longTermEffect = longTermEffect
        self.need = need
        self.counterexample = counterexample
        self.context = context
        self.note = note
    }
}

public struct LivingMapReviewRequest: Codable, Equatable, Sendable {
    public let claimReference: String
    public let action: LivingMapReviewAction
    public let scope: String?
    public let sensitive: Bool?
    public let excludedFromModel: Bool?
    public let edits: LivingMapClaimEdits

    public init(
        claimReference: String,
        action: LivingMapReviewAction,
        scope: String? = nil,
        sensitive: Bool? = nil,
        excludedFromModel: Bool? = nil,
        edits: LivingMapClaimEdits = LivingMapClaimEdits()
    ) {
        self.claimReference = claimReference
        self.action = action
        self.scope = scope
        self.sensitive = sensitive
        self.excludedFromModel = excludedFromModel
        self.edits = edits
    }
}

public struct LivingMapGenerationAccepted: Codable, Equatable, Sendable {
    public let processing: Bool
    public let jobID: Int
    public let conversationID: Int
}

// MARK: - Same-Wi-Fi sync

public struct SyncSummary: Codable, Equatable, Sendable {
    public let sent: Int
    public let received: Int
    public let conflicts: Int
}

public struct SyncConflict: Identifiable, Codable, Equatable, Sendable {
    public let id: Int
    public let recordType: String
    public let title: String
    public let summary: String
    public let reason: String
    public let createdAt: String
}

public struct DeviceSyncStatus: Codable, Equatable, Sendable {
    public let hostRunning: Bool
    public let busy: Bool
    public let secondsRemaining: Int
    public let lastSyncAt: String?
    public let lastPeerName: String?
    public let lastSummary: SyncSummary
    public let conflicts: [SyncConflict]
    public let scope: [String]
    public let secretsExcluded: Bool
}

public struct SyncQRMatrix: Codable, Equatable, Sendable {
    public let size: Int
    public let rows: [String]
}

public struct DeviceSyncInvitation: Codable, Equatable, Sendable {
    public let pairingCode: String
    public let qrMatrix: SyncQRMatrix
    public let secondsRemaining: Int
}

public struct DeviceSyncApplyResult: Codable, Equatable, Sendable {
    public let summary: SyncSummary
    public let lastSyncAt: String
    public let conflicts: [SyncConflict]
}

public enum SyncConflictResolution: String, Codable, CaseIterable, Sendable {
    case local
    case remote
}

public struct SyncConflictResolutionResult: Codable, Equatable, Sendable {
    public let conflicts: [SyncConflict]
}

// MARK: - Session summary

public enum SessionSummaryStatus: String, Codable, Sendable {
    case pending
    case approved
    case rejected
}

/// Seans sonrası üretilen özet taslağı ve kullanıcının kararı.
///
/// Taslak çekirdek tarafından arka planda yazılır; onaylanana kadar
/// kalıcı hafızaya (session_meta.summary) geçmez.
public struct SessionSummaryRecord: Codable, Equatable, Sendable {
    public let conversationID: Int
    public let draft: String
    public let approvedContent: String
    public let status: SessionSummaryStatus
    public let approvedAt: String
    public let updatedAt: String

    public init(
        conversationID: Int,
        draft: String,
        approvedContent: String,
        status: SessionSummaryStatus,
        approvedAt: String,
        updatedAt: String
    ) {
        self.conversationID = conversationID
        self.draft = draft
        self.approvedContent = approvedContent
        self.status = status
        self.approvedAt = approvedAt
        self.updatedAt = updatedAt
    }

    /// Kullanıcıya gösterilecek metin: onaylandıysa onaylanan, değilse taslak.
    public var displayText: String {
        status == .approved && !approvedContent.isEmpty
            ? approvedContent
            : draft
    }
}

/// Özet üzerinde kullanıcının yapabileceği işlemler.
public enum SessionSummaryAction: String, Sendable {
    case update
    case approve
    case reject
}

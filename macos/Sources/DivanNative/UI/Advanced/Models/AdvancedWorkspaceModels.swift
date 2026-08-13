import Foundation

public enum AdvancedModule: String, CaseIterable, Identifiable, Sendable {
    case chairWork
    case reparenting
    case livingMap
    case wifiSync

    public var id: Self { self }

    public var title: String {
        switch self {
        case .chairWork: "Sandalye çalışması"
        case .reparenting: "İmgeleme ve yeniden ebeveynlik"
        case .livingMap: "Yaşayan harita"
        case .wifiSync: "Wi-Fi ile eşitleme"
        }
    }

    public var shortTitle: String {
        switch self {
        case .chairWork: "Sandalye"
        case .reparenting: "Yeniden ebeveynlik"
        case .livingMap: "Yaşayan harita"
        case .wifiSync: "Eşitleme"
        }
    }

    public var subtitle: String {
        switch self {
        case .chairWork:
            "İki parçayı sırayla konuşturun; AI terapist yönerge ve gözlem sunsun."
        case .reparenting:
            "Güvenli mesafe, açık onay ve topraklanma adımlarıyla ilerleyin."
        case .livingMap:
            "Tekrarlayan örüntüleri ve dayanaklarını inceleyip doğrulayın."
        case .wifiSync:
            "Aynı yerel ağdaki iki Divan veri alanını açık onayla eşitleyin."
        }
    }

    public var systemImage: String {
        switch self {
        case .chairWork: "chair.lounge"
        case .reparenting: "figure.and.child.holdinghands"
        case .livingMap: "point.3.connected.trianglepath.dotted"
        case .wifiSync: "qrcode.viewfinder"
        }
    }

    public var isClinical: Bool { self != .wifiSync }
}

public struct AdvancedWorkspaceContext: Sendable, Equatable {
    public let conversationID: Int?
    public let masterID: String?
    public let masterName: String?
    public let allowsClinicalWork: Bool

    public init(
        conversationID: Int? = nil,
        masterID: String? = nil,
        masterName: String? = nil,
        allowsClinicalWork: Bool = true
    ) {
        self.conversationID = conversationID
        self.masterID = masterID
        self.masterName = masterName
        self.allowsClinicalWork = allowsClinicalWork
    }
}

public enum WorkspaceWorkPhase: String, Sendable {
    case notStarted
    case active
    case paused
    case completed
}

public struct AdvancedWorkspaceSnapshot: Sendable {
    public let clinicalIntensityLimit: Int
    public let clinicalSafetyHold: Bool
    public let chairAvailable: Bool
    public let chairUnavailableReason: String?
    public let imageryAvailable: Bool
    public let imageryUnavailableReason: String?
    public let chairConfiguration: WorkspaceChairConfiguration
    public let chairSession: WorkspaceChairSession?
    public let imagerySession: WorkspaceImagerySession?
    public let livingMap: [WorkspaceLivingMapCard]
    public let syncStatus: WorkspaceWiFiSyncStatus

    public init(
        clinicalIntensityLimit: Int = 10,
        clinicalSafetyHold: Bool = false,
        chairAvailable: Bool = false,
        chairUnavailableReason: String? = nil,
        imageryAvailable: Bool = false,
        imageryUnavailableReason: String? = nil,
        chairConfiguration: WorkspaceChairConfiguration = .twoPartDefault,
        chairSession: WorkspaceChairSession? = nil,
        imagerySession: WorkspaceImagerySession? = nil,
        livingMap: [WorkspaceLivingMapCard] = [],
        syncStatus: WorkspaceWiFiSyncStatus = .idle
    ) {
        self.clinicalIntensityLimit = max(1, clinicalIntensityLimit)
        self.clinicalSafetyHold = clinicalSafetyHold
        self.chairAvailable = chairAvailable
        self.chairUnavailableReason = chairUnavailableReason
        self.imageryAvailable = imageryAvailable
        self.imageryUnavailableReason = imageryUnavailableReason
        self.chairConfiguration = chairConfiguration
        self.chairSession = chairSession
        self.imagerySession = imagerySession
        self.livingMap = livingMap
        self.syncStatus = syncStatus
    }
}

// MARK: - Chair work

public struct WorkspaceChairConfiguration: Sendable {
    public let title: String
    public let frame: String
    public let minimumParticipants: Int
    public let maximumParticipants: Int
    public let allowsAddingParticipants: Bool
    public let defaultParticipantTitles: [String]

    public init(
        title: String,
        frame: String,
        minimumParticipants: Int,
        maximumParticipants: Int,
        allowsAddingParticipants: Bool,
        defaultParticipantTitles: [String]
    ) {
        self.title = title
        self.frame = frame
        self.minimumParticipants = max(2, minimumParticipants)
        self.maximumParticipants = max(self.minimumParticipants, min(6, maximumParticipants))
        self.allowsAddingParticipants = allowsAddingParticipants
        self.defaultParticipantTitles = defaultParticipantTitles
    }

    public static var twoPartDefault: Self {
        .init(
            title: "Parçalar arası sandalye çalışması",
            frame: "Her sandalyedeki sözleri kullanıcı söyler; AI terapist yalnız süreç yönergesi verir.",
            minimumParticipants: 2,
            maximumParticipants: 6,
            allowsAddingParticipants: true,
            defaultParticipantTitles: [
                "İhtiyacı olan parçam",
                "Beni korumaya çalışan parçam",
            ]
        )
    }
}

public struct WorkspaceChairIdentity: Identifiable, Hashable, Sendable {
    public let id: String
    public let title: String
    public let prompt: String
    public let sortOrder: Int

    public init(id: String, title: String, prompt: String, sortOrder: Int) {
        self.id = id
        self.title = title
        self.prompt = prompt
        self.sortOrder = sortOrder
    }
}

public struct WorkspaceChairTurn: Identifiable, Hashable, Sendable {
    public let id: String
    public let chairID: String
    public let chairTitle: String
    public let content: String
    public let createdAt: Date

    public init(
        id: String,
        chairID: String,
        chairTitle: String,
        content: String,
        createdAt: Date
    ) {
        self.id = id
        self.chairID = chairID
        self.chairTitle = chairTitle
        self.content = content
        self.createdAt = createdAt
    }
}

public struct WorkspaceChairGuidance: Identifiable, Hashable, Sendable {
    public let id: String
    public let observation: String
    public let nextStep: String
    public let checkIn: String
    public let createdAt: Date

    public init(
        id: String,
        observation: String,
        nextStep: String,
        checkIn: String = "",
        createdAt: Date
    ) {
        self.id = id
        self.observation = observation
        self.nextStep = nextStep
        self.checkIn = checkIn
        self.createdAt = createdAt
    }
}

public struct WorkspaceChairSession: Identifiable, Sendable {
    public let id: String
    public let title: String
    public let frame: String
    public let goalText: String
    public let stopSignal: String
    public let participants: [WorkspaceChairIdentity]
    public let minimumParticipants: Int
    public let maximumParticipants: Int
    public let allowsAddingParticipants: Bool
    public let orientationConfirmed: Bool
    public let frameConfirmed: Bool
    public let stages: [WorkspaceProtocolStage]
    public let currentStageID: String
    public let currentStageIndex: Int
    public let availableClosureActions: [WorkspaceChairClosureAction]
    public let completedClosureActions: Set<WorkspaceChairClosureAction>
    public let activeChairID: String
    public let turns: [WorkspaceChairTurn]
    public let guidance: [WorkspaceChairGuidance]
    public let phase: WorkspaceWorkPhase
    public let intensity: Int
    public let intensityLimit: Int
    public let updatedAt: Date

    public init(
        id: String,
        title: String,
        frame: String,
        goalText: String,
        stopSignal: String,
        participants: [WorkspaceChairIdentity],
        minimumParticipants: Int,
        maximumParticipants: Int,
        allowsAddingParticipants: Bool,
        orientationConfirmed: Bool,
        frameConfirmed: Bool,
        stages: [WorkspaceProtocolStage] = [],
        currentStageID: String = "",
        currentStageIndex: Int = 0,
        availableClosureActions: [WorkspaceChairClosureAction] = WorkspaceChairClosureAction.allCases,
        completedClosureActions: Set<WorkspaceChairClosureAction> = [],
        activeChairID: String,
        turns: [WorkspaceChairTurn] = [],
        guidance: [WorkspaceChairGuidance] = [],
        phase: WorkspaceWorkPhase,
        intensity: Int,
        intensityLimit: Int = 10,
        updatedAt: Date
    ) {
        self.id = id
        self.title = title
        self.frame = frame
        self.goalText = goalText
        self.stopSignal = stopSignal
        self.participants = participants
        self.minimumParticipants = minimumParticipants
        self.maximumParticipants = maximumParticipants
        self.allowsAddingParticipants = allowsAddingParticipants
        self.orientationConfirmed = orientationConfirmed
        self.frameConfirmed = frameConfirmed
        self.stages = stages
        self.currentStageID = currentStageID
        self.currentStageIndex = currentStageIndex
        self.availableClosureActions = availableClosureActions
        self.completedClosureActions = completedClosureActions
        self.activeChairID = activeChairID
        self.turns = turns
        self.guidance = guidance
        self.phase = phase
        self.intensity = intensity
        self.intensityLimit = max(1, intensityLimit)
        self.updatedAt = updatedAt
    }

    public var activeChair: WorkspaceChairIdentity? {
        participants.first(where: { $0.id == activeChairID }) ?? participants.first
    }

    /// Yoğunluk güvenli aralığın dışındayken yaşantısal çalışmaya dönülmez.
    /// Kural View'da değil burada durur: sandalye ve imgelem yolları aynı
    /// klinik sözleşmeye uymak zorundadır.
    public var intensityBlocksResume: Bool {
        WorkspaceSafety.intensityBlocksResume(
            intensity: intensity, limit: intensityLimit)
    }
}

/// Yaşantısal çalışmaların ortak klinik güvenlik eşiği.
///
/// Tek kaynaktır: hem sandalye hem imgelem aynı kuralı kullanır. Daha önce
/// bu eşik iki View'da ayrı ayrı yazılıydı ve imgelem yolu sunucunun
/// bildirdiği `intensityLimit` değerini hiç dikkate almıyordu.
public enum WorkspaceSafety {
    /// Bu değerin altındaki yoğunluklarda çalışmaya dönülebilir.
    public static let resumeCeiling = 8

    public static func intensityBlocksResume(
        intensity: Int,
        limit: Int
    ) -> Bool {
        intensity >= resumeCeiling || intensity > limit
    }
}

public enum WorkspaceChairClosureAction: String, CaseIterable, Identifiable, Hashable, Sendable {
    case ground
    case reflect
    case complete

    public var id: Self { self }

    public var title: String {
        switch self {
        case .ground: "Şimdiye dön"
        case .reflect: "Yansıt"
        case .complete: "Tamamla"
        }
    }

    public var instruction: String {
        switch self {
        case .ground:
            "Odayı, zemini ve şu anki yoğunluğunuzu yeniden fark edin."
        case .reflect:
            "İki veya daha fazla sandalyeden kalan en önemli şeyi kendi sözlerinizle yazın."
        case .complete:
            "Topraklanma ve yansıtma tamamlandıysa çalışma kaydını kapatın."
        }
    }

    public var systemImage: String {
        switch self {
        case .ground: "scope"
        case .reflect: "text.bubble"
        case .complete: "checkmark.seal"
        }
    }
}

public struct WorkspaceChairClosureRequest: Sendable {
    public let sessionID: String
    public let action: WorkspaceChairClosureAction
    public let checkpointConfirmed: Bool
    public let orientationConfirmed: Bool
    public let note: String
    public let currentIntensity: Int

    public init(
        sessionID: String,
        action: WorkspaceChairClosureAction,
        checkpointConfirmed: Bool,
        orientationConfirmed: Bool,
        note: String,
        currentIntensity: Int
    ) {
        self.sessionID = sessionID
        self.action = action
        self.checkpointConfirmed = checkpointConfirmed
        self.orientationConfirmed = orientationConfirmed
        self.note = note
        self.currentIntensity = currentIntensity
    }
}

/// A fresh, user-authored safety checkpoint for resuming paused chair work.
///
/// Adapters must forward these values as supplied. In particular, neither
/// confirmation may be inferred from an earlier checkpoint or replaced with a
/// literal `true`.
public struct WorkspaceChairResumeRequest: Sendable {
    public let sessionID: String
    public let orientationConfirmed: Bool
    public let groundingConfirmed: Bool
    public let currentIntensity: Int

    public init(
        sessionID: String,
        orientationConfirmed: Bool,
        groundingConfirmed: Bool,
        currentIntensity: Int
    ) {
        self.sessionID = sessionID
        self.orientationConfirmed = orientationConfirmed
        self.groundingConfirmed = groundingConfirmed
        self.currentIntensity = currentIntensity
    }
}

public struct WorkspaceChairStartRequest: Sendable {
    public let conversationID: Int?
    public let goalText: String
    public let stopSignal: String
    public let participantTitles: [String]
    public let startingParticipantIndex: Int
    public let intensity: Int
    public let orientationConfirmed: Bool
    public let frameConfirmed: Bool

    public init(
        conversationID: Int?,
        goalText: String,
        stopSignal: String,
        participantTitles: [String],
        startingParticipantIndex: Int,
        intensity: Int,
        orientationConfirmed: Bool,
        frameConfirmed: Bool
    ) {
        self.conversationID = conversationID
        self.goalText = goalText
        self.stopSignal = stopSignal
        self.participantTitles = participantTitles
        self.startingParticipantIndex = startingParticipantIndex
        self.intensity = intensity
        self.orientationConfirmed = orientationConfirmed
        self.frameConfirmed = frameConfirmed
    }
}

// MARK: - Imagery and limited reparenting

public struct WorkspaceProtocolStage: Identifiable, Hashable, Sendable {
    public let id: String
    public let label: String
    public let aim: String
    public let prompt: String

    public init(id: String, label: String, aim: String, prompt: String) {
        self.id = id
        self.label = label
        self.aim = aim
        self.prompt = prompt
    }
}

public struct WorkspaceImageryChoice: Identifiable, Hashable, Sendable {
    public let id: String
    public let title: String
    public let requiresExplicitConfirmation: Bool

    public init(id: String, title: String, requiresExplicitConfirmation: Bool = true) {
        self.id = id
        self.title = title
        self.requiresExplicitConfirmation = requiresExplicitConfirmation
    }
}

public struct WorkspaceImageryCheckpoint: Identifiable, Hashable, Sendable {
    public let id: String
    public let stageID: String
    public let title: String
    public let prompt: String
    public let safetyNote: String
    public let choices: [WorkspaceImageryChoice]
    public let isConfirmed: Bool

    public init(
        id: String,
        stageID: String,
        title: String,
        prompt: String,
        safetyNote: String,
        choices: [WorkspaceImageryChoice],
        isConfirmed: Bool = false
    ) {
        self.id = id
        self.stageID = stageID
        self.title = title
        self.prompt = prompt
        self.safetyNote = safetyNote
        self.choices = choices
        self.isConfirmed = isConfirmed
    }
}

public struct WorkspaceImageryEntry: Identifiable, Hashable, Sendable {
    public let id: String
    public let stageID: String
    public let stageLabel: String
    public let content: String
    public let createdAt: Date

    public init(
        id: String,
        stageID: String,
        stageLabel: String,
        content: String,
        createdAt: Date
    ) {
        self.id = id
        self.stageID = stageID
        self.stageLabel = stageLabel
        self.content = content
        self.createdAt = createdAt
    }
}

public struct WorkspaceImagerySession: Identifiable, Sendable {
    public let id: String
    public let phase: WorkspaceWorkPhase
    public let title: String
    public let frame: String
    public let stages: [WorkspaceProtocolStage]
    public let currentStageID: String
    public let currentStageIndex: Int
    public let checkpoint: WorkspaceImageryCheckpoint
    public let entries: [WorkspaceImageryEntry]
    public let sceneBoundary: String
    public let stopSignal: String
    public let orientationConfirmed: Bool
    public let frameConfirmed: Bool
    public let realityConfirmed: Bool
    public let intensity: Int
    public let intensityLimit: Int
    public let updatedAt: Date

    public init(
        id: String,
        phase: WorkspaceWorkPhase,
        title: String,
        frame: String,
        stages: [WorkspaceProtocolStage],
        currentStageID: String,
        currentStageIndex: Int,
        checkpoint: WorkspaceImageryCheckpoint,
        entries: [WorkspaceImageryEntry] = [],
        sceneBoundary: String,
        stopSignal: String,
        orientationConfirmed: Bool,
        frameConfirmed: Bool,
        realityConfirmed: Bool,
        intensity: Int,
        intensityLimit: Int = 10,
        updatedAt: Date
    ) {
        self.id = id
        self.phase = phase
        self.title = title
        self.frame = frame
        self.stages = stages
        self.currentStageID = currentStageID
        self.currentStageIndex = currentStageIndex
        self.checkpoint = checkpoint
        self.entries = entries
        self.sceneBoundary = sceneBoundary
        self.stopSignal = stopSignal
        self.orientationConfirmed = orientationConfirmed
        self.frameConfirmed = frameConfirmed
        self.realityConfirmed = realityConfirmed
        self.intensity = intensity
        self.intensityLimit = max(1, intensityLimit)
        self.updatedAt = updatedAt
    }

    /// Sandalye çalışmasıyla aynı klinik eşik. Bkz. `WorkspaceSafety`.
    public var intensityBlocksResume: Bool {
        WorkspaceSafety.intensityBlocksResume(
            intensity: intensity, limit: intensityLimit)
    }
}

public struct WorkspaceImageryStartRequest: Sendable {
    public let conversationID: Int?
    public let intention: String
    public let intensity: Int
    public let orientationConfirmed: Bool
    public let frameConfirmed: Bool
    public let realityConfirmed: Bool
    public let stopSignal: String
    public let sceneBoundary: String

    public init(
        conversationID: Int?,
        intention: String,
        intensity: Int,
        orientationConfirmed: Bool,
        frameConfirmed: Bool,
        realityConfirmed: Bool,
        stopSignal: String,
        sceneBoundary: String
    ) {
        self.conversationID = conversationID
        self.intention = intention
        self.intensity = intensity
        self.orientationConfirmed = orientationConfirmed
        self.frameConfirmed = frameConfirmed
        self.realityConfirmed = realityConfirmed
        self.stopSignal = stopSignal
        self.sceneBoundary = sceneBoundary
    }
}

public struct WorkspaceImageryCheckpointResponse: Sendable {
    public let sessionID: String
    public let checkpointID: String
    public let choiceID: String
    public let note: String
    public let currentIntensity: Int
    public let confirmed: Bool
    public let orientationConfirmed: Bool
    public let realityConfirmed: Bool

    public init(
        sessionID: String,
        checkpointID: String,
        choiceID: String,
        note: String,
        currentIntensity: Int,
        confirmed: Bool,
        orientationConfirmed: Bool,
        realityConfirmed: Bool
    ) {
        self.sessionID = sessionID
        self.checkpointID = checkpointID
        self.choiceID = choiceID
        self.note = note
        self.currentIntensity = currentIntensity
        self.confirmed = confirmed
        self.orientationConfirmed = orientationConfirmed
        self.realityConfirmed = realityConfirmed
    }
}

public struct WorkspaceImageryGroundRequest: Sendable {
    public let sessionID: String
    public let currentIntensity: Int
    public let roomOrientationConfirmed: Bool

    public init(
        sessionID: String,
        currentIntensity: Int,
        roomOrientationConfirmed: Bool
    ) {
        self.sessionID = sessionID
        self.currentIntensity = currentIntensity
        self.roomOrientationConfirmed = roomOrientationConfirmed
    }
}

public struct WorkspaceImageryResumeRequest: Sendable {
    public let sessionID: String
    public let currentIntensity: Int
    public let orientationConfirmed: Bool

    public init(
        sessionID: String,
        currentIntensity: Int,
        orientationConfirmed: Bool
    ) {
        self.sessionID = sessionID
        self.currentIntensity = currentIntensity
        self.orientationConfirmed = orientationConfirmed
    }
}

public struct WorkspaceImageryFinishRequest: Sendable {
    public let sessionID: String
    public let currentIntensity: Int
    public let groundingConfirmed: Bool
    public let orientationConfirmed: Bool
    public let realityConfirmed: Bool

    public init(
        sessionID: String,
        currentIntensity: Int,
        groundingConfirmed: Bool,
        orientationConfirmed: Bool,
        realityConfirmed: Bool
    ) {
        self.sessionID = sessionID
        self.currentIntensity = currentIntensity
        self.groundingConfirmed = groundingConfirmed
        self.orientationConfirmed = orientationConfirmed
        self.realityConfirmed = realityConfirmed
    }
}

// MARK: - Living map

public enum WorkspaceLivingMapDomain: String, CaseIterable, Identifiable, Sendable {
    case cycle
    case trigger
    case vulnerableChild
    case angryChild
    case criticalParent
    case coping
    case healthyAdult
    case value
    case need
    case strength
    case goal

    public var id: Self { self }

    public var title: String {
        switch self {
        case .cycle: "Tekrarlayan döngü"
        case .trigger: "Tetikleyici"
        case .vulnerableChild: "Kırılgan çocuk"
        case .angryChild: "Öfkeli çocuk"
        case .criticalParent: "Eleştirel ebeveyn"
        case .coping: "Başa çıkma modu"
        case .healthyAdult: "Sağlıklı yetişkin"
        case .value: "Değer ve yön"
        case .need: "İhtiyaç"
        case .strength: "Güç ve istisna"
        case .goal: "Hedef ve yararlı örüntü"
        }
    }

    public var systemImage: String {
        switch self {
        case .cycle: "arrow.triangle.2.circlepath"
        case .trigger: "bolt"
        case .vulnerableChild: "heart"
        case .angryChild: "flame"
        case .criticalParent: "exclamationmark.bubble"
        case .coping: "shield"
        case .healthyAdult: "figure.stand"
        case .value: "safari"
        case .need: "hand.raised"
        case .strength: "sparkles"
        case .goal: "scope"
        }
    }
}

public enum WorkspaceLivingMapReviewAction: String, CaseIterable, Identifiable, Sendable {
    case confirm
    case partial
    case context
    case rejectEvidence

    public var id: Self { self }

    public var title: String {
        switch self {
        case .confirm: "Bana uyuyor"
        case .partial: "Kısmen uyuyor"
        case .context: "Bağlama göre değişiyor"
        case .rejectEvidence: "Bu dayanak uygun değil"
        }
    }
}

public enum WorkspaceLivingMapConfidence: String, Sendable {
    case emerging
    case repeated
    case wellSupported

    public var title: String {
        switch self {
        case .emerging: "Yeni hipotez"
        case .repeated: "Tekrarlayan işaret"
        case .wellSupported: "Birden çok dayanak"
        }
    }
}

public struct WorkspaceLivingMapEvidence: Identifiable, Hashable, Sendable {
    public let id: String
    public let sourceTitle: String
    public let excerpt: String
    public let observedAt: Date
    public let conversationID: Int?
    public let reviewStatus: String?

    public init(
        id: String,
        sourceTitle: String,
        excerpt: String,
        observedAt: Date,
        conversationID: Int? = nil,
        reviewStatus: String? = nil
    ) {
        self.id = id
        self.sourceTitle = sourceTitle
        self.excerpt = excerpt
        self.observedAt = observedAt
        self.conversationID = conversationID
        self.reviewStatus = reviewStatus
    }
}

public struct WorkspaceLivingMapCard: Identifiable, Sendable {
    public let id: String
    public let domain: WorkspaceLivingMapDomain
    public let title: String
    public let hypothesis: String
    public let confidence: WorkspaceLivingMapConfidence
    public let evidence: [WorkspaceLivingMapEvidence]
    public let reviewPrompt: String?
    public let allowedReviewActions: [WorkspaceLivingMapReviewAction]
    public let reviewStatus: String?
    public let updatedAt: Date

    public init(
        id: String,
        domain: WorkspaceLivingMapDomain,
        title: String,
        hypothesis: String,
        confidence: WorkspaceLivingMapConfidence,
        evidence: [WorkspaceLivingMapEvidence],
        reviewPrompt: String? = nil,
        allowedReviewActions: [WorkspaceLivingMapReviewAction] = [.confirm, .partial, .context, .rejectEvidence],
        reviewStatus: String? = nil,
        updatedAt: Date
    ) {
        self.id = id
        self.domain = domain
        self.title = title
        self.hypothesis = hypothesis
        self.confidence = confidence
        self.evidence = evidence
        self.reviewPrompt = reviewPrompt
        self.allowedReviewActions = allowedReviewActions
        self.reviewStatus = reviewStatus
        self.updatedAt = updatedAt
    }
}

// MARK: - Local Wi-Fi sync

public enum WorkspaceWiFiSyncPhase: String, Sendable {
    case idle
    case preparing
    case waitingForScan
    case transferring
    case completed
    case failed
    case cancelled

    public var title: String {
        switch self {
        case .idle: "Hazır"
        case .preparing: "Güvenli bağlantı hazırlanıyor"
        case .waitingForScan: "QR kod taranmayı bekliyor"
        case .transferring: "Eşitleniyor"
        case .completed: "Eşitleme tamamlandı"
        case .failed: "Eşitleme tamamlanamadı"
        case .cancelled: "Eşitleme iptal edildi"
        }
    }

    public var isInProgress: Bool {
        [.preparing, .waitingForScan, .transferring].contains(self)
    }
}

public struct WorkspaceQRMatrix: Sendable {
    public let size: Int
    public let rows: [String]

    public init(size: Int, rows: [String]) {
        self.size = size
        self.rows = rows
    }
}

public struct WorkspaceSyncConflict: Identifiable, Hashable, Sendable {
    public let id: String
    public let title: String
    public let summary: String
    public let reason: String

    public init(id: String, title: String, summary: String, reason: String) {
        self.id = id
        self.title = title
        self.summary = summary
        self.reason = reason
    }
}

public enum WorkspaceSyncConflictResolution: String, CaseIterable, Identifiable, Sendable {
    case keepThisMac
    case keepOtherDevice

    public var id: Self { self }
    public var title: String {
        self == .keepThisMac ? "Bu Mac’teki kaydı tut" : "Diğer cihazdaki kaydı tut"
    }
}

public struct WorkspaceWiFiSyncStatus: Sendable {
    public let phase: WorkspaceWiFiSyncPhase
    public let message: String
    public let pairingCode: String?
    public let qrMatrix: WorkspaceQRMatrix?
    public let expiresAt: Date?
    public let localAddress: String?
    public let peerName: String?
    public let progress: Double?
    public let recordsTransferred: Int
    public let conflicts: [WorkspaceSyncConflict]
    public let secretsExcluded: Bool
    public let updatedAt: Date

    public init(
        phase: WorkspaceWiFiSyncPhase,
        message: String,
        pairingCode: String? = nil,
        qrMatrix: WorkspaceQRMatrix? = nil,
        expiresAt: Date? = nil,
        localAddress: String? = nil,
        peerName: String? = nil,
        progress: Double? = nil,
        recordsTransferred: Int = 0,
        conflicts: [WorkspaceSyncConflict] = [],
        secretsExcluded: Bool = true,
        updatedAt: Date = Date()
    ) {
        self.phase = phase
        self.message = message
        self.pairingCode = pairingCode
        self.qrMatrix = qrMatrix
        self.expiresAt = expiresAt
        self.localAddress = localAddress
        self.peerName = peerName
        self.progress = progress
        self.recordsTransferred = recordsTransferred
        self.conflicts = conflicts
        self.secretsExcluded = secretsExcluded
        self.updatedAt = updatedAt
    }

    public static var idle: Self {
        .init(
            phase: .idle,
            message: "Bu Mac aynı Wi-Fi ağındaki telefonla eşitlemeye hazır."
        )
    }
}

public struct AdvancedWorkspaceFailure: Identifiable, Equatable {
    public let id = UUID()
    public let title: String
    public let message: String
    public let retryAction: AdvancedRetryAction?

    public init(title: String, message: String, retryAction: AdvancedRetryAction? = nil) {
        self.title = title
        self.message = message
        self.retryAction = retryAction
    }

    public static func == (lhs: Self, rhs: Self) -> Bool {
        lhs.id == rhs.id
    }
}

public enum AdvancedRetryAction: Sendable {
    case loadWorkspace
    case loadLivingMap
    case refreshSync
}

public enum AdvancedWorkspaceValidationError: LocalizedError {
    case explicitConsentRequired
    case checkpointConfirmationRequired
    case emptyResponse
    case clinicalWorkUnavailable
    case clinicalSafetyHold
    case orientationConfirmationRequired
    case realityConfirmationRequired
    case groundingConfirmationRequired
    case resumeIntensityTooHigh
    case intensityExceedsSessionLimit
    case completionIntensityTooHigh
    case closureCheckpointRequired
    case closureSequenceIncomplete

    public var errorDescription: String? {
        switch self {
        case .explicitConsentRequired:
            "Başlamadan önce seçiminizi onaylayın. Çalışmayı istediğiniz anda durdurabilirsiniz."
        case .checkpointConfirmationRequired:
            "Devam etmeden önce bu adımı bilinçli olarak seçtiğinizi onaylayın."
        case .emptyResponse:
            "Devam etmek için kısa da olsa kendi sözlerinizi yazın."
        case .clinicalWorkUnavailable:
            "Bu görüşme bağlamında deneyimsel çalışma kullanılamıyor."
        case .clinicalSafetyHold:
            "Güvenlik bekletmesi varken yeni deneyimsel adım açılamaz. Duraklatma, şimdiye dönme ve durdurma seçenekleri kullanılabilir."
        case .orientationConfirmationRequired:
            "Devam etmeden önce şu anda bulunduğunuz odayı ve ekran başında olduğunuzu yeniden fark ettiğinizi onaylayın."
        case .realityConfirmationRequired:
            "Devam etmeden önce imge ve çağrışımların tarihsel kanıt olmadığını yeniden onaylayın."
        case .groundingConfirmationRequired:
            "Güvenli tamamlama için topraklanma adımını yaptığınızı açıkça onaylayın. Çalışmayı onaysız kapatmak yerine her zaman durdurabilirsiniz."
        case .resumeIntensityTooHigh:
            "Yoğunluk 8 veya üzerindeyken deneyimsel çalışmaya dönülmez. Yoğunluğu azaltın, şimdiye dönün veya çalışmayı durdurun."
        case .intensityExceedsSessionLimit:
            "Seçtiğiniz yoğunluk bu çalışma için belirlenen güvenlik sınırını aşıyor. Yoğunluğu azaltın veya çalışmayı kapatın."
        case .completionIntensityTooHigh:
            "Yoğunluk 8 veya üzerindeyken güvenli tamamlamaya geçilmez. Önce şimdiye dönün veya çalışmayı tamamlanmış saymadan durdurun."
        case .closureCheckpointRequired:
            "Bu kapanış adımını kendi seçiminizle yaptığınızı onaylayın."
        case .closureSequenceIncomplete:
            "Çalışmayı tamamlamadan önce şimdiye dönme ve yansıtma adımlarını ayrı ayrı bitirin."
        }
    }
}

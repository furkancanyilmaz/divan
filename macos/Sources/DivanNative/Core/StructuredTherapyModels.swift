import Foundation

// MARK: - ADHD rhythms and notebook

public struct ADHDWorkspaceSnapshot: Decodable, Equatable, Sendable {
    public let conversationID: Int
    public let defaultTargetPerWeek: Int
    public let weekStart: Double
    public let habits: [ADHDHabit]
    public let events: [ADHDEvent]
    public let journalEntries: [ADHDJournalEntry]
    public let weekCounts: [String: ADHDWeekCount]
    public let reviewDue: [Int]
    public let notices: ADHDWorkspaceNotices

    // JSONDecoder first applies `.convertFromSnakeCase`, producing
    // `conversationId`. Preserve the Swift acronym spelling explicitly.
    private enum CodingKeys: String, CodingKey {
        case conversationID = "conversationId"
        case defaultTargetPerWeek, weekStart, habits, events, journalEntries
        case weekCounts, reviewDue, notices
    }
}

public struct ADHDWeekCount: Decodable, Equatable, Sendable {
    public let done: Int
    public let partial: Int
    public let skipped: Int
    public let planned: Int
}

public struct ADHDWorkspaceNotices: Decodable, Equatable, Sendable {
    public let noStreak: String?
    public let noShame: String?
    public let notDiagnostic: String?
    public let monitoring: String?
    public let pauseAvailable: String?
}

public struct ADHDHabit: Decodable, Equatable, Identifiable, Sendable {
    public let id: Int
    public let sourceConv: Int?
    public let title: String
    public let cue: String?
    public let tinyAction: String?
    public let targetPerWeek: Int
    public let preferredDays: [Int]
    public let reminderLocalTime: String?
    public let timezone: String?
    public let status: String
    public let reviewAfter: Double?
    public let reviewDue: Bool
    public let lastReviewedAt: String?
    public let isGuest: Bool?
    public let created: String?
    public let updated: String?

    public var isActive: Bool { status == "active" }
    public var isPaused: Bool { status == "paused" }
}

public struct ADHDEvent: Decodable, Equatable, Identifiable, Sendable {
    public let id: Int
    public let habit: Int
    public let scheduledFor: Double
    public let status: String
    public let reminderId: Int?
    public let effortMinutes: Int?
    public let friction: String?
    public let note: String?
    public let startedAt: String?
    public let completedAt: String?
    public let created: String?
    public let updated: String?

    public var isOpen: Bool {
        ["scheduled", "started"].contains(status)
    }
}

public struct ADHDJournalEntry: Decodable, Equatable, Identifiable, Sendable {
    public let id: Int
    public let conv: Int
    public let habit: Int?
    public let event: Int?
    public let entryType: String
    public let content: String
    public let shareWithCoach: Bool
    public let sensitive: Bool
    public let isGuest: Bool?
    public let created: String?
    public let updated: String?
}

public struct ADHDReminderSummary: Decodable, Equatable, Identifiable, Sendable {
    public let id: Int
    public let task: String?
    public let dueAt: Double?
    public let status: String?
    public let sourceConv: Int?
}

public struct ADHDSafetyNotice: Decodable, Equatable, Sendable {
    public let detected: Bool
    public let kind: String?
    public let message: String
}

public struct ADHDHabitMutationResponse: Decodable, Equatable, Sendable {
    public let ok: Bool
    public let duplicate: Bool
    public let habit: ADHDHabit
    public let event: ADHDEvent?
    public let reminder: ADHDReminderSummary?
    public let notices: ADHDWorkspaceNotices?
}

public struct ADHDEventMutationResponse: Decodable, Equatable, Sendable {
    public let ok: Bool
    public let duplicate: Bool
    public let event: ADHDEvent
    public let notices: ADHDWorkspaceNotices?
}

public struct ADHDJournalMutationResponse: Decodable, Equatable, Sendable {
    public let ok: Bool
    public let duplicate: Bool
    public let journalEntry: ADHDJournalEntry?
    public let deleted: Int?
    public let monitoringNotice: String
    public let safety: ADHDSafetyNotice?
    public let activitiesPaused: Bool?
    public let pausedReminderIds: [Int]?
}

public enum ADHDHabitAction: String, Sendable {
    case create, update, pause, resume, archive, review, schedule
    case startNow = "start_now"
}

public struct ADHDHabitMutation: Sendable, Equatable {
    public let action: ADHDHabitAction
    public let conversationID: Int
    public let requestID: String?
    public let habitID: Int?
    public let title: String?
    public let cue: String?
    public let tinyAction: String?
    public let targetPerWeek: Int?
    public let preferredDays: [Int]?
    public let reminderLocalTime: String?
    public let timezone: String?
    public let decision: String?
    public let scheduledFor: Double?

    public init(
        action: ADHDHabitAction,
        conversationID: Int,
        requestID: String? = nil,
        habitID: Int? = nil,
        title: String? = nil,
        cue: String? = nil,
        tinyAction: String? = nil,
        targetPerWeek: Int? = nil,
        preferredDays: [Int]? = nil,
        reminderLocalTime: String? = nil,
        timezone: String? = nil,
        decision: String? = nil,
        scheduledFor: Double? = nil
    ) {
        self.action = action
        self.conversationID = conversationID
        self.requestID = requestID
        self.habitID = habitID
        self.title = title
        self.cue = cue
        self.tinyAction = tinyAction
        self.targetPerWeek = targetPerWeek
        self.preferredDays = preferredDays
        self.reminderLocalTime = reminderLocalTime
        self.timezone = timezone
        self.decision = decision
        self.scheduledFor = scheduledFor
    }
}

public enum ADHDEventAction: String, Sendable {
    case start, done, partial, skip, reschedule
}

public struct ADHDEventMutation: Sendable, Equatable {
    public let action: ADHDEventAction
    public let conversationID: Int
    public let eventID: Int
    public let requestID: String?
    public let effortMinutes: Int?
    public let friction: String?
    public let note: String?
    public let scheduledFor: Double?

    public init(
        action: ADHDEventAction,
        conversationID: Int,
        eventID: Int,
        requestID: String? = nil,
        effortMinutes: Int? = nil,
        friction: String? = nil,
        note: String? = nil,
        scheduledFor: Double? = nil
    ) {
        self.action = action
        self.conversationID = conversationID
        self.eventID = eventID
        self.requestID = requestID
        self.effortMinutes = effortMinutes
        self.friction = friction
        self.note = note
        self.scheduledFor = scheduledFor
    }
}

public enum ADHDJournalAction: String, Sendable {
    case create, update, delete
}

public enum ADHDJournalEntryType: String, CaseIterable, Identifiable, Sendable {
    case capture
    case dailyPage = "daily_page"
    case friction
    case weeklyReview = "weekly_review"
    case freewrite

    public var id: Self { self }

    public var title: String {
        switch self {
        case .capture: "Hızlı yakalama"
        case .dailyPage: "Günlük sayfa"
        case .friction: "Sürtünme notu"
        case .weeklyReview: "Haftalık değerlendirme"
        case .freewrite: "Serbest yazı"
        }
    }
}

public struct ADHDJournalMutation: Sendable, Equatable {
    public let action: ADHDJournalAction
    public let conversationID: Int
    public let requestID: String?
    public let entryID: Int?
    public let content: String?
    public let entryType: ADHDJournalEntryType?
    public let shareWithCoach: Bool?
    public let sensitive: Bool?
    public let habitID: Int?
    public let eventID: Int?

    public init(
        action: ADHDJournalAction,
        conversationID: Int,
        requestID: String? = nil,
        entryID: Int? = nil,
        content: String? = nil,
        entryType: ADHDJournalEntryType? = nil,
        shareWithCoach: Bool? = nil,
        sensitive: Bool? = nil,
        habitID: Int? = nil,
        eventID: Int? = nil
    ) {
        self.action = action
        self.conversationID = conversationID
        self.requestID = requestID
        self.entryID = entryID
        self.content = content
        self.entryType = entryType
        self.shareWithCoach = shareWithCoach
        self.sensitive = sensitive
        self.habitID = habitID
        self.eventID = eventID
    }
}

// MARK: - ADHD TUS study planner

/// Metadata-only, resumable TUS study plan owned by the ADHD workspace.
///
/// The catalog deliberately contains counts and stable identifiers only. Raw
/// question, answer, explanation and sentence text never crosses this wire.
public struct ADHDTUSPlannerSnapshot: Decodable, Equatable, Sendable {
    public let `protocol`: String
    public let conversationID: Int
    public let revision: Int
    public let enabled: Bool
    public let state: String
    public let history: [ADHDTUSAnswer]
    public let question: ADHDTUSQuestion?
    public let plan: ADHDTUSPlan?
    public let allowedActions: [String]
    public let catalog: ADHDTUSCatalogSummary
    public let catalogChanged: Bool?
    public let notices: ADHDTUSNotices
    public let safetyHold: Bool
    public let ok: Bool?
    public let duplicate: Bool?
    public let action: String?

    private enum CodingKeys: String, CodingKey {
        case `protocol`
        case conversationID = "convId"
        case revision, enabled, state, history, question, plan, allowedActions
        case catalog, catalogChanged, notices, safetyHold, ok, duplicate, action
    }

    public var contractIsSupported: Bool {
        guard `protocol` == "adhd_tus_planner_v1",
              conversationID > 0,
              (0..<Int.max).contains(revision),
              Self.states.contains(state),
              enabled == (state != "disabled"),
              Set(allowedActions).count == allowedActions.count,
              allowedActions.allSatisfy({ ADHDTUSAction(rawValue: $0) != nil }),
              catalog.contractIsSupported,
              history.count <= Self.questionIDs.count,
              Set(history.map(\.questionID)).count == history.count,
              history.allSatisfy({ $0.contractIsSupported }),
              action.map({ ADHDTUSAction(rawValue: $0) != nil }) ?? true else {
            return false
        }
        let mutationEnvelope = [ok != nil, duplicate != nil, action != nil]
        guard mutationEnvelope.allSatisfy({ $0 })
                || mutationEnvelope.allSatisfy({ !$0 }) else {
            return false
        }
        if action != nil, ok != true { return false }
        guard Set(allowedActions) == expectedAllowedActions else { return false }

        if let question {
            guard enabled,
                  state == "question",
                  plan == nil,
                  question.contractIsSupported else { return false }
        }
        if let plan {
            guard question == nil,
                  plan.contractIsSupported(for: state) else { return false }
        }

        switch state {
        case "disabled":
            // Turning the mode off pauses/hides the current plan without
            // deleting it, so a later opt-in resumes the server-owned state.
            return question == nil
        case "question":
            // A missing/changed packaged catalog intentionally produces no
            // question while keeping the user's prior selections visible.
            return plan == nil
        case "plan_ready", "active", "paused", "completed":
            return plan != nil
        default:
            return false
        }
    }

    static let questionIDs = Set([
        "activity", "lesson", "reading_area", "question_area",
        "available_time", "start_friction",
    ])
    private static let states = Set([
        "disabled", "question", "plan_ready", "active", "paused", "completed",
    ])

    private var expectedAllowedActions: Set<String> {
        if safetyHold {
            return ["plan_ready", "active", "paused"].contains(state)
                ? ["cancel", "set_mode"] : ["set_mode"]
        }
        var actions: Set<String> = [
            "disabled": ["set_mode"],
            "question": ["answer", "restart", "set_mode"],
            "plan_ready": ["start", "restart", "cancel", "set_mode"],
            "active": ["complete_step", "pause", "finish", "cancel", "set_mode"],
            "paused": ["resume", "finish", "cancel", "restart", "set_mode"],
            "completed": ["restart", "set_mode"],
        ][state] ?? []
        if !catalog.available {
            actions.remove("answer")
            actions.remove("restart")
        } else if catalogChanged == true {
            // A changed, otherwise healthy catalog is recovered by an
            // explicit restart. Only the stale question may not be answered.
            actions.remove("answer")
        }
        return actions
    }
}

public struct ADHDTUSAnswer: Decodable, Equatable, Identifiable, Sendable {
    public let questionID: String
    public let question: String
    public let answerID: String
    public let answer: String

    public var id: String { questionID }

    private enum CodingKeys: String, CodingKey {
        case questionID = "questionId"
        case question
        case answerID = "answerId"
        case answer
    }

    var contractIsSupported: Bool {
        guard ADHDTUSPlannerSnapshot.questionIDs.contains(questionID),
              ADHDTUSOption.isCatalogKey(answerID),
              !question.isEmpty, question.count <= 300,
              !answerID.isEmpty, answerID.count <= 128,
              !answer.isEmpty, answer.count <= 400 else {
            return false
        }
        switch questionID {
        case "activity":
            return ["read", "questions", "mixed", "choose"].contains(answerID)
        case "available_time":
            return ["5", "15", "25", "45", "custom"].contains(answerID)
        case "start_friction":
            return ["hard", "normal", "default"].contains(answerID)
        default:
            return true
        }
    }
}

public struct ADHDTUSQuestion: Decodable, Equatable, Identifiable, Sendable {
    public let id: String
    public let prompt: String
    public let options: [ADHDTUSOption]
    public let totalOptions: Int
    public let filterable: Bool
    public let hasMore: Bool

    var contractIsSupported: Bool {
        guard ADHDTUSPlannerSnapshot.questionIDs.contains(id),
              !prompt.isEmpty, prompt.count <= 300,
              (0...40).contains(options.count),
              totalOptions >= options.count,
              totalOptions <= 10_000_000,
              hasMore == (totalOptions > options.count),
              filterable == ["lesson", "reading_area", "question_area"].contains(id),
              Set(options.map(\.id)).count == options.count else {
            return false
        }
        guard options.allSatisfy(\.contractIsSupported) else { return false }
        let optionIDs = Set(options.map(\.id))
        switch id {
        case "activity":
            return optionIDs.contains("choose")
                && optionIDs.isSubset(of: ["read", "questions", "mixed", "choose"])
                && totalOptions == options.count
        case "available_time":
            return optionIDs == ["5", "15", "25", "45", "custom"]
                && totalOptions == options.count
        case "start_friction":
            return optionIDs == ["hard", "normal", "default"]
                && totalOptions == options.count
        default:
            return true
        }
    }
}

public struct ADHDTUSOption: Decodable, Equatable, Identifiable, Sendable {
    public let id: String
    public let label: String
    public let description: String?

    var contractIsSupported: Bool {
        Self.isCatalogKey(id)
            && !label.isEmpty && label.count <= 400
            && (description?.count ?? 0) <= 500
    }

    static func isCatalogKey(_ value: String) -> Bool {
        value.range(
            of: #"^[A-Za-z0-9][A-Za-z0-9._:\-]{0,127}$"#,
            options: .regularExpression
        ) != nil
    }
}

public struct ADHDTUSPlan: Decodable, Equatable, Identifiable, Sendable {
    public let id: String
    public let title: String
    public let summary: String
    public let status: String
    public let activity: String
    public let lesson: ADHDTUSCatalogChoice
    public let readingArea: ADHDTUSStudyArea?
    public let questionArea: ADHDTUSStudyArea?
    public let availableMinutes: Int
    public let startFriction: String
    public let progress: ADHDTUSProgress
    public let currentStep: ADHDTUSStep?
    public let steps: [ADHDTUSStep]

    func contractIsSupported(for state: String) -> Bool {
        let expectedStatuses: Set<String>
        if state == "disabled" {
            expectedStatuses = ["ready", "paused", "finished"]
        } else if let expected = [
            "plan_ready": "ready", "active": "active", "paused": "paused",
            "completed": "finished",
        ][state] {
            expectedStatuses = [expected]
        } else {
            return false
        }
        guard expectedStatuses.contains(status),
              Self.isPublicID(id),
              !title.isEmpty, title.count <= 500,
              !summary.isEmpty, summary.count <= 1_000,
              ["read", "questions", "mixed"].contains(activity),
              lesson.contractIsSupported,
              (5...180).contains(availableMinutes),
              ["hard", "normal"].contains(startFriction),
              (1...20).contains(steps.count),
              Set(steps.map(\.id)).count == steps.count,
              steps.allSatisfy(\.contractIsSupported),
              steps.reduce(0, { $0 + $1.durationMinutes }) == availableMinutes,
              progress.total == steps.count,
              progress.completed == steps.filter({ $0.status == "completed" }).count,
              progress.contractIsSupported,
              (activity == "read" ? readingArea != nil && questionArea == nil : true),
              (activity == "questions" ? readingArea == nil && questionArea != nil : true),
              (activity == "mixed" ? readingArea != nil && questionArea != nil : true),
              readingArea?.unit == nil || readingArea?.unit == "cümle",
              questionArea?.unit == nil || questionArea?.unit == "soru",
              readingArea?.contractIsSupported ?? true,
              questionArea?.contractIsSupported ?? true else {
            return false
        }

        let visible = steps.filter(\.visible)
        if let currentStep {
            guard currentStep.contractIsSupported,
                  visible.count == 1,
                  visible[0] == currentStep,
                  currentStep.collapsed == false else { return false }
            if status == "ready" && currentStep.status != "pending" { return false }
            if ["active", "paused"].contains(status)
                && currentStep.status != "active" { return false }
        } else if !visible.isEmpty || status != "finished" {
            return false
        }
        return true
    }

    static func isPublicID(_ value: String) -> Bool {
        value.range(of: #"^[0-9a-f]{32}$"#, options: .regularExpression) != nil
    }
}

public struct ADHDTUSCatalogChoice: Decodable, Equatable, Sendable {
    public let key: String
    public let name: String

    var contractIsSupported: Bool {
        ADHDTUSOption.isCatalogKey(key) && !name.isEmpty && name.count <= 180
    }
}

public struct ADHDTUSStudyArea: Decodable, Equatable, Sendable {
    public let key: String
    public let name: String
    public let source: String?
    public let availableCount: Int
    public let unit: String

    var contractIsSupported: Bool {
        ADHDTUSOption.isCatalogKey(key)
            && !name.isEmpty && name.count <= 180
            && (source?.count ?? 0) <= 180
            && (1...10_000_000).contains(availableCount)
            && ["cümle", "soru"].contains(unit)
    }
}

public struct ADHDTUSProgress: Decodable, Equatable, Sendable {
    public let completed: Int
    public let total: Int

    var contractIsSupported: Bool {
        completed >= 0 && total >= 1 && completed <= total
    }
}

public struct ADHDTUSStep: Decodable, Equatable, Identifiable, Sendable {
    public let id: String
    public let title: String
    public let detail: String?
    public let kind: String
    public let durationMinutes: Int
    public let quantity: Int?
    public let unit: String?
    public let status: String
    public let visible: Bool
    public let collapsed: Bool

    var contractIsSupported: Bool {
        ADHDTUSPlan.isPublicID(id)
            && !title.isEmpty && title.count <= 500
            && (detail?.count ?? 0) <= 2_000
            && ["setup", "reading", "recall", "questions", "review", "close"]
                .contains(kind)
            && (1...20).contains(durationMinutes)
            && (quantity.map({ (1...10_000_000).contains($0) }) ?? true)
            && (unit?.count ?? 0) <= 100
            && ["pending", "active", "completed"].contains(status)
            && collapsed == !visible
    }
}

public struct ADHDTUSCatalogSummary: Decodable, Equatable, Sendable {
    public let available: Bool
    public let errorCode: String?
    public let fingerprint: String?
    public let lessons: Int
    public let questionAreas: Int
    public let readingAreas: Int
    public let questionCount: Int?
    public let tusDefaultQuestionCount: Int?
    public let sentenceCount: Int?

    var contractIsSupported: Bool {
        guard lessons >= 0, questionAreas >= 0, readingAreas >= 0,
              (questionCount ?? 0) >= 0, (sentenceCount ?? 0) >= 0,
              (tusDefaultQuestionCount ?? 0) >= 0,
              (tusDefaultQuestionCount ?? 0) <= (questionCount ?? Int.max),
              (fingerprint?.count ?? 0) <= 96,
              (errorCode?.count ?? 0) <= 100 else { return false }
        if available {
            return fingerprint?.range(
                of: #"^sha256:[0-9a-f]{64}$"#, options: .regularExpression
            ) != nil && lessons > 0 && questionAreas + readingAreas > 0
        }
        return fingerprint == nil
    }
}

public struct ADHDTUSNotices: Decodable, Equatable, Sendable {
    public let noStreak: String?
    public let noDebt: String?
    public let localOnly: String?
    public let contentBoundary: String?
}

public enum ADHDTUSAction: String, CaseIterable, Sendable {
    case setMode = "set_mode"
    case answer, restart, start, pause, resume
    case completeStep = "complete_step"
    case finish, cancel
}

public struct ADHDTUSMutation: Sendable, Equatable {
    public let action: ADHDTUSAction
    public let conversationID: Int
    public let expectedRevision: Int
    public let requestID: String
    public let enabled: Bool?
    public let questionID: String?
    public let optionID: String?
    public let customMinutes: Int?
    public let planID: String?
    public let stepID: String?

    public init(
        action: ADHDTUSAction,
        conversationID: Int,
        expectedRevision: Int,
        requestID: String,
        enabled: Bool? = nil,
        questionID: String? = nil,
        optionID: String? = nil,
        customMinutes: Int? = nil,
        planID: String? = nil,
        stepID: String? = nil
    ) {
        self.action = action
        self.conversationID = conversationID
        self.expectedRevision = expectedRevision
        self.requestID = requestID
        self.enabled = enabled
        self.questionID = questionID
        self.optionID = optionID
        self.customMinutes = customMinutes
        self.planID = planID
        self.stepID = stepID
    }
}

// MARK: - User-owned Schema Therapy path

public struct SchemaPathSnapshot: Decodable, Equatable, Sendable {
    public let version: Int
    public let `protocol`: String?
    /// Authoritative presentation owned by the server. In chat-only v4 the
    /// client must not rebuild the clinical reducer as a form/workspace.
    public let presentation: String?
    public let stage: String?
    public let step: String?
    public let revision: Int?
    public let progress: SchemaPathProgress?
    public let nextCard: SchemaCardEnvelope?
    public let messageMeta: [SchemaMessageMetaEvent]?
    public let interactionPolicy: SchemaPathInteractionPolicy?
    public let resumeState: SchemaPathResumeState?
    public let clinicalSync: SchemaClinicalSyncState?
    public let activePath: SchemaPath?
    public let candidates: [SchemaCandidate]
    public let queuedCandidates: [SchemaCandidate]?
    public let queuedCount: Int?
    public let activePathNotice: String?
    public let methods: [SchemaPathMethod]
    public let notices: [String]
    public let allowedActions: [String]
    public let completedTurns: Int
    public let minimumListeningTurns: Int
    public let schemaMode: SchemaTherapyModeState?
    public let turnAnalysis: SchemaTurnAnalysisState?
    /// User-controlled focus and depth state added by Schema Path v3.
    /// These remain optional so an older embedded core fails soft while a
    /// rolling Mac/Android update is in progress.
    public let focus: SchemaFocusState?
    public let inlineSuggestions: [SchemaInlineSuggestion]?
    public let focusMinimumTurns: Int?
    public let origin: SchemaOriginState?
    public let growth: SchemaGrowthState?
    public let healthyAdult: SchemaHealthyAdultState?
    public let presentTransfer: SchemaPresentTransferState?

    public init(
        version: Int,
        `protocol`: String? = nil,
        presentation: String? = nil,
        stage: String? = nil,
        step: String? = nil,
        revision: Int? = nil,
        progress: SchemaPathProgress? = nil,
        nextCard: SchemaCardEnvelope? = nil,
        messageMeta: [SchemaMessageMetaEvent]? = nil,
        interactionPolicy: SchemaPathInteractionPolicy? = nil,
        resumeState: SchemaPathResumeState? = nil,
        clinicalSync: SchemaClinicalSyncState? = nil,
        activePath: SchemaPath?,
        candidates: [SchemaCandidate],
        queuedCandidates: [SchemaCandidate]? = nil,
        queuedCount: Int? = nil,
        activePathNotice: String? = nil,
        methods: [SchemaPathMethod],
        notices: [String],
        allowedActions: [String],
        completedTurns: Int,
        minimumListeningTurns: Int,
        schemaMode: SchemaTherapyModeState? = nil,
        turnAnalysis: SchemaTurnAnalysisState? = nil,
        focus: SchemaFocusState? = nil,
        inlineSuggestions: [SchemaInlineSuggestion]? = nil,
        focusMinimumTurns: Int? = nil,
        origin: SchemaOriginState? = nil,
        growth: SchemaGrowthState? = nil,
        healthyAdult: SchemaHealthyAdultState? = nil,
        presentTransfer: SchemaPresentTransferState? = nil
    ) {
        self.version = version
        self.`protocol` = `protocol`
        self.presentation = presentation
        self.stage = stage
        self.step = step
        self.revision = revision
        self.progress = progress
        self.nextCard = nextCard
        self.messageMeta = messageMeta
        self.interactionPolicy = interactionPolicy
        self.resumeState = resumeState
        self.clinicalSync = clinicalSync
        self.activePath = activePath
        self.candidates = candidates
        self.queuedCandidates = queuedCandidates
        self.queuedCount = queuedCount
        self.activePathNotice = activePathNotice
        self.methods = methods
        self.notices = notices
        self.allowedActions = allowedActions
        self.completedTurns = completedTurns
        self.minimumListeningTurns = minimumListeningTurns
        self.schemaMode = schemaMode
        self.turnAnalysis = turnAnalysis
        self.focus = focus
        self.inlineSuggestions = inlineSuggestions
        self.focusMinimumTurns = focusMinimumTurns
        self.origin = origin
        self.growth = growth
        self.healthyAdult = healthyAdult
        self.presentTransfer = presentTransfer
    }

    public func allows(_ action: SchemaPathAction) -> Bool {
        allowedActions.contains(action.rawValue)
    }
}

/// User-controlled boundary for Kerem Genç's future-turn analysis.
///
/// Enabling this mode never grants historical scope. Historical messages have
/// their own one-turn or bounded scan confirmations.
public struct SchemaTherapyModeState: Decodable, Equatable, Sendable {
    /// Effective consent on this device, not merely the synced preference.
    public let enabled: Bool
    /// Cross-device preference. It cannot authorize this device's provider.
    public let preferenceEnabled: Bool
    public let pendingDeviceConfirmation: Bool
    public let pendingProviderConfirmation: Bool
    public let canEnable: Bool
    public let reason: String?
    public let updated: String?

    private enum CodingKeys: String, CodingKey {
        case enabled, preferenceEnabled, pendingDeviceConfirmation
        case pendingProviderConfirmation, canEnable, reason, updated
    }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        enabled = try values.decode(Bool.self, forKey: .enabled)
        preferenceEnabled = try values.decodeIfPresent(
            Bool.self, forKey: .preferenceEnabled
        ) ?? enabled
        pendingDeviceConfirmation = try values.decodeIfPresent(
            Bool.self, forKey: .pendingDeviceConfirmation
        ) ?? false
        pendingProviderConfirmation = try values.decodeIfPresent(
            Bool.self, forKey: .pendingProviderConfirmation
        ) ?? false
        canEnable = try values.decode(Bool.self, forKey: .canEnable)
        reason = try values.decodeIfPresent(String.self, forKey: .reason)
        updated = try values.decodeIfPresent(String.self, forKey: .updated)
    }
}

public struct SchemaTurnAnalysisProvider: Decodable, Equatable, Sendable {
    public let id: String
    public let label: String
    public let model: String
    public let local: Bool
}

public struct SchemaTurnAnalysisJob: Decodable, Equatable, Identifiable, Sendable {
    public let id: Int
    public let status: String
    public let stage: String?
    public let progress: Int?
    public let errorCode: String?
    public let created: String?
    public let started: String?
    public let finished: String?
    public let updated: String?
}

/// Text-free progress for completed user–assistant turn analysis.
public struct SchemaTurnAnalysisState: Decodable, Equatable, Sendable {
    public let analysisUnit: String
    public let status: String
    public let processing: Bool
    public let eligibleTurns: Int
    public let analyzedTurns: Int
    public let remainingTurns: Int
    public let callsRemaining: Int?
    public let failedTurns: Int
    public let safetySkippedTurns: Int
    public let throughMessageId: Int
    public let targetMessageId: Int
    public let analyzedUserMessageIds: [Int]?
    public let processingUserMessageIds: [Int]?
    public let failedUserMessageIds: [Int]?
    public let errorCode: String?
    public let provider: SchemaTurnAnalysisProvider?
    public let job: SchemaTurnAnalysisJob?
}

// MARK: - Kerem Genç focus, origin and growth

/// A controlled, server-catalogued momentary mode hypothesis. It is not a
/// diagnosis or a stable personality label, and the model cannot invent its
/// public label or explanatory copy.
public struct SchemaFocusCandidate: Decodable, Equatable, Identifiable, Sendable {
    public let modeKey: String
    public let label: String
    public let chairLabel: String
    public let group: String
    public let copingStyle: String
    public let recognize: String
    public let question: String
    public let evidence: String

    public var id: String { modeKey }
}

/// Minimal input accepted by the server when an already-reviewed mode is
/// offered. Public labels still come from the server catalogue.
public struct SchemaFocusCandidateInput: Equatable, Sendable {
    public let modeKey: String
    public let evidence: String

    public init(modeKey: String, evidence: String) {
        self.modeKey = modeKey
        self.evidence = evidence
    }
}

public struct SchemaFocusOffer: Decodable, Equatable, Identifiable, Sendable {
    public let id: Int
    public let candidates: [SchemaFocusCandidate]
    public let created: String?
}

public struct SchemaFocusChoice: Decodable, Equatable, Sendable {
    public let modeKey: String
    public let label: String
    public let created: String?
}

public struct SchemaFocusState: Decodable, Equatable, Sendable {
    public let offer: SchemaFocusOffer?
    public let chosen: SchemaFocusChoice?
}

/// A suggestion emitted beside the exact assistant turn that prompted it.
/// It is deliberately a card, never a synthetic assistant message.
public struct SchemaInlineSuggestion: Decodable, Equatable, Identifiable, Sendable {
    public let suggestionId: Int
    public let assistantMessageId: Int
    public let modeKey: String
    public let label: String
    public let chairLabel: String
    public let group: String
    public let copingStyle: String
    public let recognize: String
    public let question: String
    public let evidence: String

    public var id: Int { suggestionId }
}

public struct SchemaOriginState: Decodable, Equatable, Sendable {
    public let recorded: Bool
    public let status: String?
    public let age: Int?
    public let ageRange: String
    public let scene: String
    public let unmetNeed: String
    public let confidence: String
    public let updated: String?
}

public struct SchemaGrowthStage: Decodable, Equatable, Identifiable, Sendable {
    public let id: Int
    public let seq: Int
    public let age: Int?
    public let label: String
    public let thenResponse: String
    public let nowResponse: String
    public let difference: String
    public let comparable: Bool
    public let status: String?
    public let environmentStatus: String?
    public let sourceUserMessagePublicId: String?
    public let sourceAssistantMessagePublicId: String?
    public let environmentSourceUserMessagePublicId: String?
    public let environmentSourceAssistantMessagePublicId: String?
}

public struct SchemaGrowthState: Decodable, Equatable, Sendable {
    public let stages: [SchemaGrowthStage]
    public let comparableCount: Int
    public let maxStages: Int
}

public struct SchemaHealthyAdultMark: Decodable, Equatable, Sendable {
    public let id: Int?
    public let publicId: String?
    public let evidence: String
    public let source: String?
    public let sourceUserMessageId: Int?
    public let sourceUserMessagePublicId: String?
    public let sourceAssistantMessageId: Int?
    public let sourceAssistantMessagePublicId: String?
    public let status: String?
    public let invalidatedAt: String?
    public let created: String?
}

public struct SchemaHealthyAdultState: Decodable, Equatable, Sendable {
    public let count: Int
    public let recent: [SchemaHealthyAdultMark]
}

/// Read-only projection of the user's completed present-day transfer. Source
/// pairs are kept so an imported local database can retain message lineage.
public struct SchemaPresentTransferState: Decodable, Equatable, Sendable {
    public let recorded: Bool
    public let status: String?
    public let id: Int?
    public let publicId: String?
    public let sourceUserMessageId: Int?
    public let sourceUserMessagePublicId: String?
    public let sourceAssistantMessageId: Int?
    public let sourceAssistantMessagePublicId: String?
    public let triggerSourceUserMessageId: Int?
    public let triggerSourceUserMessagePublicId: String?
    public let triggerSourceAssistantMessageId: Int?
    public let triggerSourceAssistantMessagePublicId: String?
    public let trigger: String?
    public let healthyAdultResponse: String?
    public let plannedAction: String?
    public let supportChoice: String?
    public let predictedResult: String?
    public let observedResult: String?
    public let created: String?
    public let updated: String?
}

// MARK: - Schema Path chat protocol v4

/// Progress is server-authored. Clients display it, but never calculate a
/// clinical stage from local form state.
public struct SchemaPathProgress: Codable, Equatable, Hashable, Sendable {
    public let stageNumber: Int
    public let stageTotal: Int
    public let stepNumber: Int
    public let stepTotal: Int
    public let label: String

    public init(
        stageNumber: Int,
        stageTotal: Int,
        stepNumber: Int,
        stepTotal: Int,
        label: String
    ) {
        self.stageNumber = stageNumber
        self.stageTotal = stageTotal
        self.stepNumber = stepNumber
        self.stepTotal = stepTotal
        self.label = label
    }
}

public struct SchemaCardSource: Codable, Equatable, Hashable, Sendable {
    public static let maximumCandidateQuoteCharacters = 700
    private static let candidateExcerptMarker =
        "\n… [kayıt bağlam için kısaltıldı] …\n"

    public let userMessageId: Int?
    public let userMessagePublicId: String?
    public let assistantMessageId: Int?
    public let assistantMessagePublicId: String?
    public let quote: String?

    public init(
        userMessageId: Int? = nil,
        userMessagePublicId: String? = nil,
        assistantMessageId: Int? = nil,
        assistantMessagePublicId: String? = nil,
        quote: String? = nil
    ) {
        self.userMessageId = userMessageId
        self.userMessagePublicId = userMessagePublicId
        self.assistantMessageId = assistantMessageId
        self.assistantMessagePublicId = assistantMessagePublicId
        self.quote = quote
    }

    /// The candidate context is copied only from the server-owned source
    /// excerpt. There is deliberately no assistant/message fallback: a
    /// missing, oversized or display-control-bearing quote makes the whole
    /// candidate surface unavailable instead of inventing clinical context.
    public var candidateQuoteForDisplay: String? {
        Self.normalizedCandidateDisplayText(
            quote,
            maximumCharacters: Self.maximumCandidateQuoteCharacters
        )
    }

    /// Returns the display quote only when it is the normalized form of the
    /// server's exact `clip_context_text(..., 700)` projection of the durable
    /// source message. Python slices Unicode code points, so this deliberately
    /// works over `unicodeScalars` rather than Swift grapheme clusters.
    public func candidateQuoteForDisplay(
        matchingUserMessageContent content: String
    ) -> String? {
        guard let displayQuote = candidateQuoteForDisplay,
              let expectedQuote = Self.normalizedCandidateDisplayText(
                  Self.serverCandidateExcerpt(content),
                  maximumCharacters: Self.maximumCandidateQuoteCharacters
              ),
              displayQuote == expectedQuote else { return nil }
        return displayQuote
    }

    private static func serverCandidateExcerpt(_ value: String) -> String {
        let scalars = Array(value.unicodeScalars)
        let limit = maximumCandidateQuoteCharacters
        guard scalars.count > limit else { return value }

        let marker = Array(candidateExcerptMarker.unicodeScalars)
        let available = limit - marker.count
        let headCount = max(80, Int(Double(available) * 0.68))
        let tailCount = max(40, available - headCount)
        var head = Array(scalars.prefix(headCount))
        while head.last.map(pythonIsWhitespace) == true { head.removeLast() }
        var tail = Array(scalars.suffix(tailCount))
        while tail.first.map(pythonIsWhitespace) == true { tail.removeFirst() }
        return String(String.UnicodeScalarView(head))
            + candidateExcerptMarker
            + String(String.UnicodeScalarView(tail))
    }

    /// Python `str.lstrip`/`rstrip` includes four C0 information separators in
    /// addition to Unicode White_Space. Keeping the set explicit prevents a
    /// platform Unicode-version difference from changing the wire projection.
    private static func pythonIsWhitespace(_ scalar: Unicode.Scalar) -> Bool {
        switch scalar.value {
        case 0x0009...0x000D, 0x001C...0x0020, 0x0085, 0x00A0, 0x1680,
             0x2000...0x200A, 0x2028...0x2029, 0x202F, 0x205F, 0x3000:
            return true
        default:
            return false
        }
    }

    fileprivate static func normalizedCandidateDisplayText(
        _ value: String?,
        maximumCharacters: Int
    ) -> String? {
        guard let value, value.count <= maximumCharacters else { return nil }
        let normalized = value
            .split(whereSeparator: \.isWhitespace)
            .joined(separator: " ")
        guard !normalized.isEmpty,
              normalized.count <= maximumCharacters,
              normalized.unicodeScalars.allSatisfy({ scalar in
                  let code = scalar.value
                  return !(code < 0x20 || (0x7F...0x9F).contains(code)
                      || (0x202A...0x202E).contains(code)
                      || (0x2066...0x2069).contains(code))
              }) else { return nil }
        return normalized
    }
}

public struct SchemaCardOption: Codable, Equatable, Hashable, Identifiable, Sendable {
    public let wireValue: JSONValue
    public let label: String
    public var value: String {
        switch wireValue {
        case .string(let value): value
        case .number(let value):
            value.rounded() == value
                && value >= Double(Int.min) && value <= Double(Int.max)
                ? String(Int(value)) : String(value)
        case .bool(let value): value ? "true" : "false"
        case .null: "null"
        case .object, .array: ""
        }
    }
    public var id: String {
        switch wireValue {
        case .string: "string:\(value)"
        case .number: "number:\(value)"
        case .bool: "boolean:\(value)"
        case .null: "null"
        case .object, .array: "unsupported"
        }
    }
    public var isSupportedByNativeCard: Bool {
        switch wireValue {
        case .string, .bool: true
        case .number(let value): value.isFinite
        case .object, .array, .null: false
        }
    }

    public init(value: String, label: String) {
        self.wireValue = .string(value)
        self.label = label
    }

    public init(wireValue: JSONValue, label: String) {
        self.wireValue = wireValue
        self.label = label
    }

    private enum CodingKeys: String, CodingKey { case value, label }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        self.wireValue = try values.decode(JSONValue.self, forKey: .value)
        self.label = try values.decode(String.self, forKey: .label)
    }

    public func encode(to encoder: Encoder) throws {
        var values = encoder.container(keyedBy: CodingKeys.self)
        try values.encode(wireValue, forKey: .value)
        try values.encode(label, forKey: .label)
    }
}

/// A field definition is intentionally data-driven so new presentation-only
/// field kinds fail soft. Unknown required kinds disable submission instead of
/// silently fabricating a value.
public struct SchemaCardField: Codable, Equatable, Hashable, Identifiable, Sendable {
    public let id: String
    public let type: String
    public let label: String
    public let required: Bool
    public let min: Int?
    public let max: Int?
    public let maxLength: Int?
    public let options: [SchemaCardOption]

    public init(
        id: String,
        type: String,
        label: String,
        required: Bool,
        min: Int? = nil,
        max: Int? = nil,
        maxLength: Int? = nil,
        options: [SchemaCardOption] = []
    ) {
        self.id = id
        self.type = type
        self.label = label
        self.required = required
        self.min = min
        self.max = max
        self.maxLength = maxLength
        self.options = options
    }

    public var isSupportedByNativeCard: Bool {
        let supportedType = [
            "text", "textarea", "integer", "number", "rating", "scale", "range",
            "select", "choice", "radio", "boolean", "checkbox",
        ].contains(type)
        guard supportedType else { return false }
        if ["rating", "scale", "range"].contains(type) {
            // Compact clinical scales are rendered as explicit choices with
            // no implicit midpoint. Refuse an unbounded or oversized server
            // descriptor instead of allocating an attacker-sized button grid.
            guard let min, let max, min <= max else {
                return false
            }
            let span = max.subtractingReportingOverflow(min)
            guard !span.overflow, span.partialValue <= 20 else { return false }
        }
        if ["integer", "number"].contains(type),
           let min, let max, min > max {
            return false
        }
        if ["select", "choice", "radio"].contains(type) {
            let identities = options.map(\.id)
            return !options.isEmpty
                && options.count <= 50
                && Set(identities).count == identities.count
                && options.allSatisfy(\.isSupportedByNativeCard)
        }
        return true
    }

    /// Safety/disclosure confirmations must be affirmatively true. Other
    /// booleans (for example `support_available`) require an explicit answer
    /// but preserve `false` as a valid user-authored value.
    public var requiresAffirmativeConfirmation: Bool {
        [
            "orientation_confirmed", "orientation_ok", "reality_clear",
            "sleep_activation_clear", "grounding_confirmed",
        ].contains(id)
    }
}

public struct SchemaCardActionEnvelope:
    Codable, Equatable, Hashable, Identifiable, Sendable {
    public let id: String
    public let action: String
    public let label: String
    public let style: String
    public let requiresConfirm: Bool
    public let payload: [String: JSONValue]

    public init(
        id: String,
        action: String,
        label: String,
        style: String,
        requiresConfirm: Bool,
        payload: [String: JSONValue] = [:]
    ) {
        self.id = id
        self.action = action
        self.label = label
        self.style = style
        self.requiresConfirm = requiresConfirm
        self.payload = payload
    }
}

/// Append-only cursor for the ordinary-chat Schema reducer. The public ID and
/// sequence are both required: path revision alone is not sufficient because
/// a clarification or revisit can append a newer prompt at the same revision.
public struct SchemaPathCheckpoint:
    Codable, Equatable, Hashable, Sendable {
    public let publicId: String
    public let seq: Int
    public let promptKey: String
    public let methodId: String?
    public let status: String
    public let canBacktrack: Bool
    public let backtrackPending: Bool
    public let pendingTargetPublicId: String?

    public init(
        publicId: String,
        seq: Int,
        promptKey: String,
        methodId: String? = nil,
        status: String,
        canBacktrack: Bool,
        backtrackPending: Bool,
        pendingTargetPublicId: String? = nil
    ) {
        self.publicId = publicId
        self.seq = seq
        self.promptKey = promptKey
        self.methodId = methodId
        self.status = status
        self.canBacktrack = canBacktrack
        self.backtrackPending = backtrackPending
        self.pendingTargetPublicId = pendingTargetPublicId
    }

    public var isSupportedByNativeContract: Bool {
        let statuses = Set([
            "active", "completed", "clarification", "paused",
            "backtracked", "invalidated",
        ])
        let methodIDs = Set([
            "young:method:imagery-rescripting",
            "young:method:chair-dialogue",
            "young:method:limited-reparenting",
        ])
        guard Self.isPublicID(publicId), seq >= 0,
              !promptKey.isEmpty, promptKey.count <= 120,
              statuses.contains(status),
              methodId.map(methodIDs.contains) ?? true else { return false }
        if seq == 0 && canBacktrack { return false }
        if backtrackPending {
            guard canBacktrack,
                  let pendingTargetPublicId,
                  Self.isPublicID(pendingTargetPublicId),
                  pendingTargetPublicId != publicId else { return false }
        } else if pendingTargetPublicId != nil {
            return false
        }
        return true
    }

    public static func isPublicID(_ value: String) -> Bool {
        value.count == 32 && value.unicodeScalars.allSatisfy {
            (48...57).contains(Int($0.value))
                || (97...102).contains(Int($0.value))
        }
    }

    public static let supportedMethodLabels = [
        "young:method:imagery-rescripting":
            "İmgeleme ile yeniden senaryolama",
        "young:method:chair-dialogue": "Sandalye diyaloğu",
        "young:method:limited-reparenting":
            "Sınırlı yeniden ebeveynleştirme",
    ]

    public static let supportedStepStages: [String: String] = {
        var values: [String: String] = [:]
        for step in [
            "listen", "candidate_review", "current_impact",
            "variable_check", "focus_confirm",
        ] { values[step] = "listen" }
        for step in [
            "method_select", "method_confirm", "origin_or_unknown",
            "imagery_precheck", "imagery_work", "mode_dialogue",
            "reparent_or_chair_precheck", "reparent_or_chair_work",
            "grounding_review",
        ] { values[step] = "depth" }
        for step in [
            "healthy_adult_voice", "age_ladder", "environment_rescript",
            "present_transfer", "optional_practice", "followup",
        ] { values[step] = "integrate" }
        values["complete"] = "complete"
        return values
    }()

    public static let supportedV5StepStages: [String: String] = [
        "listen": "listen",
        "candidate_review": "listen",
        "variable_explore": "explore",
        "origin_sequence": "origin",
        "imagery_work": "work",
        "mode_dialogue": "work",
        "reparent_or_chair_work": "work",
        "grounding_review": "work",
        "healthy_adult_voice": "integrate",
        "age_ladder": "integrate",
        "environment_rescript": "integrate",
        "present_transfer": "integrate",
        "optional_practice": "integrate",
        "followup": "integrate",
        "complete": "complete",
    ]
}

/// Delivery identity for the provider-authored question which owns a v5
/// checkpoint. State metadata never supplies visible prose: the referenced
/// completed assistant row is the only question rendered by the client.
public struct SchemaPromptDelivery:
    Codable, Equatable, Hashable, Sendable {
    public let requestId: String?
    public let status: String
    public let promptAssistantMessageId: Int?
    public let promptAssistantMessagePublicId: String?
    public let errorCode: String?

    public init(
        requestId: String?,
        status: String,
        promptAssistantMessageId: Int? = nil,
        promptAssistantMessagePublicId: String? = nil,
        errorCode: String? = nil
    ) {
        self.requestId = requestId
        self.status = status
        self.promptAssistantMessageId = promptAssistantMessageId
        self.promptAssistantMessagePublicId = promptAssistantMessagePublicId
        self.errorCode = errorCode
    }

    private enum CodingKeys: String, CodingKey {
        case requestId, status, promptAssistantMessageId
        case promptAssistantMessagePublicId, errorCode
    }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        status = try values.decode(String.self, forKey: .status)
        if status == "imported_waiting" {
            let explicitNulls: [CodingKeys] = [
                .requestId, .promptAssistantMessageId,
                .promptAssistantMessagePublicId, .errorCode,
            ]
            guard explicitNulls.allSatisfy({
                values.contains($0) && (try? values.decodeNil(forKey: $0)) == true
            }) else {
                throw DecodingError.dataCorruptedError(
                    forKey: .status,
                    in: values,
                    debugDescription:
                        "imported_waiting requires explicit null delivery identity"
                )
            }
            requestId = nil
            promptAssistantMessageId = nil
            promptAssistantMessagePublicId = nil
            errorCode = nil
        } else {
            requestId = try values.decodeIfPresent(
                String.self, forKey: .requestId
            )
            promptAssistantMessageId = try values.decodeIfPresent(
                Int.self, forKey: .promptAssistantMessageId
            )
            promptAssistantMessagePublicId = try values.decodeIfPresent(
                String.self, forKey: .promptAssistantMessagePublicId
            )
            errorCode = try values.decodeIfPresent(
                String.self, forKey: .errorCode
            )
        }
    }

    public func encode(to encoder: Encoder) throws {
        var values = encoder.container(keyedBy: CodingKeys.self)
        try values.encode(status, forKey: .status)
        if status == "imported_waiting" {
            try values.encodeNil(forKey: .requestId)
            try values.encodeNil(forKey: .promptAssistantMessageId)
            try values.encodeNil(forKey: .promptAssistantMessagePublicId)
            try values.encodeNil(forKey: .errorCode)
        } else {
            try values.encodeIfPresent(requestId, forKey: .requestId)
            try values.encodeIfPresent(
                promptAssistantMessageId, forKey: .promptAssistantMessageId
            )
            try values.encodeIfPresent(
                promptAssistantMessagePublicId,
                forKey: .promptAssistantMessagePublicId
            )
            try values.encodeIfPresent(errorCode, forKey: .errorCode)
        }
    }

    public var isSupportedByNativeContract: Bool {
        let nonterminal = Set([
            "accepted", "queued", "pending", "running", "retrying",
            "waiting_provider",
        ])
        switch status {
        case "completed":
            return requestId.map(Self.isRequestID) == true
                && promptAssistantMessageId.map { $0 > 0 } == true
                && promptAssistantMessagePublicId.map(
                    SchemaPathCheckpoint.isPublicID
                ) == true
                && errorCode == nil
        case "imported_waiting":
            // A sync receiver deliberately has no local provider request or
            // delivered assistant row. This state can authorize only typed
            // lifecycle controls through an exact import-control binding.
            return requestId == nil
                && promptAssistantMessageId == nil
                && promptAssistantMessagePublicId == nil
                && errorCode == nil
        case "missing":
            return requestId == nil
                && promptAssistantMessageId == nil
                && promptAssistantMessagePublicId == nil
                && errorCode == "schema_prompt_missing"
        case "failed", "interrupted", "cancelled":
            return requestId.map(Self.isRequestID) == true
                && promptAssistantMessageId == nil
                && promptAssistantMessagePublicId == nil
                && errorCode?.isEmpty == false
        default:
            return nonterminal.contains(status)
                && requestId.map(Self.isRequestID) == true
                && promptAssistantMessageId == nil
                && promptAssistantMessagePublicId == nil
                && errorCode == nil
        }
    }

    public static func isRequestID(_ value: String) -> Bool {
        (12...128).contains(value.count)
            && value.unicodeScalars.allSatisfy { scalar in
                (48...57).contains(Int(scalar.value))
                    || (65...90).contains(Int(scalar.value))
                    || (97...122).contains(Int(scalar.value))
                    || "._:-".unicodeScalars.contains(scalar)
            }
    }
}

/// Exact server-owned chat-state envelope. The initial candidate is the sole
/// visible choice row; later work carries hidden binding metadata only.
public struct SchemaCardEnvelope:
    Codable, Equatable, Hashable, Identifiable, Sendable {
    public let id: String
    public let kind: String
    public let presentation: String?
    public let status: String
    public let stage: String
    public let step: String
    public let pathId: Int?
    public let pathPublicId: String?
    public let revision: Int?
    public let title: String
    public let contextLine: String?
    public let body: String
    public let source: SchemaCardSource
    public let checkpoint: SchemaPathCheckpoint?
    public let promptDelivery: SchemaPromptDelivery?
    public let chatBinding: SchemaChatBinding?
    public let fields: [SchemaCardField]
    public let actions: [SchemaCardActionEnvelope]
    public let progress: SchemaPathProgress?

    public init(
        id: String,
        kind: String,
        presentation: String? = nil,
        status: String,
        stage: String,
        step: String,
        pathId: Int? = nil,
        pathPublicId: String? = nil,
        revision: Int?,
        title: String,
        contextLine: String? = nil,
        body: String,
        source: SchemaCardSource,
        checkpoint: SchemaPathCheckpoint? = nil,
        promptDelivery: SchemaPromptDelivery? = nil,
        chatBinding: SchemaChatBinding? = nil,
        fields: [SchemaCardField] = [],
        actions: [SchemaCardActionEnvelope] = [],
        progress: SchemaPathProgress? = nil
    ) {
        self.id = id
        self.kind = kind
        self.presentation = presentation
        self.status = status
        self.stage = stage
        self.step = step
        self.pathId = pathId
        self.pathPublicId = pathPublicId
        self.revision = revision
        self.title = title
        self.contextLine = contextLine
        self.body = body
        self.source = source
        self.checkpoint = checkpoint
        self.promptDelivery = promptDelivery
        self.chatBinding = chatBinding
        self.fields = fields
        self.actions = actions
        self.progress = progress
    }

    public var isActive: Bool {
        status == "active" || kind == "chat_state" && status == "paused"
    }

    /// `context_line` remains the server's clinical candidate label. Native
    /// UI removes only the frozen suffix and supplies the neutral product
    /// label; it never guesses a schema/mode from the conversation text.
    public var candidatePatternForDisplay: String? {
        guard kind == "candidate_prompt" else { return nil }
        let suffix = " tetiklenmiş olabilir."
        guard let line = SchemaCardSource.normalizedCandidateDisplayText(
                  contextLine,
                  maximumCharacters: 240
              ),
              line.hasSuffix(suffix) else { return nil }
        let label = String(line.dropLast(suffix.count))
        guard !label.isEmpty,
              label.count <= 180,
              label.unicodeScalars.contains(where: {
                  CharacterSet.alphanumerics.contains($0)
              }) else { return nil }
        return label
    }

    public var isSupportedByNativeContract: Bool {
        if presentation == "chat_only" {
            if kind == "chat_state" {
                guard fields.isEmpty, actions.isEmpty,
                      title.isEmpty, (contextLine ?? "").isEmpty,
                      body.isEmpty, progress == nil,
                      SchemaPathCheckpoint.supportedV5StepStages[step]
                        == stage,
                      let pathId, pathId > 0,
                      pathPublicId.map(
                        SchemaPathCheckpoint.isPublicID
                      ) == true,
                      let revision, revision >= 0,
                      let checkpoint,
                      checkpoint.isSupportedByNativeContract,
                      let promptDelivery,
                      promptDelivery.isSupportedByNativeContract,
                      ["active", "paused", "completed"].contains(status)
                else { return false }
                guard let chatBinding else {
                    return source.userMessageId == nil
                        && source.userMessagePublicId == nil
                        && source.assistantMessageId == nil
                        && source.assistantMessagePublicId == nil
                }
                guard chatBinding.protocol == "schema_path_chat_v5",
                      chatBinding.pathId == pathId,
                      chatBinding.pathPublicId == pathPublicId,
                      chatBinding.stepId == step,
                      chatBinding.expectedRevision == revision,
                      chatBinding.checkpointPublicId == checkpoint.publicId,
                      chatBinding.expectedCheckpointSeq == checkpoint.seq,
                      source.userMessageId
                        == chatBinding.sourceUserMessageId,
                      source.userMessagePublicId
                        == chatBinding.sourceUserMessagePublicId,
                      source.assistantMessageId
                        == chatBinding.sourceAssistantMessageId,
                      source.assistantMessagePublicId
                        == chatBinding.sourceAssistantMessagePublicId,
                      chatBinding.techniqueLinkId == nil,
                      chatBinding.techniqueLinkPublicId == nil,
                      chatBinding.expectedTechniqueRevision == nil,
                      chatBinding.sourceUserMessageId > 0,
                      SchemaPathCheckpoint.isPublicID(
                        chatBinding.sourceUserMessagePublicId),
                      chatBinding.sourceAssistantMessageId > 0,
                      SchemaPathCheckpoint.isPublicID(
                        chatBinding.sourceAssistantMessagePublicId)
                else { return false }
                if promptDelivery.status == "imported_waiting" {
                    return status == "paused"
                        && checkpoint.status == "paused"
                        && !checkpoint.canBacktrack
                        && !checkpoint.backtrackPending
                        && chatBinding.syncImportControl == true
                        && chatBinding.promptRequestId == nil
                        && chatBinding.promptAssistantMessageId == nil
                        && chatBinding.promptAssistantMessagePublicId == nil
                }
                guard promptDelivery.status == "completed",
                      ["active", "paused"].contains(status),
                      checkpoint.status == status,
                      chatBinding.syncImportControl == nil,
                      let requestID = promptDelivery.requestId,
                      chatBinding.promptRequestId == requestID,
                      let promptAssistantID =
                        promptDelivery.promptAssistantMessageId,
                      let promptAssistantPublicID =
                        promptDelivery.promptAssistantMessagePublicId,
                      chatBinding.promptAssistantMessageId
                        == promptAssistantID,
                      chatBinding.promptAssistantMessagePublicId
                        == promptAssistantPublicID,
                      source.assistantMessageId == promptAssistantID,
                      source.assistantMessagePublicId
                        == promptAssistantPublicID,
                      chatBinding.sourceAssistantMessageId
                        == promptAssistantID,
                      chatBinding.sourceAssistantMessagePublicId
                        == promptAssistantPublicID else { return false }
                return true
            }
            let supportedActions = Set([
                "accept_candidate_chat", "reject_candidate_chat", "pause",
                "resume_path", "ground_chat_technique", "stop",
            ])
            guard fields.isEmpty,
                  Set(actions.map(\.action)).isSubset(of: supportedActions),
                  SchemaPathCheckpoint.supportedStepStages[step] == stage
            else { return false }
            switch kind {
            case "candidate_prompt":
                let yes = actions.filter { $0.action == "accept_candidate_chat" }
                let no = actions.filter { $0.action == "reject_candidate_chat" }
                let payloadKeys = Set([
                    "claim_id", "candidate_public_id",
                    "source_user_message_id",
                    "source_user_message_public_id",
                    "source_assistant_message_id",
                    "source_assistant_message_public_id",
                ])
                guard let sourceUserID = source.userMessageId,
                      sourceUserID > 0,
                      let sourceUserPublicID = source.userMessagePublicId,
                      SchemaPathCheckpoint.isPublicID(sourceUserPublicID),
                      let sourceAssistantID = source.assistantMessageId,
                      sourceAssistantID > 0,
                      let sourceAssistantPublicID =
                        source.assistantMessagePublicId,
                      SchemaPathCheckpoint.isPublicID(
                        sourceAssistantPublicID
                      ),
                      source.candidateQuoteForDisplay != nil,
                      candidatePatternForDisplay != nil,
                      actions.allSatisfy({ descriptor in
                          guard Set(descriptor.payload.keys) == payloadKeys,
                                case .number(let rawClaim)? =
                                    descriptor.payload["claim_id"],
                                rawClaim.isFinite,
                                rawClaim.rounded() == rawClaim,
                                rawClaim > 0,
                                case .string(let candidatePublicID)? =
                                    descriptor.payload["candidate_public_id"],
                                SchemaPathCheckpoint.isPublicID(
                                    candidatePublicID
                                ),
                                case .number(let rawUserID)? = descriptor
                                    .payload["source_user_message_id"],
                                rawUserID.isFinite,
                                rawUserID.rounded() == rawUserID,
                                rawUserID > 0,
                                rawUserID <= Double(Int.max),
                                Int(rawUserID) == sourceUserID,
                                case .string(let payloadUserPublicID)? =
                                    descriptor.payload[
                                        "source_user_message_public_id"
                                    ],
                                payloadUserPublicID == sourceUserPublicID,
                                case .number(let rawAssistantID)? = descriptor
                                    .payload["source_assistant_message_id"],
                                rawAssistantID.isFinite,
                                rawAssistantID.rounded() == rawAssistantID,
                                rawAssistantID > 0,
                                rawAssistantID <= Double(Int.max),
                                Int(rawAssistantID) == sourceAssistantID,
                                case .string(let payloadAssistantPublicID)? =
                                    descriptor.payload[
                                        "source_assistant_message_public_id"
                                    ],
                                payloadAssistantPublicID
                                    == sourceAssistantPublicID else {
                              return false
                          }
                          return true
                      }),
                      yes.first?.payload == no.first?.payload else {
                    return false
                }
                return revision == nil && pathId == nil && pathPublicId == nil
                    && checkpoint == nil && promptDelivery == nil
                    && chatBinding == nil
                    && contextLine != nil
                    && step == "candidate_review" && title.isEmpty
                    && body == "Bunu çalışmak ister misin?"
                    && actions.map(\.action) == [
                        "accept_candidate_chat", "reject_candidate_chat",
                    ]
                    && yes.count == 1 && yes.first?.id == "candidate-yes"
                    && yes.first?.label == "Evet"
                    && yes.first?.style == "primary"
                    && yes.first?.requiresConfirm == false
                    && no.count == 1 && no.first?.id == "candidate-no"
                    && no.first?.label == "Hayır"
                    && no.first?.style == "secondary"
                    && no.first?.requiresConfirm == false
            case "chat_prompt":
                let groundingControls = actions.filter {
                    $0.action == "ground_chat_technique"
                }
                let ordinaryControls = actions.filter {
                    ["pause", "stop"].contains($0.action)
                }
                let groundingKeys = Set([
                    "step_id", "technique_link_id",
                    "technique_link_public_id",
                    "expected_technique_revision", "control_only",
                ])
                guard let checkpoint,
                      checkpoint.isSupportedByNativeContract,
                      checkpoint.status == "active",
                      promptDelivery == nil,
                      let chatBinding else { return false }
                let techniqueBindingValues: [Any?] = [
                    chatBinding.techniqueLinkId,
                    chatBinding.techniqueLinkPublicId,
                    chatBinding.expectedTechniqueRevision,
                ]
                let hasAnyTechniqueBinding = techniqueBindingValues.contains {
                    $0 != nil
                }
                let hasTechniqueBinding: Bool
                if let linkID = chatBinding.techniqueLinkId,
                   let linkPublicID = chatBinding.techniqueLinkPublicId,
                   let techniqueRevision =
                    chatBinding.expectedTechniqueRevision {
                    hasTechniqueBinding = linkID > 0
                        && SchemaPathCheckpoint.isPublicID(linkPublicID)
                        && techniqueRevision >= 0
                } else {
                    hasTechniqueBinding = false
                }
                guard !hasAnyTechniqueBinding || hasTechniqueBinding else {
                    return false
                }
                let actionNames = actions.map(\.action)
                let hasExpectedControlActions = actionNames == [
                    "pause", "stop",
                ] || hasTechniqueBinding && actionNames == [
                    "ground_chat_technique", "pause", "stop",
                ]
                guard hasExpectedControlActions,
                      actions.allSatisfy({ action in
                          switch action.action {
                          case "ground_chat_technique":
                              return action.id == "technique-ground"
                                  && action.label == "Şimdiye dön"
                                  && action.style == "secondary"
                                  && !action.requiresConfirm
                          case "pause":
                              return action.id == "schema-pause"
                                  && action.label == "Duraklat"
                                  && action.style == "secondary"
                                  && !action.requiresConfirm
                          case "stop":
                              return action.id == "schema-stop"
                                  && action.label == "Çalışmayı bitir"
                                  && action.style == "danger"
                                  && action.requiresConfirm
                          default:
                              return false
                          }
                      }) else { return false }
                if step == "method_select" {
                    guard checkpoint.methodId == nil else { return false }
                } else if step == "method_confirm" {
                    guard let methodID = checkpoint.methodId,
                          let methodLabel = SchemaPathCheckpoint
                            .supportedMethodLabels[methodID],
                          body == "Bu odağı bugün şu yöntemle çalışalım mı: \(methodLabel)? Evet ya da hayır diyebilirsin."
                    else { return false }
                }
                return pathId != nil && pathId! > 0
                    && pathPublicId.map(
                        SchemaPathCheckpoint.isPublicID
                    ) == true
                    && revision != nil && revision! >= 0
                    && !step.isEmpty
                    && chatBinding.pathId == pathId
                    && chatBinding.pathPublicId == pathPublicId
                    && chatBinding.expectedRevision == revision
                    && chatBinding.stepId == step
                    && chatBinding.checkpointPublicId == checkpoint.publicId
                    && chatBinding.expectedCheckpointSeq == checkpoint.seq
                    && SchemaPathCheckpoint.isPublicID(
                        chatBinding.sourceUserMessagePublicId
                    )
                    && SchemaPathCheckpoint.isPublicID(
                        chatBinding.sourceAssistantMessagePublicId
                    )
                    && groundingControls.allSatisfy {
                        guard Set($0.payload.keys) == groundingKeys,
                              $0.payload["control_only"] == .bool(true),
                              case .string(let step)? =
                                $0.payload["step_id"],
                              step == self.step,
                              case .number(let rawLink)? =
                                $0.payload["technique_link_id"],
                              rawLink.isFinite,
                              rawLink.rounded() == rawLink,
                              rawLink > 0,
                              rawLink <= Double(Int.max),
                              case .string(let publicLink)? =
                                $0.payload["technique_link_public_id"],
                              SchemaPathCheckpoint.isPublicID(publicLink),
                              case .number(let rawRevision)? = $0.payload[
                                "expected_technique_revision"
                              ], rawRevision.isFinite,
                              rawRevision.rounded() == rawRevision,
                              rawRevision >= 0,
                              rawRevision <= Double(Int.max) else {
                            return false
                        }
                        return chatBinding.techniqueLinkId == Int(rawLink)
                            && chatBinding.techniqueLinkPublicId == publicLink
                            && chatBinding.expectedTechniqueRevision
                                == Int(rawRevision)
                    }
                    && ordinaryControls.allSatisfy { $0.payload.isEmpty }
            case "resume", "blocked":
                let actionNames = actions.map(\.action)
                let checkpointStatus = checkpoint?.status
                let exactRecoveryDescriptors = actions.allSatisfy { action in
                    switch action.action {
                    case "resume_path":
                        return action.id == "schema-resume"
                            && action.label == "Sürdür"
                            && action.style == "primary"
                            && !action.requiresConfirm
                    case "pause":
                        return action.id == "schema-pause"
                            && action.label == "Duraklat"
                            && action.style == "secondary"
                            && !action.requiresConfirm
                    case "stop":
                        // The frozen fixture uses the long label; the frozen
                        // server also emits the compact equivalent for paused
                        // and sync-conflict recovery cards.
                        return action.id == "schema-stop"
                            && ["Çalışmayı bitir", "Bitir"].contains(
                                action.label
                            )
                            && action.style == "danger"
                            && action.requiresConfirm
                    default:
                        return false
                    }
                }
                let hasExpectedActions: Bool
                if kind == "resume" {
                    hasExpectedActions = checkpointStatus == "paused"
                        ? actionNames == ["resume_path", "stop"]
                        : checkpointStatus == "active"
                            && actionNames == ["pause", "stop"]
                } else {
                    hasExpectedActions = ["active", "paused"].contains(
                        checkpointStatus
                    ) && (actionNames == ["stop"]
                        || actionNames == ["pause", "stop"])
                }
                return checkpoint?.isSupportedByNativeContract == true
                    && promptDelivery == nil
                    && pathId != nil && pathId! > 0
                    && pathPublicId.map(
                        SchemaPathCheckpoint.isPublicID
                    ) == true
                    && revision != nil && revision! >= 0
                    && !step.isEmpty && chatBinding == nil
                    && hasExpectedActions
                    && exactRecoveryDescriptors
                    && actions.allSatisfy(\.payload.isEmpty)
            default:
                return false
            }
        }
        let kinds = Set([
            "listen_prompt", "candidate_review", "current_impact",
            "variable_check", "focus_confirm", "origin",
            "technique_precheck", "technique_turn", "mode_dialogue",
            "healthy_adult", "growth_stage", "environment_rescript",
            "present_transfer", "practice", "followup", "resume",
            "blocked", "complete",
        ])
        let stages = Set(["listen", "depth", "integrate", "complete"])
        let steps = Set([
            "listen", "candidate_review", "current_impact",
            "variable_check", "focus_confirm", "origin_or_unknown",
            "imagery_precheck", "imagery_work", "mode_dialogue",
            "reparent_or_chair_precheck", "reparent_or_chair_work",
            "grounding_review", "healthy_adult_voice", "age_ladder",
            "environment_rescript", "present_transfer", "optional_practice",
            "followup", "complete",
        ])
        let fieldIDs = fields.map(\.id)
        let actionIDs = actions.map(\.id)
        return kinds.contains(kind) && stages.contains(stage)
            && steps.contains(step)
            && revision != nil && revision! >= 0
            && fields.count <= 50 && actions.count <= 30
            && fieldIDs.allSatisfy { !$0.isEmpty }
            && actionIDs.allSatisfy { !$0.isEmpty }
            && Set(fieldIDs).count == fieldIDs.count
            && Set(actionIDs).count == actionIDs.count
    }
    public var hasUnsupportedRequiredField: Bool {
        fields.contains { $0.required && !$0.isSupportedByNativeCard }
    }
}

public enum SchemaPathComposerMode: String, Codable, Sendable {
    case bound
    case ordinary
    case disabled
}

public struct SchemaPathInteractionPolicy: Codable, Equatable, Hashable, Sendable {
    public let requiresInApp: Bool
    public let remoteReplyAllowed: Bool
    public let composerBindingRequired: Bool
    public let composerAllowed: Bool?
    public let composerMode: SchemaPathComposerMode?
    public let composerSurface: String?
    public let boundStepId: String?
    public let inlineControlsOnly: Bool?
    public let reason: String?

    public init(
        requiresInApp: Bool,
        remoteReplyAllowed: Bool,
        composerBindingRequired: Bool,
        composerAllowed: Bool? = nil,
        composerMode: SchemaPathComposerMode? = nil,
        composerSurface: String? = nil,
        boundStepId: String? = nil,
        inlineControlsOnly: Bool? = nil,
        reason: String? = nil
    ) {
        self.requiresInApp = requiresInApp
        self.remoteReplyAllowed = remoteReplyAllowed
        self.composerBindingRequired = composerBindingRequired
        self.composerAllowed = composerAllowed
        self.composerMode = composerMode
        self.composerSurface = composerSurface
        self.boundStepId = boundStepId
        self.inlineControlsOnly = inlineControlsOnly
        self.reason = reason
    }
}

public struct SchemaPathResumeState: Codable, Equatable, Hashable, Sendable {
    public let required: Bool
    public let reason: String?
    public let stage: String?
    public let step: String?
    public let cardId: String?

    public init(
        required: Bool,
        reason: String? = nil,
        stage: String? = nil,
        step: String? = nil,
        cardId: String? = nil
    ) {
        self.required = required
        self.reason = reason
        self.stage = stage
        self.step = step
        self.cardId = cardId
    }
}

/// Explicit, per-conversation sync consent for deep schema and Living Map
/// artifacts. It is independent from provider/model analysis consent.
public struct SchemaClinicalSyncState: Codable, Equatable, Hashable, Sendable {
    public let enabled: Bool
    /// Synced intent alone never authorizes this device to project clinical
    /// data. `enabled` remains the authoritative effective state.
    public let preferenceEnabled: Bool?
    public let initialized: Bool?
    public let pendingDeviceConfirmation: Bool?
    /// Clinical graph generation is independent from provider consent and is
    /// used to invalidate withdrawn sync payloads across devices.
    public let generation: Int?
    public let canEnable: Bool
    public let reason: String
    public let notice: String

    public init(
        enabled: Bool,
        preferenceEnabled: Bool? = nil,
        initialized: Bool? = nil,
        pendingDeviceConfirmation: Bool? = nil,
        generation: Int? = nil,
        canEnable: Bool,
        reason: String,
        notice: String
    ) {
        self.enabled = enabled
        self.preferenceEnabled = preferenceEnabled
        self.initialized = initialized
        self.pendingDeviceConfirmation = pendingDeviceConfirmation
        self.generation = generation
        self.canEnable = canEnable
        self.reason = reason
        self.notice = notice
    }

    public var needsDeviceConfirmation: Bool {
        enabled == false && (
            pendingDeviceConfirmation == true
                || (preferenceEnabled == true && initialized != true)
                || reason == "device_confirmation_required"
        )
    }
}

public struct SchemaClinicalSyncMutation: Equatable, Sendable {
    public let conversationID: Int
    public let requestID: String?
    public let enabled: Bool
    public let confirmed: Bool

    public init(
        conversationID: Int,
        requestID: String? = nil,
        enabled: Bool,
        confirmed: Bool
    ) {
        self.conversationID = conversationID
        self.requestID = requestID
        self.enabled = enabled
        self.confirmed = confirmed
    }
}

/// Durable metadata anchored to a real conversation message. The payload is
/// displayed as read-only details; mutations use only server-declared actions.
public struct SchemaMessageMetaEvent:
    Codable, Equatable, Hashable, Identifiable, Sendable {
    public let databaseId: Int
    public let publicId: String
    public let kind: String
    public let status: String
    public let messageId: Int
    public let sourceUserMessageId: Int?
    public let sourceAssistantMessageId: Int?
    /// Listening-stage Living Map updates intentionally exist before a
    /// Schema Path has been started. Their optimistic concurrency boundary
    /// is the clinical generation and exact source pair instead of a path.
    public let pathId: Int?
    public let pathPublicId: String?
    public let expectedRevision: Int?
    public let clinicalGeneration: Int?
    public let stage: String
    public let step: String
    public let title: String
    public let summary: String
    public let payload: [String: JSONValue]
    public let actions: [SchemaCardActionEnvelope]
    public let created: String?
    public let updated: String?

    public var id: String { publicId }

    private enum CodingKeys: String, CodingKey {
        case databaseId = "id"
        case publicId, kind, status, messageId, sourceUserMessageId
        case sourceAssistantMessageId, pathId, pathPublicId, stage, step
        case expectedRevision, clinicalGeneration
        case title, summary, payload, actions, created, updated
    }

    public init(
        databaseId: Int,
        publicId: String,
        kind: String,
        status: String,
        messageId: Int,
        sourceUserMessageId: Int? = nil,
        sourceAssistantMessageId: Int? = nil,
        pathId: Int? = nil,
        pathPublicId: String? = nil,
        expectedRevision: Int? = nil,
        clinicalGeneration: Int? = nil,
        stage: String,
        step: String,
        title: String,
        summary: String,
        payload: [String: JSONValue] = [:],
        actions: [SchemaCardActionEnvelope] = [],
        created: String? = nil,
        updated: String? = nil
    ) {
        self.databaseId = databaseId
        self.publicId = publicId
        self.kind = kind
        self.status = status
        self.messageId = messageId
        self.sourceUserMessageId = sourceUserMessageId
        self.sourceAssistantMessageId = sourceAssistantMessageId
        self.pathId = pathId
        self.pathPublicId = pathPublicId
        self.expectedRevision = expectedRevision
        self.clinicalGeneration = clinicalGeneration
        self.stage = stage
        self.step = step
        self.title = title
        self.summary = summary
        self.payload = payload
        self.actions = actions
        self.created = created
        self.updated = updated
    }
}

public struct SchemaTechniqueLink:
    Codable, Equatable, Hashable, Identifiable, Sendable {
    public let id: Int
    public let publicId: String
    public let step: String
    public let methodId: String
    public let techniqueRunId: Int
    public let techniqueRevision: Int
    public let status: String
    public let `protocol`: String
    public let currentStage: String
    public let requiresPrecheck: Bool

    public init(
        id: Int,
        publicId: String,
        step: String,
        methodId: String,
        techniqueRunId: Int,
        techniqueRevision: Int,
        status: String,
        `protocol`: String,
        currentStage: String,
        requiresPrecheck: Bool
    ) {
        self.id = id
        self.publicId = publicId
        self.step = step
        self.methodId = methodId
        self.techniqueRunId = techniqueRunId
        self.techniqueRevision = techniqueRevision
        self.status = status
        self.`protocol` = `protocol`
        self.currentStage = currentStage
        self.requiresPrecheck = requiresPrecheck
    }
}

/// Hidden binding attached to the ordinary chat composer while a chat-only
/// Schema Path is active. It carries identity and optimistic-concurrency data
/// only: the user's authored material remains the ordinary chat bubble.
public struct SchemaChatBinding: Codable, Equatable, Hashable, Sendable {
    public let `protocol`: String
    /// Present and true only at a receiver-created sync boundary. False is
    /// never a valid wire shape; absence denotes an ordinary delivered v5
    /// prompt binding.
    public let syncImportControl: Bool?
    public let pathId: Int
    public let pathPublicId: String
    public let stepId: String
    public let expectedRevision: Int
    public let checkpointPublicId: String
    public let expectedCheckpointSeq: Int
    public let promptRequestId: String?
    public let promptAssistantMessageId: Int?
    public let promptAssistantMessagePublicId: String?
    public let sourceUserMessageId: Int
    public let sourceUserMessagePublicId: String
    public let sourceAssistantMessageId: Int
    public let sourceAssistantMessagePublicId: String
    public let techniqueLinkId: Int?
    public let techniqueLinkPublicId: String?
    public let expectedTechniqueRevision: Int?

    public init(
        `protocol`: String = "schema_path_chat_v4",
        syncImportControl: Bool? = nil,
        pathId: Int,
        pathPublicId: String,
        stepId: String,
        expectedRevision: Int,
        checkpointPublicId: String,
        expectedCheckpointSeq: Int,
        promptRequestId: String? = nil,
        promptAssistantMessageId: Int? = nil,
        promptAssistantMessagePublicId: String? = nil,
        sourceUserMessageId: Int,
        sourceUserMessagePublicId: String,
        sourceAssistantMessageId: Int,
        sourceAssistantMessagePublicId: String,
        techniqueLinkId: Int? = nil,
        techniqueLinkPublicId: String? = nil,
        expectedTechniqueRevision: Int? = nil
    ) {
        self.`protocol` = `protocol`
        self.syncImportControl = syncImportControl
        self.pathId = pathId
        self.pathPublicId = pathPublicId
        self.stepId = stepId
        self.expectedRevision = expectedRevision
        self.checkpointPublicId = checkpointPublicId
        self.expectedCheckpointSeq = expectedCheckpointSeq
        self.promptRequestId = promptRequestId
        self.promptAssistantMessageId = promptAssistantMessageId
        self.promptAssistantMessagePublicId = promptAssistantMessagePublicId
        self.sourceUserMessageId = sourceUserMessageId
        self.sourceUserMessagePublicId = sourceUserMessagePublicId
        self.sourceAssistantMessageId = sourceAssistantMessageId
        self.sourceAssistantMessagePublicId = sourceAssistantMessagePublicId
        self.techniqueLinkId = techniqueLinkId
        self.techniqueLinkPublicId = techniqueLinkPublicId
        self.expectedTechniqueRevision = expectedTechniqueRevision
    }

    private enum CodingKeys: String, CodingKey {
        case `protocol`
        case syncImportControl
        case pathId
        case pathPublicId
        case stepId
        case expectedRevision
        case checkpointPublicId
        case expectedCheckpointSeq
        case promptRequestId
        case promptAssistantMessageId
        case promptAssistantMessagePublicId
        case sourceUserMessageId
        case sourceUserMessagePublicId
        case sourceAssistantMessageId
        case sourceAssistantMessagePublicId
        case techniqueLinkId
        case techniqueLinkPublicId
        case expectedTechniqueRevision
    }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        self.`protocol` = try values.decode(String.self, forKey: .protocol)
        self.syncImportControl = try values.decodeIfPresent(
            Bool.self, forKey: .syncImportControl
        )
        self.pathId = try values.decode(Int.self, forKey: .pathId)
        self.pathPublicId = try values.decode(String.self, forKey: .pathPublicId)
        self.stepId = try values.decode(String.self, forKey: .stepId)
        self.expectedRevision = try values.decode(
            Int.self, forKey: .expectedRevision
        )
        self.checkpointPublicId = try values.decode(
            String.self, forKey: .checkpointPublicId
        )
        self.expectedCheckpointSeq = try values.decode(
            Int.self, forKey: .expectedCheckpointSeq
        )
        if syncImportControl == true {
            let explicitNulls: [CodingKeys] = [
                .promptRequestId, .promptAssistantMessageId,
                .promptAssistantMessagePublicId,
            ]
            guard explicitNulls.allSatisfy({
                values.contains($0) && (try? values.decodeNil(forKey: $0)) == true
            }) else {
                throw DecodingError.dataCorruptedError(
                    forKey: .syncImportControl,
                    in: values,
                    debugDescription:
                        "sync import control requires explicit null prompt identity"
                )
            }
            self.promptRequestId = nil
            self.promptAssistantMessageId = nil
            self.promptAssistantMessagePublicId = nil
        } else {
            self.promptRequestId = try values.decodeIfPresent(
                String.self, forKey: .promptRequestId
            )
            self.promptAssistantMessageId = try values.decodeIfPresent(
                Int.self, forKey: .promptAssistantMessageId
            )
            self.promptAssistantMessagePublicId = try values.decodeIfPresent(
                String.self, forKey: .promptAssistantMessagePublicId
            )
        }
        self.sourceUserMessageId = try values.decode(
            Int.self, forKey: .sourceUserMessageId
        )
        self.sourceUserMessagePublicId = try values.decode(
            String.self, forKey: .sourceUserMessagePublicId
        )
        self.sourceAssistantMessageId = try values.decode(
            Int.self, forKey: .sourceAssistantMessageId
        )
        self.sourceAssistantMessagePublicId = try values.decode(
            String.self, forKey: .sourceAssistantMessagePublicId
        )
        self.techniqueLinkId = try values.decodeIfPresent(
            Int.self, forKey: .techniqueLinkId
        )
        self.techniqueLinkPublicId = try values.decodeIfPresent(
            String.self, forKey: .techniqueLinkPublicId
        )
        self.expectedTechniqueRevision = try values.decodeIfPresent(
            Int.self, forKey: .expectedTechniqueRevision
        )
    }

    public func encode(to encoder: Encoder) throws {
        var values = encoder.container(keyedBy: CodingKeys.self)
        try values.encode(`protocol`, forKey: .protocol)
        try values.encodeIfPresent(
            syncImportControl, forKey: .syncImportControl
        )
        try values.encode(pathId, forKey: .pathId)
        try values.encode(pathPublicId, forKey: .pathPublicId)
        try values.encode(stepId, forKey: .stepId)
        try values.encode(expectedRevision, forKey: .expectedRevision)
        try values.encode(checkpointPublicId, forKey: .checkpointPublicId)
        try values.encode(
            expectedCheckpointSeq, forKey: .expectedCheckpointSeq
        )
        if syncImportControl == true {
            try values.encodeNil(forKey: .promptRequestId)
            try values.encodeNil(forKey: .promptAssistantMessageId)
            try values.encodeNil(forKey: .promptAssistantMessagePublicId)
        } else {
            try values.encodeIfPresent(
                promptRequestId, forKey: .promptRequestId
            )
            try values.encodeIfPresent(
                promptAssistantMessageId, forKey: .promptAssistantMessageId
            )
            try values.encodeIfPresent(
                promptAssistantMessagePublicId,
                forKey: .promptAssistantMessagePublicId
            )
        }
        try values.encode(sourceUserMessageId, forKey: .sourceUserMessageId)
        try values.encode(
            sourceUserMessagePublicId, forKey: .sourceUserMessagePublicId
        )
        try values.encode(
            sourceAssistantMessageId, forKey: .sourceAssistantMessageId
        )
        try values.encode(
            sourceAssistantMessagePublicId,
            forKey: .sourceAssistantMessagePublicId
        )
        try values.encodeIfPresent(techniqueLinkId, forKey: .techniqueLinkId)
        try values.encodeIfPresent(
            techniqueLinkPublicId, forKey: .techniqueLinkPublicId
        )
        try values.encodeIfPresent(
            expectedTechniqueRevision,
            forKey: .expectedTechniqueRevision
        )
    }
}

/// Projection result emitted with the terminal chat event. A chat pair can be
/// durable while a concurrent safety/revision change correctly refuses to
/// attach it to the clinical path; clients must make that distinction visible.
public struct SchemaChatBindingResult: Codable, Equatable, Hashable, Sendable {
    public let applied: Bool
    public let progressed: Bool
    public let followupRequired: Bool
    public let missing: [String]
    public let errorCode: String?
    public let action: String?
    public let pathId: Int?
    public let pathRevision: Int?
    public let stage: String?
    public let step: String
    public let checkpointPublicId: String?
    public let checkpointSeq: Int?
    public let backtracked: Bool
    public let event: [String: JSONValue]?

    public init(
        applied: Bool,
        progressed: Bool = false,
        followupRequired: Bool = false,
        missing: [String] = [],
        errorCode: String? = nil,
        action: String? = nil,
        pathId: Int? = nil,
        pathRevision: Int? = nil,
        stage: String? = nil,
        step: String = "",
        checkpointPublicId: String? = nil,
        checkpointSeq: Int? = nil,
        backtracked: Bool = false,
        event: [String: JSONValue]? = nil
    ) {
        self.applied = applied
        self.progressed = progressed
        self.followupRequired = followupRequired
        self.missing = missing
        self.errorCode = errorCode
        self.action = action
        self.pathId = pathId
        self.pathRevision = pathRevision
        self.stage = stage
        self.step = step
        self.checkpointPublicId = checkpointPublicId
        self.checkpointSeq = checkpointSeq
        self.backtracked = backtracked
        self.event = event
    }

    private enum CodingKeys: String, CodingKey {
        case applied, progressed, followupRequired, missing, errorCode
        case action, pathId, pathRevision, revision, stage, step
        case checkpointPublicId, checkpointSeq, backtracked, event
    }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        applied = try values.decode(Bool.self, forKey: .applied)
        // Older durable chat rows predate these projections. Missing legacy
        // values never imply that a clinical step progressed.
        progressed = try values.decodeIfPresent(
            Bool.self, forKey: .progressed
        ) ?? false
        followupRequired = try values.decodeIfPresent(
            Bool.self, forKey: .followupRequired
        ) ?? false
        missing = try values.decodeIfPresent(
            [String].self, forKey: .missing
        ) ?? []
        errorCode = try values.decodeIfPresent(String.self, forKey: .errorCode)
        action = try values.decodeIfPresent(String.self, forKey: .action)
        pathId = try values.decodeIfPresent(Int.self, forKey: .pathId)
        pathRevision = try values.decodeIfPresent(
            Int.self, forKey: .pathRevision
        ) ?? values.decodeIfPresent(Int.self, forKey: .revision)
        stage = try values.decodeIfPresent(String.self, forKey: .stage)
        step = try values.decodeIfPresent(String.self, forKey: .step) ?? ""
        checkpointPublicId = try values.decodeIfPresent(
            String.self, forKey: .checkpointPublicId
        )
        checkpointSeq = try values.decodeIfPresent(
            Int.self, forKey: .checkpointSeq
        )
        backtracked = try values.decodeIfPresent(
            Bool.self, forKey: .backtracked
        ) ?? false
        event = try values.decodeIfPresent(
            [String: JSONValue].self, forKey: .event
        )
    }

    public func encode(to encoder: Encoder) throws {
        var values = encoder.container(keyedBy: CodingKeys.self)
        try values.encode(applied, forKey: .applied)
        try values.encode(progressed, forKey: .progressed)
        try values.encode(followupRequired, forKey: .followupRequired)
        try values.encode(missing, forKey: .missing)
        try values.encodeIfPresent(errorCode, forKey: .errorCode)
        try values.encodeIfPresent(action, forKey: .action)
        try values.encodeIfPresent(pathId, forKey: .pathId)
        try values.encodeIfPresent(pathRevision, forKey: .pathRevision)
        try values.encodeIfPresent(stage, forKey: .stage)
        try values.encode(step, forKey: .step)
        try values.encodeIfPresent(
            checkpointPublicId, forKey: .checkpointPublicId
        )
        try values.encodeIfPresent(checkpointSeq, forKey: .checkpointSeq)
        try values.encode(backtracked, forKey: .backtracked)
        try values.encodeIfPresent(event, forKey: .event)
    }

    /// Source compatibility for older call sites. The wire name is now the
    /// unambiguous `path_revision`.
    public var revision: Int? { pathRevision }

    public var failureMessage: String? {
        guard !applied else { return nil }
        return switch errorCode {
        case "schema_chat_followup_required":
            nil
        case "schema_chat_binding_stale", "schema_checkpoint_stale",
             "stale_schema_revision",
             "stale_technique_revision",
             "schema_step_mismatch", "schema_card_inactive":
            "Mesaj konuşmada kaldı; Şema adımı değiştiği için çalışmaya işlenmedi. Güncel kartı açın."
        case "schema_method_required", "schema_method_ambiguous",
             "schema_method_confirmation_required":
            "Mesaj konuşmada kaldı; yöntem seçimi netleşmedi. Kerem’in güncel kısa sorusundan devam edin."
        case "schema_backtrack_unavailable", "schema_backtrack_source_invalid":
            "Mesaj konuşmada kaldı; önceki adıma güvenle dönülemedi. Güncel yerden devam edin veya çalışmayı durdurun."
        case "schema_source_invalid":
            "Mesaj konuşmada kaldı; dayandığı konuşma çifti artık geçerli olmadığı için Şema çalışmasına işlenmedi."
        case "schema_safety_pause":
            "Mesaj konuşmada kaldı; güvenlik duraklatması nedeniyle derin çalışmaya işlenmedi."
        case "schema_provider_reconfirm":
            "Mesaj konuşmada kaldı; bu cihazdaki model onayı yenilenmeden Şema çalışmasına işlenmedi."
        case "schema_sync_conflict":
            "Mesaj konuşmada kaldı; cihazlar arası çakışma çözülmeden Şema çalışmasına işlenmedi."
        default:
            "Mesaj konuşmada kaldı ancak Şema çalışma adımına işlenmedi; güncel kartı gözden geçirin."
        }
    }
}

/// Whitelist for server-declared v4 actions. Unknown actions remain visible on
/// read-only cards, but are never posted by this client.
public enum SchemaChatCardAction: String, CaseIterable, Sendable {
    case acceptCandidateChat = "accept_candidate_chat"
    case rejectCandidateChat = "reject_candidate_chat"
    case reviewCandidate = "review_candidate"
    case rejectCandidate = "reject_candidate"
    case start
    case rateCurrentSituation = "rate_current_situation"
    case recordVariableCheck = "record_variable_check"
    case confirmFocus = "confirm_focus"
    case recordOrigin = "record_origin"
    case skipStep = "skip_step"
    case resumePath = "resume_path"
    case startChatTechnique = "start_chat_technique"
    case submitChatTechnique = "submit_chat_technique"
    case groundChatTechnique = "ground_chat_technique"
    case completeChatTechnique = "complete_chat_technique"
    case addGrowthStage = "add_growth_stage"
    case recordGrowth = "record_growth"
    case markHealthyAdult = "mark_healthy_adult"
    case recordEnvironmentRescript = "record_environment_rescript"
    case recordPresentTransfer = "record_present_transfer"
    case assignPractice = "assign_practice"
    case undoMapUpdate = "undo_map_update"
    case makeMapUpdatePrivate = "make_map_update_private"
    case editMapUpdate = "edit_map_update"
    case pause
    case stop
    case close

}

/// One immutable card intent. Keeping the request/client event IDs inside this
/// value makes an explicit retry idempotent.
public struct SchemaCardMutation: Equatable, Sendable {
    public let action: SchemaChatCardAction
    public let conversationID: Int
    public let requestID: String
    /// Pathless Stage 1 map actions omit both values. All other v4 actions,
    /// including map actions created after a path starts, pin both.
    public let pathID: Int?
    /// Stable cross-device identity paired with `pathID`. Chat-only direct
    /// controls always echo this value from the authoritative card/path.
    public let pathPublicID: String?
    public let expectedRevision: Int?
    public let sourceUserMessageID: Int?
    public let sourceUserMessagePublicID: String?
    public let sourceAssistantMessageID: Int?
    public let sourceAssistantMessagePublicID: String?
    public let stepID: String?
    public let clientEventID: String?
    public let expectedTechniqueRevision: Int?
    public let values: [String: JSONValue]

    public init(
        action: SchemaChatCardAction,
        conversationID: Int,
        requestID: String,
        pathID: Int?,
        pathPublicID: String? = nil,
        expectedRevision: Int?,
        sourceUserMessageID: Int? = nil,
        sourceUserMessagePublicID: String? = nil,
        sourceAssistantMessageID: Int? = nil,
        sourceAssistantMessagePublicID: String? = nil,
        stepID: String? = nil,
        clientEventID: String? = nil,
        expectedTechniqueRevision: Int? = nil,
        values: [String: JSONValue] = [:]
    ) {
        self.action = action
        self.conversationID = conversationID
        self.requestID = requestID
        self.pathID = pathID
        self.pathPublicID = pathPublicID
        self.expectedRevision = expectedRevision
        self.sourceUserMessageID = sourceUserMessageID
        self.sourceUserMessagePublicID = sourceUserMessagePublicID
        self.sourceAssistantMessageID = sourceAssistantMessageID
        self.sourceAssistantMessagePublicID = sourceAssistantMessagePublicID
        self.stepID = stepID
        self.clientEventID = clientEventID
        self.expectedTechniqueRevision = expectedTechniqueRevision
        self.values = values
    }
}

public struct SchemaEvidenceSummary: Decodable, Equatable, Sendable {
    public let accepted: Int
    public let pending: Int
    public let reviewable: Int
}

public struct SchemaEvidenceSource: Decodable, Equatable, Identifiable, Sendable {
    public let evidenceId: Int?
    public let messageId: Int
    public let relation: String?
    public let reviewStatus: String?
    public let excerpt: String
    public let sourceCreated: String?
    public let created: String?

    public var id: String { "\(evidenceId ?? 0)-\(messageId)-\(relation ?? "source")" }
}

public struct SchemaCandidate: Decodable, Equatable, Identifiable, Sendable {
    public let id: Int
    public let publicId: String?
    public let claimType: String?
    public let title: String
    public let statement: String
    public let trigger: String?
    public let experience: String?
    public let response: String?
    public let shortTermEffect: String?
    public let longTermEffect: String?
    public let need: String?
    public let counterexample: String?
    public let context: String?
    public let status: String
    public let scope: String?
    public let sensitive: Bool
    public let sources: [SchemaEvidenceSource]
    public let directUserEvidence: [SchemaEvidenceSource]
    public let counterexamples: [SchemaEvidenceSource]
    public let evidenceSummary: SchemaEvidenceSummary
    public let approvedForPath: Bool
    public let schema: SchemaCandidateLabel?
    public let mode: SchemaCandidateLabel?
    public let sourceTurn: SchemaCandidateSourceTurn?
    public let decisionState: String?
    public let availableDecisions: [String]?
    public let deferredForNextSession: Bool?
    public let created: String?
    public let updated: String?
}

public struct SchemaCandidateLabel: Decodable, Equatable, Sendable {
    public let id: String
    public let label: String
}

public struct SchemaCandidateSourceTurn: Decodable, Equatable, Sendable {
    public let userMessageId: Int
    public let assistantMessageId: Int?
    public let userExcerpt: String
    public let assistantExcerpt: String
}

public struct SchemaPathMethod: Decodable, Equatable, Identifiable, Sendable {
    public let methodId: String
    public let nodeId: String
    public let name: String
    public let description: String?
    public let interactionMode: String?
    public let riskLevel: String?
    public let requiresConsent: Bool?
    public let requiresPrecheck: Bool
    public let processTags: [String]

    public var id: String { methodId }
}

public struct SchemaSelectedMethod: Decodable, Equatable, Sendable {
    public let methodId: String
    public let nodeId: String?
    public let name: String
    public let requiresPrecheck: Bool
}

public struct SchemaPractice: Codable, Equatable, Sendable {
    public let variable: String
    public let constant: String
    public let prediction: String
    public let action: String
    public let observableResult: String
    public let tinyVersion: String
    public let targetPerWeek: Int

    public init(
        variable: String,
        constant: String,
        prediction: String,
        action: String,
        observableResult: String,
        tinyVersion: String,
        targetPerWeek: Int
    ) {
        self.variable = variable
        self.constant = constant
        self.prediction = prediction
        self.action = action
        self.observableResult = observableResult
        self.tinyVersion = tinyVersion
        self.targetPerWeek = targetPerWeek
    }
}

public struct SchemaPath: Decodable, Equatable, Identifiable, Sendable {
    public let id: Int
    public let publicId: String?
    public let convId: Int
    public let therapist: String
    public let claimId: Int
    public let candidate: SchemaCandidate?
    public let phase: String
    public let status: String
    public let methodId: String?
    public let method: SchemaSelectedMethod?
    public let techniqueRunId: Int?
    public let techniqueLinks: [SchemaTechniqueLink]?
    public let activeTechniqueLink: SchemaTechniqueLink?
    public let practice: SchemaPractice?
    public let practiceStatus: String?
    public let records: [String: [String]]
    public let revision: Int
    public let created: String?
    public let updated: String?
    public let closedAt: String?
    public let flowVersion: Int?
    public let clinicalGeneration: Int?
    public let stage: String?
    public let step: String?
    public let pauseReason: String?
    public let resumeRequired: Bool?

    public init(
        id: Int,
        convId: Int,
        therapist: String,
        claimId: Int,
        candidate: SchemaCandidate? = nil,
        phase: String,
        status: String,
        methodId: String? = nil,
        method: SchemaSelectedMethod? = nil,
        techniqueRunId: Int? = nil,
        techniqueLinks: [SchemaTechniqueLink]? = nil,
        activeTechniqueLink: SchemaTechniqueLink? = nil,
        practice: SchemaPractice? = nil,
        practiceStatus: String? = nil,
        records: [String: [String]] = [:],
        revision: Int,
        created: String? = nil,
        updated: String? = nil,
        closedAt: String? = nil,
        publicId: String? = nil,
        flowVersion: Int? = nil,
        clinicalGeneration: Int? = nil,
        stage: String? = nil,
        step: String? = nil,
        pauseReason: String? = nil,
        resumeRequired: Bool? = nil
    ) {
        self.id = id
        self.publicId = publicId
        self.convId = convId
        self.therapist = therapist
        self.claimId = claimId
        self.candidate = candidate
        self.phase = phase
        self.status = status
        self.methodId = methodId
        self.method = method
        self.techniqueRunId = techniqueRunId
        self.techniqueLinks = techniqueLinks
        self.activeTechniqueLink = activeTechniqueLink
        self.practice = practice
        self.practiceStatus = practiceStatus
        self.records = records
        self.revision = revision
        self.created = created
        self.updated = updated
        self.closedAt = closedAt
        self.flowVersion = flowVersion
        self.clinicalGeneration = clinicalGeneration
        self.stage = stage
        self.step = step
        self.pauseReason = pauseReason
        self.resumeRequired = resumeRequired
    }

    public func latestRecord(_ kind: String) -> String {
        records[kind]?.last ?? ""
    }
}

public struct SchemaPathPrecheck: Sendable, Equatable {
    public let orientationConfirmed: Bool
    public let realityClear: Bool
    public let sleepActivationClear: Bool
    public let intensity: Int
    public let supportAvailable: Bool
    public let stopSignal: String

    public init(
        orientationConfirmed: Bool,
        realityClear: Bool,
        sleepActivationClear: Bool,
        intensity: Int,
        supportAvailable: Bool,
        stopSignal: String
    ) {
        self.orientationConfirmed = orientationConfirmed
        self.realityClear = realityClear
        self.sleepActivationClear = sleepActivationClear
        self.intensity = intensity
        self.supportAvailable = supportAvailable
        self.stopSignal = stopSignal
    }
}

public enum SchemaPathAction: String, Sendable {
    case reviewCandidate = "review_candidate"
    case start, record, advance
    case offerFocus = "offer_focus"
    case chooseFocus = "choose_focus"
    case declineFocus = "decline_focus"
    case dismissSuggestion = "dismiss_suggestion"
    case acceptSuggestion = "accept_suggestion"
    case recordOrigin = "record_origin"
    case addGrowthStage = "add_growth_stage"
    case recordGrowth = "record_growth"
    case markHealthyAdult = "mark_healthy_adult"
    case chooseMethod = "choose_method"
    case assignPractice = "assign_practice"
    case linkTechnique = "link_technique"
    case pause, resume, stop, close
}

public enum SchemaCandidateDecision: String, CaseIterable, Identifiable, Sendable {
    case accept, `defer`, dismiss
    case confirm, partial, contextual, unsure, reject, `private`
    public var id: Self { self }

    public var title: String {
        switch self {
        case .accept: "Bana uyuyor"
        case .defer: "Sonraki görüşmeye bırak"
        case .dismiss: "Şimdilik değil"
        case .confirm: "Bana uyuyor"
        case .partial: "Kısmen"
        case .contextual: "Yalnız bu durumda"
        case .unsure: "Emin değilim"
        case .reject: "Uymuyor"
        case .private: "Özel tut"
        }
    }
}

public enum SchemaTurnAnalysisAction: String, Sendable {
    case setMode = "set_mode"
    case analyzeTurn = "analyze_turn"
    case scanHistory = "scan_history"
    case retryScan = "retry_scan"
}

/// Explicit mutation boundary for future analysis, one historical turn, or a
/// bounded historical scan. Missing consent values are never inferred.
public struct SchemaTurnAnalysisMutation: Sendable, Equatable {
    public let action: SchemaTurnAnalysisAction
    public let conversationID: Int
    public let requestID: String?
    public let enabled: Bool?
    public let userMessageID: Int?
    public let consent: Bool?
    public let providerID: String?
    public let modelID: String?
    public let jobID: Int?

    public init(
        action: SchemaTurnAnalysisAction,
        conversationID: Int,
        requestID: String? = nil,
        enabled: Bool? = nil,
        userMessageID: Int? = nil,
        consent: Bool? = nil,
        providerID: String? = nil,
        modelID: String? = nil,
        jobID: Int? = nil
    ) {
        self.action = action
        self.conversationID = conversationID
        self.requestID = requestID
        self.enabled = enabled
        self.userMessageID = userMessageID
        self.consent = consent
        self.providerID = providerID
        self.modelID = modelID
        self.jobID = jobID
    }
}

public struct SchemaTurnAnalysisMutationResponse: Decodable, Equatable, Sendable {
    public let ok: Bool
    public let processing: Bool?
    public let queued: Bool?
    public let alreadyAnalyzed: Bool?
    public let jobId: Int?
    public let userMessageId: Int?
    public let message: String?
    public let turnAnalysis: SchemaTurnAnalysisState?
    public let schemaMode: SchemaTherapyModeState?
}

public struct SchemaPathMutation: Sendable, Equatable {
    public let action: SchemaPathAction
    public let conversationID: Int
    public let requestID: String?
    public let schemaProtocol: String?
    public let flowVersion: Int?
    public let pathID: Int?
    public let claimID: Int?
    public let decision: SchemaCandidateDecision?
    public let context: String?
    public let note: String?
    public let kind: String?
    public let value: String?
    public let toPhase: String?
    public let methodID: String?
    public let confirmed: Bool?
    public let precheck: SchemaPathPrecheck?
    public let experiment: SchemaPractice?
    public let userConfirmed: Bool?
    public let techniqueRunID: Int?
    public let reason: String?
    public let suggestionID: Int?
    public let modeKey: String?
    public let authoredBy: String?
    public let age: Int?
    public let ageRange: String?
    public let scene: String?
    public let unmetNeed: String?
    public let confidence: String?
    public let stageID: Int?
    public let label: String?
    public let thenResponse: String?
    public let nowResponse: String?
    public let difference: String?
    public let evidence: String?
    public let focusCandidates: [SchemaFocusCandidateInput]?

    public init(
        action: SchemaPathAction,
        conversationID: Int,
        requestID: String? = nil,
        schemaProtocol: String? = nil,
        flowVersion: Int? = nil,
        pathID: Int? = nil,
        claimID: Int? = nil,
        decision: SchemaCandidateDecision? = nil,
        context: String? = nil,
        note: String? = nil,
        kind: String? = nil,
        value: String? = nil,
        toPhase: String? = nil,
        methodID: String? = nil,
        confirmed: Bool? = nil,
        precheck: SchemaPathPrecheck? = nil,
        experiment: SchemaPractice? = nil,
        userConfirmed: Bool? = nil,
        techniqueRunID: Int? = nil,
        reason: String? = nil,
        suggestionID: Int? = nil,
        modeKey: String? = nil,
        authoredBy: String? = nil,
        age: Int? = nil,
        ageRange: String? = nil,
        scene: String? = nil,
        unmetNeed: String? = nil,
        confidence: String? = nil,
        stageID: Int? = nil,
        label: String? = nil,
        thenResponse: String? = nil,
        nowResponse: String? = nil,
        difference: String? = nil,
        evidence: String? = nil,
        focusCandidates: [SchemaFocusCandidateInput]? = nil
    ) {
        self.action = action
        self.conversationID = conversationID
        self.requestID = requestID
        self.schemaProtocol = schemaProtocol
        self.flowVersion = flowVersion
        self.pathID = pathID
        self.claimID = claimID
        self.decision = decision
        self.context = context
        self.note = note
        self.kind = kind
        self.value = value
        self.toPhase = toPhase
        self.methodID = methodID
        self.confirmed = confirmed
        self.precheck = precheck
        self.experiment = experiment
        self.userConfirmed = userConfirmed
        self.techniqueRunID = techniqueRunID
        self.reason = reason
        self.suggestionID = suggestionID
        self.modeKey = modeKey
        self.authoredBy = authoredBy
        self.age = age
        self.ageRange = ageRange
        self.scene = scene
        self.unmetNeed = unmetNeed
        self.confidence = confidence
        self.stageID = stageID
        self.label = label
        self.thenResponse = thenResponse
        self.nowResponse = nowResponse
        self.difference = difference
        self.evidence = evidence
        self.focusCandidates = focusCandidates
    }
}

public struct SchemaPathMutationResponse: Decodable, Equatable, Sendable {
    public let ok: Bool
    public let duplicate: Bool?
    public let version: Int
    public let `protocol`: String?
    public let presentation: String?
    public let stage: String?
    public let step: String?
    public let revision: Int?
    public let progress: SchemaPathProgress?
    public let nextCard: SchemaCardEnvelope?
    public let messageMeta: [SchemaMessageMetaEvent]?
    public let interactionPolicy: SchemaPathInteractionPolicy?
    public let resumeState: SchemaPathResumeState?
    public let clinicalSync: SchemaClinicalSyncState?
    public let activePath: SchemaPath?
    public let candidates: [SchemaCandidate]
    public let queuedCandidates: [SchemaCandidate]?
    public let queuedCount: Int?
    public let activePathNotice: String?
    public let methods: [SchemaPathMethod]
    public let notices: [String]
    public let allowedActions: [String]
    public let completedTurns: Int
    public let minimumListeningTurns: Int
    public let schemaMode: SchemaTherapyModeState?
    public let turnAnalysis: SchemaTurnAnalysisState?
    public let candidate: SchemaCandidate?
    public let focus: SchemaFocusState?
    public let inlineSuggestions: [SchemaInlineSuggestion]?
    public let focusMinimumTurns: Int?
    public let origin: SchemaOriginState?
    public let growth: SchemaGrowthState?
    public let healthyAdult: SchemaHealthyAdultState?
    public private(set) var presentTransfer: SchemaPresentTransferState? = nil

    public var snapshot: SchemaPathSnapshot {
        SchemaPathSnapshot(
            version: version,
            protocol: `protocol`,
            presentation: presentation,
            stage: stage,
            step: step,
            revision: revision,
            progress: progress,
            nextCard: nextCard,
            messageMeta: messageMeta,
            interactionPolicy: interactionPolicy,
            resumeState: resumeState,
            clinicalSync: clinicalSync,
            activePath: activePath,
            candidates: candidates,
            queuedCandidates: queuedCandidates,
            queuedCount: queuedCount,
            activePathNotice: activePathNotice,
            methods: methods,
            notices: notices,
            allowedActions: allowedActions,
            completedTurns: completedTurns,
            minimumListeningTurns: minimumListeningTurns,
            schemaMode: schemaMode,
            turnAnalysis: turnAnalysis,
            focus: focus,
            inlineSuggestions: inlineSuggestions,
            focusMinimumTurns: focusMinimumTurns,
            origin: origin,
            growth: growth,
            healthyAdult: healthyAdult,
            presentTransfer: presentTransfer
        )
    }
}

import Foundation

public enum DivanCatalogKind: String, CaseIterable, Identifiable, Sendable {
    case therapist
    case philosopher

    public var id: Self { self }

    public var title: String {
        switch self {
        case .therapist: "Terapistler"
        case .philosopher: "Felsefeciler"
        }
    }

    public var systemImage: String {
        switch self {
        case .therapist: "person.2.fill"
        case .philosopher: "building.columns.fill"
        }
    }
}

public enum DivanSessionMode: String, CaseIterable, Identifiable, Sendable {
    case therapy = "terapi"
    case lesson = "ders"

    public var id: Self { self }
    public var title: String { self == .therapy ? "Terapi" : "Ders" }
    public var systemImage: String { self == .therapy ? "heart.text.square" : "book.closed" }
}

public struct DivanMaster: Identifiable, Hashable, Sendable {
    public let id: String
    public let kind: DivanCatalogKind
    public let name: String
    public let school: String
    public let subtitle: String
    public let portraitURL: URL?
    public let isLiving: Bool
    public let supportedModes: Set<DivanSessionMode>

    public init(
        id: String,
        kind: DivanCatalogKind,
        name: String,
        school: String,
        subtitle: String,
        portraitURL: URL? = nil,
        isLiving: Bool = false,
        supportedModes: Set<DivanSessionMode> = [.lesson]
    ) {
        self.id = id
        self.kind = kind
        self.name = name
        self.school = school
        self.subtitle = subtitle
        self.portraitURL = portraitURL
        self.isLiving = isLiving
        self.supportedModes = supportedModes
    }
}

public struct DivanConversation: Identifiable, Hashable, Sendable {
    public let id: Int
    public let masterID: String
    public let title: String
    public let preview: String
    public let updatedAt: Date
    public let isArchived: Bool
    public let isPinned: Bool
    public let isEnded: Bool
    public let mode: DivanSessionMode

    public init(
        id: Int,
        masterID: String,
        title: String,
        preview: String,
        updatedAt: Date,
        isArchived: Bool,
        isPinned: Bool = false,
        isEnded: Bool = false,
        mode: DivanSessionMode
    ) {
        self.id = id
        self.masterID = masterID
        self.title = title
        self.preview = preview
        self.updatedAt = updatedAt
        self.isArchived = isArchived
        self.isPinned = isPinned
        self.isEnded = isEnded
        self.mode = mode
    }
}

public struct DivanNewConversation: Sendable {
    public let conversation: DivanConversation
    public let greeting: String

    public init(conversation: DivanConversation, greeting: String) {
        self.conversation = conversation
        self.greeting = greeting
    }
}

public enum DivanMessageRole: String, Sendable {
    case user
    case assistant
    case system
}

public struct DivanMessage: Identifiable, Hashable, Sendable {
    public let id: String
    public let serverID: Int?
    public let role: DivanMessageRole
    public var content: String
    public let createdAt: Date
    public var isPending: Bool
    public var failedDescription: String?

    public init(
        id: String,
        serverID: Int?,
        role: DivanMessageRole,
        content: String,
        createdAt: Date,
        isPending: Bool = false,
        failedDescription: String? = nil
    ) {
        self.id = id
        self.serverID = serverID
        self.role = role
        self.content = content
        self.createdAt = createdAt
        self.isPending = isPending
        self.failedDescription = failedDescription
    }
}

public struct DivanConversationPage: Sendable {
    public let conversation: DivanConversation
    public let master: DivanMaster?
    public let messages: [DivanMessage]
    public let messageCount: Int
    public let loadedMessageCount: Int
    public let hasMoreMessages: Bool
    public let oldestMessageID: Int?
    public let pendingChat: DivanPendingChat?

    public init(
        conversation: DivanConversation,
        master: DivanMaster?,
        messages: [DivanMessage],
        messageCount: Int,
        loadedMessageCount: Int,
        hasMoreMessages: Bool,
        oldestMessageID: Int?,
        pendingChat: DivanPendingChat? = nil
    ) {
        self.conversation = conversation
        self.master = master
        self.messages = messages
        self.messageCount = messageCount
        self.loadedMessageCount = loadedMessageCount
        self.hasMoreMessages = hasMoreMessages
        self.oldestMessageID = oldestMessageID
        self.pendingChat = pendingChat
    }
}

public struct DivanPendingChat: Sendable, Equatable {
    public let requestID: String
    public let status: String
    public let content: String
    public let retryable: Bool
    public let isPending: Bool
    public let waitingForProvider: Bool

    public init(
        requestID: String,
        status: String,
        content: String,
        retryable: Bool,
        isPending: Bool,
        waitingForProvider: Bool
    ) {
        self.requestID = requestID
        self.status = status
        self.content = content
        self.retryable = retryable
        self.isPending = isPending
        self.waitingForProvider = waitingForProvider
    }

    public var isTerminal: Bool {
        ["completed", "failed", "interrupted", "cancelled"]
            .contains(status.localizedLowercase)
    }
}

public enum DivanChatUpdate: Sendable {
    case accepted(requestID: String?)
    case assistantStarted(messageID: Int?, createdAt: Date)
    case assistantDelta(String)
    case assistantReplaced(String)
    case status(String)
    case assistantCompleted(messageID: Int?, createdAt: Date)
    case failed(message: String, retryable: Bool)
}

public enum DivanProviderState: String, Sendable {
    case ready
    case needsAttention
    case unavailable
}

public enum DivanProviderID: String, CaseIterable, Identifiable, Sendable {
    case lmStudio = "lmstudio"
    case openAI = "openai"
    case anthropic
    case deepSeek = "deepseek"

    public var id: Self { self }

    public var title: String {
        switch self {
        case .lmStudio: "LM Studio"
        case .openAI: "OpenAI"
        case .anthropic: "Claude (Anthropic)"
        case .deepSeek: "DeepSeek"
        }
    }

    public var needsAPIKey: Bool { self != .lmStudio }
}

public struct DivanSettingsSummary: Sendable, Equatable {
    public let provider: DivanProviderID
    public let providerName: String
    public let modelName: String
    public let baseURL: String
    public let connectionDetail: String
    public let state: DivanProviderState
    public let apiKeyStored: Bool
    public let localOnly: Bool

    public init(
        provider: DivanProviderID,
        providerName: String,
        modelName: String,
        baseURL: String,
        connectionDetail: String,
        state: DivanProviderState,
        apiKeyStored: Bool,
        localOnly: Bool
    ) {
        self.provider = provider
        self.providerName = providerName
        self.modelName = modelName
        self.baseURL = baseURL
        self.connectionDetail = connectionDetail
        self.state = state
        self.apiKeyStored = apiKeyStored
        self.localOnly = localOnly
    }
}

public struct DivanSettingsInput: Sendable {
    public let provider: DivanProviderID
    public let modelName: String
    public let baseURL: String
    /// A write-only value. Adapters must never return this value in a summary.
    public let newAPIKey: String?

    public init(
        provider: DivanProviderID,
        modelName: String,
        baseURL: String,
        newAPIKey: String?
    ) {
        self.provider = provider
        self.modelName = modelName
        self.baseURL = baseURL
        self.newAPIKey = newAPIKey
    }
}

public struct DivanUISnapshot: Sendable {
    public let therapists: [DivanMaster]
    public let philosophers: [DivanMaster]
    public let activeConversations: [DivanConversation]
    public let archivedConversations: [DivanConversation]
    public let settings: DivanSettingsSummary

    public init(
        therapists: [DivanMaster],
        philosophers: [DivanMaster],
        activeConversations: [DivanConversation],
        archivedConversations: [DivanConversation],
        settings: DivanSettingsSummary
    ) {
        self.therapists = therapists
        self.philosophers = philosophers
        self.activeConversations = activeConversations
        self.archivedConversations = archivedConversations
        self.settings = settings
    }
}

public enum DivanAdvancedPreview: String, CaseIterable, Identifiable, Sendable {
    case chairWork
    case livingMap
    case storyStudio
    case experientialModules

    public var id: Self { self }

    public var title: String {
        switch self {
        case .chairWork: "Sandalye çalışması"
        case .livingMap: "Yaşayan harita"
        case .storyStudio: "Hikâye oluşturucu"
        case .experientialModules: "Deneyimsel çalışma modülleri"
        }
    }

    public var systemImage: String {
        switch self {
        case .chairWork: "chair.lounge"
        case .livingMap: "point.3.connected.trianglepath.dotted"
        case .storyStudio: "rectangle.portrait.on.rectangle.portrait"
        case .experientialModules: "square.grid.2x2"
        }
    }
}

public enum DivanSummaryAction: String, Sendable {
    case update
    case approve
    case reject
}

/// Seans sonrası özet taslağı; kullanıcı onaylayana kadar kalıcı
/// hafızaya geçmez.
public struct DivanSessionSummary: Identifiable, Hashable, Sendable {
    public let conversationID: Int
    public let draft: String
    public let approvedContent: String
    public let isApproved: Bool
    public let isRejected: Bool

    public var id: Int { conversationID }

    public init(
        conversationID: Int,
        draft: String,
        approvedContent: String,
        isApproved: Bool,
        isRejected: Bool
    ) {
        self.conversationID = conversationID
        self.draft = draft
        self.approvedContent = approvedContent
        self.isApproved = isApproved
        self.isRejected = isRejected
    }

    public var displayText: String {
        isApproved && !approvedContent.isEmpty ? approvedContent : draft
    }

    public var hasContent: Bool {
        !displayText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }
}

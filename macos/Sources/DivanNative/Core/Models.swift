import Foundation

public enum MasterKind: String, Codable, CaseIterable, Sendable {
    case therapist
    case philosopher
}

public struct MasterSummary: Identifiable, Codable, Equatable, Sendable {
    public let id: String
    public let name: String
    public let school: String
    public let subtitle: String
    public let portraitURL: URL?
    public let kind: MasterKind
    public let isLiving: Bool
    public let supportedModes: [String]

    public init(
        id: String,
        name: String,
        school: String,
        subtitle: String,
        portraitURL: URL?,
        kind: MasterKind,
        isLiving: Bool,
        supportedModes: [String]
    ) {
        self.id = id
        self.name = name
        self.school = school
        self.subtitle = subtitle
        self.portraitURL = portraitURL
        self.kind = kind
        self.isLiving = isLiving
        self.supportedModes = supportedModes
    }
}

public struct ProviderSummary: Identifiable, Codable, Equatable, Sendable {
    public let id: String
    public let label: String
    public let model: String
    public let keySet: Bool
    public let isLocal: Bool
    public let baseURL: String?

    public init(
        id: String,
        label: String,
        model: String,
        keySet: Bool,
        isLocal: Bool,
        baseURL: String? = nil
    ) {
        self.id = id
        self.label = label
        self.model = model
        self.keySet = keySet
        self.isLocal = isLocal
        self.baseURL = baseURL
    }
}

public struct PublicSettings: Codable, Equatable, Sendable {
    public let selectedProviderID: String
    public let providers: [ProviderSummary]
    public let contextWindowTokens: Int
    public let contextWindowOptions: [Int]
    public let privacySeen: Bool
    public let pinSet: Bool
    public let retentionDays: Int
    public let simpleMode: Bool
    public let credentialStorage: String
    public let appVersion: String

    public init(
        selectedProviderID: String = "deepseek",
        providers: [ProviderSummary] = [],
        contextWindowTokens: Int = 65_536,
        contextWindowOptions: [Int] = [],
        privacySeen: Bool = false,
        pinSet: Bool = false,
        retentionDays: Int = 0,
        simpleMode: Bool = false,
        credentialStorage: String = "",
        appVersion: String = ""
    ) {
        self.selectedProviderID = selectedProviderID
        self.providers = providers
        self.contextWindowTokens = contextWindowTokens
        self.contextWindowOptions = contextWindowOptions
        self.privacySeen = privacySeen
        self.pinSet = pinSet
        self.retentionDays = retentionDays
        self.simpleMode = simpleMode
        self.credentialStorage = credentialStorage
        self.appVersion = appVersion
    }
}

public struct BootstrapPayload: Codable, Equatable, Sendable {
    public let apiContractVersion: Int
    public let appVersion: String
    public let capabilities: [String: JSONValue]
    public let therapists: [MasterSummary]
    public let philosophers: [MasterSummary]
    public let settings: PublicSettings

    public init(
        apiContractVersion: Int,
        appVersion: String,
        capabilities: [String: JSONValue],
        therapists: [MasterSummary],
        philosophers: [MasterSummary],
        settings: PublicSettings
    ) {
        self.apiContractVersion = apiContractVersion
        self.appVersion = appVersion
        self.capabilities = capabilities
        self.therapists = therapists
        self.philosophers = philosophers
        self.settings = settings
    }

    public var allMasters: [MasterSummary] { therapists + philosophers }
}

public struct ConversationSummary: Identifiable, Codable, Equatable, Sendable {
    public let id: Int
    public let masterID: String
    public let title: String
    public let preview: String
    public let updatedAt: String
    public let createdAt: String
    public let isArchived: Bool
    public let isPinned: Bool
    public let isEnded: Bool
    public let mode: String
    public let submode: String?
    public let messageCount: Int
    public let chatStatus: String?

    public init(
        id: Int,
        masterID: String,
        title: String,
        preview: String,
        updatedAt: String,
        createdAt: String,
        isArchived: Bool,
        isPinned: Bool = false,
        isEnded: Bool,
        mode: String,
        submode: String?,
        messageCount: Int,
        chatStatus: String?
    ) {
        self.id = id
        self.masterID = masterID
        self.title = title
        self.preview = preview
        self.updatedAt = updatedAt
        self.createdAt = createdAt
        self.isArchived = isArchived
        self.isPinned = isPinned
        self.isEnded = isEnded
        self.mode = mode
        self.submode = submode
        self.messageCount = messageCount
        self.chatStatus = chatStatus
    }
}

public struct ConversationDetail: Identifiable, Codable, Equatable, Sendable {
    public let id: Int
    public let masterID: String
    public let title: String
    public let mode: String
    public let submode: String?
    public let createdAt: String
    public let updatedAt: String
    public let isEnded: Bool
    public let isArchived: Bool

    public init(
        id: Int,
        masterID: String,
        title: String,
        mode: String,
        submode: String?,
        createdAt: String,
        updatedAt: String,
        isEnded: Bool,
        isArchived: Bool
    ) {
        self.id = id
        self.masterID = masterID
        self.title = title
        self.mode = mode
        self.submode = submode
        self.createdAt = createdAt
        self.updatedAt = updatedAt
        self.isEnded = isEnded
        self.isArchived = isArchived
    }
}

public struct MessageRecord: Identifiable, Codable, Equatable, Sendable {
    public let id: Int
    public let role: String
    public let content: String
    public let createdAt: String
    public let replyTo: Int?
    public let deliveryStatus: String?

    public init(
        id: Int,
        role: String,
        content: String,
        createdAt: String,
        replyTo: Int? = nil,
        deliveryStatus: String? = nil
    ) {
        self.id = id
        self.role = role
        self.content = content
        self.createdAt = createdAt
        self.replyTo = replyTo
        self.deliveryStatus = deliveryStatus
    }
}

public struct ConversationPage: Codable, Equatable, Sendable {
    public let conversation: ConversationDetail
    public let messages: [MessageRecord]
    public let messageCount: Int
    public let loadedMessageCount: Int
    public let hasMoreMessages: Bool
    public let oldestMessageID: Int?
    public let latestChatRequest: ChatRequestStatus?

    public init(
        conversation: ConversationDetail,
        messages: [MessageRecord],
        messageCount: Int,
        loadedMessageCount: Int,
        hasMoreMessages: Bool,
        oldestMessageID: Int?,
        latestChatRequest: ChatRequestStatus? = nil
    ) {
        self.conversation = conversation
        self.messages = messages
        self.messageCount = messageCount
        self.loadedMessageCount = loadedMessageCount
        self.hasMoreMessages = hasMoreMessages
        self.oldestMessageID = oldestMessageID
        self.latestChatRequest = latestChatRequest
    }

    public var masterID: String { conversation.masterID }
}

public struct NewConversation: Codable, Equatable, Sendable {
    public let id: Int
    public let title: String
    public let greeting: String

    public init(id: Int, title: String, greeting: String) {
        self.id = id
        self.title = title
        self.greeting = greeting
    }
}

public struct ChatRequestStatus: Codable, Equatable, Sendable {
    public let requestID: String
    public let conversationID: Int
    public let status: String
    public let retryable: Bool
    public let userMessageID: Int?
    public let assistantMessageID: Int?
    public let replyTo: Int?
    public let provider: String
    public let model: String
    public let content: String
    public let errorCode: String
    public let attempt: Int
    public let maxAttempts: Int
    public let automaticRetry: Bool
    public let pending: Bool
    public let waitingForProvider: Bool
    public let nextRetryAt: String?

    public init(
        requestID: String,
        conversationID: Int,
        status: String,
        retryable: Bool,
        userMessageID: Int?,
        assistantMessageID: Int?,
        replyTo: Int?,
        provider: String,
        model: String,
        content: String,
        errorCode: String,
        attempt: Int,
        maxAttempts: Int,
        automaticRetry: Bool,
        pending: Bool,
        waitingForProvider: Bool,
        nextRetryAt: String?
    ) {
        self.requestID = requestID
        self.conversationID = conversationID
        self.status = status
        self.retryable = retryable
        self.userMessageID = userMessageID
        self.assistantMessageID = assistantMessageID
        self.replyTo = replyTo
        self.provider = provider
        self.model = model
        self.content = content
        self.errorCode = errorCode
        self.attempt = attempt
        self.maxAttempts = maxAttempts
        self.automaticRetry = automaticRetry
        self.pending = pending
        self.waitingForProvider = waitingForProvider
        self.nextRetryAt = nextRetryAt
    }

    public var isTerminal: Bool {
        ["completed", "failed", "interrupted", "cancelled"].contains(status)
    }
}

public struct ChatEvent: Codable, Equatable, Sendable {
    public enum Kind: String, Codable, Sendable {
        case accepted
        case thinking
        case delta
        case replace
        case waitingProvider = "waiting_provider"
        case retrying
        case error
        case done
        case status
        case unknown
    }

    public let kind: Kind
    public let text: String
    public let requestID: String?
    public let status: String?
    public let userMessageID: Int?
    public let assistantMessageID: Int?
    public let code: String?
    public let attempt: Int?
    public let maxAttempts: Int?
    public let request: ChatRequestStatus?

    public init(
        kind: Kind,
        text: String = "",
        requestID: String? = nil,
        status: String? = nil,
        userMessageID: Int? = nil,
        assistantMessageID: Int? = nil,
        code: String? = nil,
        attempt: Int? = nil,
        maxAttempts: Int? = nil,
        request: ChatRequestStatus? = nil
    ) {
        self.kind = kind
        self.text = text
        self.requestID = requestID
        self.status = status
        self.userMessageID = userMessageID
        self.assistantMessageID = assistantMessageID
        self.code = code
        self.attempt = attempt
        self.maxAttempts = maxAttempts
        self.request = request
    }
}

/// Provider secrets are write-only. This value never conforms to Codable or
/// CustomStringConvertible so accidental logging/serialization is harder.
public struct ProviderSettingsUpdate: Sendable {
    public let providerID: String?
    public let modelID: String?
    public let localBaseURL: String?
    public let apiKey: String?
    public let clearAPIKey: Bool
    public let contextWindowTokens: Int?

    public init(
        providerID: String? = nil,
        modelID: String? = nil,
        localBaseURL: String? = nil,
        apiKey: String? = nil,
        clearAPIKey: Bool = false,
        contextWindowTokens: Int? = nil
    ) {
        self.providerID = providerID
        self.modelID = modelID
        self.localBaseURL = localBaseURL
        self.apiKey = apiKey
        self.clearAPIKey = clearAPIKey
        self.contextWindowTokens = contextWindowTokens
    }
}

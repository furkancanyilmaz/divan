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
    /// Filled when the durable chat request is accepted/completed. Keeping the
    /// local SwiftUI `id` stable avoids a visual jump while still allowing
    /// exact message-bound schema cards to attach immediately.
    public var serverID: Int?
    public let role: DivanMessageRole
    public var content: String
    public let createdAt: Date
    public var isPending: Bool
    public var failedDescription: String?
    public var technique: MessageTechniqueMetadata?
    public var schemaMetaEvents: [SchemaMessageMetaEvent]
    public var schemaBindingResult: SchemaChatBindingResult?
    /// Durable server identity/status used by v5 to prove that the visible
    /// Kerem row is exactly the completed prompt named by the hidden binding.
    public var publicID: String?
    public var deliveryStatus: String?

    public init(
        id: String,
        serverID: Int?,
        role: DivanMessageRole,
        content: String,
        createdAt: Date,
        isPending: Bool = false,
        failedDescription: String? = nil,
        technique: MessageTechniqueMetadata? = nil,
        schemaMetaEvents: [SchemaMessageMetaEvent] = [],
        schemaBindingResult: SchemaChatBindingResult? = nil,
        publicID: String? = nil,
        deliveryStatus: String? = nil
    ) {
        self.id = id
        self.serverID = serverID
        self.role = role
        self.content = content
        self.createdAt = createdAt
        self.isPending = isPending
        self.failedDescription = failedDescription
        self.technique = technique
        self.schemaMetaEvents = schemaMetaEvents
        self.schemaBindingResult = schemaBindingResult
        self.publicID = publicID
        self.deliveryStatus = deliveryStatus
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
    public let schemaBindingResult: SchemaChatBindingResult?
    public let schemaPromptProtocol: String
    public let schemaPromptIntent: String

    public init(
        requestID: String,
        status: String,
        content: String,
        retryable: Bool,
        isPending: Bool,
        waitingForProvider: Bool,
        schemaBindingResult: SchemaChatBindingResult? = nil,
        schemaPromptProtocol: String = "",
        schemaPromptIntent: String = ""
    ) {
        self.requestID = requestID
        self.status = status
        self.content = content
        self.retryable = retryable
        self.isPending = isPending
        self.waitingForProvider = waitingForProvider
        self.schemaBindingResult = schemaBindingResult
        self.schemaPromptProtocol = schemaPromptProtocol
        self.schemaPromptIntent = schemaPromptIntent
    }

    public var isTerminal: Bool {
        ["completed", "failed", "interrupted", "cancelled"]
            .contains(status.localizedLowercase)
    }
}

public enum DivanChatUpdate: Sendable {
    case accepted(requestID: String?, userMessageID: Int?)
    case assistantStarted(messageID: Int?, createdAt: Date)
    case assistantDelta(String)
    case assistantReplaced(String)
    case status(String)
    case assistantCompleted(
        messageID: Int?,
        createdAt: Date,
        technique: MessageTechniqueMetadata?,
        messageMeta: [SchemaMessageMetaEvent],
        nextCard: SchemaCardEnvelope?,
        schemaPath: SchemaPath? = nil,
        interactionPolicy: SchemaPathInteractionPolicy? = nil,
        resumeState: SchemaPathResumeState? = nil,
        schemaBindingResult: SchemaChatBindingResult?
    )
    case failed(message: String, retryable: Bool)
}

public enum DivanProviderState: String, Sendable {
    case ready
    case needsAttention
    case unavailable
}

/// Bir sağlayıcının sunucuda saklanan, gizli içermeyen ayar özeti. Ayarlar
/// ekranı sağlayıcılar arasında geçiş yaparken model/adres alanlarını bu
/// kayıtlardan doldurur; böylece kayıtlı değerler kaybolmaz.
public struct DivanProviderSnapshot: Identifiable, Equatable, Sendable {
    public let provider: DivanProviderID
    public let label: String
    public let model: String
    public let baseURL: String?
    public let keySet: Bool
    public let isLocal: Bool

    public var id: DivanProviderID { provider }

    public init(
        provider: DivanProviderID,
        label: String,
        model: String,
        baseURL: String?,
        keySet: Bool,
        isLocal: Bool
    ) {
        self.provider = provider
        self.label = label
        self.model = model
        self.baseURL = baseURL
        self.keySet = keySet
        self.isLocal = isLocal
    }
}

/// Yerel sunucu taramasının bir sonucu: adres, algılanan modeller ve bu
/// sunucunun karşılık geldiği sağlayıcı (bilinmiyorsa nil).
public struct DivanLocalServer: Identifiable, Equatable, Sendable {
    public let id: String
    public let label: String
    public let baseURL: String
    public let models: [String]
    public let provider: DivanProviderID?

    public init(
        id: String,
        label: String,
        baseURL: String,
        models: [String],
        provider: DivanProviderID?
    ) {
        self.id = id
        self.label = label
        self.baseURL = baseURL
        self.models = models
        self.provider = provider
    }
}

/// Sağlayıcı başına tutulan, henüz kaydedilmemiş olabilecek düzenleme
/// taslağı. Sağlayıcılar arasında geçiş yapınca alanlar ayrı ayrı hatırlanır.
public struct DivanProviderDraft: Equatable, Sendable {
    public var model: String
    public var baseURL: String

    public init(model: String = "", baseURL: String = "") {
        self.model = model
        self.baseURL = baseURL
    }
}

public enum DivanProviderID: String, CaseIterable, Identifiable, Sendable {
    case lmStudio = "lmstudio"
    case ollama
    case openAI = "openai"
    case anthropic
    case gemini
    case deepSeek = "deepseek"

    public var id: Self { self }

    public var title: String {
        switch self {
        case .lmStudio: "LM Studio"
        case .ollama: "Ollama"
        case .openAI: "OpenAI"
        case .anthropic: "Claude (Anthropic)"
        case .gemini: "Google Gemini"
        case .deepSeek: "DeepSeek"
        }
    }

    /// Bu Mac'te çalışan OpenAI uyumlu bir yerel sunucuya konuşur.
    public var isLocal: Bool { self == .lmStudio || self == .ollama }
    public var needsAPIKey: Bool { !isLocal }

    /// Yerel sağlayıcının varsayılan adresi; bulut sağlayıcılar için boş.
    public var defaultBaseURL: String {
        switch self {
        case .lmStudio: "http://127.0.0.1:1234/v1"
        case .ollama: "http://127.0.0.1:11434/v1"
        default: ""
        }
    }
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
    /// Misafir oturumu açık mı? Açıkken yalnız misafir görüşmeleri
    /// listelenir; kapanınca misafir görüşmeleri silinir.
    public let guestMode: Bool
    /// Tüm sağlayıcıların sunucuda saklanan ayar özetleri. Sağlayıcılar arası
    /// geçişte alanlar bu listeden doldurulur; anahtar durumu da buradan
    /// sağlayıcıya özel okunur.
    public let providers: [DivanProviderSnapshot]

    public init(
        provider: DivanProviderID,
        providerName: String,
        modelName: String,
        baseURL: String,
        connectionDetail: String,
        state: DivanProviderState,
        apiKeyStored: Bool,
        localOnly: Bool,
        guestMode: Bool = false,
        providers: [DivanProviderSnapshot] = []
    ) {
        self.provider = provider
        self.providerName = providerName
        self.modelName = modelName
        self.baseURL = baseURL
        self.connectionDetail = connectionDetail
        self.state = state
        self.apiKeyStored = apiKeyStored
        self.localOnly = localOnly
        self.guestMode = guestMode
        self.providers = providers
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

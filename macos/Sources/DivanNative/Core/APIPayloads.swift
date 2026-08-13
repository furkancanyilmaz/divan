import Foundation

struct PortraitPayload: Decodable {
    let file: String?
    let url: String?
}

struct MasterPayload: Decodable {
    let id: String
    let name: String
    let school: String?
    let sub: String?
    let subtitle: String?
    let kind: String?
    let modes: [String]?
    let portrait: PortraitPayload?
    let isLiving: Bool?
}

struct ProviderPayload: Decodable {
    let id: String?
    let label: String?
    let model: String?
    let keySet: Bool?
    let local: Bool?
    // JSONDecoder's snake-case conversion spells acronyms as ordinary words
    // (base_url -> baseUrl). Keep wire DTOs aligned with that spelling and map
    // to the public `baseURL` model at the API boundary.
    let baseUrl: String?
}

struct BootstrapResponse: Decodable {
    let apiContractVersion: Int
    let appVersion: String
    let capabilities: [String: JSONValue]
    let provider: ProviderPayload?
    let therapists: [MasterPayload]
    let philosophers: [MasterPayload]
    let settings: BootstrapSettingsPayload
}

struct BootstrapSettingsPayload: Decodable {
    let contextWindowTokens: Int?
    let contextWindowOptions: [Int]?
    let privacySeen: Bool?
    let pinSet: Bool?
    let retentionDays: Int?
    let simpleMode: Bool?
    let credentialStorage: String?
}

struct SettingsResponse: Decodable {
    let provider: String?
    let llmProvider: String?
    let providers: [String: ProviderPayload]?
    let contextWindowTokens: Int?
    let contextWindowOptions: [Int]?
    let privacySeen: Bool?
    let pinSet: Bool?
    let retentionDays: Int?
    let simpleMode: Bool?
    let credentialStorage: String?
    let version: String?
}

struct ConversationPayload: Decodable {
    let id: Int
    let therapist: String?
    let title: String?
    let preview: String?
    let updated: String?
    let created: String?
    let archivedAt: String?
    let pinnedAt: String?
    let ended: Int?
    let mode: String?
    let submode: String?
    let n: Int?
    let chatStatus: String?
}

struct MessagePayload: Decodable {
    let id: Int
    let role: String?
    let content: String?
    let created: String?
    let replyTo: Int?
    let deliveryStatus: String?
}

struct ConversationPageResponse: Decodable {
    let conversation: ConversationPayload
    let messages: [MessagePayload]
    let messageCount: Int?
    let loadedMessageCount: Int?
    let hasMoreMessages: Bool?
    let oldestMessageId: Int?
    let chatRequest: ChatRequestPayload?
}

struct NewConversationResponse: Decodable {
    let id: Int
    let title: String?
    let greeting: String?
}

struct OKResponse: Decodable {
    let ok: Bool?
}

struct EndConversationResponse: Decodable {
    let closing: String?
    let processing: Bool?
}

struct ChatEnvelope: Decodable {
    let chat: ChatRequestPayload?
}

struct ChatMutationResponse: Decodable {
    let chat: ChatRequestPayload?
}

struct ChatRequestPayload: Decodable {
    let requestId: String?
    let convId: Int?
    let status: String?
    let retryable: Bool?
    let userMessageId: Int?
    let assistantMessageId: Int?
    let replyTo: Int?
    let provider: String?
    let model: String?
    let content: String?
    let errorCode: String?
    let attempt: Int?
    let maxAttempts: Int?
    let automaticRetry: Bool?
    let pending: Bool?
    let waitingForProvider: Bool?
    let nextRetryAt: String?
}

struct ChatEventPayload: Decodable {
    let type: String?
    let text: String?
    let requestId: String?
    let status: String?
    let userMessageId: Int?
    let assistantMessageId: Int?
    let code: String?
    let attempt: Int?
    let maxAttempts: Int?
}

struct DuplicateChatResponse: Decodable {
    let message: String?
    let requestId: String?
    let status: String?
    let userMessageId: Int?
    let assistantMessageId: Int?
}

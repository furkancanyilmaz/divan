import Foundation

/// The intentionally small boundary between SwiftUI and the Core runtime.
/// Core DTOs are converted once by the application adapter; views never know
/// about HTTP, JSON, database paths, or provider credentials.
public protocol DivanUIDataSource: Sendable {
    func bootstrap() async throws -> DivanUISnapshot

    func masters(kind: DivanCatalogKind) async throws -> [DivanMaster]
    func conversations(archived: Bool) async throws -> [DivanConversation]
    func conversation(id: Int, limit: Int, beforeID: Int?) async throws
        -> DivanConversationPage

    func createConversation(masterID: String, mode: DivanSessionMode) async throws
        -> DivanNewConversation
    func setArchived(_ archived: Bool, conversationID: Int) async throws
    func setPinned(_ pinned: Bool, conversationID: Int) async throws
    func profileText() async throws -> String
    func updateProfileText(_ text: String) async throws
    func notebook(masterID: String, mode: DivanSessionMode) async throws -> LibraryNotebook
    func letters(masterID: String) async throws -> LibraryLetters
    func dreamJournal(masterID: String) async throws -> LibraryDreamJournal
    func analyzeDreams(masterID: String) async throws -> String
    func search(_ term: String) async throws -> [LibrarySearchHit]
    func sessionSummary(conversationID: Int) async throws -> DivanSessionSummary?
    func updateSessionSummary(
        conversationID: Int,
        action: DivanSummaryAction,
        content: String?
    ) async throws -> DivanSessionSummary?
    func deleteConversation(id: Int) async throws
    func endConversation(id: Int) async throws

    func sendMessage(conversationID: Int, text: String) async
        -> AsyncThrowingStream<DivanChatUpdate, Error>
    func chatStatus(requestID: String) async throws -> DivanPendingChat
    func portraitData(url: URL) async throws -> Data
    func settingsSummary() async throws -> DivanSettingsSummary
    func saveSettings(_ input: DivanSettingsInput) async throws
        -> DivanSettingsSummary
    func clearAPIKey(provider: DivanProviderID) async throws
        -> DivanSettingsSummary
}

public actor DivanPortraitCache {
    private let maximumBytes: Int
    private var values: [URL: Data] = [:]
    private var order: [URL] = []
    private var totalBytes = 0
    private var inFlight: [URL: Task<Data, Error>] = [:]

    public init(maximumBytes: Int = 32 * 1024 * 1024) {
        self.maximumBytes = maximumBytes
    }

    public func data(
        for url: URL,
        loader: @escaping @Sendable () async throws -> Data
    ) async throws -> Data {
        if let cached = values[url] {
            touch(url)
            return cached
        }
        if let task = inFlight[url] { return try await task.value }
        let task = Task { try await loader() }
        inFlight[url] = task
        do {
            let data = try await task.value
            inFlight[url] = nil
            insert(data, for: url)
            return data
        } catch {
            inFlight[url] = nil
            throw error
        }
    }

    private func touch(_ url: URL) {
        order.removeAll { $0 == url }
        order.append(url)
    }

    private func insert(_ data: Data, for url: URL) {
        guard data.count <= maximumBytes else { return }
        if let previous = values[url] { totalBytes -= previous.count }
        values[url] = data
        totalBytes += data.count
        touch(url)
        while totalBytes > maximumBytes, let oldest = order.first {
            order.removeFirst()
            if let removed = values.removeValue(forKey: oldest) {
                totalBytes -= removed.count
            }
        }
    }
}

public struct DivanUIClientError: LocalizedError, Sendable {
    public let userMessage: String
    public let recoverySuggestion: String?

    public init(_ userMessage: String, recoverySuggestion: String? = nil) {
        self.userMessage = userMessage
        self.recoverySuggestion = recoverySuggestion
    }

    public var errorDescription: String? { userMessage }
}

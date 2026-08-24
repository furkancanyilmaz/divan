import Foundation
@testable import DivanNative

enum SchemaChatV4FakeFailure: Sendable {
    case transient
    case stale
}

private enum SchemaChatV4ReadFailure: Error {
    case unavailable
}

actor SchemaChatV4DataSource: DivanUIDataSource {
    static let conversationID = 4_404
    static let sourceUserMessageID = 101
    static let sourceAssistantMessageID = 102

    private let master = DivanMaster(
        id: "young",
        kind: .therapist,
        name: "Kerem Genç",
        school: "Şema Terapi",
        subtitle: "Sohbet içi şema çalışması",
        supportedModes: [.therapy]
    )
    private let conversation = DivanConversation(
        id: conversationID,
        masterID: "young",
        title: "Şema v4",
        preview: "Birlikte bakalım.",
        updatedAt: Date(timeIntervalSince1970: 1_787_334_400),
        isArchived: false,
        mode: .therapy
    )
    private var snapshot: SchemaPathSnapshot
    private var postSendSnapshot: SchemaPathSnapshot?
    private let streamProjectionSnapshot: SchemaPathSnapshot?
    private var streamNextCardOverride: SchemaCardEnvelope??
    private var failSchemaReadsAfterSend: Bool
    private var streamBindingResult: SchemaChatBindingResult?
    private let streamDelayNanoseconds: UInt64
    private var mutationSnapshot: SchemaPathSnapshot?
    private var hasSent = false
    private var staleReplacement: SchemaPathSnapshot?
    private var failures: [SchemaChatV4FakeFailure]
    private var bindings: [SchemaChatBinding?] = []
    private var sentTexts: [String] = []
    private var cardMutations: [SchemaCardMutation] = []
    private var pathMutations: [SchemaPathMutation] = []
    private var turnAnalysisMutations: [SchemaTurnAnalysisMutation] = []
    private let conversationMessages: [DivanMessage]
    private var pendingChat: DivanPendingChat?

    init(
        snapshot: SchemaPathSnapshot,
        failures: [SchemaChatV4FakeFailure] = [],
        staleReplacement: SchemaPathSnapshot? = nil,
        postSendSnapshot: SchemaPathSnapshot? = nil,
        streamProjectionSnapshot: SchemaPathSnapshot? = nil,
        streamNextCardOverride: SchemaCardEnvelope?? = nil,
        failSchemaReadsAfterSend: Bool = false,
        streamBindingResult: SchemaChatBindingResult? = .init(applied: true),
        streamDelayNanoseconds: UInt64 = 0,
        mutationSnapshot: SchemaPathSnapshot? = nil,
        conversationMessages: [DivanMessage]? = nil,
        pendingChat: DivanPendingChat? = nil
    ) {
        self.snapshot = snapshot
        self.failures = failures
        self.staleReplacement = staleReplacement
        self.postSendSnapshot = postSendSnapshot
        self.streamProjectionSnapshot = streamProjectionSnapshot
        self.streamNextCardOverride = streamNextCardOverride
        self.failSchemaReadsAfterSend = failSchemaReadsAfterSend
        self.streamBindingResult = streamBindingResult
        self.streamDelayNanoseconds = streamDelayNanoseconds
        self.mutationSnapshot = mutationSnapshot
        self.pendingChat = pendingChat
        self.conversationMessages = conversationMessages ?? [
            DivanMessage(
                id: "schema-source-user",
                serverID: Self.sourceUserMessageID,
                role: .user,
                content: "Bugün aynı döngü tekrarlandı.",
                createdAt: Date(timeIntervalSince1970: 1_787_334_340),
                publicID: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                deliveryStatus: "completed"
            ),
            DivanMessage(
                id: "schema-source-assistant",
                serverID: Self.sourceAssistantMessageID,
                role: .assistant,
                content: "Bunu birlikte sınayabiliriz.",
                createdAt: Date(timeIntervalSince1970: 1_787_334_400),
                publicID: "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                deliveryStatus: "completed"
            ),
        ]
    }

    func bootstrap() async throws -> DivanUISnapshot {
        DivanUISnapshot(
            therapists: [master],
            philosophers: [],
            activeConversations: [conversation],
            archivedConversations: [],
            settings: settings
        )
    }

    func masters(kind: DivanCatalogKind) async throws -> [DivanMaster] {
        kind == .therapist ? [master] : []
    }

    func conversations(archived: Bool) async throws -> [DivanConversation] {
        archived ? [] : [conversation]
    }

    func conversation(
        id: Int,
        limit: Int,
        beforeID: Int?
    ) async throws -> DivanConversationPage {
        let recoveredPending = pendingChat
        // Process-death recovery is observed once. A later durable reload
        // sees the now-terminal request instead of reopening an endless fake
        // pending loop in tests.
        pendingChat = nil
        return DivanConversationPage(
            conversation: conversation,
            master: master,
            messages: conversationMessages,
            messageCount: conversationMessages.count,
            loadedMessageCount: conversationMessages.count,
            hasMoreMessages: false,
            oldestMessageID: conversationMessages.compactMap(\.serverID).min(),
            pendingChat: recoveredPending
        )
    }

    func sendMessage(
        conversationID: Int,
        text: String
    ) async -> AsyncThrowingStream<DivanChatUpdate, Error> {
        await sendMessage(
            conversationID: conversationID,
            text: text,
            schemaBinding: nil
        )
    }

    func sendMessage(
        conversationID: Int,
        text: String,
        schemaBinding: SchemaChatBinding?
    ) async -> AsyncThrowingStream<DivanChatUpdate, Error> {
        bindings.append(schemaBinding)
        sentTexts.append(text)
        hasSent = true
        if let postSendSnapshot { snapshot = postSendSnapshot }
        let streamedSnapshot = streamProjectionSnapshot ?? snapshot
        let nextCard: SchemaCardEnvelope?
        if let override = streamNextCardOverride { nextCard = override }
        else { nextCard = streamedSnapshot.nextCard }
        let bindingResult = streamBindingResult
        let meta = SchemaMessageMetaEvent(
            databaseId: 77,
            publicId: "schema-meta-after-bound-chat",
            kind: "technique",
            status: "active",
            messageId: 104,
            sourceUserMessageId: 103,
            sourceAssistantMessageId: 104,
            pathId: streamedSnapshot.activePath?.id ?? 9,
            pathPublicId: "33333333333333333333333333333333",
            stage: streamedSnapshot.stage ?? "depth",
            step: streamedSnapshot.step ?? "imagery_work",
            title: "İmgeleme adımı",
            summary: "Yanıt güncel sohbet adımına bağlandı."
        )
        let delay = streamDelayNanoseconds
        return AsyncThrowingStream<DivanChatUpdate, Error>(
            bufferingPolicy: .unbounded
        ) { continuation in
            Task {
                continuation.yield(.accepted(
                    requestID: "schema-chat-request-1234",
                    userMessageID: 103
                ))
                if delay > 0 { try? await Task.sleep(nanoseconds: delay) }
                continuation.yield(.assistantStarted(
                    messageID: 104,
                    createdAt: Date()
                ))
                continuation.yield(.assistantDelta(
                    "Burada kalıp birlikte bakalım."
                ))
                continuation.yield(.assistantCompleted(
                    messageID: 104,
                    createdAt: Date(),
                    technique: MessageTechniqueMetadata(
                        name: "İmgeleme ile yeniden yazım",
                        phase: "work",
                        rationale: "Açık onaylı sohbet adımı"
                    ),
                    messageMeta: [meta],
                    nextCard: nextCard,
                    schemaPath: streamedSnapshot.activePath,
                    interactionPolicy: streamedSnapshot.interactionPolicy,
                    resumeState: streamedSnapshot.resumeState,
                    schemaBindingResult: bindingResult
                ))
                continuation.finish()
            }
        }
    }

    func schemaPath(conversationID: Int) async throws -> SchemaPathSnapshot {
        if failSchemaReadsAfterSend && hasSent {
            throw SchemaChatV4ReadFailure.unavailable
        }
        return snapshot
    }

    func mutateSchemaPath(
        _ mutation: SchemaPathMutation
    ) async throws -> SchemaPathMutationResponse {
        pathMutations.append(mutation)
        return response(for: snapshot)
    }

    func mutateSchemaCard(
        _ mutation: SchemaCardMutation
    ) async throws -> SchemaPathMutationResponse {
        cardMutations.append(mutation)
        if !failures.isEmpty {
            switch failures.removeFirst() {
            case .transient:
                throw DivanAPIError(
                    message: "Geçici bağlantı hatası",
                    errorCode: "temporarily_unavailable"
                )
            case .stale:
                if let staleReplacement { snapshot = staleReplacement }
                throw DivanAPIError(
                    message: "Revizyon değişti",
                    errorCode: "stale_schema_revision"
                )
            }
        }
        if let mutationSnapshot { snapshot = mutationSnapshot }
        return response(for: snapshot)
    }

    func mutateSchemaClinicalSync(
        _ mutation: SchemaClinicalSyncMutation
    ) async throws -> SchemaPathMutationResponse {
        response(for: snapshot)
    }

    func mutateSchemaTurnAnalysis(
        _ mutation: SchemaTurnAnalysisMutation
    ) async throws -> SchemaTurnAnalysisMutationResponse {
        turnAnalysisMutations.append(mutation)
        return SchemaTurnAnalysisMutationResponse(
            ok: true,
            processing: false,
            queued: false,
            alreadyAnalyzed: false,
            jobId: nil,
            userMessageId: mutation.userMessageID,
            message: nil,
            turnAnalysis: nil,
            schemaMode: nil
        )
    }

    func capturedBindings() -> [SchemaChatBinding?] { bindings }
    func capturedSentTexts() -> [String] { sentTexts }
    func capturedCardMutations() -> [SchemaCardMutation] { cardMutations }
    func capturedPathMutations() -> [SchemaPathMutation] { pathMutations }
    func capturedTurnAnalysisMutations() -> [SchemaTurnAnalysisMutation] {
        turnAnalysisMutations
    }
    func replaceSnapshot(_ value: SchemaPathSnapshot) { snapshot = value }
    func setFailSchemaReadsAfterSend(_ value: Bool) {
        failSchemaReadsAfterSend = value
    }

    func createConversation(
        masterID: String,
        mode: DivanSessionMode
    ) async throws -> DivanNewConversation {
        DivanNewConversation(conversation: conversation, greeting: "")
    }
    func setArchived(_ archived: Bool, conversationID: Int) async throws {}
    func setPinned(_ pinned: Bool, conversationID: Int) async throws {}
    func profileText() async throws -> String { "" }
    func updateProfileText(_ text: String) async throws {}
    func notebook(
        masterID: String,
        mode: DivanSessionMode
    ) async throws -> LibraryNotebook {
        LibraryNotebook(notes: [], formulations: [])
    }
    func letters(masterID: String) async throws -> LibraryLetters {
        LibraryLetters(letters: [], referrals: [])
    }
    func dreamJournal(masterID: String) async throws -> LibraryDreamJournal {
        LibraryDreamJournal(dreams: [], analysis: "")
    }
    func analyzeDreams(masterID: String) async throws -> String { "" }
    func search(_ term: String) async throws -> [LibrarySearchHit] { [] }
    func sessionSummary(
        conversationID: Int
    ) async throws -> DivanSessionSummary? { nil }
    func updateSessionSummary(
        conversationID: Int,
        action: DivanSummaryAction,
        content: String?
    ) async throws -> DivanSessionSummary? { nil }
    func deleteConversation(id: Int) async throws {}
    func endConversation(id: Int) async throws {}
    func chatStatus(requestID: String) async throws -> DivanPendingChat {
        DivanPendingChat(
            requestID: requestID,
            status: "completed",
            content: "Tamamlandı",
            retryable: false,
            isPending: false,
            waitingForProvider: false
        )
    }
    func portraitData(url: URL) async throws -> Data { Data() }
    func settingsSummary() async throws -> DivanSettingsSummary { settings }
    func saveSettings(
        _ input: DivanSettingsInput
    ) async throws -> DivanSettingsSummary {
        DivanSettingsSummary(
            provider: input.provider,
            providerName: input.provider.title,
            modelName: input.modelName,
            baseURL: input.baseURL,
            connectionDetail: "Test sağlayıcısı",
            state: .ready,
            apiKeyStored: input.newAPIKey != nil,
            localOnly: input.provider.isLocal
        )
    }
    func clearAPIKey(
        provider: DivanProviderID
    ) async throws -> DivanSettingsSummary { settings }
    func scanLocalModels() async throws -> [DivanLocalServer] { [] }

    private var settings: DivanSettingsSummary {
        DivanSettingsSummary(
            provider: .lmStudio,
            providerName: "LM Studio",
            modelName: "yerel-model",
            baseURL: "http://127.0.0.1:1234/v1",
            connectionDetail: "Yerel sağlayıcı",
            state: .ready,
            apiKeyStored: false,
            localOnly: true
        )
    }

    private func response(
        for value: SchemaPathSnapshot
    ) -> SchemaPathMutationResponse {
        SchemaPathMutationResponse(
            ok: true,
            duplicate: false,
            version: value.version,
            protocol: value.protocol,
            presentation: value.presentation,
            stage: value.stage,
            step: value.step,
            revision: value.revision,
            progress: value.progress,
            nextCard: value.nextCard,
            messageMeta: value.messageMeta,
            interactionPolicy: value.interactionPolicy,
            resumeState: value.resumeState,
            clinicalSync: value.clinicalSync,
            activePath: value.activePath,
            candidates: value.candidates,
            queuedCandidates: value.queuedCandidates,
            queuedCount: value.queuedCount,
            activePathNotice: value.activePathNotice,
            methods: value.methods,
            notices: value.notices,
            allowedActions: value.allowedActions,
            completedTurns: value.completedTurns,
            minimumListeningTurns: value.minimumListeningTurns,
            schemaMode: value.schemaMode,
            turnAnalysis: value.turnAnalysis,
            candidate: nil,
            focus: value.focus,
            inlineSuggestions: value.inlineSuggestions,
            focusMinimumTurns: value.focusMinimumTurns,
            origin: value.origin,
            growth: value.growth,
            healthyAdult: value.healthyAdult
        )
    }
}

final class MemorySchemaChatDraftStore: SchemaChatDraftStore {
    private var records: [Int: SchemaChatDraftRecord] = [:]

    func load(conversationID: Int) -> SchemaChatDraftRecord? {
        records[conversationID]
    }

    func save(_ record: SchemaChatDraftRecord) {
        records[record.conversationID] = record
    }

    func remove(conversationID: Int) {
        records.removeValue(forKey: conversationID)
    }

    func record(conversationID: Int) -> SchemaChatDraftRecord? {
        records[conversationID]
    }
}

@MainActor
final class MemorySchemaDisplayPreferencesStore: DivanDisplayPreferencesStore {
    private var preferences = DivanDisplayPreferences.default

    func load() -> DivanDisplayPreferences { preferences }
    func save(_ preferences: DivanDisplayPreferences) {
        self.preferences = preferences
    }
}

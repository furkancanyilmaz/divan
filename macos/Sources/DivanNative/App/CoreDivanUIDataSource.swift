import Foundation

@MainActor
public final class DivanRuntimeLoader {
    public let controller: RuntimeController

    public init(controller: RuntimeController) {
        self.controller = controller
    }

    public func service() async throws -> (APIClient, BootstrapPayload) {
        if let client = controller.client,
           let bootstrap = controller.bootstrapPayload {
            return (client, bootstrap)
        }
        await controller.start()
        if let client = controller.client,
           let bootstrap = controller.bootstrapPayload {
            return (client, bootstrap)
        }
        if case .failed(let message) = controller.state {
            throw DivanUIClientError(
                message,
                recoverySuggestion: "Python ve yerel Divan çekirdek dosyalarını denetleyin."
            )
        }
        throw DivanUIClientError("Yerel Divan çalışma zamanı başlatılamadı.")
    }

    public func stop() async {
        await controller.stop()
    }
}

/// Converts the public Core DTOs to UI-only values. No view decodes JSON or
/// sends raw HTTP and no provider secret ever travels from Core back to UI.
public final class CoreDivanUIDataSource: DivanUIDataSource, @unchecked Sendable {
    private let loader: DivanRuntimeLoader

    public init(loader: DivanRuntimeLoader) {
        self.loader = loader
    }

    public func bootstrap() async throws -> DivanUISnapshot {
        let (client, payload) = try await loader.service()
        async let activeTask = client.conversations(archived: false)
        async let archivedTask = client.conversations(archived: true)
        let (active, archived) = try await (activeTask, archivedTask)
        return DivanUISnapshot(
            therapists: payload.therapists.map(Self.master),
            philosophers: payload.philosophers.map(Self.master),
            activeConversations: active.map(Self.conversation),
            archivedConversations: archived.map(Self.conversation),
            settings: Self.settings(payload.settings)
        )
    }

    public func masters(kind: DivanCatalogKind) async throws -> [DivanMaster] {
        let (client, _) = try await loader.service()
        let coreKind: MasterKind = kind == .therapist ? .therapist : .philosopher
        return try await client.masters(kind: coreKind).map(Self.master)
    }

    public func conversations(archived: Bool) async throws -> [DivanConversation] {
        let (client, _) = try await loader.service()
        return try await client.conversations(archived: archived)
            .map(Self.conversation)
    }

    public func conversation(
        id: Int,
        limit: Int,
        beforeID: Int?
    ) async throws -> DivanConversationPage {
        let (client, _) = try await loader.service()
        let page = try await client.conversation(
            id: id,
            limit: limit,
            beforeID: beforeID
        )
        let preview = page.messages.last?.content ?? ""
        let detail = page.conversation
        let summary = DivanConversation(
            id: detail.id,
            masterID: detail.masterID,
            title: detail.title,
            preview: preview,
            updatedAt: Self.date(detail.updatedAt),
            isArchived: detail.isArchived,
            isEnded: detail.isEnded,
            mode: Self.mode(detail.mode)
        )
        return DivanConversationPage(
            conversation: summary,
            master: nil,
            messages: page.messages.map(Self.message),
            messageCount: page.messageCount,
            loadedMessageCount: page.loadedMessageCount,
            hasMoreMessages: page.hasMoreMessages,
            oldestMessageID: page.oldestMessageID,
            pendingChat: page.latestChatRequest.map(Self.pendingChat)
        )
    }

    public func createConversation(
        masterID: String,
        mode: DivanSessionMode
    ) async throws -> DivanNewConversation {
        let (client, _) = try await loader.service()
        let result = try await client.createConversation(
            masterID: masterID,
            mode: mode.rawValue,
            submode: mode == .lesson ? "serbest" : nil
        )
        return DivanNewConversation(
            conversation: DivanConversation(
                id: result.id,
                masterID: masterID,
                title: result.title,
                preview: result.greeting,
                updatedAt: Date(),
                isArchived: false,
                isEnded: false,
                mode: mode
            ),
            greeting: result.greeting
        )
    }

    public func setArchived(
        _ archived: Bool,
        conversationID: Int
    ) async throws {
        let (client, _) = try await loader.service()
        try await client.setArchived(archived, id: conversationID)
    }

    public func setPinned(
        _ pinned: Bool,
        conversationID: Int
    ) async throws {
        let (client, _) = try await loader.service()
        try await client.setPinned(pinned, id: conversationID)
    }

    // MARK: - Defter yüzeyleri

    public func profileText() async throws -> String {
        let (client, _) = try await loader.service()
        return try await client.profileText()
    }

    public func updateProfileText(_ text: String) async throws {
        let (client, _) = try await loader.service()
        try await client.updateProfileText(text)
    }

    public func notebook(
        masterID: String,
        mode: DivanSessionMode
    ) async throws -> LibraryNotebook {
        let (client, _) = try await loader.service()
        return try await client.notebook(
            masterID: masterID, mode: mode.rawValue)
    }

    public func letters(masterID: String) async throws -> LibraryLetters {
        let (client, _) = try await loader.service()
        return try await client.letters(masterID: masterID)
    }

    public func dreamJournal(
        masterID: String
    ) async throws -> LibraryDreamJournal {
        let (client, _) = try await loader.service()
        return try await client.dreamJournal(masterID: masterID)
    }

    public func analyzeDreams(masterID: String) async throws -> String {
        let (client, _) = try await loader.service()
        return try await client.analyzeDreams(masterID: masterID)
    }

    public func search(_ term: String) async throws -> [LibrarySearchHit] {
        let (client, _) = try await loader.service()
        return try await client.search(term)
    }

    public func sessionSummary(
        conversationID: Int
    ) async throws -> DivanSessionSummary? {
        let (client, _) = try await loader.service()
        let record = try await client.sessionSummary(
            conversationID: conversationID)
        return record.map(Self.summary)
    }

    public func updateSessionSummary(
        conversationID: Int,
        action: DivanSummaryAction,
        content: String?
    ) async throws -> DivanSessionSummary? {
        let (client, _) = try await loader.service()
        let record = try await client.updateSessionSummary(
            conversationID: conversationID,
            action: SessionSummaryAction(rawValue: action.rawValue) ?? .update,
            content: content
        )
        return record.map(Self.summary)
    }

    private static func summary(
        _ value: SessionSummaryRecord
    ) -> DivanSessionSummary {
        DivanSessionSummary(
            conversationID: value.conversationID,
            draft: value.draft,
            approvedContent: value.approvedContent,
            isApproved: value.status == .approved,
            isRejected: value.status == .rejected
        )
    }

    public func deleteConversation(id: Int) async throws {
        let (client, _) = try await loader.service()
        try await client.deleteConversation(id: id)
    }

    public func endConversation(id: Int) async throws {
        let (client, _) = try await loader.service()
        try await client.endConversation(id: id)
    }

    public func sendMessage(
        conversationID: Int,
        text: String
    ) async -> AsyncThrowingStream<DivanChatUpdate, Error> {
        await sendMessage(
            conversationID: conversationID,
            text: text,
            schemaBinding: nil
        )
    }

    public func sendMessage(
        conversationID: Int,
        text: String,
        schemaBinding: SchemaChatBinding?
    ) async -> AsyncThrowingStream<DivanChatUpdate, Error> {
        do {
            let (client, _) = try await loader.service()
            let events = try await client.sendMessage(
                conversationID: conversationID,
                text: text,
                replyTo: nil,
                schemaBinding: schemaBinding
            )
            return AsyncThrowingStream { continuation in
                let task = Task {
                    do {
                        for try await event in events {
                            continuation.yield(Self.chatUpdate(event))
                        }
                        continuation.finish()
                    } catch {
                        continuation.finish(throwing: error)
                    }
                }
                continuation.onTermination = { _ in task.cancel() }
            }
        } catch {
            return AsyncThrowingStream { continuation in
                continuation.finish(throwing: error)
            }
        }
    }

    public func chatStatus(requestID: String) async throws -> DivanPendingChat {
        let (client, _) = try await loader.service()
        return Self.pendingChat(try await client.chatStatus(requestID: requestID))
    }

    public func schemaPath(
        conversationID: Int
    ) async throws -> SchemaPathSnapshot {
        let (client, _) = try await loader.service()
        return try await client.schemaPath(conversationID: conversationID)
    }

    public func mutateSchemaPath(
        _ mutation: SchemaPathMutation
    ) async throws -> SchemaPathMutationResponse {
        let (client, _) = try await loader.service()
        return try await client.mutateSchemaPath(mutation)
    }

    public func mutateSchemaCard(
        _ mutation: SchemaCardMutation
    ) async throws -> SchemaPathMutationResponse {
        let (client, _) = try await loader.service()
        return try await client.mutateSchemaCard(mutation)
    }

    public func mutateSchemaClinicalSync(
        _ mutation: SchemaClinicalSyncMutation
    ) async throws -> SchemaPathMutationResponse {
        let (client, _) = try await loader.service()
        return try await client.mutateSchemaClinicalSync(mutation)
    }

    public func mutateSchemaTurnAnalysis(
        _ mutation: SchemaTurnAnalysisMutation
    ) async throws -> SchemaTurnAnalysisMutationResponse {
        let (client, _) = try await loader.service()
        return try await client.mutateSchemaTurnAnalysis(mutation)
    }

    public func portraitData(url: URL) async throws -> Data {
        let (client, _) = try await loader.service()
        return try await client.portraitData(url: url)
    }

    public func settingsSummary() async throws -> DivanSettingsSummary {
        let (client, _) = try await loader.service()
        return Self.settings(try await client.settings())
    }

    public func saveSettings(_ input: DivanSettingsInput) async throws
        -> DivanSettingsSummary {
        let (client, _) = try await loader.service()
        let value = try await client.saveSettings(ProviderSettingsUpdate(
            providerID: input.provider.rawValue,
            modelID: input.modelName,
            localBaseURL: input.provider.isLocal ? input.baseURL : nil,
            apiKey: input.newAPIKey,
            clearAPIKey: false
        ))
        return Self.settings(value)
    }

    public func scanLocalModels() async throws -> [DivanLocalServer] {
        let (client, _) = try await loader.service()
        let servers = try await client.scanLocalModels()
        return servers.map { server in
            let providerID = server.provider.flatMap {
                DivanProviderID(rawValue: $0.localizedLowercase)
            }
            return DivanLocalServer(
                id: server.provider?.isEmpty == false
                    ? (server.provider ?? UUID().uuidString)
                    : "generic-\(server.baseUrl ?? "")",
                label: server.label ?? "Yerel sunucu",
                baseURL: server.baseUrl ?? "",
                models: server.models ?? [],
                provider: providerID
            )
        }
    }

    public func clearAPIKey(provider: DivanProviderID) async throws
        -> DivanSettingsSummary {
        let (client, _) = try await loader.service()
        let value = try await client.saveSettings(ProviderSettingsUpdate(
            providerID: provider.rawValue,
            clearAPIKey: true
        ))
        return Self.settings(value)
    }

    public func setGuestMode(_ active: Bool) async throws -> DivanSettingsSummary {
        let (client, _) = try await loader.service()
        return Self.settings(try await client.setGuestMode(active))
    }

    private static func master(_ value: MasterSummary) -> DivanMaster {
        let declaredModes = Set(value.supportedModes.compactMap(mode))
        let supportedModes = declaredModes.isEmpty
            ? (value.kind == .therapist
               ? Set([DivanSessionMode.therapy, .lesson])
               : Set([DivanSessionMode.lesson]))
            : declaredModes
        return DivanMaster(
            id: value.id,
            kind: value.kind == .therapist ? .therapist : .philosopher,
            name: value.name,
            school: value.school,
            subtitle: value.subtitle,
            portraitURL: value.portraitURL,
            isLiving: value.isLiving,
            supportedModes: supportedModes
        )
    }

    private static func conversation(_ value: ConversationSummary) -> DivanConversation {
        DivanConversation(
            id: value.id,
            masterID: value.masterID,
            title: value.title,
            preview: value.preview,
            updatedAt: date(value.updatedAt),
            isArchived: value.isArchived,
            isPinned: value.isPinned,
            isEnded: value.isEnded,
            mode: mode(value.mode)
        )
    }

    private static func message(_ value: MessageRecord) -> DivanMessage {
        DivanMessage(
            id: "server-\(value.id)",
            serverID: value.id,
            role: messageRole(value.role),
            content: value.content,
            createdAt: date(value.createdAt),
            isPending: ["pending", "running", "retrying"]
                .contains(value.deliveryStatus?.localizedLowercase ?? ""),
            technique: value.technique,
            schemaMetaEvents: value.metaEvents,
            schemaBindingResult: value.schemaBindingResult,
            publicID: value.publicID,
            deliveryStatus: value.deliveryStatus
        )
    }

    private static func settings(_ value: PublicSettings) -> DivanSettingsSummary {
        let providerID = provider(value.selectedProviderID)
        let selected = value.providers.first { $0.id == value.selectedProviderID }
            ?? value.providers.first
        let local = selected?.isLocal ?? providerID.isLocal
        let keyStored = selected?.keySet ?? false
        let state: DivanProviderState = local || keyStored ? .ready : .needsAttention
        let detail: String
        if local {
            detail = selected?.baseURL ?? providerID.defaultBaseURL
        } else if keyStored {
            detail = "API anahtarı güvenli biçimde kayıtlı"
        } else {
            detail = "Sohbet için API anahtarı gerekli"
        }
        // Sunucuda saklanan her sağlayıcının özeti UI'a birebir taşınır;
        // sağlayıcılar arasında geçişte model/adres/anahtar durumu buradan
        // hatırlanır.
        let snapshots = value.providers.map { summary -> DivanProviderSnapshot in
            let id = provider(summary.id)
            return DivanProviderSnapshot(
                provider: id,
                label: summary.label,
                model: summary.model,
                baseURL: summary.baseURL,
                keySet: summary.keySet,
                isLocal: summary.isLocal || id.isLocal
            )
        }
        return DivanSettingsSummary(
            provider: providerID,
            providerName: selected?.label ?? providerID.title,
            modelName: selected?.model ?? "",
            baseURL: selected?.baseURL ?? providerID.defaultBaseURL,
            connectionDetail: detail,
            state: state,
            apiKeyStored: keyStored,
            localOnly: local,
            guestMode: value.guestMode,
            providers: snapshots
        )
    }

    private static func pendingChat(_ value: ChatRequestStatus) -> DivanPendingChat {
        DivanPendingChat(
            requestID: value.requestID,
            status: value.status,
            content: value.content,
            retryable: value.retryable,
            isPending: value.pending || !value.isTerminal,
            waitingForProvider: value.waitingForProvider,
            schemaBindingResult: value.schemaBindingResult,
            schemaPromptProtocol: value.schemaPromptProtocol,
            schemaPromptIntent: value.schemaPromptIntent
        )
    }

    private static func chatUpdate(_ event: ChatEvent) -> DivanChatUpdate {
        switch event.kind {
        case .accepted:
            return .accepted(
                requestID: event.requestID,
                userMessageID: event.userMessageID
            )
        case .thinking:
            return .assistantStarted(
                messageID: event.assistantMessageID,
                createdAt: Date()
            )
        case .delta:
            return .assistantDelta(event.text)
        case .replace:
            return .assistantReplaced(event.text)
        case .waitingProvider:
            return .status("sağlayıcı bekleniyor")
        case .retrying:
            let attempt = event.attempt.map(String.init) ?? ""
            let total = event.maxAttempts.map(String.init) ?? ""
            return .status(
                attempt.isEmpty ? "yanıt yeniden deneniyor"
                    : "yanıt yeniden deneniyor · \(attempt)/\(total)"
            )
        case .error:
            return .failed(
                message: event.text.isEmpty ? DivanStrings.responseIncomplete : event.text,
                retryable: event.request?.retryable ?? true
            )
        case .done:
            let status = event.status?.localizedLowercase ?? ""
            if status.isEmpty || status == "completed" {
                return .assistantCompleted(
                    messageID: event.assistantMessageID,
                    createdAt: Date(),
                    technique: event.technique,
                    messageMeta: event.messageMeta,
                    nextCard: event.nextCard,
                    schemaPath: event.schemaPath,
                    interactionPolicy: event.interactionPolicy,
                    resumeState: event.resumeState,
                    schemaBindingResult: event.schemaBindingResult
                )
            }
            if ["queued", "running", "waiting_provider", "retrying"]
                .contains(status) {
                return .status(Self.chatStatusLabel(status))
            }
            return .failed(
                message: event.text.isEmpty
                    ? DivanStrings.responseIncomplete
                    : event.text,
                retryable: event.request?.retryable ?? true
            )
        case .status:
            return .status(event.text.isEmpty
                ? Self.chatStatusLabel(event.status ?? "")
                : event.text)
        case .unknown:
            return .status(event.text)
        }
    }

    private static func chatStatusLabel(_ raw: String) -> String {
        switch raw.localizedLowercase {
        case "queued": return "yanıt sırada"
        case "running": return "yazıyor"
        case "waiting_provider": return "sağlayıcı bekleniyor"
        case "retrying": return "yanıt yeniden deneniyor"
        case "fallback_nonstream": return "yanıt bağlantısı uyarlanıyor"
        default: return raw
        }
    }

    private static func provider(_ value: String) -> DivanProviderID {
        DivanProviderID(rawValue: value.localizedLowercase) ?? .deepSeek
    }

    private static func mode(_ value: String) -> DivanSessionMode {
        DivanSessionMode(rawValue: value.localizedLowercase) ?? .lesson
    }

    private static func messageRole(_ value: String) -> DivanMessageRole {
        DivanMessageRole(rawValue: value.localizedLowercase) ?? .system
    }

    private static func date(_ value: String) -> Date {
        guard !value.isEmpty else { return Date() }
        let fractional = ISO8601DateFormatter()
        fractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let parsed = fractional.date(from: value) { return parsed }
        let standard = ISO8601DateFormatter()
        if let parsed = standard.date(from: value) { return parsed }
        let sqlite = DateFormatter()
        sqlite.locale = Locale(identifier: "en_US_POSIX")
        sqlite.timeZone = TimeZone.current
        sqlite.dateFormat = "yyyy-MM-dd HH:mm:ss"
        if let parsed = sqlite.date(from: value) { return parsed }
        sqlite.dateFormat = "yyyy-MM-dd HH:mm"
        return sqlite.date(from: value) ?? Date()
    }
}

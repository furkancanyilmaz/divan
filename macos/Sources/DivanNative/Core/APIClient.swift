import Foundation
import CryptoKit

final class LoopbackRedirectDelegate: NSObject, URLSessionTaskDelegate,
    @unchecked Sendable {
    private let origin: URL

    init(origin: URL) {
        self.origin = origin
    }

    func urlSession(
        _ session: URLSession,
        task: URLSessionTask,
        willPerformHTTPRedirection response: HTTPURLResponse,
        newRequest request: URLRequest,
        completionHandler: @escaping (URLRequest?) -> Void
    ) {
        guard let target = request.url,
              target.scheme?.lowercased() == origin.scheme?.lowercased(),
              target.host?.lowercased() == origin.host?.lowercased(),
              target.port == origin.port else {
            completionHandler(nil)
            return
        }
        completionHandler(request)
    }
}

/// Paketlenen Python çekirdeğine karşı tek yetkili HTTP istemcisi.
///
/// Yalnız loopback üzerinde konuşur: `LoopbackRedirectDelegate` yönlendirmeleri
/// aynı kökene kilitler, böylece yanıltıcı bir `Location` başlığı isteği
/// dışarı taşıyamaz. Oturum anahtarı HttpOnly çerezle taşınır ve hiçbir hata
/// metnine, günlüğe veya URL'ye yazılmaz.
///
/// Boyut sınırları (`maximumJSONBytes`, `maximumPortraitBytes`,
/// `maximumSSELineBytes`) kötü biçimli veya kasıtlı büyük yanıtların belleği
/// tüketmesini engeller.
///
/// Bu tip `actor`'dır: eşzamanlı çağrılar sıraya girer, paylaşılan durum
/// (çerez, oturum) yarış koşulu üretmez.
///
/// Genişletmeler: klinik/ileri uçlar `AdvancedAPIClient.swift` içinde aynı
/// oturumu kullanan bir `extension` olarak durur.
public actor APIClient: DivanService {
    private static let maximumJSONBytes = 64 * 1024 * 1024
    private static let maximumPortraitBytes = 10 * 1024 * 1024
    private static let maximumImageryCardBytes = 500 * 1024
    private static let maximumSSELineBytes = 2 * 1024 * 1024
    private static let acceptedPortraitMIMETypes = Set([
        "image/jpeg", "image/png", "image/webp",
    ])

    private let baseURL: URL
    private let sessionToken: String
    private let session: URLSession
    private var sessionBootstrapped = false
    private var cachedBootstrap: BootstrapPayload?

    public init(endpoint: RuntimeEndpoint) throws {
        guard Self.isValidLoopbackBaseURL(endpoint.baseURL) else {
            throw DivanAPIError.invalidEndpoint
        }
        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = 30
        configuration.timeoutIntervalForResource = 600
        configuration.httpCookieAcceptPolicy = .always
        configuration.httpShouldSetCookies = true
        configuration.requestCachePolicy = .reloadIgnoringLocalCacheData
        configuration.urlCache = nil
        let delegate = LoopbackRedirectDelegate(origin: endpoint.baseURL)
        self.baseURL = endpoint.baseURL
        self.sessionToken = endpoint.sessionToken
        self.session = URLSession(
            configuration: configuration,
            delegate: delegate,
            delegateQueue: nil
        )
    }

    init(baseURL: URL, sessionToken: String, session: URLSession) throws {
        guard Self.isValidLoopbackBaseURL(baseURL) else {
            throw DivanAPIError.invalidEndpoint
        }
        self.baseURL = baseURL
        self.sessionToken = sessionToken
        self.session = session
    }

    deinit {
        session.invalidateAndCancel()
    }

    public func bootstrap() async throws -> BootstrapPayload {
        if let cachedBootstrap { return cachedBootstrap }
        do {
            let response: BootstrapResponse = try await get("/api/v1/bootstrap")
            let selectedProvider = mapProvider(
                response.provider,
                fallbackID: response.provider?.id ?? "deepseek"
            )
            let richerSettings = try? await settings()
            let fallbackSettings = PublicSettings(
                selectedProviderID: selectedProvider.id,
                providers: [selectedProvider],
                contextWindowTokens: response.settings.contextWindowTokens ?? 65_536,
                contextWindowOptions: response.settings.contextWindowOptions ?? [],
                privacySeen: response.settings.privacySeen ?? false,
                pinSet: response.settings.pinSet ?? false,
                retentionDays: response.settings.retentionDays ?? 0,
                simpleMode: response.settings.simpleMode ?? false,
                guestMode: response.settings.guestMode ?? false,
                credentialStorage: response.settings.credentialStorage ?? "",
                appVersion: response.appVersion
            )
            let payload = BootstrapPayload(
                apiContractVersion: response.apiContractVersion,
                appVersion: response.appVersion,
                capabilities: response.capabilities,
                therapists: response.therapists.map {
                    mapMaster($0, fallbackKind: .therapist)
                },
                philosophers: response.philosophers.map {
                    mapMaster($0, fallbackKind: .philosopher)
                },
                settings: richerSettings ?? fallbackSettings
            )
            cachedBootstrap = payload
            return payload
        } catch let error as DivanAPIError where error.statusCode == 404 {
            let therapists: [MasterPayload] = try await get("/api/therapists")
            let philosophers: [MasterPayload] = try await get("/api/philosophers")
            let legacySettings = try await settings()
            let payload = BootstrapPayload(
                apiContractVersion: 0,
                appVersion: legacySettings.appVersion,
                capabilities: [:],
                therapists: therapists.map {
                    mapMaster($0, fallbackKind: .therapist)
                },
                philosophers: philosophers.map {
                    mapMaster($0, fallbackKind: .philosopher)
                },
                settings: legacySettings
            )
            cachedBootstrap = payload
            return payload
        }
    }

    public func masters(kind: MasterKind) async throws -> [MasterSummary] {
        let payloads: [MasterPayload] = try await get(
            kind == .therapist ? "/api/therapists" : "/api/philosophers"
        )
        return payloads.map { mapMaster($0, fallbackKind: kind) }
    }

    public func portraitData(url: URL) async throws -> Data {
        guard Self.isSameOrigin(url, baseURL),
              url.user == nil,
              url.password == nil,
              url.fragment == nil,
              Self.hasAllowedPortraitQuery(url),
              Self.hasAllowedPortraitPath(url) else {
            throw DivanAPIError(
                message: "Portre adresi güvenli değil.",
                errorCode: "invalid_portrait_url"
            )
        }
        try await ensureSessionBootstrap()
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.cachePolicy = .reloadIgnoringLocalCacheData
        request.timeoutInterval = 30
        request.setValue("image/webp,image/png,image/jpeg", forHTTPHeaderField: "Accept")

        let (bytes, response) = try await session.bytes(for: request)
        guard let http = response as? HTTPURLResponse,
              Self.isSameOrigin(http.url, baseURL) else {
            throw DivanAPIError.invalidEndpoint
        }
        guard (200..<300).contains(http.statusCode) else {
            throw DivanAPIError(
                message: "Portre yüklenemedi.",
                statusCode: http.statusCode,
                errorCode: "portrait_load_failed"
            )
        }
        let mime = (http.value(forHTTPHeaderField: "Content-Type") ?? "")
            .split(separator: ";", maxSplits: 1)
            .first?
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased() ?? ""
        guard Self.acceptedPortraitMIMETypes.contains(mime) else {
            throw DivanAPIError(
                message: "Portre dosya türü desteklenmiyor.",
                errorCode: "invalid_portrait_type"
            )
        }
        if http.expectedContentLength > Int64(Self.maximumPortraitBytes) {
            throw DivanAPIError(
                message: "Portre dosyası beklenenden büyük.",
                errorCode: "portrait_too_large"
            )
        }
        var data = Data()
        if http.expectedContentLength > 0 {
            data.reserveCapacity(Int(http.expectedContentLength))
        }
        for try await byte in bytes {
            guard data.count < Self.maximumPortraitBytes else {
                throw DivanAPIError(
                    message: "Portre dosyası beklenenden büyük.",
                    errorCode: "portrait_too_large"
                )
            }
            data.append(byte)
        }
        guard !data.isEmpty else {
            throw DivanAPIError(
                message: "Portre dosyası boş.",
                errorCode: "empty_portrait"
            )
        }
        return data
    }

    /// Loads one allowlisted visual free-association card through the same
    /// authenticated loopback session used by the API.
    ///
    /// A card can never redirect or resolve outside the runtime origin. The
    /// manifest-provided byte count and digest are rechecked after transport,
    /// so malformed or substituted image data fails closed in the native UI.
    public func freudImageryCardData(
        card: FreudImageryCard
    ) async throws -> Data {
        let rawURL = card.url.trimmingCharacters(in: .whitespacesAndNewlines)
        guard rawURL == card.url,
              let url = URL(string: rawURL, relativeTo: baseURL)?.absoluteURL,
              Self.isSameOrigin(url, baseURL),
              url.user == nil,
              url.password == nil,
              url.fragment == nil,
              Self.hasAllowedImageryQuery(url),
              Self.hasAllowedImageryPath(url, expectedFile: card.file),
              card.mime == "image/webp",
              (1...Self.maximumImageryCardBytes).contains(card.bytes),
              card.sha256.count == 64 else {
            throw DivanAPIError(
                message: "Görsel kart adresi güvenli değil.",
                errorCode: "invalid_imagery_url"
            )
        }
        try await ensureSessionBootstrap()
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.cachePolicy = .reloadIgnoringLocalCacheData
        request.timeoutInterval = 30
        request.setValue("image/webp", forHTTPHeaderField: "Accept")

        let (bytes, response) = try await session.bytes(for: request)
        guard let http = response as? HTTPURLResponse,
              let responseURL = http.url,
              Self.isSameOrigin(responseURL, baseURL),
              Self.hasAllowedImageryQuery(responseURL),
              Self.hasAllowedImageryPath(responseURL, expectedFile: card.file) else {
            throw DivanAPIError.invalidEndpoint
        }
        guard (200..<300).contains(http.statusCode) else {
            throw DivanAPIError(
                message: "Görsel kart yüklenemedi.",
                statusCode: http.statusCode,
                errorCode: "imagery_load_failed"
            )
        }
        let mime = (http.value(forHTTPHeaderField: "Content-Type") ?? "")
            .split(separator: ";", maxSplits: 1)
            .first?
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased() ?? ""
        guard mime == "image/webp" else {
            throw DivanAPIError(
                message: "Görsel kart dosya türü desteklenmiyor.",
                errorCode: "invalid_imagery_type"
            )
        }
        guard http.expectedContentLength <= Int64(Self.maximumImageryCardBytes),
              http.expectedContentLength <= 0
                || http.expectedContentLength == Int64(card.bytes) else {
            throw DivanAPIError(
                message: "Görsel kart beklenmeyen boyutta.",
                errorCode: "imagery_size_mismatch"
            )
        }
        var data = Data()
        data.reserveCapacity(card.bytes)
        for try await byte in bytes {
            guard data.count < Self.maximumImageryCardBytes else {
                throw DivanAPIError(
                    message: "Görsel kart beklenenden büyük.",
                    errorCode: "imagery_too_large"
                )
            }
            data.append(byte)
        }
        guard data.count == card.bytes,
              Self.isBoundedWebP(data),
              SHA256.hash(data: data).map({ String(format: "%02x", $0) })
                .joined() == card.sha256 else {
            throw DivanAPIError(
                message: "Görsel kart bütünlüğü doğrulanamadı.",
                errorCode: "imagery_integrity_failed"
            )
        }
        return data
    }

    public func conversations(archived: Bool) async throws -> [ConversationSummary] {
        let payloads: [ConversationPayload] = try await get(
            "/api/conversations",
            query: [URLQueryItem(name: "archived", value: archived ? "1" : "0")]
        )
        return payloads.map(mapConversationSummary)
    }

    public func conversation(
        id: Int,
        limit: Int = 80,
        beforeID: Int? = nil
    ) async throws -> ConversationPage {
        guard id > 0 else {
            throw DivanAPIError(message: "Geçersiz sohbet.", errorCode: "invalid_conversation")
        }
        guard (1...200).contains(limit) else {
            throw DivanAPIError(
                message: "Mesaj sayısı 1–200 arasında olmalı.",
                errorCode: "invalid_page_limit"
            )
        }
        var query = [
            URLQueryItem(name: "id", value: String(id)),
            URLQueryItem(name: "limit", value: String(limit)),
        ]
        if let beforeID {
            guard beforeID > 0 else {
                throw DivanAPIError(
                    message: "Geçersiz eski mesaj sınırı.",
                    errorCode: "invalid_before_id"
                )
            }
            query.append(URLQueryItem(name: "before_id", value: String(beforeID)))
        }
        let payload: ConversationPageResponse = try await get(
            "/api/conversation",
            query: query
        )
        return ConversationPage(
            conversation: mapConversationDetail(payload.conversation),
            messages: payload.messages.map(mapMessage),
            messageCount: payload.messageCount ?? payload.messages.count,
            loadedMessageCount: payload.loadedMessageCount ?? payload.messages.count,
            hasMoreMessages: payload.hasMoreMessages ?? false,
            oldestMessageID: payload.oldestMessageId,
            latestChatRequest: payload.chatRequest.flatMap(mapChatRequest)
        )
    }

    public func createConversation(
        masterID: String,
        mode: String,
        submode: String? = nil
    ) async throws -> NewConversation {
        let cleanMaster = masterID.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !cleanMaster.isEmpty, cleanMaster.count <= 100 else {
            throw DivanAPIError(message: "Geçersiz usta.", errorCode: "invalid_master")
        }
        guard mode == "terapi" || mode == "ders" else {
            throw DivanAPIError(message: "Geçersiz görüşme türü.", errorCode: "invalid_mode")
        }
        var body: [String: JSONValue] = [
            "therapist": .string(cleanMaster),
            "mode": .string(mode),
        ]
        if let submode, !submode.isEmpty { body["submode"] = .string(submode) }
        let response: NewConversationResponse = try await post("/api/new", body: body)
        return NewConversation(
            id: response.id,
            title: response.title ?? (mode == "terapi" ? "Yeni seans" : "Yeni ders"),
            greeting: response.greeting ?? ""
        )
    }

    public func setArchived(_ archived: Bool, id: Int) async throws {
        let _: OKResponse = try await post(
            "/api/archive",
            body: ["id": .number(Double(id)), "archived": .bool(archived)]
        )
    }

    public func setPinned(_ pinned: Bool, id: Int) async throws {
        let _: OKResponse = try await post(
            "/api/pin",
            body: ["id": .number(Double(id)), "pinned": .bool(pinned)]
        )
    }

    public func deleteConversation(id: Int) async throws {
        let _: OKResponse = try await post(
            "/api/delete",
            body: ["id": .number(Double(id))]
        )
    }

    public func endConversation(id: Int) async throws {
        guard id > 0 else {
            throw DivanAPIError(message: "Geçersiz sohbet.", errorCode: "invalid_conversation")
        }
        let _: EndConversationResponse = try await post(
            "/api/end",
            body: ["conv_id": .number(Double(id))]
        )
    }

    public func settings() async throws -> PublicSettings {
        let response: SettingsResponse = try await get("/api/settings")
        let selected = response.provider ?? response.llmProvider ?? "deepseek"
        let providers = (response.providers ?? [:])
            .map { mapProvider($0.value, fallbackID: $0.key) }
            .sorted { $0.label.localizedCaseInsensitiveCompare($1.label) == .orderedAscending }
        return PublicSettings(
            selectedProviderID: selected,
            providers: providers,
            contextWindowTokens: response.contextWindowTokens ?? 65_536,
            contextWindowOptions: response.contextWindowOptions ?? [],
            privacySeen: response.privacySeen ?? false,
            pinSet: response.pinSet ?? false,
            retentionDays: response.retentionDays ?? 0,
            simpleMode: response.simpleMode ?? false,
            guestMode: response.guestMode ?? false,
            credentialStorage: response.credentialStorage ?? "",
            appVersion: response.version ?? ""
        )
    }

    public func setGuestMode(_ active: Bool) async throws -> PublicSettings {
        let response: GuestModeResponse = try await post(
            "/api/guest-mode",
            body: ["active": .bool(active)]
        )
        guard response.ok == true, response.guestMode == active else {
            throw DivanAPIError(
                message: "Misafir modu değiştirilemedi.",
                errorCode: "guest_mode_failed"
            )
        }
        cachedBootstrap = nil
        return try await settings()
    }

    public func saveSettings(_ update: ProviderSettingsUpdate) async throws -> PublicSettings {
        let provider = update.providerID?.trimmingCharacters(in: .whitespacesAndNewlines)
        let allowedProviders = Set([
            "deepseek", "openai", "anthropic", "gemini", "lmstudio", "ollama",
        ])
        if let provider, !allowedProviders.contains(provider) {
            throw DivanAPIError(
                message: "Model sağlayıcısı geçersiz.",
                errorCode: "invalid_provider"
            )
        }
        var body: [String: JSONValue] = [:]
        if let provider { body["provider"] = .string(provider) }
        if let model = update.modelID?.trimmingCharacters(in: .whitespacesAndNewlines),
           !model.isEmpty {
            guard let provider else {
                throw DivanAPIError(
                    message: "Modeli kaydetmek için sağlayıcı gerekli.",
                    errorCode: "provider_required"
                )
            }
            body["\(provider)_model"] = .string(model)
        }
        if let baseURL = update.localBaseURL?.trimmingCharacters(in: .whitespacesAndNewlines),
           let provider,
           ["lmstudio", "ollama"].contains(provider) {
            body["\(provider)_base_url"] = .string(baseURL)
        }
        if let apiKey = update.apiKey, !apiKey.isEmpty {
            guard let provider else {
                throw DivanAPIError(
                    message: "API anahtarını kaydetmek için sağlayıcı gerekli.",
                    errorCode: "provider_required"
                )
            }
            guard apiKey.count <= 2_000,
                  !apiKey.unicodeScalars.contains(where: {
                      CharacterSet.controlCharacters.contains($0)
                  }) else {
                throw DivanAPIError(
                    message: "API anahtarı geçersiz.",
                    errorCode: "invalid_api_key"
                )
            }
            body["\(provider)_api_key"] = .string(apiKey)
        }
        if update.clearAPIKey {
            guard let provider else {
                throw DivanAPIError(
                    message: "Silinecek sağlayıcı belirtilmedi.",
                    errorCode: "provider_required"
                )
            }
            body["clear_\(provider)_api_key"] = .bool(true)
        }
        if let tokens = update.contextWindowTokens {
            body["context_window_tokens"] = .number(Double(tokens))
        }
        let _: OKResponse = try await post("/api/settings", body: body)
        cachedBootstrap = nil
        return try await settings()
    }

    func scanLocalModels() async throws -> [LocalServerPayload] {
        let response: LocalModelsResponse = try await post(
            "/api/provider/models",
            body: ["scan_all": .bool(true)],
            timeout: 20
        )
        return response.servers ?? []
    }

    public func sendMessage(
        conversationID: Int,
        text: String,
        replyTo: Int? = nil
    ) async throws -> AsyncThrowingStream<ChatEvent, Error> {
        try await sendMessage(
            conversationID: conversationID,
            text: text,
            replyTo: replyTo,
            schemaBinding: nil
        )
    }

    public func sendMessage(
        conversationID: Int,
        text: String,
        replyTo: Int? = nil,
        schemaBinding: SchemaChatBinding?
    ) async throws -> AsyncThrowingStream<ChatEvent, Error> {
        let cleanText = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard conversationID > 0, !cleanText.isEmpty else {
            throw DivanAPIError(message: "Mesaj boş olamaz.", errorCode: "empty_message")
        }
        try await ensureSessionBootstrap()
        let requestID = "native-" + Self.randomRequestSuffix()
        var body: [String: JSONValue] = [
            "conv_id": .number(Double(conversationID)),
            "message": .string(cleanText),
            "request_id": .string(requestID),
        ]
        if let replyTo { body["reply_to"] = .number(Double(replyTo)) }
        if let binding = schemaBinding {
            guard binding.pathId > 0, !binding.stepId.isEmpty,
                  binding.expectedRevision >= 0,
                  SchemaPathCheckpoint.isPublicID(binding.pathPublicId),
                  SchemaPathCheckpoint.isPublicID(
                    binding.checkpointPublicId
                  ),
                  binding.expectedCheckpointSeq >= 0,
                  binding.sourceUserMessageId > 0,
                  SchemaPathCheckpoint.isPublicID(
                    binding.sourceUserMessagePublicId
                  ),
                  binding.sourceAssistantMessageId > 0,
                  SchemaPathCheckpoint.isPublicID(
                    binding.sourceAssistantMessagePublicId
                  ) else {
                throw DivanAPIError(
                    message: "Şema çalışma adımı güncel değil.",
                    errorCode: "schema_step_mismatch"
                )
            }
            let techniqueIdentity = (
                binding.techniqueLinkId,
                binding.techniqueLinkPublicId,
                binding.expectedTechniqueRevision
            )
            switch binding.`protocol` {
            case "schema_path_chat_v4":
                guard binding.promptRequestId == nil,
                      binding.promptAssistantMessageId == nil,
                      binding.promptAssistantMessagePublicId == nil else {
                    throw DivanAPIError(
                        message: "Şema çalışma adımı güncel değil.",
                        errorCode: "schema_step_mismatch"
                    )
                }
                switch techniqueIdentity {
                case (nil, nil, nil):
                    break
                case let (linkID?, publicID?, revision?)
                    where linkID > 0
                        && SchemaPathCheckpoint.isPublicID(publicID)
                        && revision >= 0:
                    break
                default:
                    throw DivanAPIError(
                        message: "Şema teknik bağlantısı güncel değil.",
                        errorCode: "schema_step_mismatch"
                    )
                }
            case "schema_path_chat_v5":
                let importControl = binding.syncImportControl == true
                let deliveredPrompt = binding.syncImportControl == nil
                    && binding.promptRequestId.map(
                        SchemaPromptDelivery.isRequestID
                    ) == true
                    && binding.promptAssistantMessageId.map { $0 > 0 }
                        == true
                    && binding.promptAssistantMessageId
                        == binding.sourceAssistantMessageId
                    && binding.promptAssistantMessagePublicId.map(
                        SchemaPathCheckpoint.isPublicID
                    ) == true
                    && binding.promptAssistantMessagePublicId
                        == binding.sourceAssistantMessagePublicId
                let importedBoundary = importControl
                    && binding.promptRequestId == nil
                    && binding.promptAssistantMessageId == nil
                    && binding.promptAssistantMessagePublicId == nil
                guard (deliveredPrompt || importedBoundary),
                      techniqueIdentity.0 == nil,
                      techniqueIdentity.1 == nil,
                      techniqueIdentity.2 == nil else {
                    throw DivanAPIError(
                        message: "Şema sorusu henüz konuşmaya ulaşmadı.",
                        errorCode: "schema_prompt_delivery_incomplete"
                    )
                }
            default:
                throw DivanAPIError(
                    message: "Şema çalışma adımı güncel değil.",
                    errorCode: "schema_step_mismatch"
                )
            }
            var value: [String: JSONValue] = [
                "protocol": .string(binding.`protocol`),
                "path_id": .number(Double(binding.pathId)),
                "path_public_id": .string(binding.pathPublicId),
                "step_id": .string(binding.stepId),
                "expected_revision": .number(Double(binding.expectedRevision)),
                "checkpoint_public_id": .string(
                    binding.checkpointPublicId
                ),
                "expected_checkpoint_seq": .number(
                    Double(binding.expectedCheckpointSeq)
                ),
                "source_user_message_id": .number(
                    Double(binding.sourceUserMessageId)
                ),
                "source_user_message_public_id": .string(
                    binding.sourceUserMessagePublicId
                ),
                "source_assistant_message_id": .number(
                    Double(binding.sourceAssistantMessageId)
                ),
                "source_assistant_message_public_id": .string(
                    binding.sourceAssistantMessagePublicId
                ),
            ]
            if binding.syncImportControl == true {
                value["sync_import_control"] = .bool(true)
                // Explicit nulls distinguish this receiver-only control
                // boundary from a malformed delivered-prompt binding.
                value["prompt_request_id"] = .null
                value["prompt_assistant_message_id"] = .null
                value["prompt_assistant_message_public_id"] = .null
            }
            if let requestID = binding.promptRequestId {
                value["prompt_request_id"] = .string(requestID)
            }
            if let messageID = binding.promptAssistantMessageId {
                value["prompt_assistant_message_id"] = .number(
                    Double(messageID)
                )
            }
            if let publicID = binding.promptAssistantMessagePublicId {
                value["prompt_assistant_message_public_id"] = .string(
                    publicID
                )
            }
            if let linkID = binding.techniqueLinkId {
                value["technique_link_id"] = .number(Double(linkID))
            }
            if let publicID = binding.techniqueLinkPublicId,
               !publicID.isEmpty {
                value["technique_link_public_id"] = .string(publicID)
            }
            if let revision = binding.expectedTechniqueRevision {
                value["expected_technique_revision"] = .number(Double(revision))
            }
            body["schema_binding"] = .object(value)
        }
        var request = try makeRequest(path: "/api/chat", method: "POST", body: body)
        request.setValue(
            "text/event-stream, application/json;q=0.9",
            forHTTPHeaderField: "Accept"
        )

        return AsyncThrowingStream { continuation in
            let streamTask = Task {
                await self.performChatStream(
                    request: request,
                    requestID: requestID,
                    conversationID: conversationID,
                    continuation: continuation
                )
            }
            continuation.onTermination = { @Sendable _ in
                streamTask.cancel()
            }
        }
    }

    public func chatStatus(requestID: String) async throws -> ChatRequestStatus {
        let envelope: ChatEnvelope = try await get(
            "/api/chat-status",
            query: [URLQueryItem(name: "request_id", value: requestID)]
        )
        guard let chat = envelope.chat, let result = mapChatRequest(chat) else {
            throw DivanAPIError(
                message: "Mesaj isteği bulunamadı.",
                errorCode: "chat_not_found"
            )
        }
        return result
    }

    public func cancelChat(requestID: String) async throws -> ChatRequestStatus {
        let response: ChatMutationResponse = try await post(
            "/api/chat/cancel",
            body: ["request_id": .string(requestID)]
        )
        guard let chat = response.chat, let result = mapChatRequest(chat) else {
            throw DivanAPIError(message: "Mesaj durdurulamadı.", errorCode: "cancel_failed")
        }
        return result
    }

    public func retryChat(requestID: String) async throws -> ChatRequestStatus {
        let response: ChatMutationResponse = try await post(
            "/api/chat/retry",
            body: ["request_id": .string(requestID)]
        )
        guard let chat = response.chat, let result = mapChatRequest(chat) else {
            throw DivanAPIError(message: "Mesaj yeniden denenemedi.", errorCode: "retry_failed")
        }
        return result
    }

    private func performChatStream(
        request: URLRequest,
        requestID: String,
        conversationID: Int,
        continuation: AsyncThrowingStream<ChatEvent, Error>.Continuation
    ) async {
        var receivedDone = false
        var receivedFailure = false
        var lastContent = ""
        do {
            let (bytes, response) = try await session.bytes(for: request)
            guard let http = response as? HTTPURLResponse else {
                throw DivanAPIError(message: "Yerel sunucu geçersiz yanıt verdi.")
            }
            guard (200..<300).contains(http.statusCode) else {
                var data = Data()
                for try await byte in bytes {
                    if data.count >= Self.maximumJSONBytes { break }
                    data.append(byte)
                }
                throw Self.error(from: data, statusCode: http.statusCode)
            }
            let contentType = (http.value(forHTTPHeaderField: "Content-Type") ?? "")
                .lowercased()
            if contentType.contains("application/json") {
                var data = Data()
                for try await byte in bytes {
                    guard data.count < Self.maximumJSONBytes else {
                        throw DivanAPIError(message: "Sunucu yanıtı beklenenden büyük.")
                    }
                    data.append(byte)
                }
                let duplicate = try Self.decoder().decode(DuplicateChatResponse.self, from: data)
                let resolvedRequestID = duplicate.requestId ?? requestID
                let duplicateStatus = Self.normalizedChatStatus(duplicate.status)
                continuation.yield(ChatEvent(
                    kind: .accepted,
                    requestID: resolvedRequestID,
                    status: duplicate.status,
                    userMessageID: duplicate.userMessageId,
                    assistantMessageID: duplicate.assistantMessageId
                ))
                if let message = duplicate.message, !message.isEmpty {
                    lastContent = message
                    continuation.yield(ChatEvent(
                        kind: .replace,
                        text: message,
                        requestID: resolvedRequestID,
                        status: duplicate.status,
                        userMessageID: duplicate.userMessageId,
                        assistantMessageID: duplicate.assistantMessageId
                    ))
                }
                if Self.isActiveChatStatus(duplicateStatus) {
                    await recoverDurableChat(
                        requestID: resolvedRequestID,
                        conversationID: conversationID,
                        lastContent: lastContent,
                        continuation: continuation
                    )
                    return
                }
                if Self.isSuccessfulChatStatus(duplicateStatus) {
                    continuation.yield(ChatEvent(
                        kind: .done,
                        requestID: resolvedRequestID,
                        status: duplicate.status,
                        userMessageID: duplicate.userMessageId,
                        assistantMessageID: duplicate.assistantMessageId
                    ))
                    continuation.finish()
                    return
                }
                continuation.yield(ChatEvent(
                    kind: .error,
                    text: duplicate.message ?? DivanStrings.responseIncomplete,
                    requestID: resolvedRequestID,
                    status: duplicate.status,
                    userMessageID: duplicate.userMessageId,
                    assistantMessageID: duplicate.assistantMessageId
                ))
                continuation.finish()
                return
            }

            var parser = SSEParser()

            func deliver(_ event: ChatEvent) {
                if event.kind == .replace { lastContent = event.text }
                if event.kind == .delta { lastContent += event.text }
                if event.kind == .error { receivedFailure = true }
                if event.kind == .done {
                    let status = Self.normalizedChatStatus(event.status)
                    if Self.isActiveChatStatus(status) {
                        continuation.yield(ChatEvent(
                            kind: .status,
                            requestID: event.requestID ?? requestID,
                            status: event.status
                        ))
                    } else if Self.isSuccessfulChatStatus(status) {
                        continuation.yield(event)
                        receivedDone = true
                    } else {
                        if !receivedFailure {
                            continuation.yield(ChatEvent(
                                kind: .error,
                                text: DivanStrings.responseIncomplete,
                                requestID: event.requestID ?? requestID,
                                status: event.status,
                                assistantMessageID: event.assistantMessageID
                            ))
                        }
                        receivedDone = true
                    }
                } else {
                    continuation.yield(event)
                }
            }

            func consume(_ line: String) {
                guard let data = parser.consume(line: line),
                      let event = try? Self.decodeChatEvent(data) else { return }
                deliver(event)
            }

            // `AsyncBytes.lines` does not preserve empty SSE separator lines
            // consistently on every supported macOS Foundation build.  If a
            // separator disappears, all JSON events are concatenated and the
            // UI sees only the later durable polling result.  Frame the stream
            // from raw bytes so the first safe delta is visible immediately.
            var lineBytes = Data()
            for try await byte in bytes {
                try Task.checkCancellation()
                if byte == 0x0A {
                    if lineBytes.last == 0x0D { lineBytes.removeLast() }
                    guard let line = String(data: lineBytes, encoding: .utf8) else {
                        throw DivanAPIError(
                            message: "Canlı yanıt geçersiz metin içeriyor.",
                            errorCode: "invalid_stream_encoding"
                        )
                    }
                    lineBytes.removeAll(keepingCapacity: true)
                    consume(line)
                } else {
                    guard lineBytes.count < Self.maximumSSELineBytes else {
                        throw DivanAPIError(
                            message: "Canlı yanıt satırı beklenenden büyük.",
                            errorCode: "stream_line_too_large"
                        )
                    }
                    lineBytes.append(byte)
                }
            }
            if !lineBytes.isEmpty {
                if lineBytes.last == 0x0D { lineBytes.removeLast() }
                guard let line = String(data: lineBytes, encoding: .utf8) else {
                    throw DivanAPIError(
                        message: "Canlı yanıt geçersiz metin içeriyor.",
                        errorCode: "invalid_stream_encoding"
                    )
                }
                consume(line)
            }
            if let data = parser.finish(),
               let event = try? Self.decodeChatEvent(data) {
                deliver(event)
            }
            if receivedDone {
                continuation.finish()
                return
            }
        } catch is CancellationError {
            continuation.finish()
            return
        } catch {
            // A dropped UI stream does not mean the durable server request
            // stopped. Resolve it through the status endpoint before failing.
        }

        await recoverDurableChat(
            requestID: requestID,
            conversationID: conversationID,
            lastContent: lastContent,
            continuation: continuation
        )
    }

    private func recoverDurableChat(
        requestID: String,
        conversationID: Int,
        lastContent: String,
        continuation: AsyncThrowingStream<ChatEvent, Error>.Continuation
    ) async {
        var previousContent = lastContent
        var missingAttempts = 0
        var transientAttempts = 0
        var nextDelay = Duration.milliseconds(350)
        do {
            while !Task.isCancelled {
                do {
                    let current = try await chatStatus(requestID: requestID)
                    missingAttempts = 0
                    transientAttempts = 0
                    nextDelay = .milliseconds(350)
                    if current.content != previousContent, !current.content.isEmpty {
                        previousContent = current.content
                        continuation.yield(ChatEvent(
                            kind: .replace,
                            text: current.content,
                            requestID: requestID,
                            status: current.status,
                            userMessageID: current.userMessageID,
                            assistantMessageID: current.assistantMessageID,
                            request: current
                        ))
                    } else {
                        continuation.yield(ChatEvent(
                            kind: .status,
                            requestID: requestID,
                            status: current.status,
                            request: current
                        ))
                    }
                    if current.isTerminal {
                        continuation.yield(ChatEvent(
                            kind: current.status == "completed" ? .done : .error,
                            text: current.status == "completed" ? "" : current.content,
                            requestID: requestID,
                            status: current.status,
                            assistantMessageID: current.assistantMessageID,
                            code: current.errorCode,
                            request: current
                        ))
                        continuation.finish()
                        return
                    }
                } catch let error as DivanAPIError where error.statusCode == 404 {
                    missingAttempts += 1
                    if missingAttempts >= 6 { throw error }
                    nextDelay = .milliseconds(min(1_200, 200 * missingAttempts))
                } catch {
                    guard Self.isTransientChatRecoveryError(error) else {
                        throw error
                    }
                    transientAttempts += 1
                    guard transientAttempts < 8 else { throw error }
                    nextDelay = .milliseconds(min(
                        2_000,
                        250 * (1 << min(transientAttempts - 1, 3))
                    ))
                }
                try await Task.sleep(for: nextDelay)
            }
            continuation.finish()
        } catch is CancellationError {
            continuation.finish()
        } catch {
            continuation.finish(throwing: error)
        }
    }

    private static func normalizedChatStatus(_ status: String?) -> String {
        status?.trimmingCharacters(in: .whitespacesAndNewlines)
            .localizedLowercase ?? ""
    }

    private static func isActiveChatStatus(_ status: String) -> Bool {
        ["queued", "running", "waiting_provider", "retrying"].contains(status)
    }

    private static func isSuccessfulChatStatus(_ status: String) -> Bool {
        // Older compatible cores emitted a bare `done` without a status.
        status.isEmpty || status == "completed"
    }

    private static func isTransientChatRecoveryError(_ error: Error) -> Bool {
        if let api = error as? DivanAPIError {
            if api.retryable { return true }
            guard let status = api.statusCode else { return false }
            return [408, 425, 429].contains(status) || (500...599).contains(status)
        }
        if let transport = error as? URLError {
            return [
                .timedOut, .cannotFindHost, .cannotConnectToHost,
                .networkConnectionLost, .dnsLookupFailed, .notConnectedToInternet,
                .resourceUnavailable,
            ].contains(transport.code)
        }
        return false
    }

    func get<Response: Decodable>(
        _ path: String,
        query: [URLQueryItem] = []
    ) async throws -> Response {
        try await ensureSessionBootstrap()
        let request = try makeRequest(path: path, method: "GET", query: query)
        return try await dataResponse(request)
    }

    func post<Response: Decodable>(
        _ path: String,
        body: [String: JSONValue],
        timeout: TimeInterval? = nil
    ) async throws -> Response {
        try await ensureSessionBootstrap()
        var request = try makeRequest(path: path, method: "POST", body: body)
        if let timeout {
            request.timeoutInterval = max(1, min(timeout, 600))
        }
        return try await dataResponse(request)
    }

    private func ensureSessionBootstrap() async throws {
        if sessionBootstrapped { return }
        var components = URLComponents(
            url: baseURL.appendingPathComponent("/"),
            resolvingAgainstBaseURL: false
        )
        components?.queryItems = [
            URLQueryItem(name: "_divan_session", value: sessionToken),
        ]
        guard let url = components?.url else { throw DivanAPIError.invalidEndpoint }
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.cachePolicy = .reloadIgnoringLocalCacheData
        request.timeoutInterval = 15
        let (_, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse,
              (200..<400).contains(http.statusCode),
              Self.isSameOrigin(http.url, baseURL) else {
            throw DivanAPIError(
                message: "Yerel Divan oturumu doğrulanamadı.",
                errorCode: "session_bootstrap_failed"
            )
        }
        sessionBootstrapped = true
    }

    private func makeRequest(
        path: String,
        method: String,
        query: [URLQueryItem] = [],
        body: [String: JSONValue]? = nil
    ) throws -> URLRequest {
        guard path.hasPrefix("/api/") else { throw DivanAPIError.invalidEndpoint }
        var components = URLComponents(url: baseURL, resolvingAgainstBaseURL: false)
        components?.path = path
        components?.queryItems = query.isEmpty ? nil : query
        guard let url = components?.url,
              Self.isSameOrigin(url, baseURL) else {
            throw DivanAPIError.invalidEndpoint
        }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.cachePolicy = .reloadIgnoringLocalCacheData
        request.timeoutInterval = method == "POST" && path == "/api/chat" ? 600 : 30
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if let body {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONEncoder().encode(body)
        }
        return request
    }

    private func dataResponse<Response: Decodable>(
        _ request: URLRequest
    ) async throws -> Response {
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse,
              Self.isSameOrigin(http.url, baseURL) else {
            throw DivanAPIError.invalidEndpoint
        }
        guard data.count <= Self.maximumJSONBytes else {
            throw DivanAPIError(message: "Sunucu yanıtı beklenenden büyük.")
        }
        guard (200..<300).contains(http.statusCode) else {
            throw Self.error(from: data, statusCode: http.statusCode)
        }
        do {
            return try Self.decoder().decode(Response.self, from: data)
        } catch {
            throw DivanAPIError(
                message: "Yerel sunucunun yanıtı okunamadı.",
                statusCode: http.statusCode,
                errorCode: "decode_failed"
            )
        }
    }

    private func mapMaster(
        _ payload: MasterPayload,
        fallbackKind: MasterKind
    ) -> MasterSummary {
        let kind = MasterKind(rawValue: payload.kind ?? "") ?? fallbackKind
        let subtitle = payload.subtitle ?? payload.sub ?? ""
        return MasterSummary(
            id: payload.id,
            name: payload.name,
            school: payload.school ?? "",
            subtitle: subtitle,
            portraitURL: portraitURL(payload.portrait),
            kind: kind,
            isLiving: payload.isLiving ?? Self.inferLiving(from: subtitle),
            supportedModes: payload.modes ?? (kind == .therapist ? ["terapi", "ders"] : ["ders"])
        )
    }

    private func portraitURL(_ portrait: PortraitPayload?) -> URL? {
        if let raw = portrait?.url, raw.hasPrefix("/assets/portraits/") {
            return URL(string: raw, relativeTo: baseURL)?.absoluteURL
        }
        guard let file = portrait?.file,
              !file.isEmpty,
              !file.contains("/"),
              !file.contains("..") else { return nil }
        return baseURL
            .appendingPathComponent("assets", isDirectory: true)
            .appendingPathComponent("portraits", isDirectory: true)
            .appendingPathComponent(file)
    }

    private func mapProvider(
        _ payload: ProviderPayload?,
        fallbackID: String
    ) -> ProviderSummary {
        ProviderSummary(
            id: payload?.id ?? fallbackID,
            label: payload?.label ?? fallbackID,
            model: payload?.model ?? "",
            keySet: payload?.keySet ?? false,
            isLocal: payload?.local ?? false,
            baseURL: payload?.baseUrl
        )
    }

    private func mapConversationSummary(_ payload: ConversationPayload) -> ConversationSummary {
        ConversationSummary(
            id: payload.id,
            masterID: payload.therapist ?? "freud",
            title: payload.title ?? "Görüşme",
            preview: payload.preview ?? "",
            updatedAt: payload.updated ?? "",
            createdAt: payload.created ?? "",
            isArchived: payload.archivedAt != nil,
            isPinned: payload.pinnedAt != nil,
            isEnded: (payload.ended ?? 0) != 0,
            mode: payload.mode ?? "terapi",
            submode: payload.submode,
            messageCount: payload.n ?? 0,
            chatStatus: payload.chatStatus
        )
    }

    private func mapConversationDetail(_ payload: ConversationPayload) -> ConversationDetail {
        ConversationDetail(
            id: payload.id,
            masterID: payload.therapist ?? "freud",
            title: payload.title ?? "Görüşme",
            mode: payload.mode ?? "terapi",
            submode: payload.submode,
            createdAt: payload.created ?? "",
            updatedAt: payload.updated ?? "",
            isEnded: (payload.ended ?? 0) != 0,
            isArchived: payload.archivedAt != nil
        )
    }

    private func mapMessage(_ payload: MessagePayload) -> MessageRecord {
        let technique = payload.technique.flatMap { name -> MessageTechniqueMetadata? in
            let clean = name.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !clean.isEmpty else { return nil }
            return MessageTechniqueMetadata(
                name: clean,
                phase: payload.techniquePhase,
                rationale: payload.techniqueRationale
            )
        }
        return MessageRecord(
            id: payload.id,
            publicID: payload.publicId,
            role: payload.role ?? "assistant",
            content: payload.content ?? "",
            createdAt: payload.created ?? "",
            replyTo: payload.replyTo,
            deliveryStatus: payload.deliveryStatus,
            technique: technique,
            metaEvents: payload.metaEvents ?? [],
            schemaBindingResult: payload.schemaBindingResult
        )
    }

    private func mapChatRequest(_ payload: ChatRequestPayload) -> ChatRequestStatus? {
        guard let requestID = payload.requestId, !requestID.isEmpty else { return nil }
        return ChatRequestStatus(
            requestID: requestID,
            conversationID: payload.convId ?? 0,
            status: payload.status ?? "unknown",
            retryable: payload.retryable ?? false,
            userMessageID: payload.userMessageId,
            assistantMessageID: payload.assistantMessageId,
            replyTo: payload.replyTo,
            provider: payload.provider ?? "",
            model: payload.model ?? "",
            content: payload.content ?? "",
            errorCode: payload.errorCode ?? "",
            schemaPromptProtocol: payload.schemaPromptProtocol ?? "",
            schemaPromptIntent: payload.schemaPromptIntent ?? "",
            attempt: payload.attempt ?? 0,
            maxAttempts: payload.maxAttempts ?? 1,
            automaticRetry: payload.automaticRetry ?? false,
            pending: payload.pending ?? false,
            waitingForProvider: payload.waitingForProvider ?? false,
            nextRetryAt: payload.nextRetryAt,
            schemaBindingResult: payload.schemaBindingResult
        )
    }

    private static func decodeChatEvent(_ data: Data) throws -> ChatEvent {
        let payload = try decoder().decode(ChatEventPayload.self, from: data)
        let kind = ChatEvent.Kind(rawValue: payload.type ?? "") ?? .unknown
        return ChatEvent(
            kind: kind,
            text: payload.text ?? "",
            requestID: payload.requestId,
            status: payload.status,
            userMessageID: payload.userMessageId,
            assistantMessageID: payload.assistantMessageId,
            code: payload.code,
            attempt: payload.attempt,
            maxAttempts: payload.maxAttempts,
            technique: payload.technique.flatMap { name in
                let clean = name.trimmingCharacters(in: .whitespacesAndNewlines)
                guard !clean.isEmpty else { return nil }
                return MessageTechniqueMetadata(
                    name: clean,
                    phase: payload.techniquePhase,
                    rationale: payload.techniqueRationale
                )
            },
            messageMeta: payload.messageMeta ?? [],
            nextCard: payload.nextCard,
            schemaPath: payload.schemaPath,
            interactionPolicy: payload.interactionPolicy,
            resumeState: payload.resumeState,
            schemaBindingResult: payload.schemaBindingResult
        )
    }

    private static func decoder() -> JSONDecoder {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return decoder
    }

    private static func error(from data: Data, statusCode: Int) -> DivanAPIError {
        let envelope = try? decoder().decode(ErrorEnvelope.self, from: data)
        return DivanAPIError(
            message: envelope?.error ?? "Yerel sunucu isteği tamamlayamadı.",
            statusCode: statusCode,
            errorCode: envelope?.errorCode ?? envelope?.code,
            errorID: envelope?.errorId,
            retryable: envelope?.retryable ?? (statusCode == 503)
        )
    }

    private static func randomRequestSuffix() -> String {
        UUID().uuidString.replacingOccurrences(of: "-", with: "")
            + UUID().uuidString.replacingOccurrences(of: "-", with: "")
    }

    private static func inferLiving(from subtitle: String) -> Bool {
        let folded = subtitle.folding(
            options: [.diacriticInsensitive, .caseInsensitive],
            locale: Locale(identifier: "tr_TR")
        )
        if folded.contains("mo ") || folded.contains("m.o") { return false }
        let pattern = #"[–-]\s*(\d{3,4})(?:\D|$)"#
        guard let expression = try? NSRegularExpression(pattern: pattern),
              let match = expression.firstMatch(
                  in: subtitle,
                  range: NSRange(subtitle.startIndex..., in: subtitle)
              ),
              let range = Range(match.range(at: 1), in: subtitle),
              let year = Int(subtitle[range]) else {
            return true
        }
        return year >= Calendar.current.component(.year, from: Date())
    }

    private static func isValidLoopbackBaseURL(_ url: URL) -> Bool {
        guard url.scheme?.lowercased() == "http",
              let host = url.host?.lowercased(),
              ["127.0.0.1", "localhost", "::1"].contains(host),
              url.user == nil,
              url.password == nil,
              url.port != nil else { return false }
        return url.path.isEmpty || url.path == "/"
    }

    private static func isValidSchemaBindingJSON(
        _ value: JSONValue,
        depth: Int
    ) -> Bool {
        guard depth <= 4 else { return false }
        switch value {
        case .string(let text):
            return text.count <= 2_000 && !text.unicodeScalars.contains {
                CharacterSet.controlCharacters.contains($0)
                    && $0 != "\n" && $0 != "\t"
            }
        case .number(let number):
            return number.isFinite
        case .bool, .null:
            return true
        case .object(let object):
            return object.count <= 32 && object.allSatisfy { key, child in
                !key.isEmpty && key.count <= 80
                    && key.unicodeScalars.allSatisfy {
                        CharacterSet.alphanumerics
                            .union(CharacterSet(charactersIn: "_-"))
                            .contains($0)
                    }
                    && isValidSchemaBindingJSON(child, depth: depth + 1)
            }
        case .array(let array):
            return array.count <= 32 && array.allSatisfy {
                isValidSchemaBindingJSON($0, depth: depth + 1)
            }
        }
    }

    private static func isSameOrigin(_ candidate: URL?, _ origin: URL) -> Bool {
        guard let candidate else { return false }
        return candidate.scheme?.lowercased() == origin.scheme?.lowercased()
            && candidate.host?.lowercased() == origin.host?.lowercased()
            && candidate.port == origin.port
    }

    private static func hasAllowedPortraitQuery(_ url: URL) -> Bool {
        guard let components = URLComponents(url: url, resolvingAgainstBaseURL: false),
              let items = components.queryItems else { return url.query == nil }
        guard items.count == 1,
              items[0].name == "v",
              let version = items[0].value,
              !version.isEmpty else { return false }
        return version.unicodeScalars.allSatisfy {
            CharacterSet(charactersIn: "0123456789.").contains($0)
        }
    }

    private static func hasAllowedPortraitPath(_ url: URL) -> Bool {
        let prefix = "/assets/portraits/"
        guard url.path.hasPrefix(prefix) else { return false }
        let file = String(url.path.dropFirst(prefix.count))
        guard !file.isEmpty,
              !file.contains("/"),
              !file.contains(".."),
              ["jpg", "jpeg", "png", "webp"].contains(
                  (file as NSString).pathExtension.lowercased()
              ) else { return false }
        return file.unicodeScalars.allSatisfy {
            CharacterSet.alphanumerics
                .union(CharacterSet(charactersIn: "._-"))
                .contains($0)
        }
    }

    private static func hasAllowedImageryQuery(_ url: URL) -> Bool {
        guard let components = URLComponents(url: url, resolvingAgainstBaseURL: false),
              let items = components.queryItems,
              items.count == 1,
              items[0].name == "v",
              let version = items[0].value,
              !version.isEmpty else { return false }
        return version.unicodeScalars.allSatisfy {
            CharacterSet(charactersIn: "0123456789.").contains($0)
        }
    }

    private static func hasAllowedImageryPath(
        _ url: URL,
        expectedFile: String
    ) -> Bool {
        let prefix = "/assets/imagery/"
        guard url.path.hasPrefix(prefix) else { return false }
        let file = String(url.path.dropFirst(prefix.count))
        guard file == expectedFile,
              !file.isEmpty,
              !file.contains("/"),
              !file.contains(".."),
              (file as NSString).pathExtension.lowercased() == "webp" else {
            return false
        }
        return file.unicodeScalars.allSatisfy {
            CharacterSet(charactersIn: "abcdefghijklmnopqrstuvwxyz0123456789-.webp")
                .contains($0)
        }
    }

    private static func isBoundedWebP(_ data: Data) -> Bool {
        guard data.count >= 20 else { return false }
        let header = Array(data.prefix(20))
        guard Array(header[0..<4]) == Array("RIFF".utf8),
              Array(header[8..<12]) == Array("WEBP".utf8) else { return false }
        let declared = Int(header[4])
            | Int(header[5]) << 8
            | Int(header[6]) << 16
            | Int(header[7]) << 24
        return declared + 8 == data.count
    }
}

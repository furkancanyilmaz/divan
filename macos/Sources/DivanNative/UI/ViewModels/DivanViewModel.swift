import AppKit
import Foundation
import SwiftUI

public enum DivanSidebarDestination: String, CaseIterable, Identifiable {
    case recent
    case archived
    case masters
    case works
    case livingMap
    case sync
    case settings
    case notebook
    case letters
    case dreams
    case profile

    public var id: Self { self }

    public var title: String {
        switch self {
        case .recent: "Son konuşmalar"
        case .archived: "Arşiv"
        case .masters: "Ustalar"
        case .works: "Çalışmalar"
        case .livingMap: "Yaşayan harita"
        case .sync: "Cihaz eşitleme"
        case .settings: "Sağlayıcı ve ayarlar"
        case .notebook: "Defter"
        case .letters: "Mektuplar"
        case .dreams: "Rüya defteri"
        case .profile: "Hakkımda"
        }
    }

    public var systemImage: String {
        switch self {
        case .recent: "bubble.left.and.bubble.right"
        case .archived: "archivebox"
        case .masters: "person.2.fill"
        case .works: "chair.lounge.fill"
        case .livingMap: "map.fill"
        case .sync: "arrow.triangle.2.circlepath"
        case .settings: "gearshape"
        case .notebook: "note.text"
        case .letters: "envelope"
        case .dreams: "moon.stars"
        case .profile: "person.text.rectangle"
        }
    }
}

public struct DivanNotice: Identifiable, Equatable {
    public enum Retry: Equatable {
        case bootstrap
        case conversations(archived: Bool)
        case conversation(Int)
        case olderMessages
        case settings
    }

    public let id = UUID()
    public let title: String
    public let message: String
    public let retry: Retry?
}

@MainActor
public final class DivanViewModel: ObservableObject {
    private struct SchemaProjectionCursor: Equatable {
        let pathPublicID: String?
        let pathID: Int?
        let revision: Int?
        let checkpointPublicID: String?
        let checkpointSeq: Int?
        let cardID: String?
    }

    private struct SchemaSendProjectionAnchor: Equatable {
        let pathPublicID: String?
        let pathID: Int?
        let pathStatus: String?
        let revision: Int?
        let step: String?
        let checkpointPublicID: String?
        let checkpointSeq: Int?
        let cardID: String?
    }

    private enum SchemaProjectionOrder {
        case streamed
        case durable
        case conflict
    }

    private enum SchemaDurableProjectionDecision {
        case acceptDurable
        case preserveStreamedSnapshot
        case conflict
    }

    public static let pageSize = 80

    private let dataSource: any DivanUIDataSource
    private let displayPreferencesStore: any DivanDisplayPreferencesStore
    private let schemaChatDraftStore: any SchemaChatDraftStore
    private var suppressSchemaChatDraftPersistence = false
    private var openToken = UUID()
    private var olderToken = UUID()
    private var sendToken = UUID()
    private var backgroundPollToken = UUID()
    private var schemaPollToken = UUID()
    private var schemaPromptPollToken = UUID()
    private var schemaRequestIDs: [String: String] = [:]
    private var failedSchemaCardMutation: SchemaCardMutation?
    private var failedSchemaPrepathMutation: SchemaPathMutation?
    private var ephemeralGreetings: [Int: DivanMessage] = [:]
    private let portraitCache = DivanPortraitCache()
    private var portraitLoads = Set<String>()
    private var portraitFailures = Set<String>()

    @Published public var columnVisibility: NavigationSplitViewVisibility = .all
    @Published public var destination: DivanSidebarDestination = .recent
    @Published public var catalogSearch = ""
    @Published public var conversationSearch = ""
    @Published public var masterCatalogKind: DivanCatalogKind = .therapist
    @Published public var selectedCatalogMasterID: String?
    @Published public var advancedConversationID: Int?
    @Published public var advancedInitialModule: AdvancedModule = .chairWork

    @Published public private(set) var therapists: [DivanMaster] = []
    @Published public private(set) var philosophers: [DivanMaster] = []
    @Published public private(set) var activeConversations: [DivanConversation] = []
    @Published public private(set) var archivedConversations: [DivanConversation] = []

    @Published public private(set) var selectedConversation: DivanConversation?
    @Published public private(set) var selectedMaster: DivanMaster?
    @Published public private(set) var messages: [DivanMessage] = []
    @Published public private(set) var messageCount = 0
    @Published public private(set) var hasMoreMessages = false
    @Published public private(set) var oldestMessageID: Int?

    @Published public var composerText = "" {
        didSet { persistSchemaComposerDraftIfEligible() }
    }
    @Published public private(set) var isBootstrapping = false
    @Published public private(set) var isLoadingConversation = false
    @Published public private(set) var isLoadingOlderMessages = false
    @Published public private(set) var isSending = false
    @Published public private(set) var isMutatingConversation = false
    @Published public private(set) var isEndingConversation = false
    @Published public private(set) var chatStatusText = ""
    @Published public private(set) var schemaPathSnapshot: SchemaPathSnapshot?
    @Published public private(set) var schemaStatusText = ""
    @Published public private(set) var schemaBusyCandidateID: Int?
    @Published public private(set) var schemaBusySuggestionID: Int?
    @Published public private(set) var schemaBusyMessageID: Int?
    @Published public private(set) var schemaModeConfirmationBusy = false
    @Published public private(set) var schemaBusyCardID: String?
    @Published public private(set) var schemaFailedCardID: String?
    @Published public private(set) var schemaClinicalSyncBusy = false
    @Published public private(set) var streamedSchemaCard: SchemaCardEnvelope?
    @Published public private(set) var streamedSchemaMessageMeta:
        [SchemaMessageMetaEvent] = []
    /// `done.next_card` is always present in schema v4 and may explicitly be
    /// null. Keep presence separate from Optional so null clears a stale card.
    private var hasAuthoritativeStreamedSchemaCard = false
    private var authoritativeStreamedSchemaCursor: SchemaProjectionCursor?
    /// A successful direct safety action owns the reducer projection. Any
    /// already-in-flight chat completion may still deliver its old card, but
    /// must not reopen or advance work after pause/ground/stop.
    private var suppressInFlightSchemaCardProjection = false
    @Published public var notice: DivanNotice?
    /// Açık görüşmenin seans özeti taslağı. Seans bitince çekirdek arka
    /// planda üretir; kullanıcı onaylayana kadar hafızaya geçmez.
    // MARK: - Defter yüzeyleri
    @Published public var profileText = ""
    @Published public var isProfileBusy = false
    @Published public var notebook: LibraryNotebook?
    @Published public var letters: LibraryLetters?
    @Published public var dreamJournal: LibraryDreamJournal?
    @Published public var isDreamAnalysisBusy = false
    @Published public var searchHits: [LibrarySearchHit] = []
    @Published public var isSearching = false

    @Published public var sessionSummary: DivanSessionSummary?
    @Published public var isSummaryBusy = false

    /// Changes whenever a newly opened conversation should jump to its end.
    @Published public private(set) var scrollToLatestRequest = UUID()
    /// The ID to restore at the top after an older page has been prepended.
    @Published public private(set) var historyAnchorRequest: String?

    @Published public var isNewSessionPresented = false
    @Published public var newSessionMaster: DivanMaster?
    @Published public var newSessionMode: DivanSessionMode = .therapy
    @Published public private(set) var isCreatingSession = false

    @Published public private(set) var settings: DivanSettingsSummary?
    @Published public private(set) var portraitDataByMasterID: [String: Data] = [:]
    /// Seçili sağlayıcı. Sunucu bu seçimi kalıcı olarak hatırlar; uygulama
    /// yeniden açıldığında son sağlayıcıyla gelir.
    @Published public var settingsProvider: DivanProviderID = .lmStudio {
        didSet {
            guard settingsProvider != oldValue else { return }
            settingsNewAPIKey = ""
            // Yerel sağlayıcı ilk kez seçilince varsayılan adres önerilir.
            if settingsProvider.isLocal,
               providerDrafts[settingsProvider]?.baseURL.isEmpty != false {
                providerDrafts[settingsProvider, default: DivanProviderDraft()]
                    .baseURL = settingsProvider.defaultBaseURL
            }
        }
    }
    /// Sağlayıcı başına düzenleme taslağı. Kullanıcı DeepSeek'ten LM
    /// Studio'ya geçip geri döndüğünde her sağlayıcının modeli ve adresi
    /// kendi alanında durur; kaydedilmemiş değerler bile unutulmaz.
    @Published public private(set) var providerDrafts:
        [DivanProviderID: DivanProviderDraft] = [:]
    /// Sunucuda saklanan sağlayıcı özetleri (anahtar var/yok dahil).
    @Published public private(set) var providerConfigs:
        [DivanProviderID: DivanProviderSnapshot] = [:]
    /// Deliberately transient and cleared after every save attempt.
    @Published public var settingsNewAPIKey = ""
    @Published public private(set) var isSavingSettings = false
    @Published public private(set) var settingsMessage = ""

    /// Bu Mac'te açık olan yerel model sunucuları (LM Studio, Ollama,
    /// llama.cpp). Ayarlar ekranı açılınca otomatik taranır.
    @Published public private(set) var detectedLocalServers: [DivanLocalServer] = []
    @Published public private(set) var isScanningLocalServers = false
    @Published public private(set) var localScanMessage = ""

    /// Misafir oturumu açık mı? Açıkken yalnız misafir görüşmeleri
    /// listelenir; kapanınca misafir görüşmeleri silinir ve normal
    /// görüşmeler yeniden görünür.
    @Published public private(set) var guestModeActive = false
    @Published public private(set) var isTogglingGuestMode = false

    /// Misafir modunda gizlenen kişisel yüzeyler.
    public static let guestHiddenDestinations: Set<DivanSidebarDestination> = [
        .notebook, .letters, .dreams, .profile,
    ]

    /// Seçili sağlayıcının model taslağı. Sağlayıcı değişince bu alan
    /// otomatik olarak o sağlayıcının kendi taslağını gösterir.
    public var settingsModel: String {
        get { providerDrafts[settingsProvider]?.model ?? "" }
        set {
            providerDrafts[settingsProvider, default: DivanProviderDraft()]
                .model = newValue
        }
    }

    /// Seçili sağlayıcının yerel adres taslağı (yalnız yerel sağlayıcılar).
    public var settingsBaseURL: String {
        get { providerDrafts[settingsProvider]?.baseURL ?? "" }
        set {
            providerDrafts[settingsProvider, default: DivanProviderDraft()]
                .baseURL = newValue
        }
    }

    /// Native presentation preferences are persisted locally and never sent
    /// through the provider/API-key settings endpoint.
    @Published public var textSizePreference: DivanTextSizePreference {
        didSet { persistDisplayPreferences() }
    }
    @Published public var appearancePreference: DivanAppearancePreference {
        didSet { persistDisplayPreferences() }
    }
    /// Pencerenin diğer uygulamaların üstünde kalması (FaceTime tarzı).
    /// Yalnız yerel bir sunum tercihi; sağlayıcı ayarlarına gitmez.
    @Published public var keepsWindowOnTop: Bool {
        didSet { persistDisplayPreferences() }
    }

    public convenience init(dataSource: any DivanUIDataSource) {
        self.init(
            dataSource: dataSource,
            displayPreferencesStore: UserDefaultsDivanDisplayPreferencesStore(),
            schemaChatDraftStore: DisabledSchemaChatDraftStore.shared
        )
    }

    public init(
        dataSource: any DivanUIDataSource,
        displayPreferencesStore: any DivanDisplayPreferencesStore,
        schemaChatDraftStore: (any SchemaChatDraftStore)? = nil
    ) {
        self.dataSource = dataSource
        self.displayPreferencesStore = displayPreferencesStore
        self.schemaChatDraftStore = schemaChatDraftStore
            ?? DisabledSchemaChatDraftStore.shared
        let preferences = displayPreferencesStore.load()
        self.textSizePreference = preferences.textSize
        self.appearancePreference = preferences.appearance
        self.keepsWindowOnTop = preferences.keepsWindowOnTop
    }

    public var displayPreferences: DivanDisplayPreferences {
        DivanDisplayPreferences(
            textSize: textSizePreference,
            appearance: appearancePreference,
            keepsWindowOnTop: keepsWindowOnTop
        )
    }

    public var allMasters: [DivanMaster] { therapists + philosophers }

    public var visibleMasters: [DivanMaster] {
        let source = masterCatalogKind == .philosopher
            ? philosophers : therapists
        let query = searchKey(catalogSearch)
        guard !query.isEmpty else { return source }
        return source.filter {
            searchKey([$0.name, $0.school, $0.subtitle].joined(separator: " "))
                .contains(query)
        }
    }

    public var selectedCatalogMaster: DivanMaster? {
        guard let selectedCatalogMasterID else { return visibleMasters.first }
        return visibleMasters.first { $0.id == selectedCatalogMasterID }
            ?? visibleMasters.first
    }

    public var activeTherapyConversations: [DivanConversation] {
        activeConversations.filter { !$0.isEnded && $0.mode == .therapy }
    }

    public var advancedConversation: DivanConversation? {
        guard let advancedConversationID else { return nil }
        return activeTherapyConversations.first { $0.id == advancedConversationID }
    }

    public var visibleConversations: [DivanConversation] {
        let source = destination == .archived
            ? archivedConversations : activeConversations
        let query = searchKey(conversationSearch)
        guard !query.isEmpty else { return source }
        return source.filter {
            searchKey([
                $0.title, $0.preview, master(id: $0.masterID)?.name ?? "",
            ].joined(separator: " ")).contains(query)
        }
    }

    public var canSend: Bool {
        selectedConversation != nil && selectedConversation?.isEnded == false &&
            selectedConversation?.isArchived == false &&
            !composerText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty &&
            !isSending && !isLoadingConversation && !schemaComposerLockedByCard
    }

    public var isYoungSchemaConversation: Bool {
        selectedConversation?.mode == .therapy
            && selectedConversation?.masterID == "young"
            && selectedConversation?.isEnded == false
            && selectedConversation?.isArchived == false
            && !guestModeActive
    }

    public var schemaRecommendationCandidates: [SchemaCandidate] {
        guard isYoungSchemaConversation else { return [] }
        let source = schemaPathSnapshot?.activePath == nil
            ? (schemaPathSnapshot?.candidates ?? [])
            : (schemaPathSnapshot?.queuedCandidates ?? [])
        return Array(source.filter {
            $0.sourceTurn != nil && $0.scope != "private"
                && $0.scope != "excluded" && !$0.sensitive
                && !["dismissed", "rejected"].contains($0.decisionState ?? "")
        }.prefix(3))
    }

    public func schemaInlineSuggestions(
        forAssistantMessageID messageID: Int?
    ) -> [SchemaInlineSuggestion] {
        guard isYoungSchemaConversation, let messageID else { return [] }
        return (schemaPathSnapshot?.inlineSuggestions ?? []).filter {
            $0.assistantMessageId == messageID
        }
    }

    public var usesSchemaChatProtocolV4: Bool {
        isYoungSchemaConversation
            && schemaPathSnapshot?.version == 4
            && schemaPathSnapshot?.protocol == "schema_path_chat_v4"
    }

    public var usesSchemaChatProtocolV5: Bool {
        isYoungSchemaConversation
            && schemaPathSnapshot?.version == 5
            && schemaPathSnapshot?.protocol == "schema_path_chat_v5"
    }

    public var usesSchemaChatProtocol: Bool {
        usesSchemaChatProtocolV4 || usesSchemaChatProtocolV5
    }

    public var usesSchemaChatOnlyPresentation: Bool {
        usesSchemaChatProtocol
            && schemaPathSnapshot?.presentation == "chat_only"
    }

    /// There is exactly one interactive card. Checkpoints are append-only, so
    /// their sequence breaks ties when a clarification/backtrack keeps the
    /// path revision unchanged.
    public var activeSchemaCard: SchemaCardEnvelope? {
        guard usesSchemaChatProtocol else { return nil }
        let durable = schemaPathSnapshot?.nextCard
        if hasAuthoritativeStreamedSchemaCard {
            if let streamed = streamedSchemaCard {
                if let durable {
                    switch schemaProjectionOrder(
                        streamed: streamed,
                        durable: durable
                    ) {
                    case .durable:
                        return durable.isActive ? durable : nil
                    case .conflict:
                        // Equal cursors with different append-only identities
                        // are tampered/ambiguous. Neither projection may bind
                        // the ordinary composer until a genuinely newer GET.
                        return nil
                    case .streamed:
                        break
                    }
                }
                // The exact-pair SSE envelope wins a same-revision durable
                // card so it anchors beneath the assistant bubble just made.
                return streamed.isActive ? streamed : nil
            }
            return nil
        }
        return durable?.isActive == true ? durable : nil
    }

    private func schemaProjectionOrder(
        streamed: SchemaCardEnvelope,
        durable: SchemaCardEnvelope
    ) -> SchemaProjectionOrder {
        if streamed.pathPublicId != durable.pathPublicId
            || streamed.pathId != durable.pathId {
            return .durable
        }
        guard let streamedRevision = streamed.revision,
              let durableRevision = durable.revision else {
            return streamed.id == durable.id ? .streamed : .durable
        }
        if durableRevision != streamedRevision {
            return durableRevision > streamedRevision ? .durable : .streamed
        }
        let streamedSeq = streamed.checkpoint?.seq ?? -1
        let durableSeq = durable.checkpoint?.seq ?? -1
        if durableSeq != streamedSeq {
            return durableSeq > streamedSeq ? .durable : .streamed
        }
        if streamed.checkpoint?.publicId != durable.checkpoint?.publicId {
            return .conflict
        }
        let streamedImported = streamed.promptDelivery?.status
            == "imported_waiting"
        let durableImported = durable.promptDelivery?.status
            == "imported_waiting"
        if streamedImported != durableImported {
            // The receiver import boundary is stable at the same cursor. A
            // late local request from before process death must not replace
            // it; only a genuinely newer revision/checkpoint may resume it.
            return durableImported ? .durable : .streamed
        }
        guard streamed.id == durable.id,
              streamed.promptDelivery == durable.promptDelivery,
              streamed.chatBinding == durable.chatBinding else {
            return .conflict
        }
        return .streamed
    }

    private func schemaProjectionCursor(
        card: SchemaCardEnvelope?,
        result: SchemaChatBindingResult?
    ) -> SchemaProjectionCursor {
        if let card {
            return SchemaProjectionCursor(
                pathPublicID: card.pathPublicId,
                pathID: card.pathId,
                revision: card.revision,
                checkpointPublicID: card.checkpoint?.publicId,
                checkpointSeq: card.checkpoint?.seq,
                cardID: card.id
            )
        }
        let currentPath = schemaPathSnapshot?.activePath
        let resultPathID = result?.pathId
        return SchemaProjectionCursor(
            pathPublicID: currentPath?.id == resultPathID
                ? currentPath?.publicId : nil,
            pathID: resultPathID,
            revision: result?.pathRevision,
            checkpointPublicID: result?.checkpointPublicId,
            checkpointSeq: result?.checkpointSeq,
            cardID: nil
        )
    }

    private func durableSnapshotSupersedesStreamedNull(
        _ snapshot: SchemaPathSnapshot,
        cursor: SchemaProjectionCursor
    ) -> Bool {
        // A null SSE card is a short-lived ordering barrier, not a permanent
        // tombstone. Once GET has caught up to the same path/revision (or to
        // the same pathless state), release it so a later background analysis
        // can surface a new pathless candidate.
        if snapshot.nextCard == nil {
            if snapshot.activePath == nil,
               cursor.pathID == nil,
               cursor.pathPublicID == nil {
                return true
            }
            if let path = snapshot.activePath,
               path.id == cursor.pathID,
               path.publicId == cursor.pathPublicID {
                guard let cursorRevision = cursor.revision else { return true }
                if path.revision >= cursorRevision { return true }
            }
        }
        if let card = snapshot.nextCard {
            if card.pathPublicId != cursor.pathPublicID
                || card.pathId != cursor.pathID {
                return true
            }
            if let cardRevision = card.revision,
               let cursorRevision = cursor.revision,
               cardRevision > cursorRevision {
                return true
            }
            if card.revision == cursor.revision,
               (card.checkpoint?.seq ?? -1) > (cursor.checkpointSeq ?? -1) {
                return true
            }
            if card.revision == cursor.revision,
               card.checkpoint?.seq == cursor.checkpointSeq,
               card.checkpoint?.publicId != cursor.checkpointPublicID {
                return true
            }
        }
        if let path = snapshot.activePath {
            if path.publicId != cursor.pathPublicID || path.id != cursor.pathID {
                return true
            }
            if let cursorRevision = cursor.revision,
               path.revision > cursorRevision {
                return true
            }
        }
        return false
    }

    public func schemaCard(
        forAssistantMessageID messageID: Int?
    ) -> SchemaCardEnvelope? {
        guard let messageID, let card = activeSchemaCard,
              card.source.assistantMessageId == messageID else { return nil }
        return card
    }

    public func schemaCandidatePrompt(
        forAssistantMessageID messageID: Int?
    ) -> SchemaCardEnvelope? {
        guard usesSchemaChatOnlyPresentation,
              let card = schemaCard(forAssistantMessageID: messageID),
              card.presentation == "chat_only",
              card.kind == "candidate_prompt",
              card.isSupportedByNativeContract,
              schemaCandidateSourceMatchesLoadedChat(card) else { return nil }
        return card
    }

    private func schemaCandidateSourceMatchesLoadedChat(
        _ card: SchemaCardEnvelope
    ) -> Bool {
        guard let userID = card.source.userMessageId,
              let userPublicID = card.source.userMessagePublicId,
              let assistantID = card.source.assistantMessageId,
              let assistantPublicID = card.source.assistantMessagePublicId,
              let userIndex = messages.lastIndex(where: {
                  $0.role == .user && $0.serverID == userID
              }),
              let assistantIndex = messages.lastIndex(where: {
                  $0.role == .assistant && $0.serverID == assistantID
              }),
              messages.index(after: userIndex) == assistantIndex else {
            return false
        }
        let user = messages[userIndex]
        let assistant = messages[assistantIndex]
        return user.publicID == userPublicID
            && assistant.publicID == assistantPublicID
            && card.source.candidateQuoteForDisplay(
                matchingUserMessageContent: user.content
            ) != nil
            && !user.isPending && user.failedDescription == nil
            && !assistant.isPending && assistant.failedDescription == nil
            && !user.content.trimmingCharacters(
                in: .whitespacesAndNewlines
            ).isEmpty
            && !assistant.content.trimmingCharacters(
                in: .whitespacesAndNewlines
            ).isEmpty
    }

    private func installCandidateLineageOnExactLocalPair(
        _ card: SchemaCardEnvelope?
    ) {
        guard let card,
              card.kind == "candidate_prompt",
              card.isSupportedByNativeContract,
              let userID = card.source.userMessageId,
              let userPublicID = card.source.userMessagePublicId,
              let assistantID = card.source.assistantMessageId,
              let assistantPublicID = card.source.assistantMessagePublicId,
              let userIndex = messages.lastIndex(where: {
                  $0.role == .user && $0.serverID == userID
              }),
              let assistantIndex = messages.lastIndex(where: {
                  $0.role == .assistant && $0.serverID == assistantID
              }),
              messages.index(after: userIndex) == assistantIndex,
              messages[userIndex].id.hasPrefix("local-user-"),
              messages[assistantIndex].id.hasPrefix("local-assistant-"),
              [nil, userPublicID].contains(messages[userIndex].publicID),
              [nil, assistantPublicID].contains(
                messages[assistantIndex].publicID
              ) else { return }
        let localUserID = messages[userIndex].id
        let localAssistantID = messages[assistantIndex].id
        mutateMessage(id: localUserID) {
            $0.publicID = userPublicID
            $0.deliveryStatus = "completed"
        }
        mutateMessage(id: localAssistantID) {
            $0.publicID = assistantPublicID
            $0.deliveryStatus = "completed"
        }
    }

    public func schemaSafetyControls(
        forAssistantMessageID messageID: Int?
    ) -> SchemaCardEnvelope? {
        // v5 has no schema-specific button row. Safety commands remain
        // server-owned and may be typed in the ordinary composer while the
        // current prompt binding is valid.
        nil
    }

    public func schemaChatPromptContinuation(
        for message: DivanMessage
    ) -> String? {
        // Visible questions must be durable provider-authored assistant rows.
        // Metadata body text is never appended beneath a conversation bubble.
        nil
    }

    private var latestRealAssistantMessageID: Int? {
        messages.last {
            $0.role == .assistant && $0.serverID != nil
        }?.serverID
    }

    public func schemaMetaEvents(for message: DivanMessage) -> [SchemaMessageMetaEvent] {
        guard let messageID = message.serverID else { return message.schemaMetaEvents }
        let combined = message.schemaMetaEvents
            + (schemaPathSnapshot?.messageMeta ?? []).filter { $0.messageId == messageID }
            + streamedSchemaMessageMeta.filter { $0.messageId == messageID }
        var byPublicID: [String: SchemaMessageMetaEvent] = [:]
        for event in combined { byPublicID[event.publicId] = event }
        let values = byPublicID.values.filter {
            !usesSchemaChatProtocol
                || ["technique", "map_update"].contains($0.kind)
        }
        return values.sorted {
            ($0.created ?? "", $0.databaseId) < ($1.created ?? "", $1.databaseId)
        }
    }

    private var schemaComposerBindingV5: SchemaChatBinding? {
        guard usesSchemaChatProtocolV5,
              schemaPathSnapshot?.presentation == "chat_only",
              let snapshot = schemaPathSnapshot,
              let card = activeSchemaCard,
              card.kind == "chat_state",
              card.presentation == "chat_only",
              card.isSupportedByNativeContract,
              card.fields.isEmpty, card.actions.isEmpty,
              card.title.isEmpty, (card.contextLine ?? "").isEmpty,
              card.body.isEmpty,
              let policy = snapshot.interactionPolicy,
              policy.composerAllowed == true,
              policy.composerMode == .bound,
              policy.composerSurface == "ordinary_chat",
              policy.composerBindingRequired,
              policy.inlineControlsOnly == false,
              policy.boundStepId == card.step,
              let path = snapshot.activePath,
              path.convId == selectedConversation?.id,
              path.flowVersion == 5,
              ["active", "paused"].contains(path.status),
              let pathPublicID = path.publicId,
              SchemaPathCheckpoint.isPublicID(pathPublicID),
              path.id == card.pathId,
              pathPublicID == card.pathPublicId,
              path.revision == card.revision,
              snapshot.revision == card.revision,
              path.stage == card.stage,
              path.step == card.step,
              snapshot.stage == card.stage,
              snapshot.step == card.step,
              SchemaPathCheckpoint.supportedV5StepStages[card.step]
                == card.stage,
              let checkpoint = card.checkpoint,
              checkpoint.isSupportedByNativeContract,
              let delivery = card.promptDelivery,
              delivery.isSupportedByNativeContract,
              let sourceUserID = card.source.userMessageId,
              sourceUserID > 0,
              let sourceUserPublicID = card.source.userMessagePublicId,
              SchemaPathCheckpoint.isPublicID(sourceUserPublicID),
              let sourceAssistantID = card.source.assistantMessageId,
              sourceAssistantID > 0,
              let sourceAssistantPublicID =
                card.source.assistantMessagePublicId,
              SchemaPathCheckpoint.isPublicID(sourceAssistantPublicID),
              let binding = card.chatBinding,
              binding.protocol == "schema_path_chat_v5",
              binding.pathId == path.id,
              binding.pathPublicId == pathPublicID,
              binding.stepId == card.step,
              binding.expectedRevision == path.revision,
              binding.checkpointPublicId == checkpoint.publicId,
              binding.expectedCheckpointSeq == checkpoint.seq,
              binding.sourceUserMessageId == sourceUserID,
              binding.sourceUserMessagePublicId == sourceUserPublicID,
              binding.sourceAssistantMessageId == sourceAssistantID,
              binding.sourceAssistantMessagePublicId
                == sourceAssistantPublicID,
              binding.techniqueLinkId == nil,
              binding.techniqueLinkPublicId == nil,
              binding.expectedTechniqueRevision == nil else { return nil }

        let controlOnly = path.status == "paused"
        guard card.status == (controlOnly ? "paused" : "active"),
              checkpoint.status == (controlOnly ? "paused" : "active")
        else { return nil }

        if delivery.status == "imported_waiting" {
            guard controlOnly,
                  path.resumeRequired == true,
                  path.pauseReason == "sync_import_resume_required",
                  snapshot.resumeState?.required == true,
                  snapshot.resumeState?.reason
                    == "sync_import_resume_required",
                  policy.reason == "prompt_delivery_imported_waiting",
                  !checkpoint.canBacktrack,
                  !checkpoint.backtrackPending,
                  binding.syncImportControl == true,
                  binding.promptRequestId == nil,
                  binding.promptAssistantMessageId == nil,
                  binding.promptAssistantMessagePublicId == nil else {
                return nil
            }
            // Imported source rows may be outside the current page after a
            // restart. Their exact public IDs remain an audit/control pin,
            // never clinical prompt authority.
            return binding
        }

        guard delivery.status == "completed",
              binding.syncImportControl == nil,
              let requestID = delivery.requestId,
              binding.promptRequestId == requestID,
              let promptAssistantID = delivery.promptAssistantMessageId,
              let promptAssistantPublicID =
                delivery.promptAssistantMessagePublicId,
              binding.promptAssistantMessageId == promptAssistantID,
              binding.promptAssistantMessagePublicId
                == promptAssistantPublicID,
              sourceAssistantID == promptAssistantID,
              sourceAssistantPublicID == promptAssistantPublicID else {
            return nil
        }
        if controlOnly {
            // A paused card owns lifecycle commands only. Its previously
            // delivered prompt need not still be the newest paginated row.
            return binding
        }
        guard schemaV5LoadedPromptPairMatches(binding) else { return nil }
        return binding
    }

    private func schemaV5LoadedPromptPairMatches(
        _ binding: SchemaChatBinding
    ) -> Bool {
        guard let userIndex = messages.lastIndex(where: {
                  $0.role == .user
                    && $0.serverID == binding.sourceUserMessageId
              }),
              let assistantIndex = messages.lastIndex(where: {
                  $0.role == .assistant
                    && $0.serverID == binding.promptAssistantMessageId
              }),
              messages.index(after: userIndex) == assistantIndex,
              assistantIndex == messages.indices.last else { return false }
        let user = messages[userIndex]
        let assistant = messages[assistantIndex]
        return user.publicID == binding.sourceUserMessagePublicId
            && ["saved", "completed"].contains(
                user.deliveryStatus?.localizedLowercase ?? ""
            )
            && assistant.publicID
                == binding.promptAssistantMessagePublicId
            && assistant.deliveryStatus?.localizedLowercase == "completed"
            && !assistant.isPending
            && assistant.failedDescription == nil
            && !assistant.content.trimmingCharacters(
                in: .whitespacesAndNewlines
            ).isEmpty
    }

    public var schemaComposerBinding: SchemaChatBinding? {
        if usesSchemaChatProtocolV5 {
            return schemaComposerBindingV5
        }
        guard usesSchemaChatProtocolV4,
              usesSchemaChatOnlyPresentation,
              let snapshot = schemaPathSnapshot,
              let card = activeSchemaCard,
              card.isSupportedByNativeContract,
              card.presentation == "chat_only",
              card.kind == "chat_prompt",
              card.fields.isEmpty,
              let policy = schemaPathSnapshot?.interactionPolicy,
              policy.composerAllowed == true,
              policy.composerMode == .bound,
              policy.composerSurface == "ordinary_chat",
              policy.composerBindingRequired,
              let stepID = policy.boundStepId, !stepID.isEmpty,
              let path = schemaPathSnapshot?.activePath,
              path.convId == selectedConversation?.id,
              path.flowVersion == 4,
              path.status == "active",
              let pathPublicID = path.publicId,
              SchemaPathCheckpoint.isPublicID(pathPublicID),
              let revision = card.revision,
              revision >= 0,
              snapshot.revision == revision,
              path.revision == revision,
              snapshot.stage == card.stage,
              snapshot.step == card.step,
              path.stage == card.stage,
              path.step == card.step,
              SchemaPathCheckpoint.supportedStepStages[card.step]
                == card.stage,
              let checkpoint = card.checkpoint,
              checkpoint.isSupportedByNativeContract,
              checkpoint.status == "active",
              let binding = card.chatBinding,
              binding.protocol == "schema_path_chat_v4",
              binding.promptRequestId == nil,
              binding.promptAssistantMessageId == nil,
              binding.promptAssistantMessagePublicId == nil,
              binding.pathId == path.id,
              binding.pathPublicId == pathPublicID,
              binding.stepId == stepID,
              binding.expectedRevision == revision,
              binding.checkpointPublicId == checkpoint.publicId,
              binding.expectedCheckpointSeq == checkpoint.seq,
              card.pathId == path.id,
              card.pathPublicId == pathPublicID,
              let sourceUserID = card.source.userMessageId,
              sourceUserID > 0,
              messages.contains(where: {
                  $0.role == .user && $0.serverID == sourceUserID
              }),
              let sourceUserPublicID = card.source.userMessagePublicId,
              SchemaPathCheckpoint.isPublicID(sourceUserPublicID),
              let sourceAssistantID = card.source.assistantMessageId,
              sourceAssistantID > 0,
              sourceAssistantID == latestRealAssistantMessageID,
              let sourceAssistantPublicID =
                card.source.assistantMessagePublicId,
              SchemaPathCheckpoint.isPublicID(sourceAssistantPublicID),
              binding.sourceUserMessageId == sourceUserID,
              binding.sourceUserMessagePublicId == sourceUserPublicID,
              binding.sourceAssistantMessageId == sourceAssistantID,
              binding.sourceAssistantMessagePublicId
                == sourceAssistantPublicID else { return nil }
        let methodSteps = Set(["method_select", "method_confirm"])
        let beforeMethodSteps = Set([
            "listen", "candidate_review", "current_impact",
            "variable_check", "focus_confirm", "method_select",
        ])
        let links = path.techniqueLinks ?? []
        let liveTechniqueLinks = links.filter {
            ["active", "paused"].contains($0.status)
        }
        guard liveTechniqueLinks.count <= 1 else { return nil }
        if methodSteps.contains(card.step) {
            guard path.methodId == nil, path.method == nil,
                  path.techniqueRunId == nil,
                  path.activeTechniqueLink == nil,
                  links.allSatisfy({
                    !["active", "paused"].contains($0.status)
                  }) else { return nil }
            if card.step == "method_select" {
                guard checkpoint.methodId == nil else { return nil }
            } else {
                guard checkpoint.methodId != nil else { return nil }
            }
        }
        let technique = path.activeTechniqueLink
        if checkpoint.seq == 0 {
            guard !checkpoint.canBacktrack,
                  path.techniqueRunId == nil,
                  technique == nil, liveTechniqueLinks.isEmpty,
                  binding.techniqueLinkId == nil,
                  binding.techniqueLinkPublicId == nil,
                  binding.expectedTechniqueRevision == nil else { return nil }
        }
        if beforeMethodSteps.contains(card.step) {
            guard path.methodId == nil, path.method == nil,
                  checkpoint.methodId == nil else { return nil }
        } else if card.step == "method_confirm" {
            guard path.methodId == nil, path.method == nil,
                  checkpoint.methodId != nil else { return nil }
        } else {
            guard let methodID = path.methodId,
                  let selected = path.method,
                  checkpoint.methodId == methodID,
                  selected.methodId == methodID,
                  selected.nodeId == nil || selected.nodeId == methodID
            else { return nil }
        }
        if let technique {
            guard technique.methodId == path.methodId,
                  checkpoint.methodId == technique.methodId,
                  SchemaPathCheckpoint.isPublicID(technique.publicId),
                  liveTechniqueLinks.count == 1,
                  liveTechniqueLinks.first == technique,
                  path.techniqueRunId == technique.techniqueRunId
            else { return nil }
        } else {
            guard liveTechniqueLinks.isEmpty,
                  path.techniqueRunId == nil else { return nil }
        }
        guard binding.techniqueLinkId == technique?.id,
              binding.techniqueLinkPublicId == technique?.publicId,
              binding.expectedTechniqueRevision
                == technique?.techniqueRevision else { return nil }
        return binding
    }

    /// The chat-only runner keeps the composer visually ordinary. This value
    /// describes only the hidden authoritative binding behind that composer.
    public var schemaComposerExpectsTextReply: Bool {
        schemaComposerBinding != nil
    }

    public var schemaComposerLockedByCard: Bool {
        if isYoungSchemaConversation,
           let snapshot = schemaPathSnapshot,
           snapshot.version >= 4 {
            let exactProtocol = snapshot.version == 4
                ? "schema_path_chat_v4"
                : snapshot.version == 5
                    ? "schema_path_chat_v5" : ""
            if exactProtocol.isEmpty || snapshot.protocol != exactProtocol {
                return snapshot.activePath != nil || snapshot.nextCard != nil
                    || activeSchemaCard != nil
            }
        }
        if usesSchemaChatOnlyPresentation {
            guard let policy = schemaPathSnapshot?.interactionPolicy else {
                return schemaPathSnapshot?.activePath != nil
                    || activeSchemaCard != nil
            }
            switch policy.composerMode {
            case .bound:
                return policy.composerAllowed != true
                    || policy.composerSurface != "ordinary_chat"
                    || !policy.composerBindingRequired
                    || schemaComposerBinding == nil
            case .ordinary:
                return policy.composerAllowed != true
                    || policy.composerBindingRequired
                    || policy.composerSurface != "ordinary_chat"
            case .disabled:
                return true
            case nil:
                return schemaPathSnapshot?.activePath != nil
                    || activeSchemaCard != nil
            }
        }
        // Stored pre-chat-only v4 projections are decode-compatible, but no
        // longer own native input. Fail closed until the core projects the
        // explicit chat-only contract.
        return usesSchemaChatProtocol && activeSchemaCard != nil
    }

    public var canReloadAfterFailedResponse: Bool {
        messages.contains { $0.failedDescription != nil } &&
            !isSending && selectedConversation?.isEnded == false &&
            selectedConversation?.isArchived == false
    }

    public func master(id: String) -> DivanMaster? {
        allMasters.first { $0.id == id }
    }

    public func portraitData(for master: DivanMaster?) -> Data? {
        guard let master else { return nil }
        return portraitDataByMasterID[master.id]
    }

    public func loadPortrait(for master: DivanMaster?) async {
        guard let master, let url = master.portraitURL,
              portraitDataByMasterID[master.id] == nil,
              !portraitLoads.contains(master.id),
              !portraitFailures.contains(master.id) else { return }
        portraitLoads.insert(master.id)
        defer { portraitLoads.remove(master.id) }
        do {
            let dataSource = self.dataSource
            let data = try await portraitCache.data(for: url) {
                try await dataSource.portraitData(url: url)
            }
            let valid = await Task.detached(priority: .utility) {
                NSImage(data: data)?.isValid == true
            }.value
            guard valid else {
                portraitFailures.insert(master.id)
                return
            }
            portraitDataByMasterID[master.id] = data
        } catch {
            // A missing or rejected portrait never blocks the catalog. Initials
            // remain visible and the failed URL is not hammered on every render.
            portraitFailures.insert(master.id)
        }
    }

    public func bootstrap() async {
        guard !isBootstrapping else { return }
        isBootstrapping = true
        notice = nil
        defer { isBootstrapping = false }
        do {
            let snapshot = try await dataSource.bootstrap()
            therapists = snapshot.therapists.sorted(by: masterSort)
            philosophers = snapshot.philosophers.sorted(by: masterSort)
            activeConversations = sortConversations(snapshot.activeConversations)
            archivedConversations = sortConversations(snapshot.archivedConversations)
            if selectedCatalogMasterID == nil {
                selectedCatalogMasterID = therapists.first?.id
                    ?? philosophers.first?.id
            }
            if advancedConversation == nil {
                advancedConversationID = activeTherapyConversations.first?.id
            }
            applySettings(snapshot.settings)
        } catch {
            notice = errorNotice(
                title: "Divan açılamadı",
                error: error,
                retry: .bootstrap
            )
        }
    }

    public func selectDestination(_ newDestination: DivanSidebarDestination) {
        // Misafir modunda kişisel yüzeyler (defter, mektuplar, rüya defteri,
        // hakkımda) kullanılamaz; normal kullanıcının verileri asla misafir
        // ekranına taşınmaz.
        let destination = guestModeActive
            && Self.guestHiddenDestinations.contains(newDestination)
            ? .recent : newDestination
        self.destination = destination
        notice = nil
        if (destination == .recent && selectedConversation?.isArchived == true)
            || (destination == .archived
                && selectedConversation?.isArchived != true) {
            clearConversationSelection()
        }
        if destination != .masters { catalogSearch = "" }
        if ![.recent, .archived].contains(destination) {
            conversationSearch = ""
        }
        if destination == .works || destination == .livingMap {
            if let selectedConversation,
               selectedConversation.mode == .therapy,
               !selectedConversation.isEnded,
               !selectedConversation.isArchived {
                advancedConversationID = selectedConversation.id
            } else if advancedConversation == nil {
                advancedConversationID = activeTherapyConversations.first?.id
            }
        }
    }

    private func clearConversationSelection() {
        openToken = UUID()
        olderToken = UUID()
        sendToken = UUID()
        backgroundPollToken = UUID()
        selectedConversation = nil
        selectedMaster = nil
        messages = []
        messageCount = 0
        hasMoreMessages = false
        oldestMessageID = nil
        setComposerTextWithoutDraftPersistence("")
        isLoadingConversation = false
        isLoadingOlderMessages = false
        isSending = false
        chatStatusText = ""
    }

    public func closeConversation() {
        clearConversationSelection()
    }

    public func selectMasterCatalogKind(_ kind: DivanCatalogKind) {
        masterCatalogKind = kind
        let source = kind == .therapist ? therapists : philosophers
        if !source.contains(where: { $0.id == selectedCatalogMasterID }) {
            selectedCatalogMasterID = source.first?.id
        }
    }

    public func selectCatalogMaster(_ master: DivanMaster?) {
        selectedCatalogMasterID = master?.id
    }

    public func selectAdvancedConversation(id: Int?) {
        guard let id else {
            advancedConversationID = nil
            return
        }
        if activeTherapyConversations.contains(where: { $0.id == id }) {
            advancedConversationID = id
        }
    }

    public func openAdvancedModule(_ module: AdvancedModule) {
        advancedInitialModule = module
        selectDestination(module == .livingMap ? .livingMap :
            module == .wifiSync ? .sync : .works)
    }

    public func refreshCurrentDestination() async {
        switch destination {
        case .recent: await refreshConversations(archived: false)
        case .archived: await refreshConversations(archived: true)
        case .masters: await refreshMasters(kind: masterCatalogKind)
        case .works, .livingMap, .sync: break
        case .settings: await refreshSettings()
        case .notebook: await loadNotebook()
        case .letters: await loadLetters()
        case .dreams: await loadDreamJournal()
        case .profile: await loadProfile()
        }
    }

    public func refreshMasters(kind: DivanCatalogKind) async {
        do {
            let values = try await dataSource.masters(kind: kind).sorted(by: masterSort)
            if kind == .therapist { therapists = values } else { philosophers = values }
        } catch {
            notice = errorNotice(title: "Usta kataloğu yenilenemedi", error: error)
        }
    }

    public func refreshConversations(archived: Bool) async {
        do {
            let values = sortConversations(
                try await dataSource.conversations(archived: archived)
            )
            if archived { archivedConversations = values }
            else { activeConversations = values }
        } catch {
            notice = errorNotice(
                title: archived ? "Arşiv yenilenemedi" : "Konuşmalar yenilenemedi",
                error: error,
                retry: .conversations(archived: archived)
            )
        }
    }

    public func openConversation(_ conversation: DivanConversation) async {
        let token = UUID()
        openToken = token
        olderToken = UUID()
        sendToken = UUID()
        backgroundPollToken = UUID()
        schemaPollToken = UUID()
        schemaPromptPollToken = UUID()
        schemaRequestIDs.removeAll()
        isSending = false
        setComposerTextWithoutDraftPersistence("")
        selectedConversation = conversation
        selectedMaster = master(id: conversation.masterID)
        isLoadingConversation = true
        notice = nil
        sessionSummary = nil
        messages = []
        messageCount = 0
        hasMoreMessages = false
        oldestMessageID = nil
        chatStatusText = ""
        schemaPathSnapshot = nil
        schemaStatusText = ""
        schemaBusyCandidateID = nil
        schemaBusySuggestionID = nil
        schemaBusyMessageID = nil
        schemaModeConfirmationBusy = false
        schemaBusyCardID = nil
        schemaFailedCardID = nil
        schemaClinicalSyncBusy = false
        failedSchemaCardMutation = nil
        failedSchemaPrepathMutation = nil
        streamedSchemaCard = nil
        streamedSchemaMessageMeta = []
        hasAuthoritativeStreamedSchemaCard = false
        authoritativeStreamedSchemaCursor = nil
        suppressInFlightSchemaCardProjection = false
        defer {
            if openToken == token { isLoadingConversation = false }
        }
        do {
            let page = try await dataSource.conversation(
                id: conversation.id,
                limit: Self.pageSize,
                beforeID: nil
            )
            guard openToken == token else { return }
            selectedConversation = page.conversation
            selectedMaster = page.master ?? master(id: page.conversation.masterID)
            var loaded = page.messages
            if let greeting = ephemeralGreetings[conversation.id],
               !loaded.contains(where: {
                   $0.role == .assistant && $0.content == greeting.content
               }) {
                loaded.insert(greeting, at: 0)
            }
            messages = deduplicated(loaded)
            messageCount = page.messageCount
            hasMoreMessages = page.hasMoreMessages
            oldestMessageID = page.oldestMessageID
            if let pending = page.pendingChat, pending.isPending {
                isSending = true
                let pendingID = "background-\(pending.requestID)"
                let silentV5 = pending.schemaPromptProtocol
                    == "schema_path_chat_v5"
                if !silentV5 {
                    messages.append(DivanMessage(
                        id: pendingID,
                        serverID: nil,
                        role: .assistant,
                        content: pending.content,
                        createdAt: Date(),
                        isPending: true
                    ))
                }
                chatStatusText = pending.waitingForProvider
                    ? "sağlayıcı bekleniyor" : "arka planda yanıt hazırlanıyor"
                startBackgroundPoll(
                    pending,
                    conversationID: conversation.id,
                    placeholderID: pendingID,
                    suppressAssistantPlaceholder: silentV5
                )
            }
            scrollToLatestRequest = UUID()
            // Özet yalnız bitmiş seanslarda anlamlıdır ve taslağı çekirdek
            // arka planda üretir; yükleme sohbeti bloke etmez.
            if page.conversation.isEnded {
                await loadSessionSummary()
            }
            if isYoungSchemaConversation {
                Task { [weak self] in
                    await self?.refreshSchemaRecommendations()
                }
            }
        } catch {
            guard openToken == token else { return }
            notice = errorNotice(
                title: "Konuşma yüklenemedi",
                error: error,
                retry: .conversation(conversation.id)
            )
        }
    }

    public func loadOlderMessages() async {
        guard let conversation = selectedConversation,
              let beforeID = oldestMessageID,
              hasMoreMessages,
              !isLoadingOlderMessages else { return }
        let token = UUID()
        olderToken = token
        let conversationID = conversation.id
        let preservedAnchor = messages.first?.id
        isLoadingOlderMessages = true
        notice = nil
        defer {
            if olderToken == token { isLoadingOlderMessages = false }
        }
        do {
            let page = try await dataSource.conversation(
                id: conversationID,
                limit: Self.pageSize,
                beforeID: beforeID
            )
            guard olderToken == token,
                  selectedConversation?.id == conversationID else { return }
            let existing = Set(messages.map(\.id))
            let older = page.messages.filter { !existing.contains($0.id) }
            messages = deduplicated(older + messages)
            messageCount = page.messageCount
            hasMoreMessages = page.hasMoreMessages
            oldestMessageID = page.oldestMessageID
            historyAnchorRequest = preservedAnchor
        } catch {
            guard olderToken == token else { return }
            notice = errorNotice(
                title: "Eski mesajlar yüklenemedi",
                error: error,
                retry: .olderMessages
            )
        }
    }

    public func prepareNewSession(master: DivanMaster? = nil) {
        let candidate = master ?? therapists.first ?? philosophers.first
        newSessionMaster = candidate
        if let candidate {
            if candidate.supportedModes.contains(.therapy) {
                newSessionMode = .therapy
            } else {
                newSessionMode = .lesson
            }
        }
        isNewSessionPresented = true
    }

    public func createNewSession() async {
        guard let master = newSessionMaster, !isCreatingSession else { return }
        let mode = master.supportedModes.contains(newSessionMode)
            ? newSessionMode
            : (DivanSessionMode.allCases.first {
                master.supportedModes.contains($0)
            } ?? .lesson)
        isCreatingSession = true
        notice = nil
        defer { isCreatingSession = false }
        do {
            let result = try await dataSource.createConversation(
                masterID: master.id,
                mode: mode
            )
            let conversation = result.conversation
            if !result.greeting.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                ephemeralGreetings[conversation.id] = DivanMessage(
                    id: "greeting-\(conversation.id)",
                    serverID: nil,
                    role: .assistant,
                    content: result.greeting,
                    createdAt: Date()
                )
            }
            activeConversations = sortConversations(
                [conversation] + activeConversations.filter { $0.id != conversation.id }
            )
            destination = .recent
            isNewSessionPresented = false
            await openConversation(conversation)
        } catch {
            notice = errorNotice(title: "Yeni görüşme başlatılamadı", error: error)
        }
    }

    public func setSelectedConversationArchived(_ archived: Bool) async {
        guard let conversation = selectedConversation else { return }
        await setConversationArchived(conversation, archived: archived)
    }

    public func setConversationArchived(
        _ conversation: DivanConversation,
        archived: Bool
    ) async {
        guard !isMutatingConversation else { return }
        isMutatingConversation = true
        notice = nil
        defer { isMutatingConversation = false }
        do {
            try await dataSource.setArchived(archived, conversationID: conversation.id)
            let updated = copying(conversation, archived: archived)
            activeConversations.removeAll { $0.id == conversation.id }
            archivedConversations.removeAll { $0.id == conversation.id }
            if archived { archivedConversations.insert(updated, at: 0) }
            else { activeConversations.insert(updated, at: 0) }
            if archived && advancedConversationID == conversation.id {
                advancedConversationID = activeTherapyConversations.first?.id
            }
            if archived {
                clearSchemaChatDraft(
                    conversationID: conversation.id,
                    clearComposer: selectedConversation?.id == conversation.id
                )
            }
            if selectedConversation?.id == conversation.id {
                clearOpenConversation()
            }
        } catch {
            notice = errorNotice(
                title: archived ? "Konuşma arşivlenemedi" : "Konuşma geri alınamadı",
                error: error
            )
        }
    }

    /// Açık görüşmenin özet taslağını yükler. Taslak henüz üretilmediyse
    /// sessizce boş kalır; bu bir hata değildir.
    // MARK: - Defter eylemleri

    public func loadProfile() async {
        do { profileText = try await dataSource.profileText() }
        catch { notice = errorNotice(title: "Hakkımda okunamadı", error: error) }
    }

    public func saveProfile() async {
        guard !isProfileBusy else { return }
        isProfileBusy = true
        defer { isProfileBusy = false }
        do { try await dataSource.updateProfileText(profileText) }
        catch { notice = errorNotice(title: "Hakkımda kaydedilemedi", error: error) }
    }

    /// Seçili ustanın defteri. Usta seçilmemişse sessizce boş kalır.
    public func loadNotebook() async {
        guard let master = selectedMaster ?? masterForLibrary else { return }
        do {
            notebook = try await dataSource.notebook(
                masterID: master.id,
                mode: selectedConversation?.mode ?? .therapy)
        } catch {
            notice = errorNotice(title: "Defter okunamadı", error: error)
        }
    }

    public func loadLetters() async {
        guard let master = selectedMaster ?? masterForLibrary else { return }
        do { letters = try await dataSource.letters(masterID: master.id) }
        catch { notice = errorNotice(title: "Mektuplar okunamadı", error: error) }
    }

    public func loadDreamJournal() async {
        guard let master = selectedMaster ?? masterForLibrary else { return }
        do { dreamJournal = try await dataSource.dreamJournal(masterID: master.id) }
        catch { notice = errorNotice(title: "Rüya defteri okunamadı", error: error) }
    }

    /// Rüya motiflerini ustaya yorumlatır: model çağrısı içerir, yavaştır.
    public func analyzeDreams() async {
        guard let master = selectedMaster ?? masterForLibrary,
              !isDreamAnalysisBusy else { return }
        isDreamAnalysisBusy = true
        defer { isDreamAnalysisBusy = false }
        do {
            _ = try await dataSource.analyzeDreams(masterID: master.id)
            await loadDreamJournal()
        } catch {
            notice = errorNotice(title: "Rüyalar yorumlanamadı", error: error)
        }
    }

    /// Tüm görüşmelerde mesaj ve not araması.
    public func runSearch(_ term: String) async {
        let query = term.trimmingCharacters(in: .whitespacesAndNewlines)
        guard query.count >= 2 else { searchHits = []; return }
        isSearching = true
        defer { isSearching = false }
        do { searchHits = try await dataSource.search(query) }
        catch {
            searchHits = []
            notice = errorNotice(title: "Arama yapılamadı", error: error)
        }
    }

    /// Defter yüzeyleri bir usta bağlamı ister; açık sohbet yoksa
    /// katalogda seçili usta kullanılır.
    private var masterForLibrary: DivanMaster? {
        selectedCatalogMasterID.flatMap { master(id: $0) } ?? therapists.first
    }

    public func loadSessionSummary() async {
        guard let conversation = selectedConversation else {
            sessionSummary = nil
            return
        }
        do {
            sessionSummary = try await dataSource.sessionSummary(
                conversationID: conversation.id)
        } catch {
            sessionSummary = nil
        }
    }

    public func resolveSessionSummary(
        _ action: DivanSummaryAction,
        content: String? = nil
    ) async {
        guard let conversation = selectedConversation, !isSummaryBusy else {
            return
        }
        isSummaryBusy = true
        defer { isSummaryBusy = false }
        do {
            sessionSummary = try await dataSource.updateSessionSummary(
                conversationID: conversation.id,
                action: action,
                content: content
            )
        } catch {
            notice = errorNotice(title: "Özet güncellenemedi", error: error)
        }
    }

    public func setConversationPinned(
        _ conversation: DivanConversation,
        pinned: Bool
    ) async {
        guard !isMutatingConversation else { return }
        isMutatingConversation = true
        notice = nil
        defer { isMutatingConversation = false }
        do {
            try await dataSource.setPinned(pinned, conversationID: conversation.id)
            let updated = copying(conversation, pinned: pinned)
            // Sunucu sıralaması raptiyelileri öne alır; yerel liste de aynı
            // düzeni hemen yansıtsın ki satır gözden kaybolmasın.
            if let index = activeConversations.firstIndex(where: {
                $0.id == conversation.id
            }) {
                activeConversations.remove(at: index)
            }
            if pinned {
                activeConversations.insert(updated, at: 0)
            } else {
                let firstUnpinned = activeConversations.firstIndex {
                    !$0.isPinned
                } ?? activeConversations.endIndex
                activeConversations.insert(updated, at: firstUnpinned)
            }
        } catch {
            notice = errorNotice(
                title: pinned
                    ? "Konuşma raptiyelenemedi"
                    : "Raptiye kaldırılamadı",
                error: error
            )
        }
    }

    public func deleteSelectedConversation() async {
        guard let conversation = selectedConversation else { return }
        await deleteConversation(conversation)
    }

    public func deleteConversation(_ conversation: DivanConversation) async {
        guard !isMutatingConversation else { return }
        isMutatingConversation = true
        notice = nil
        defer { isMutatingConversation = false }
        do {
            try await dataSource.deleteConversation(id: conversation.id)
            activeConversations.removeAll { $0.id == conversation.id }
            archivedConversations.removeAll { $0.id == conversation.id }
            if advancedConversationID == conversation.id {
                advancedConversationID = activeTherapyConversations.first?.id
            }
            clearSchemaChatDraft(
                conversationID: conversation.id,
                clearComposer: selectedConversation?.id == conversation.id
            )
            if selectedConversation?.id == conversation.id {
                clearOpenConversation()
            }
        } catch {
            notice = errorNotice(title: "Konuşma silinemedi", error: error)
        }
    }

    public func endSelectedConversation() async {
        guard let conversation = selectedConversation,
              !conversation.isEnded,
              !isEndingConversation else { return }
        isEndingConversation = true
        notice = nil
        defer { isEndingConversation = false }
        do {
            try await dataSource.endConversation(id: conversation.id)
            clearSchemaChatDraft(
                conversationID: conversation.id,
                clearComposer: true
            )
            let updated = copying(conversation, ended: true)
            selectedConversation = updated
            if let index = activeConversations.firstIndex(where: {
                $0.id == conversation.id
            }) {
                activeConversations[index] = updated
            }
            await refreshConversations(archived: false)
            let refreshed = activeConversations.first(where: {
                $0.id == conversation.id
            }) ?? updated
            await openConversation(refreshed)
            chatStatusText = "Seans tamamlandı. Bu konuşma artık salt okunur."
        } catch {
            notice = errorNotice(title: "Seans bitirilemedi", error: error)
        }
    }

    public func sendComposerMessage() async {
        let text = composerText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, !schemaComposerLockedByCard else { return }
        let binding = schemaComposerBinding
        composerText = ""
        await performSend(
            text: text,
            appendUserMessage: true,
            schemaBinding: binding
        )
    }

    public func reloadConversationAfterFailedResponse() async {
        guard let conversation = selectedConversation, !isSending else { return }
        await openConversation(conversation)
    }

    private func performSend(
        text: String,
        appendUserMessage: Bool,
        schemaBinding: SchemaChatBinding? = nil
    ) async {
        guard let conversation = selectedConversation,
              !conversation.isEnded,
              !conversation.isArchived,
              !isSending else {
            if appendUserMessage { composerText = text }
            return
        }
        let conversationID = conversation.id
        let schemaV5SilentAssistant = schemaBinding?.protocol
            == "schema_path_chat_v5"
        let requestSchemaProjectionAnchor = schemaSendProjectionAnchor()
        let token = UUID()
        sendToken = token
        let now = Date()
        var userPlaceholderID: String?
        if appendUserMessage {
            let localUserID = "local-user-\(UUID().uuidString)"
            userPlaceholderID = localUserID
            messages.append(DivanMessage(
                id: localUserID,
                serverID: nil,
                role: .user,
                content: text,
                createdAt: now
            ))
        }
        let pendingID = "local-assistant-\(UUID().uuidString)"
        if !schemaV5SilentAssistant {
            messages.append(DivanMessage(
                id: pendingID,
                serverID: nil,
                role: .assistant,
                content: "",
                createdAt: now,
                isPending: true
            ))
        }
        isSending = true
        chatStatusText = "yanıt hazırlanıyor"
        scrollToLatestRequest = UUID()

        let stream = await dataSource.sendMessage(
            conversationID: conversationID,
            text: text,
            schemaBinding: schemaBinding
        )
        var acceptedByCore = false
        do {
            for try await update in stream {
                guard sendToken == token else { return }
                if case .accepted = update { acceptedByCore = true }
                if applyChatUpdate(
                    update,
                    pendingID: pendingID,
                    userPlaceholderID: userPlaceholderID,
                    requestSchemaBinding: schemaBinding,
                    requestSchemaProjectionAnchor:
                        requestSchemaProjectionAnchor
                ) {
                    scrollToLatestRequest = UUID()
                }
            }
            guard sendToken == token else { return }
            if schemaV5SilentAssistant {
                try? await reloadLatestSchemaConversationMessages(
                    conversationID: conversationID
                )
            } else if messages.first(where: { $0.id == pendingID })?
                        .failedDescription == nil {
                finishPendingMessage(pendingID: pendingID)
            }
        } catch {
            guard sendToken == token else { return }
            if schemaBinding != nil && !acceptedByCore {
                messages.removeAll {
                    $0.id == pendingID || $0.id == userPlaceholderID
                }
                if composerText.isEmpty { composerText = text }
                let message = schemaErrorMessage(error)
                schemaStatusText = message
                notice = DivanNotice(
                    title: "Şema sohbet yanıtı gönderilemedi",
                    message: message,
                    retry: nil
                )
                await refreshSchemaRecommendations()
            } else if schemaV5SilentAssistant {
                // A v5 request may already have committed its user row while
                // the stream was interrupted. Reload durable rows without
                // manufacturing an assistant failure bubble.
                try? await reloadLatestSchemaConversationMessages(
                    conversationID: conversationID
                )
                notice = DivanNotice(
                    title: "Şema sohbet yanıtı tamamlanamadı",
                    message: error.localizedDescription,
                    retry: .conversation(conversationID)
                )
            } else {
                markPendingMessageFailed(
                    pendingID,
                    message: error.localizedDescription
                )
            }
        }
        if sendToken == token {
            isSending = false
            if !messages.contains(where: { $0.failedDescription != nil }) {
                chatStatusText = ""
            }
            await refreshConversations(archived: false)
            if isYoungSchemaConversation,
               messages.first(where: { $0.id == pendingID })?.failedDescription == nil {
                await refreshSchemaRecommendations(waitForRunningAnalysis: true)
            }
        }
    }

    @discardableResult
    private func applyChatUpdate(
        _ update: DivanChatUpdate,
        pendingID: String,
        userPlaceholderID: String?,
        requestSchemaBinding: SchemaChatBinding?,
        requestSchemaProjectionAnchor: SchemaSendProjectionAnchor
    ) -> Bool {
        switch update {
        case .accepted(_, let userMessageID):
            if let userPlaceholderID, let userMessageID {
                mutateMessage(id: userPlaceholderID) {
                    $0.serverID = userMessageID
                }
            }
            chatStatusText = "istek alındı"
            return false
        case .assistantStarted:
            chatStatusText = "yazıyor"
            return false
        case .assistantDelta(let text):
            mutateMessage(id: pendingID) {
                $0.content += text
                $0.isPending = true
            }
            chatStatusText = "yazıyor"
            return !text.isEmpty
        case .assistantReplaced(let text):
            mutateMessage(id: pendingID) {
                $0.content = text
                $0.isPending = true
            }
            chatStatusText = "yazıyor"
            return !text.isEmpty
        case .status(let text):
            if !text.isEmpty { chatStatusText = text }
            return false
        case .assistantCompleted(
            let messageID,
            _,
            let technique,
            let messageMeta,
            let nextCard,
            let schemaPath,
            let interactionPolicy,
            let resumeState,
            let schemaBindingResult
        ):
            if let messageID {
                mutateMessage(id: pendingID) {
                    $0.serverID = messageID
                    $0.technique = technique
                    $0.schemaMetaEvents = messageMeta
                }
            }
            if let userPlaceholderID {
                mutateMessage(id: userPlaceholderID) {
                    $0.schemaBindingResult = schemaBindingResult
                }
            }
            // Ordinary streaming does not carry public IDs separately. The
            // exact, contract-validated candidate envelope does, so install
            // that lineage onto only the just-accepted adjacent local pair.
            installCandidateLineageOnExactLocalPair(nextCard)
            if !messageMeta.isEmpty {
                streamedSchemaMessageMeta = messageMeta
            }
            if !suppressInFlightSchemaCardProjection,
               streamedSchemaProjectionStillBelongsToRequest(
                    requestSchemaBinding,
                    requestAnchor: requestSchemaProjectionAnchor
               ) {
                let streamedCursor = schemaProjectionCursor(
                    card: nextCard,
                    result: schemaBindingResult
                )
                applySchemaStreamProjection(
                    activePath: schemaPath,
                    interactionPolicy: interactionPolicy,
                    resumeState: resumeState,
                    nextCard: nextCard,
                    result: schemaBindingResult
                )
                streamedSchemaCard = nextCard
                authoritativeStreamedSchemaCursor = streamedCursor
                hasAuthoritativeStreamedSchemaCard = true
            }
            if let schemaBindingResult,
               let message = schemaBindingResult.failureMessage {
                schemaStatusText = message
            }
            if messages.first(where: { $0.id == pendingID })?
                .failedDescription == nil {
                finishPendingMessage(pendingID: pendingID)
            }
            return true
        case .failed(let message, _):
            markPendingMessageFailed(
                pendingID,
                message: message
            )
            return true
        }
    }

    private func streamedSchemaProjectionStillBelongsToRequest(
        _ requestBinding: SchemaChatBinding?,
        requestAnchor: SchemaSendProjectionAnchor
    ) -> Bool {
        // Even ordinary chat can finish after background analysis or another
        // device has published a candidate/path. It may project only while
        // the reducer identity is still exactly what this request started
        // from; otherwise its older null/card would erase the newer state.
        guard let requestBinding else {
            return schemaSendProjectionAnchor() == requestAnchor
        }
        // A bound clinical turn is additionally pinned to the full hidden
        // binding. Only its exact outbound identity may replace the current
        // dashboard projection.
        guard let snapshot = schemaPathSnapshot,
              snapshot.protocol == requestBinding.protocol,
              (requestBinding.protocol == "schema_path_chat_v4"
                && snapshot.version == 4
                || requestBinding.protocol == "schema_path_chat_v5"
                && snapshot.version == 5),
              let path = snapshot.activePath,
              ["active", "paused"].contains(path.status),
              path.id == requestBinding.pathId,
              path.publicId == requestBinding.pathPublicId,
              path.revision == requestBinding.expectedRevision,
              path.step == requestBinding.stepId,
              let card = activeSchemaCard,
              card.chatBinding == requestBinding,
              card.checkpoint?.publicId
                == requestBinding.checkpointPublicId,
              card.checkpoint?.seq
                == requestBinding.expectedCheckpointSeq else {
            return false
        }
        return true
    }

    private func schemaSendProjectionAnchor() -> SchemaSendProjectionAnchor {
        let path = schemaPathSnapshot?.activePath
        let card = activeSchemaCard
        return SchemaSendProjectionAnchor(
            pathPublicID: path?.publicId,
            pathID: path?.id,
            pathStatus: path?.status,
            revision: path?.revision ?? schemaPathSnapshot?.revision,
            step: path?.step ?? schemaPathSnapshot?.step,
            checkpointPublicID: card?.checkpoint?.publicId,
            checkpointSeq: card?.checkpoint?.seq,
            cardID: card?.id
        )
    }

    private func startBackgroundPoll(
        _ initial: DivanPendingChat,
        conversationID: Int,
        placeholderID: String,
        suppressAssistantPlaceholder: Bool = false
    ) {
        let token = UUID()
        backgroundPollToken = token
        Task { [weak self] in
            guard let self else { return }
            var status = initial
            for _ in 0..<300 {
                guard self.backgroundPollToken == token,
                      self.selectedConversation?.id == conversationID else { return }
                if status.isTerminal { break }
                try? await Task.sleep(for: .seconds(2))
                guard self.backgroundPollToken == token else { return }
                do {
                    status = try await self.dataSource.chatStatus(
                        requestID: initial.requestID
                    )
                    guard self.selectedConversation?.id == conversationID else { return }
                    if !suppressAssistantPlaceholder,
                       !status.content.isEmpty {
                        if self.messages.contains(where: { $0.id == placeholderID }) {
                            self.mutateMessage(id: placeholderID) {
                                $0.content = status.content
                            }
                        } else {
                            self.messages.append(DivanMessage(
                                id: placeholderID,
                                serverID: nil,
                                role: .assistant,
                                content: status.content,
                                createdAt: Date(),
                                isPending: true
                            ))
                        }
                    }
                    self.chatStatusText = status.waitingForProvider
                        ? "sağlayıcı bekleniyor" : "arka planda yanıt hazırlanıyor"
                } catch {
                    self.chatStatusText = "yanıt durumu yeniden denetlenecek"
                }
            }
            guard self.backgroundPollToken == token,
                  self.selectedConversation?.id == conversationID else { return }
            self.backgroundPollToken = UUID()
            if status.status.localizedLowercase == "failed" {
                if suppressAssistantPlaceholder {
                    self.notice = DivanNotice(
                        title: "Şema sohbet yanıtı tamamlanamadı",
                        message: "Konuşmayı yenileyerek dayanıklı son durumu denetleyin.",
                        retry: .conversation(conversationID)
                    )
                } else {
                    self.markPendingMessageFailed(
                        placeholderID,
                        message: "Arka plandaki yanıt tamamlanamadı. Konuşmayı yenileyin."
                    )
                }
                self.isSending = false
                return
            }
            if status.isTerminal, let conversation = self.selectedConversation {
                await self.openConversation(conversation)
            } else {
                self.isSending = false
                self.chatStatusText = "yanıt durumu doğrulanamadı"
                self.notice = DivanNotice(
                    title: "Yanıt hâlâ beklemede görünüyor",
                    message: "Konuşmayı yenileyerek sunucudaki son durumu denetleyin.",
                    retry: .conversation(conversationID)
                )
            }
        }
    }

    private func finishPendingMessage(pendingID: String) {
        mutateMessage(id: pendingID) {
            $0.isPending = false
            $0.failedDescription = $0.content.isEmpty
                ? "Yanıt tamamlandı ancak içerik alınamadı. Konuşmayı yenileyin."
                : nil
        }
    }

    private func markPendingMessageFailed(
        _ pendingID: String,
        message: String
    ) {
        mutateMessage(id: pendingID) {
            $0.isPending = true
            $0.failedDescription = message.isEmpty
                ? DivanStrings.responseIncomplete : message
        }
        chatStatusText = "yanıt tamamlanamadı"
    }

    private func mutateMessage(id: String, mutation: (inout DivanMessage) -> Void) {
        guard let index = messages.firstIndex(where: { $0.id == id }) else { return }
        mutation(&messages[index])
    }

    // MARK: - Kerem Genç completed-turn schema recommendations

    public func canAnalyzeSchemaTurn(_ message: DivanMessage) -> Bool {
        let analyzed = Set(
            schemaPathSnapshot?.turnAnalysis?.analyzedUserMessageIds ?? []
        )
        let processing = Set(
            schemaPathSnapshot?.turnAnalysis?.processingUserMessageIds ?? []
        )
        guard let index = messages.firstIndex(where: { $0.id == message.id }) else {
            return false
        }
        let pairedAssistant = messages[messages.index(after: index)...]
            .first { $0.role != .system }
        let pairIsDurablyComplete = pairedAssistant?.role == .assistant
            && pairedAssistant?.serverID != nil
            && pairedAssistant?.isPending == false
            && pairedAssistant?.failedDescription == nil
        return isYoungSchemaConversation && schemaPathSnapshot?.schemaMode?.enabled == true
            && schemaPathSnapshot?.turnAnalysis?.provider != nil
            && message.role == .user && message.serverID != nil
            && !message.isPending && message.failedDescription == nil
            && pairIsDurablyComplete
            && !analyzed.contains(message.serverID ?? 0)
            && !processing.contains(message.serverID ?? 0)
    }

    public var schemaModeNeedsLocalConfirmation: Bool {
        guard isYoungSchemaConversation,
              let mode = schemaPathSnapshot?.schemaMode else { return false }
        return !mode.enabled && mode.preferenceEnabled
            && (mode.pendingDeviceConfirmation
                || mode.pendingProviderConfirmation
                || mode.reason == "device_confirmation_required"
                || mode.reason == "provider_confirmation_required")
    }

    public func confirmSchemaModeOnThisDevice() async {
        guard schemaModeNeedsLocalConfirmation,
              let conversationID = selectedConversation?.id,
              !schemaModeConfirmationBusy else { return }
        guard let provider = schemaPathSnapshot?.turnAnalysis?.provider else {
            schemaStatusText = "Şema terapisi tercihi açık; bu cihazda sağlayıcı ve model seçilip ayrıca onaylanana kadar hiçbir mesaj modele gönderilmez."
            return
        }
        schemaModeConfirmationBusy = true
        schemaStatusText = "Bu cihazdaki sağlayıcı onaylanıyor…"
        let key = [
            "schema", "device-confirm", String(conversationID),
            provider.id, provider.model,
        ].joined(separator: "|")
        do {
            _ = try await dataSource.mutateSchemaTurnAnalysis(.init(
                action: .setMode,
                conversationID: conversationID,
                requestID: schemaRequestID(for: key),
                enabled: true,
                providerID: provider.id,
                modelID: provider.model
            ))
            schemaRequestIDs.removeValue(forKey: key)
            schemaStatusText = "Bu cihaz için onaylandı; yalnız bundan sonra tamamlanan Kerem turları incelenecek."
            await refreshSchemaRecommendations()
        } catch {
            schemaStatusText = (error as? LocalizedError)?.errorDescription
                ?? error.localizedDescription
        }
        schemaModeConfirmationBusy = false
    }

    public func refreshSchemaRecommendations(
        waitForRunningAnalysis: Bool = false
    ) async {
        guard isYoungSchemaConversation,
              let conversationID = selectedConversation?.id else {
            if let conversationID = selectedConversation?.id {
                clearSchemaChatDraft(
                    conversationID: conversationID,
                    clearComposer: true
                )
            }
            schemaPollToken = UUID()
            schemaPromptPollToken = UUID()
            schemaPathSnapshot = nil
            schemaStatusText = ""
            streamedSchemaCard = nil
            streamedSchemaMessageMeta = []
            hasAuthoritativeStreamedSchemaCard = false
            authoritativeStreamedSchemaCursor = nil
            suppressInFlightSchemaCardProjection = false
            return
        }
        do {
            let value = try await dataSource.schemaPath(
                conversationID: conversationID
            )
            guard selectedConversation?.id == conversationID else { return }
            let projectionDecision = schemaDurableProjectionDecision(
                against: value
            )
            switch projectionDecision {
            case .acceptDurable:
                schemaPathSnapshot = value
                streamedSchemaCard = nil
                hasAuthoritativeStreamedSchemaCard = false
                authoritativeStreamedSchemaCursor = nil
            case .preserveStreamedSnapshot:
                // The SSE done envelope is an atomic schema projection. Keep
                // its path, policy, checkpoint and card together while GET is
                // behind; mixing a newer card with an older path deadlocks the
                // hidden composer binding.
                break
            case .conflict:
                // Keep both projections available to `activeSchemaCard`,
                // which fails closed on equal-cursor identity disagreement.
                schemaPathSnapshot = value
            }
            installCandidateLineageOnExactLocalPair(activeSchemaCard)
            streamedSchemaMessageMeta = []
            suppressInFlightSchemaCardProjection = false
            reconcileSchemaComposerDraft(conversationID: conversationID)
            if value.turnAnalysis?.processing == true || waitForRunningAnalysis {
                scheduleSchemaRecommendationPoll(conversationID: conversationID)
            }
            if schemaV5PromptNeedsPolling(value) {
                scheduleSchemaPromptDeliveryPoll(conversationID: conversationID)
            }
        } catch {
            // Recommendations are a derived, optional surface. A transient
            // failure must not obscure or fail the authoritative chat.
        }
    }

    private func schemaDurableProjectionDecision(
        against durableSnapshot: SchemaPathSnapshot
    ) -> SchemaDurableProjectionDecision {
        guard hasAuthoritativeStreamedSchemaCard else {
            return .acceptDurable
        }
        // An explicit SSE `next_card:null` is authoritative and prevents a
        // lagging GET from resurrecting a completed/stopped prompt, but a new
        // path/candidate or a genuinely newer cursor must supersede it.
        guard let streamedSchemaCard else {
            guard let authoritativeStreamedSchemaCursor else {
                return .acceptDurable
            }
            if let durable = durableSnapshot.nextCard {
                // A fast local analysis may publish the candidate for the
                // assistant bubble that just completed before GET ever
                // exposes an intermediate pathless nil. That exact current
                // pair is newer than the null SSE barrier; older delayed
                // candidates remain suppressed until durable nil catches up.
                if authoritativeStreamedSchemaCursor.pathID == nil,
                   authoritativeStreamedSchemaCursor.pathPublicID == nil,
                   durable.kind == "candidate_prompt",
                   durable.pathId == nil,
                   durable.pathPublicId == nil,
                   durable.source.assistantMessageId
                    == latestRealAssistantMessageID {
                    return .acceptDurable
                }
                let samePathCursor = durable.pathId
                        == authoritativeStreamedSchemaCursor.pathID
                    && durable.pathPublicId
                        == authoritativeStreamedSchemaCursor.pathPublicID
                    && durable.revision
                        == authoritativeStreamedSchemaCursor.revision
                    && durable.checkpoint?.seq
                        == authoritativeStreamedSchemaCursor.checkpointSeq
                if samePathCursor,
                   durable.checkpoint?.publicId
                    != authoritativeStreamedSchemaCursor.checkpointPublicID {
                    return .conflict
                }
            }
            return durableSnapshotSupersedesStreamedNull(
                durableSnapshot,
                cursor: authoritativeStreamedSchemaCursor
            ) ? .acceptDurable : .preserveStreamedSnapshot
        }
        guard let durable = durableSnapshot.nextCard else {
            if let durableRevision = durableSnapshot.revision,
               let streamedRevision = streamedSchemaCard.revision {
                return durableRevision <= streamedRevision
                    ? .preserveStreamedSnapshot : .acceptDurable
            }
            return .preserveStreamedSnapshot
        }
        let sameCursor = streamedSchemaCard.id == durable.id
            && streamedSchemaCard.pathId == durable.pathId
            && streamedSchemaCard.pathPublicId == durable.pathPublicId
            && streamedSchemaCard.revision == durable.revision
            && streamedSchemaCard.checkpoint?.seq == durable.checkpoint?.seq
            && streamedSchemaCard.checkpoint?.publicId
                == durable.checkpoint?.publicId
            && streamedSchemaCard.promptDelivery == durable.promptDelivery
            && streamedSchemaCard.chatBinding == durable.chatBinding
        if sameCursor {
            return .acceptDurable
        }
        switch schemaProjectionOrder(
            streamed: streamedSchemaCard,
            durable: durable
        ) {
        case .streamed:
            return .preserveStreamedSnapshot
        case .conflict:
            return .conflict
        case .durable:
            return .acceptDurable
        }
    }

    private func applySchemaStreamProjection(
        activePath: SchemaPath?,
        interactionPolicy: SchemaPathInteractionPolicy?,
        resumeState: SchemaPathResumeState?,
        nextCard: SchemaCardEnvelope?,
        result: SchemaChatBindingResult?
    ) {
        guard let current = schemaPathSnapshot,
              (current.protocol == "schema_path_chat_v4"
                && current.version == 4
                || current.protocol == "schema_path_chat_v5"
                && current.version == 5) else { return }
        schemaPathSnapshot = SchemaPathSnapshot(
            version: current.version,
            protocol: current.protocol,
            presentation: current.presentation,
            stage: activePath?.stage ?? nextCard?.stage ?? result?.stage,
            step: activePath?.step ?? nextCard?.step ?? result?.step,
            revision: activePath?.revision ?? nextCard?.revision
                ?? result?.pathRevision,
            progress: nextCard?.progress ?? current.progress,
            nextCard: nextCard,
            messageMeta: current.messageMeta,
            interactionPolicy: interactionPolicy,
            resumeState: resumeState,
            clinicalSync: current.clinicalSync,
            activePath: activePath,
            candidates: current.candidates,
            queuedCandidates: current.queuedCandidates,
            queuedCount: current.queuedCount,
            activePathNotice: current.activePathNotice,
            methods: current.methods,
            notices: current.notices,
            allowedActions: current.allowedActions,
            completedTurns: current.completedTurns,
            minimumListeningTurns: current.minimumListeningTurns,
            schemaMode: current.schemaMode,
            turnAnalysis: current.turnAnalysis,
            focus: current.focus,
            inlineSuggestions: current.inlineSuggestions,
            focusMinimumTurns: current.focusMinimumTurns,
            origin: current.origin,
            growth: current.growth,
            healthyAdult: current.healthyAdult,
            presentTransfer: current.presentTransfer
        )
    }

    public func analyzeSchemaTurn(_ message: DivanMessage) async {
        guard canAnalyzeSchemaTurn(message),
              let conversationID = selectedConversation?.id,
              let messageID = message.serverID,
              let provider = schemaPathSnapshot?.turnAnalysis?.provider,
              schemaBusyMessageID == nil else { return }
        schemaBusyMessageID = messageID
        schemaStatusText = "Bu tamamlanmış mesaj çifti inceleniyor…"
        let key = "schema|analyze-turn|\(conversationID)|\(messageID)"
        do {
            let result = try await dataSource.mutateSchemaTurnAnalysis(
                SchemaTurnAnalysisMutation(
                    action: .analyzeTurn,
                    conversationID: conversationID,
                    requestID: schemaRequestID(for: key),
                    userMessageID: messageID,
                    consent: true,
                    providerID: provider.id,
                    modelID: provider.model
                )
            )
            schemaRequestIDs.removeValue(forKey: key)
            schemaStatusText = result.alreadyAnalyzed == true
                ? "Bu tamamlanmış mesaj çifti daha önce incelendi."
                : "Mesaj çifti incelemesi sıraya alındı."
            await refreshSchemaRecommendations(waitForRunningAnalysis: true)
        } catch {
            schemaStatusText = (error as? LocalizedError)?.errorDescription
                ?? error.localizedDescription
        }
        if schemaBusyMessageID == messageID { schemaBusyMessageID = nil }
    }

    public func reviewSchemaRecommendation(
        _ candidate: SchemaCandidate,
        decision: SchemaCandidateDecision
    ) async {
        guard isYoungSchemaConversation,
              let conversationID = selectedConversation?.id,
              schemaBusyCandidateID == nil else { return }
        schemaBusyCandidateID = candidate.id
        let key = "schema|conversation-review|\(candidate.id)|\(decision.rawValue)"
        do {
            let result = try await dataSource.mutateSchemaPath(
                SchemaPathMutation(
                    action: .reviewCandidate,
                    conversationID: conversationID,
                    requestID: schemaRequestID(for: key),
                    claimID: candidate.id,
                    decision: decision
                )
            )
            schemaRequestIDs.removeValue(forKey: key)
            schemaPathSnapshot = result.snapshot
            switch decision {
            case .accept, .confirm:
                schemaStatusText = "Olasılık size ait bir çalışma adayı olarak kabul edildi. Başlatmak için ayrıca “Bunu çalışalım”ı seçin."
            case .defer, .unsure:
                schemaStatusText = "Olasılık sonraki görüşmeye bırakıldı."
            case .dismiss, .reject:
                schemaStatusText = "Olasılık şimdilik kapatıldı."
            default:
                schemaStatusText = "Değerlendirmeniz kaydedildi."
            }
        } catch {
            schemaStatusText = (error as? LocalizedError)?.errorDescription
                ?? error.localizedDescription
        }
        if schemaBusyCandidateID == candidate.id { schemaBusyCandidateID = nil }
    }

    public func startSchemaRecommendation(_ candidate: SchemaCandidate) async {
        guard isYoungSchemaConversation,
              schemaPathSnapshot?.activePath == nil,
              candidate.approvedForPath,
              let conversationID = selectedConversation?.id,
              schemaBusyCandidateID == nil else { return }
        schemaBusyCandidateID = candidate.id
        let key = "schema|conversation-start|\(candidate.id)"
        do {
            let result = try await dataSource.mutateSchemaPath(
                SchemaPathMutation(
                    action: .start,
                    conversationID: conversationID,
                    requestID: schemaRequestID(for: key),
                    claimID: candidate.id
                )
            )
            schemaRequestIDs.removeValue(forKey: key)
            schemaPathSnapshot = result.snapshot
            schemaStatusText = "Bu şema çalışma yolu başladı. Diğer olasılıklar başka görüşmeye ayrıldı."
        } catch {
            schemaStatusText = (error as? LocalizedError)?.errorDescription
                ?? error.localizedDescription
        }
        if schemaBusyCandidateID == candidate.id { schemaBusyCandidateID = nil }
    }

    public func resolveSchemaInlineSuggestion(
        _ suggestion: SchemaInlineSuggestion,
        accept: Bool
    ) async {
        guard isYoungSchemaConversation,
              let conversationID = selectedConversation?.id,
              schemaPathSnapshot?.activePath == nil,
              schemaBusySuggestionID == nil else { return }
        schemaBusySuggestionID = suggestion.id
        let action: SchemaPathAction = accept
            ? .acceptSuggestion : .dismissSuggestion
        let key = [
            "schema", "inline-suggestion", action.rawValue,
            String(conversationID), String(suggestion.id),
        ].joined(separator: "|")
        do {
            let result = try await dataSource.mutateSchemaPath(
                SchemaPathMutation(
                    action: action,
                    conversationID: conversationID,
                    requestID: schemaRequestID(for: key),
                    suggestionID: suggestion.id
                )
            )
            schemaRequestIDs.removeValue(forKey: key)
            schemaPathSnapshot = result.snapshot
            schemaStatusText = accept
                ? "Bu olasılık adaylara eklendi. Çalışmayı başlatmak için ayrıca onaylayın."
                : "Bu mod önerisi kapatıldı."
        } catch {
            schemaStatusText = (error as? LocalizedError)?.errorDescription
                ?? error.localizedDescription
        }
        if schemaBusySuggestionID == suggestion.id {
            schemaBusySuggestionID = nil
        }
    }

    public func submitSchemaCard(
        _ card: SchemaCardEnvelope,
        action: SchemaCardActionEnvelope,
        fieldValues: [String: JSONValue]
    ) async {
        guard let actionID = SchemaChatCardAction(rawValue: action.action) else {
            schemaStatusText = "Bu işlem bu Mac sürümünde desteklenmiyor."
            return
        }
        let safetyActions: Set<SchemaChatCardAction> = [
            .pause, .resumePath, .groundChatTechnique, .stop,
        ]
        guard usesSchemaChatOnlyPresentation,
              let current = activeSchemaCard,
              current.id == card.id,
              current.revision == card.revision,
              current == card,
              current.isActive,
              current.isSupportedByNativeContract,
              current.presentation == "chat_only",
              current.fields.isEmpty,
              fieldValues.isEmpty,
              current.actions.contains(action),
              let conversationID = selectedConversation?.id,
              schemaBusyCardID == nil,
              !isSending || safetyActions.contains(actionID) else {
            schemaStatusText = "Bu kart artık etkin değil; güncel adım gösteriliyor."
            await refreshSchemaRecommendations()
            return
        }
        guard let path = schemaPathSnapshot?.activePath else {
            guard schemaCandidateSourceMatchesLoadedChat(current) else {
                schemaStatusText =
                    "Bu başlangıç kartının kaynak mesaj bağı doğrulanamadı."
                await refreshSchemaRecommendations()
                return
            }
            await submitSchemaPrepathCard(
                current,
                action: action,
                actionID: actionID,
                conversationID: conversationID
            )
            return
        }
        let pathAndActionAreCompatible: Bool = {
            switch (card.kind, path.status, actionID) {
            case ("chat_prompt", "active", _):
                return true
            case ("resume", "paused", .resumePath),
                 ("resume", "paused", .stop),
                 ("resume", "active", .pause),
                 ("resume", "active", .stop),
                 ("blocked", "active", .pause),
                 ("blocked", "active", .stop),
                 ("blocked", "paused", .stop):
                return true
            default:
                return false
            }
        }()
        guard let pathPublicID = path.publicId,
              SchemaPathCheckpoint.isPublicID(pathPublicID),
              card.pathId == path.id,
              card.pathPublicId == pathPublicID,
              let cardRevision = card.revision,
              schemaPathSnapshot?.revision == cardRevision,
              path.revision == cardRevision,
              schemaPathSnapshot?.stage == card.stage,
              schemaPathSnapshot?.step == card.step,
              path.stage == card.stage,
              path.step == card.step,
              pathAndActionAreCompatible else {
            schemaStatusText = "Bu kartın çalışma yolu kimliği değişti; güncel adım açılıyor."
            await refreshSchemaRecommendations()
            return
        }

        var values = action.payload
        let techniqueReplyActions: Set<SchemaChatCardAction> = [
            .groundChatTechnique,
        ]
        let payloadStepID: String? = {
            guard case .string(let value)? = values.removeValue(forKey: "step_id")
            else { return nil }
            return value
        }()
        let payloadTechniqueRevision: Int? = {
            guard case .number(let value)? = values.removeValue(
                forKey: "expected_technique_revision"
            ), value.isFinite, value.rounded() == value,
                  value >= 0, value <= Double(Int.max) else { return nil }
            return Int(value)
        }()
        if techniqueReplyActions.contains(actionID) {
            guard let activeLink = path.activeTechniqueLink,
                  payloadTechniqueRevision == nil
                    || payloadTechniqueRevision == activeLink.techniqueRevision,
                  case .number(let rawLink)? = values["technique_link_id"],
                  rawLink.isFinite, rawLink.rounded() == rawLink,
                  rawLink > 0, rawLink <= Double(Int.max),
                  Int(rawLink) == activeLink.id,
                  case .string(let publicLinkID)? =
                    values["technique_link_public_id"],
                  publicLinkID == activeLink.publicId,
                  values["control_only"] == .bool(true),
                  Set(values.keys) == Set([
                      "technique_link_id", "technique_link_public_id",
                      "control_only",
                  ]) else {
                schemaStatusText = "Teknik kartı güncel bağlantıyla uyuşmuyor; son adım açılıyor."
                await refreshSchemaRecommendations()
                return
            }
        }
        let expectedRevision = schemaPathSnapshot?.revision ?? card.revision
        let key = [
            "schema-card", String(conversationID), card.id,
            String(describing: card.revision),
            String(card.checkpoint?.seq ?? -1), action.id,
        ].joined(separator: "|")
        let isDirectControl = safetyActions.contains(actionID)
        let mutation = SchemaCardMutation(
            action: actionID,
            conversationID: conversationID,
            requestID: schemaRequestID(for: key),
            pathID: path.id,
            pathPublicID: pathPublicID,
            expectedRevision: expectedRevision,
            sourceUserMessageID: isDirectControl
                ? nil : card.source.userMessageId,
            sourceAssistantMessageID: isDirectControl
                ? nil : card.source.assistantMessageId,
            stepID: techniqueReplyActions.contains(actionID)
                ? (payloadStepID ?? card.step) : nil,
            clientEventID: nil,
            expectedTechniqueRevision: techniqueReplyActions.contains(actionID)
                ? path.activeTechniqueLink?.techniqueRevision : nil,
            values: values
        )
        await performSchemaCardMutation(
            mutation,
            cardID: card.id,
            requestKey: key
        )
    }

    public func retryFailedSchemaCard() async {
        guard let cardID = schemaFailedCardID,
              schemaBusyCardID == nil else { return }
        if let mutation = failedSchemaCardMutation {
            await performSchemaCardMutation(
                mutation,
                cardID: cardID,
                requestKey: nil
            )
        } else if let mutation = failedSchemaPrepathMutation {
            await performSchemaPrepathMutation(
                mutation,
                cardID: cardID,
                requestKey: nil
            )
        }
    }

    public func submitSchemaMetaAction(
        event: SchemaMessageMetaEvent,
        action: SchemaCardActionEnvelope,
        note: String? = nil
    ) async {
        guard usesSchemaChatProtocol,
              ["active", "private"].contains(event.status),
              event.actions.contains(action),
              let actionID = SchemaChatCardAction(rawValue: action.action),
              [.undoMapUpdate, .makeMapUpdatePrivate, .editMapUpdate]
                .contains(actionID),
              let conversationID = selectedConversation?.id,
              schemaBusyCardID == nil,
              !isSending else { return }

        func exactInteger(_ value: JSONValue?) -> Int? {
            guard case .number(let raw)? = value,
                  raw.isFinite, raw.rounded() == raw,
                  raw >= 0, raw <= Double(Int.max) else { return nil }
            return Int(raw)
        }

        guard let payloadMetaID = exactInteger(action.payload["meta_event_id"]),
              payloadMetaID > 0,
              payloadMetaID == event.databaseId,
              case .string(let payloadPublicID)? =
                action.payload["meta_event_public_id"],
              !payloadPublicID.isEmpty,
              payloadPublicID == event.publicId,
              let payloadGeneration = exactInteger(
                action.payload["clinical_generation"]
              ),
              payloadGeneration == event.clinicalGeneration,
              let sourceUserID = event.sourceUserMessageId,
              let sourceAssistantID = event.sourceAssistantMessageId,
              sourceUserID > 0, sourceAssistantID > 0,
              exactInteger(action.payload["source_user_message_id"])
                == sourceUserID,
              exactInteger(action.payload["source_assistant_message_id"])
                == sourceAssistantID else {
            schemaStatusText = "Yaşayan Harita kartının kimlik veya mesaj dayanağı değişti; güncel kartı açın."
            return
        }

        let pathID: Int?
        let pathPublicID: String?
        let expectedRevision: Int?
        if let eventPathID = event.pathId {
            guard eventPathID > 0,
                  let eventPathPublicID = event.pathPublicId,
                  !eventPathPublicID.isEmpty,
                  let eventRevision = event.expectedRevision,
                  eventRevision >= 0,
                  exactInteger(action.payload["path_id"]) == eventPathID,
                  exactInteger(action.payload["expected_revision"])
                    == eventRevision else {
                schemaStatusText = "Yaşayan Harita kartının çalışma yolu değişti; güncel kartı açın."
                return
            }
            pathID = eventPathID
            pathPublicID = eventPathPublicID
            expectedRevision = eventRevision
        } else {
            guard event.expectedRevision == nil,
                  event.pathPublicId == nil,
                  action.payload["path_id"] == nil,
                  action.payload["expected_revision"] == nil else {
                schemaStatusText = "Dinleme aşaması Harita kartına geçersiz çalışma yolu eklenmiş."
                return
            }
            pathID = nil
            pathPublicID = nil
            expectedRevision = nil
        }

        var values: [String: JSONValue] = [
            "meta_event_id": .number(Double(payloadMetaID)),
            "meta_event_public_id": .string(payloadPublicID),
            "clinical_generation": .number(Double(payloadGeneration)),
        ]
        if actionID == .editMapUpdate {
            let clean = note?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            guard !clean.isEmpty else {
                schemaStatusText = "Harita notu boş bırakılamaz."
                return
            }
            values["note"] = .string(clean)
        }
        let key = [
            "schema-meta", event.publicId,
            String(expectedRevision ?? payloadGeneration), action.id,
        ].joined(separator: "|")
        let mutation = SchemaCardMutation(
            action: actionID,
            conversationID: conversationID,
            requestID: schemaRequestID(for: key),
            pathID: pathID,
            pathPublicID: pathPublicID,
            expectedRevision: expectedRevision,
            sourceUserMessageID: sourceUserID,
            sourceAssistantMessageID: sourceAssistantID,
            values: values
        )
        await performSchemaCardMutation(
            mutation,
            cardID: "meta-\(event.publicId)",
            requestKey: key
        )
    }

    private func performSchemaCardMutation(
        _ mutation: SchemaCardMutation,
        cardID: String,
        requestKey: String?
    ) async {
        schemaBusyCardID = cardID
        schemaFailedCardID = nil
        failedSchemaCardMutation = nil
        failedSchemaPrepathMutation = nil
        schemaStatusText = "Şema çalışma adımı kaydediliyor…"
        defer {
            if schemaBusyCardID == cardID { schemaBusyCardID = nil }
        }
        do {
            let result = try await dataSource.mutateSchemaCard(mutation)
            if let requestKey { schemaRequestIDs.removeValue(forKey: requestKey) }
            schemaPathSnapshot = result.snapshot
            streamedSchemaCard = nil
            streamedSchemaMessageMeta = []
            hasAuthoritativeStreamedSchemaCard = false
            authoritativeStreamedSchemaCursor = nil
            let safetyActions: Set<SchemaChatCardAction> = [
                .pause, .groundChatTechnique, .stop,
            ]
            if mutation.action == .resumePath {
                suppressInFlightSchemaCardProjection = false
                reconcileSchemaComposerDraft(
                    conversationID: mutation.conversationID
                )
            } else if safetyActions.contains(mutation.action) {
                suppressInFlightSchemaCardProjection = true
                clearSchemaChatDraft(
                    conversationID: mutation.conversationID,
                    clearComposer: true
                )
            } else {
                reconcileSchemaComposerDraft(
                    conversationID: mutation.conversationID
                )
            }
            schemaStatusText = result.duplicate == true
                ? "Bu adım daha önce kaydedilmişti; güncel yerden devam ediliyor."
                : "Kaydedildi."
            if result.snapshot.version == 5,
               result.snapshot.protocol == "schema_path_chat_v5",
               mutation.action == .acceptCandidateChat {
                // The server committed the real authored `Evet` message in
                // the same transaction. Show that durable row immediately;
                // the provider question remains absent until completion.
                try? await reloadLatestSchemaConversationMessages(
                    conversationID: mutation.conversationID
                )
            }
            if schemaV5PromptNeedsPolling(result.snapshot) {
                scheduleSchemaPromptDeliveryPoll(
                    conversationID: mutation.conversationID
                )
            }
            scrollToLatestRequest = UUID()
        } catch {
            let code = (error as? DivanAPIError)?.errorCode ?? ""
            schemaStatusText = schemaErrorMessage(error)
            if [
                "stale_schema_revision", "schema_chat_binding_stale",
                "schema_checkpoint_stale", "schema_source_invalid",
                "stale_technique_revision", "schema_sync_conflict",
                "schema_step_mismatch", "schema_card_inactive",
                "schema_safety_pause", "schema_provider_reconfirm",
                "schema_method_required", "schema_method_ambiguous",
                "schema_method_confirmation_required",
                "schema_backtrack_unavailable",
                "schema_backtrack_source_invalid",
            ].contains(code) {
                await refreshSchemaRecommendations()
            } else {
                failedSchemaCardMutation = mutation
                schemaFailedCardID = cardID
            }
        }
    }

    private func submitSchemaPrepathCard(
        _ card: SchemaCardEnvelope,
        action: SchemaCardActionEnvelope,
        actionID: SchemaChatCardAction,
        conversationID: Int
    ) async {
        guard usesSchemaChatOnlyPresentation,
              card.presentation == "chat_only",
              card.kind == "candidate_prompt",
              card.revision == nil,
              card.pathId == nil,
              card.pathPublicId == nil,
              card.fields.isEmpty,
              card.body == "Bunu çalışmak ister misin?",
              [.acceptCandidateChat, .rejectCandidateChat].contains(actionID),
              case .number(let rawClaim)? = action.payload["claim_id"],
              rawClaim.isFinite,
              rawClaim.rounded() == rawClaim,
              rawClaim > 0,
              rawClaim <= Double(Int.max),
              case .string(let candidatePublicID)? =
                action.payload["candidate_public_id"],
              !candidatePublicID.isEmpty,
              candidatePublicID.count <= 128,
              let sourceUserID = card.source.userMessageId,
              sourceUserID > 0,
              let sourceUserPublicID = card.source.userMessagePublicId,
              !sourceUserPublicID.isEmpty,
              let sourceAssistantID = card.source.assistantMessageId,
              sourceAssistantID > 0,
              let sourceAssistantPublicID =
                card.source.assistantMessagePublicId,
              !sourceAssistantPublicID.isEmpty,
              action.payload["source_user_message_id"]
                == .number(Double(sourceUserID)),
              action.payload["source_user_message_public_id"]
                == .string(sourceUserPublicID),
              action.payload["source_assistant_message_id"]
                == .number(Double(sourceAssistantID)),
              action.payload["source_assistant_message_public_id"]
                == .string(sourceAssistantPublicID) else {
            schemaStatusText = "Bu başlangıç kartının güvenli aday bağı geçersiz."
            return
        }
        let key = [
            "schema-prepath", String(conversationID), card.id,
            action.id,
        ].joined(separator: "|")
        let mutation = SchemaCardMutation(
            action: actionID,
            conversationID: conversationID,
            requestID: schemaRequestID(for: key),
            pathID: nil,
            expectedRevision: nil,
            sourceUserMessageID: sourceUserID,
            sourceUserMessagePublicID: sourceUserPublicID,
            sourceAssistantMessageID: sourceAssistantID,
            sourceAssistantMessagePublicID: sourceAssistantPublicID,
            values: [
                "claim_id": .number(rawClaim),
                "candidate_public_id": .string(candidatePublicID),
            ]
        )
        await performSchemaCardMutation(
            mutation,
            cardID: card.id,
            requestKey: key
        )
    }

    private func performSchemaPrepathMutation(
        _ mutation: SchemaPathMutation,
        cardID: String,
        requestKey: String?
    ) async {
        schemaBusyCardID = cardID
        schemaFailedCardID = nil
        failedSchemaCardMutation = nil
        failedSchemaPrepathMutation = nil
        schemaStatusText = "Şema çalışma seçimi kaydediliyor…"
        defer {
            if schemaBusyCardID == cardID { schemaBusyCardID = nil }
        }
        do {
            let result = try await dataSource.mutateSchemaPath(mutation)
            if let requestKey { schemaRequestIDs.removeValue(forKey: requestKey) }
            schemaPathSnapshot = result.snapshot
            streamedSchemaCard = nil
            streamedSchemaMessageMeta = []
            hasAuthoritativeStreamedSchemaCard = false
            authoritativeStreamedSchemaCursor = nil
            schemaStatusText = mutation.action == .start
                ? "Şema çalışma yolu sohbet içinde başladı."
                : "Aday seçiminiz kaydedildi."
            scrollToLatestRequest = UUID()
        } catch {
            let code = (error as? DivanAPIError)?.errorCode ?? ""
            schemaStatusText = schemaErrorMessage(error)
            if [
                "schema_source_invalid", "schema_card_inactive",
                "schema_safety_pause", "schema_provider_reconfirm",
                "schema_mode_off", "active_path_locked",
            ].contains(code) {
                await refreshSchemaRecommendations()
            } else {
                failedSchemaPrepathMutation = mutation
                schemaFailedCardID = cardID
            }
        }
    }

    public func setSchemaClinicalSync(_ enabled: Bool) async {
        guard isYoungSchemaConversation,
              let conversationID = selectedConversation?.id,
              !schemaClinicalSyncBusy else { return }
        if enabled && schemaPathSnapshot?.clinicalSync?.canEnable != true {
            schemaStatusText = schemaPathSnapshot?.clinicalSync?.notice
                ?? "Bu görüşmede klinik çalışma eşitlemesi açılamıyor."
            return
        }
        schemaClinicalSyncBusy = true
        let key = "schema|clinical-sync|\(conversationID)|\(enabled)"
        defer { schemaClinicalSyncBusy = false }
        do {
            let result = try await dataSource.mutateSchemaClinicalSync(.init(
                conversationID: conversationID,
                requestID: schemaRequestID(for: key),
                enabled: enabled,
                confirmed: true
            ))
            schemaRequestIDs.removeValue(forKey: key)
            schemaPathSnapshot = result.snapshot
            schemaStatusText = enabled
                ? "Şema ve Yaşayan Harita çalışmaları cihazlar arasında eşitlenecek."
                : "Derin çalışmalar artık yalnız bu cihazda tutulacak."
        } catch {
            schemaStatusText = schemaErrorMessage(error)
            await refreshSchemaRecommendations()
        }
    }

    private func schemaErrorMessage(_ error: Error) -> String {
        switch (error as? DivanAPIError)?.errorCode {
        case "schema_chat_binding_stale", "stale_schema_revision",
             "stale_technique_revision",
             "schema_step_mismatch", "schema_card_inactive",
             "schema_checkpoint_stale":
            return "Adım başka bir cihazda veya pencerede değişti; güncel yer açıldı."
        case "schema_sync_conflict":
            return "İki cihazdaki çalışma durumu çakıştı; güncel güvenli kart açıldı."
        case "schema_source_invalid":
            return "Bu kartın dayandığı mesaj artık geçerli değil; güncel adım açıldı."
        case "schema_safety_pause":
            return "Güvenlik için çalışma duraklatıldı. Önce topraklanma adımına dönün."
        case "schema_provider_reconfirm":
            return "Sağlayıcı değişti; modelle devam etmeden önce bu cihazda yeniden onaylayın."
        case "schema_method_required", "schema_method_ambiguous",
             "schema_method_confirmation_required":
            return "Yöntem henüz açıkça seçilmedi; Kerem’in kısa sorusunu yanıtlayın."
        case "schema_backtrack_unavailable", "schema_backtrack_source_invalid":
            return "Önceki adıma güvenle dönülemedi; güncel yerden devam edebilirsiniz."
        case "clinical_sync_confirmation_required":
            return "Eşitleme ancak açık onayınızla değiştirilebilir."
        case "clinical_sync_unavailable":
            return "Bu görüşmede klinik çalışma eşitlemesi kullanılamıyor."
        default:
            return (error as? LocalizedError)?.errorDescription
                ?? error.localizedDescription
        }
    }

    private func scheduleSchemaRecommendationPoll(conversationID: Int) {
        let token = UUID()
        schemaPollToken = token
        Task { [weak self] in
            guard let self else { return }
            for _ in 0..<90 {
                try? await Task.sleep(for: .seconds(2))
                guard self.schemaPollToken == token,
                      self.selectedConversation?.id == conversationID else { return }
                do {
                    let value = try await self.dataSource.schemaPath(
                        conversationID: conversationID
                    )
                    guard self.schemaPollToken == token else { return }
                    switch self.schemaDurableProjectionDecision(
                        against: value
                    ) {
                    case .acceptDurable:
                        self.schemaPathSnapshot = value
                        self.streamedSchemaCard = nil
                        self.hasAuthoritativeStreamedSchemaCard = false
                        self.authoritativeStreamedSchemaCursor = nil
                    case .preserveStreamedSnapshot:
                        break
                    case .conflict:
                        self.schemaPathSnapshot = value
                    }
                    self.streamedSchemaMessageMeta = []
                    self.reconcileSchemaComposerDraft(
                        conversationID: conversationID
                    )
                    if value.turnAnalysis?.processing != true {
                        self.schemaPollToken = UUID()
                        self.schemaStatusText = value.candidates.contains {
                            $0.sourceTurn != nil
                                && ["pending", "deferred"].contains(
                                    $0.decisionState ?? "pending"
                                )
                    } ? "Bu anlatımda birlikte bakabileceğiniz çalışma olasılıkları var."
                      : "Tamamlanan mesaj çifti incelendi."
                    return
                    }
                } catch {
                    // Keep the last durable recommendation state and retry.
                }
            }
            guard self.schemaPollToken == token,
                  self.selectedConversation?.id == conversationID else { return }
            self.schemaPollToken = UUID()
            self.schemaStatusText = "İnceleme arka planda sürüyor. Son durumu görmek için yenileyin."
        }
    }

    private func schemaV5PromptNeedsPolling(
        _ snapshot: SchemaPathSnapshot
    ) -> Bool {
        guard snapshot.version == 5,
              snapshot.protocol == "schema_path_chat_v5",
              snapshot.activePath?.status == "active",
              let card = snapshot.nextCard,
              card.kind == "chat_state",
              card.status == "active",
              let delivery = card.promptDelivery else { return false }
        return ![
            "completed", "failed", "interrupted", "cancelled",
            "imported_waiting",
        ].contains(delivery.status)
    }

    private func reloadLatestSchemaConversationMessages(
        conversationID: Int
    ) async throws {
        let page = try await dataSource.conversation(
            id: conversationID,
            limit: Self.pageSize,
            beforeID: nil
        )
        guard selectedConversation?.id == conversationID else { return }
        var loaded = page.messages
        if let greeting = ephemeralGreetings[conversationID],
           !loaded.contains(where: {
               $0.role == .assistant && $0.content == greeting.content
           }) {
            loaded.insert(greeting, at: 0)
        }
        selectedConversation = page.conversation
        selectedMaster = page.master ?? master(id: page.conversation.masterID)
        messages = deduplicated(loaded)
        messageCount = page.messageCount
        hasMoreMessages = page.hasMoreMessages
        oldestMessageID = page.oldestMessageID
        scrollToLatestRequest = UUID()
    }

    /// A v5 state card never contains question text. Candidate acceptance
    /// creates a durable provider request, so poll until its completed
    /// assistant row and matching metadata can be loaded together.
    private func scheduleSchemaPromptDeliveryPoll(conversationID: Int) {
        guard let expectedPathPublicID =
                schemaPathSnapshot?.activePath?.publicId,
              SchemaPathCheckpoint.isPublicID(expectedPathPublicID) else {
            return
        }
        let token = UUID()
        schemaPromptPollToken = token
        Task { [weak self] in
            guard let self else { return }
            for _ in 0..<180 {
                try? await Task.sleep(for: .seconds(1))
                guard self.schemaPromptPollToken == token,
                      self.selectedConversation?.id == conversationID,
                      !self.isSending else { return }
                do {
                    let value = try await self.dataSource.schemaPath(
                        conversationID: conversationID
                    )
                    guard self.schemaPromptPollToken == token,
                          value.version == 5,
                          value.protocol == "schema_path_chat_v5",
                          value.activePath?.publicId
                            == expectedPathPublicID else { return }

                    let decision = self.schemaDurableProjectionDecision(
                        against: value
                    )
                    switch decision {
                    case .acceptDurable:
                        self.schemaPathSnapshot = value
                        self.streamedSchemaCard = nil
                        self.hasAuthoritativeStreamedSchemaCard = false
                        self.authoritativeStreamedSchemaCursor = nil
                    case .preserveStreamedSnapshot:
                        break
                    case .conflict:
                        self.schemaPathSnapshot = value
                    }
                    self.streamedSchemaMessageMeta = []

                    guard let delivery = value.nextCard?.promptDelivery else {
                        self.schemaPromptPollToken = UUID()
                        self.reconcileSchemaComposerDraft(
                            conversationID: conversationID
                        )
                        return
                    }
                    if delivery.status == "completed" {
                        try await self.reloadLatestSchemaConversationMessages(
                            conversationID: conversationID
                        )
                        guard self.schemaPromptPollToken == token,
                              self.selectedConversation?.id
                                == conversationID else { return }
                        self.schemaPromptPollToken = UUID()
                        self.reconcileSchemaComposerDraft(
                            conversationID: conversationID
                        )
                        self.schemaStatusText =
                            self.schemaComposerBinding == nil
                            ? "Kerem’in güncel sorusu doğrulanamadı; konuşmayı yenileyin."
                            : ""
                        return
                    }
                    if ["failed", "interrupted", "cancelled"].contains(
                        delivery.status
                    ) {
                        self.schemaPromptPollToken = UUID()
                        self.reconcileSchemaComposerDraft(
                            conversationID: conversationID
                        )
                        self.schemaStatusText =
                            "Kerem’in sorusu hazırlanamadı; konuşmayı yenileyin."
                        return
                    }
                } catch {
                    // Keep the last verified state and retry briefly.
                }
            }
            guard self.schemaPromptPollToken == token,
                  self.selectedConversation?.id == conversationID else {
                return
            }
            self.schemaPromptPollToken = UUID()
            self.schemaStatusText =
                "Kerem’in sorusu hâlâ hazırlanıyor; konuşmayı yenileyebilirsiniz."
        }
    }

    private func schemaRequestID(for key: String) -> String {
        if let existing = schemaRequestIDs[key] { return existing }
        let value = "native-schema-turn-\(UUID().uuidString.lowercased())"
        schemaRequestIDs[key] = value
        return value
    }

    public func refreshSettings() async {
        do {
            applySettings(try await dataSource.settingsSummary())
            settingsMessage = "Ayarlar yenilendi."
        } catch {
            notice = errorNotice(
                title: "Ayarlar okunamadı",
                error: error,
                retry: .settings
            )
        }
    }

    /// Bu Mac'te açık olan yerel model sunucularını tarar. Hiçbiri açık
    /// değilse liste boş kalır; bu bir hata değildir.
    public func scanLocalServers() async {
        guard !isScanningLocalServers else { return }
        isScanningLocalServers = true
        localScanMessage = ""
        defer { isScanningLocalServers = false }
        do {
            let servers = try await dataSource.scanLocalModels()
            detectedLocalServers = servers
            let modelCount = servers.reduce(0) { $0 + $1.models.count }
            localScanMessage = servers.isEmpty
                ? "Açık bir yerel model sunucusu bulunamadı. LM Studio veya Ollama’yı başlatıp yeniden tarayın."
                : "\(modelCount) yerel model algılandı."
        } catch {
            detectedLocalServers = []
            localScanMessage = "Yerel sunucular taranamadı: \(error.localizedDescription)"
        }
    }

    /// Algılanan bir yerel sunucunun modelini seçer: sağlayıcıyı, modeli ve
    /// adresi doldurup hemen kaydeder.
    public func useDetectedServer(_ server: DivanLocalServer, model: String) async {
        guard let provider = server.provider, !model.isEmpty else { return }
        settingsProvider = provider
        var draft = providerDrafts[provider] ?? DivanProviderDraft()
        draft.model = model
        if !server.baseURL.isEmpty { draft.baseURL = server.baseURL }
        providerDrafts[provider] = draft
        settingsNewAPIKey = ""
        await saveSettings()
    }

    /// Misafir oturumunu açar/kapatır. Kapatma sunucuda yalnız misafir
    /// görüşmelerini siler; normal kullanıcının görüşmeleri korunur.
    public func setGuestMode(active: Bool) async {
        guard !isTogglingGuestMode, guestModeActive != active else { return }
        isTogglingGuestMode = true
        notice = nil
        defer { isTogglingGuestMode = false }
        do {
            let value = try await dataSource.setGuestMode(active)
            applySettings(value)
            // Kapsam değişti: açık sohbeti kapat ve listeleri yeniden çek.
            clearConversationSelection()
            destination = .recent
            await refreshConversations(archived: false)
            await refreshConversations(archived: true)
            if active {
                settingsMessage = "Misafir moduna geçildi. Bu moddaki görüşmeler ayrı tutulur ve moddan çıkınca silinir."
            } else {
                settingsMessage = "Misafir modu kapatıldı; misafir görüşmeleri silindi. Görüşmeleriniz yeniden görünüyor."
            }
        } catch {
            notice = errorNotice(
                title: active ? "Misafir moduna geçilemedi" : "Misafir modu kapatılamadı",
                error: error
            )
        }
    }

    public func saveSettings() async {
        guard !isSavingSettings else { return }
        let provider = settingsProvider
        var draft = providerDrafts[provider] ?? DivanProviderDraft()
        let model = draft.model.trimmingCharacters(in: .whitespacesAndNewlines)
        let baseURL = draft.baseURL.trimmingCharacters(in: .whitespacesAndNewlines)
        let key = settingsNewAPIKey.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !model.isEmpty else {
            settingsMessage = "Model adı boş bırakılamaz."
            return
        }
        if provider.isLocal,
           URL(string: baseURL)?.scheme?.hasPrefix("http") != true {
            settingsMessage = "\(provider.title) adresi http:// veya https:// ile başlamalı."
            return
        }
        draft.model = model
        draft.baseURL = provider.isLocal ? baseURL : ""
        providerDrafts[provider] = draft
        isSavingSettings = true
        settingsMessage = "Ayarlar kaydediliyor…"
        defer {
            isSavingSettings = false
            settingsNewAPIKey = ""
        }
        do {
            let previous = settings
            let value = try await dataSource.saveSettings(DivanSettingsInput(
                provider: provider,
                modelName: model,
                baseURL: provider.isLocal ? baseURL : "",
                newAPIKey: key.isEmpty ? nil : key
            ))
            applySettings(value)
            if previous?.provider != value.provider
                || previous?.modelName != value.modelName
                || previous?.baseURL != value.baseURL
                || !key.isEmpty {
                invalidateOpenSchemaDraftForProviderChange()
                await refreshSchemaRecommendations()
            }
            settingsMessage = "Ayarlar güvenli biçimde kaydedildi."
        } catch {
            settingsMessage = error.localizedDescription
        }
    }

    public func clearCurrentProviderAPIKey() async {
        guard !isSavingSettings else { return }
        isSavingSettings = true
        settingsMessage = "Anahtar kaldırılıyor…"
        defer {
            isSavingSettings = false
            settingsNewAPIKey = ""
        }
        do {
            applySettings(try await dataSource.clearAPIKey(provider: settingsProvider))
            invalidateOpenSchemaDraftForProviderChange()
            await refreshSchemaRecommendations()
            settingsMessage = "Kayıtlı API anahtarı kaldırıldı."
        } catch {
            settingsMessage = error.localizedDescription
        }
    }

    public func retryNotice() async {
        guard let retry = notice?.retry else { return }
        notice = nil
        switch retry {
        case .bootstrap: await bootstrap()
        case .conversations(let archived): await refreshConversations(archived: archived)
        case .conversation(let id):
            if let value = (activeConversations + archivedConversations)
                .first(where: { $0.id == id }) {
                await openConversation(value)
            }
        case .olderMessages: await loadOlderMessages()
        case .settings: await refreshSettings()
        }
    }

    public func dismissNotice() { notice = nil }

    private func applySettings(_ value: DivanSettingsSummary) {
        settings = value
        guestModeActive = value.guestMode
        providerConfigs = Dictionary(
            uniqueKeysWithValues: value.providers.map { ($0.provider, $0) }
        )
        // Önce taslaklar sunucu kayıtlarıyla tohumlanır, sonra seçili
        // sağlayıcı değiştirilir; böylece kayıtlı özel adresler varsayılan
        // adresle ezilmez. Elle yazılmış, henüz kaydedilmemiş değerler
        // korunur: yalnız boş taslaklar doldurulur.
        for snapshot in value.providers {
            var draft = providerDrafts[snapshot.provider] ?? DivanProviderDraft()
            if draft.model.isEmpty { draft.model = snapshot.model }
            if draft.baseURL.isEmpty {
                draft.baseURL = snapshot.baseURL ?? snapshot.provider.defaultBaseURL
            }
            providerDrafts[snapshot.provider] = draft
        }
        settingsProvider = value.provider
        settingsNewAPIKey = ""
    }

    private func persistDisplayPreferences() {
        displayPreferencesStore.save(displayPreferences)
    }

    private func persistSchemaComposerDraftIfEligible() {
        guard !suppressSchemaChatDraftPersistence,
              let conversationID = selectedConversation?.id,
              let binding = schemaComposerBinding else { return }
        guard !composerText.trimmingCharacters(
            in: .whitespacesAndNewlines
        ).isEmpty else {
            schemaChatDraftStore.remove(conversationID: conversationID)
            return
        }
        schemaChatDraftStore.save(.init(
            conversationID: conversationID,
            bindingFingerprint: binding.deviceLocalDraftFingerprint(
                conversationID: conversationID
            ),
            text: composerText
        ))
    }

    private func reconcileSchemaComposerDraft(conversationID: Int) {
        guard selectedConversation?.id == conversationID else { return }
        guard let binding = schemaComposerBinding else {
            clearSchemaChatDraft(
                conversationID: conversationID,
                clearComposer: true
            )
            return
        }
        guard let record = schemaChatDraftStore.load(
            conversationID: conversationID
        ) else { return }
        let fingerprint = binding.deviceLocalDraftFingerprint(
            conversationID: conversationID
        )
        guard record.bindingFingerprint == fingerprint,
              record.conversationID == conversationID else {
            clearSchemaChatDraft(
                conversationID: conversationID,
                clearComposer: true
            )
            return
        }
        if composerText.isEmpty {
            setComposerTextWithoutDraftPersistence(record.text)
        }
    }

    private func clearSchemaChatDraft(
        conversationID: Int,
        clearComposer: Bool
    ) {
        schemaChatDraftStore.remove(conversationID: conversationID)
        if clearComposer, selectedConversation?.id == conversationID {
            setComposerTextWithoutDraftPersistence("")
        }
    }

    private func invalidateOpenSchemaDraftForProviderChange() {
        guard let conversationID = selectedConversation?.id else { return }
        clearSchemaChatDraft(
            conversationID: conversationID,
            clearComposer: true
        )
    }

    private func setComposerTextWithoutDraftPersistence(_ value: String) {
        suppressSchemaChatDraftPersistence = true
        composerText = value
        suppressSchemaChatDraftPersistence = false
    }

    private func clearOpenConversation() {
        openToken = UUID()
        olderToken = UUID()
        sendToken = UUID()
        backgroundPollToken = UUID()
        schemaPollToken = UUID()
        schemaPromptPollToken = UUID()
        schemaRequestIDs.removeAll()
        isSending = false
        selectedConversation = nil
        selectedMaster = nil
        messages = []
        messageCount = 0
        hasMoreMessages = false
        oldestMessageID = nil
        setComposerTextWithoutDraftPersistence("")
        chatStatusText = ""
        schemaPathSnapshot = nil
        schemaStatusText = ""
        schemaBusyCandidateID = nil
        schemaBusySuggestionID = nil
        schemaBusyMessageID = nil
        schemaModeConfirmationBusy = false
        schemaBusyCardID = nil
        schemaFailedCardID = nil
        schemaClinicalSyncBusy = false
        failedSchemaCardMutation = nil
        failedSchemaPrepathMutation = nil
        streamedSchemaCard = nil
        streamedSchemaMessageMeta = []
        hasAuthoritativeStreamedSchemaCard = false
        authoritativeStreamedSchemaCursor = nil
        suppressInFlightSchemaCardProjection = false
    }

    private func deduplicated(_ values: [DivanMessage]) -> [DivanMessage] {
        var seen = Set<String>()
        return values.filter { seen.insert($0.id).inserted }
    }

    private func masterSort(_ lhs: DivanMaster, _ rhs: DivanMaster) -> Bool {
        lhs.name.localizedStandardCompare(rhs.name) == .orderedAscending
    }

    private func searchKey(_ value: String) -> String {
        value.trimmingCharacters(in: .whitespacesAndNewlines)
            .folding(
                options: [.caseInsensitive, .diacriticInsensitive, .widthInsensitive],
                locale: Locale(identifier: "tr_TR")
            )
            .localizedLowercase
    }

    private func sortConversations(_ values: [DivanConversation]) -> [DivanConversation] {
        values.sorted { $0.updatedAt > $1.updatedAt }
    }

    private func copying(
        _ conversation: DivanConversation,
        archived: Bool
    ) -> DivanConversation {
        DivanConversation(
            id: conversation.id,
            masterID: conversation.masterID,
            title: conversation.title,
            preview: conversation.preview,
            updatedAt: conversation.updatedAt,
            isArchived: archived,
            isPinned: conversation.isPinned,
            isEnded: conversation.isEnded,
            mode: conversation.mode
        )
    }

    private func copying(
        _ conversation: DivanConversation,
        pinned: Bool
    ) -> DivanConversation {
        DivanConversation(
            id: conversation.id,
            masterID: conversation.masterID,
            title: conversation.title,
            preview: conversation.preview,
            updatedAt: conversation.updatedAt,
            isArchived: conversation.isArchived,
            isPinned: pinned,
            isEnded: conversation.isEnded,
            mode: conversation.mode
        )
    }

    private func copying(
        _ conversation: DivanConversation,
        ended: Bool
    ) -> DivanConversation {
        DivanConversation(
            id: conversation.id,
            masterID: conversation.masterID,
            title: conversation.title,
            preview: conversation.preview,
            updatedAt: conversation.updatedAt,
            isArchived: conversation.isArchived,
            isPinned: conversation.isPinned,
            isEnded: conversation.isEnded,
            mode: conversation.mode
        )
    }

    private func errorNotice(
        title: String,
        error: Error,
        retry: DivanNotice.Retry? = nil
    ) -> DivanNotice {
        let message = (error as? LocalizedError)?.errorDescription
            ?? error.localizedDescription
        return DivanNotice(
            title: title,
            message: message.isEmpty ? "Beklenmeyen bir sorun oluştu." : message,
            retry: retry
        )
    }
}

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
    public static let pageSize = 80

    private let dataSource: any DivanUIDataSource
    private let displayPreferencesStore: any DivanDisplayPreferencesStore
    private var openToken = UUID()
    private var olderToken = UUID()
    private var sendToken = UUID()
    private var backgroundPollToken = UUID()
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

    @Published public var composerText = ""
    @Published public private(set) var isBootstrapping = false
    @Published public private(set) var isLoadingConversation = false
    @Published public private(set) var isLoadingOlderMessages = false
    @Published public private(set) var isSending = false
    @Published public private(set) var isMutatingConversation = false
    @Published public private(set) var isEndingConversation = false
    @Published public private(set) var chatStatusText = ""
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
    @Published public var settingsProvider: DivanProviderID = .lmStudio
    @Published public var settingsModel = ""
    @Published public var settingsBaseURL = ""
    /// Deliberately transient and cleared after every save attempt.
    @Published public var settingsNewAPIKey = ""
    @Published public private(set) var isSavingSettings = false
    @Published public private(set) var settingsMessage = ""

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
            displayPreferencesStore: UserDefaultsDivanDisplayPreferencesStore()
        )
    }

    public init(
        dataSource: any DivanUIDataSource,
        displayPreferencesStore: any DivanDisplayPreferencesStore
    ) {
        self.dataSource = dataSource
        self.displayPreferencesStore = displayPreferencesStore
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
            !isSending && !isLoadingConversation
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
        destination = newDestination
        notice = nil
        if (newDestination == .recent && selectedConversation?.isArchived == true)
            || (newDestination == .archived
                && selectedConversation?.isArchived != true) {
            clearConversationSelection()
        }
        if newDestination != .masters { catalogSearch = "" }
        if ![.recent, .archived].contains(newDestination) {
            conversationSearch = ""
        }
        if newDestination == .works || newDestination == .livingMap {
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
        isSending = false
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
                messages.append(DivanMessage(
                    id: pendingID,
                    serverID: nil,
                    role: .assistant,
                    content: pending.content,
                    createdAt: Date(),
                    isPending: true
                ))
                chatStatusText = pending.waitingForProvider
                    ? "sağlayıcı bekleniyor" : "arka planda yanıt hazırlanıyor"
                startBackgroundPoll(
                    pending,
                    conversationID: conversation.id,
                    placeholderID: pendingID
                )
            }
            scrollToLatestRequest = UUID()
            // Özet yalnız bitmiş seanslarda anlamlıdır ve taslağı çekirdek
            // arka planda üretir; yükleme sohbeti bloke etmez.
            if page.conversation.isEnded {
                await loadSessionSummary()
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
        guard !text.isEmpty else { return }
        composerText = ""
        await performSend(text: text, appendUserMessage: true)
    }

    public func reloadConversationAfterFailedResponse() async {
        guard let conversation = selectedConversation, !isSending else { return }
        await openConversation(conversation)
    }

    private func performSend(text: String, appendUserMessage: Bool) async {
        guard let conversation = selectedConversation,
              !conversation.isEnded,
              !conversation.isArchived,
              !isSending else {
            if appendUserMessage { composerText = text }
            return
        }
        let conversationID = conversation.id
        let token = UUID()
        sendToken = token
        let now = Date()
        if appendUserMessage {
            messages.append(DivanMessage(
                id: "local-user-\(UUID().uuidString)",
                serverID: nil,
                role: .user,
                content: text,
                createdAt: now
            ))
        }
        let pendingID = "local-assistant-\(UUID().uuidString)"
        messages.append(DivanMessage(
            id: pendingID,
            serverID: nil,
            role: .assistant,
            content: "",
            createdAt: now,
            isPending: true
        ))
        isSending = true
        chatStatusText = "yanıt hazırlanıyor"
        scrollToLatestRequest = UUID()

        let stream = await dataSource.sendMessage(
            conversationID: conversationID,
            text: text
        )
        do {
            for try await update in stream {
                guard sendToken == token else { return }
                if applyChatUpdate(update, pendingID: pendingID) {
                    scrollToLatestRequest = UUID()
                }
            }
            guard sendToken == token else { return }
            if messages.first(where: { $0.id == pendingID })?
                .failedDescription == nil {
                finishPendingMessage(pendingID: pendingID)
            }
        } catch {
            guard sendToken == token else { return }
            markPendingMessageFailed(
                pendingID,
                message: error.localizedDescription
            )
        }
        if sendToken == token {
            isSending = false
            if !messages.contains(where: { $0.failedDescription != nil }) {
                chatStatusText = ""
            }
            await refreshConversations(archived: false)
        }
    }

    @discardableResult
    private func applyChatUpdate(_ update: DivanChatUpdate, pendingID: String) -> Bool {
        switch update {
        case .accepted:
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
        case .assistantCompleted:
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

    private func startBackgroundPoll(
        _ initial: DivanPendingChat,
        conversationID: Int,
        placeholderID: String
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
                    if !status.content.isEmpty {
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
                self.markPendingMessageFailed(
                    placeholderID,
                    message: "Arka plandaki yanıt tamamlanamadı. Konuşmayı yenileyin."
                )
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

    public func saveSettings() async {
        guard !isSavingSettings else { return }
        let model = settingsModel.trimmingCharacters(in: .whitespacesAndNewlines)
        let baseURL = settingsBaseURL.trimmingCharacters(in: .whitespacesAndNewlines)
        let key = settingsNewAPIKey.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !model.isEmpty else {
            settingsMessage = "Model adı boş bırakılamaz."
            return
        }
        if settingsProvider == .lmStudio,
           URL(string: baseURL)?.scheme?.hasPrefix("http") != true {
            settingsMessage = "LM Studio adresi http:// veya https:// ile başlamalı."
            return
        }
        isSavingSettings = true
        settingsMessage = "Ayarlar kaydediliyor…"
        defer {
            isSavingSettings = false
            settingsNewAPIKey = ""
        }
        do {
            let value = try await dataSource.saveSettings(DivanSettingsInput(
                provider: settingsProvider,
                modelName: model,
                baseURL: baseURL,
                newAPIKey: key.isEmpty ? nil : key
            ))
            applySettings(value)
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
        settingsProvider = value.provider
        settingsModel = value.modelName
        settingsBaseURL = value.baseURL
        settingsNewAPIKey = ""
    }

    private func persistDisplayPreferences() {
        displayPreferencesStore.save(displayPreferences)
    }

    private func clearOpenConversation() {
        openToken = UUID()
        olderToken = UUID()
        sendToken = UUID()
        backgroundPollToken = UUID()
        isSending = false
        selectedConversation = nil
        selectedMaster = nil
        messages = []
        messageCount = 0
        hasMoreMessages = false
        oldestMessageID = nil
        composerText = ""
        chatStatusText = ""
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

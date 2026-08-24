import XCTest
@testable import DivanNative

/// Sağlayıcılar arasında geçiş yapınca her sağlayıcının model/adres
/// değerlerinin ayrı ayrı hatırlanması ve Ollama/yere tarama akışı.
@MainActor
final class ProviderMemoryTests: XCTestCase {

    func testProviderSwitchShowsEachProvidersOwnFields() async {
        let source = ProviderMemoryDataSource()
        let model = DivanViewModel(dataSource: source)
        await model.bootstrap()

        XCTAssertEqual(model.settingsProvider, .deepSeek)
        XCTAssertEqual(model.settingsModel, "deepseek-chat")

        model.settingsProvider = .lmStudio
        XCTAssertEqual(model.settingsModel, "auto")
        XCTAssertEqual(model.settingsBaseURL, "http://127.0.0.1:1234/v1")

        model.settingsProvider = .ollama
        XCTAssertEqual(model.settingsModel, "llama3.1")
        XCTAssertEqual(model.settingsBaseURL, "http://127.0.0.1:11434/v1")
    }

    func testTypedDraftsSurviveProviderSwitches() async {
        let source = ProviderMemoryDataSource()
        let model = DivanViewModel(dataSource: source)
        await model.bootstrap()

        model.settingsProvider = .deepSeek
        model.settingsModel = "yeni-derin-model"

        model.settingsProvider = .lmStudio
        model.settingsModel = "yerel-yeni"

        model.settingsProvider = .deepSeek
        XCTAssertEqual(model.settingsModel, "yeni-derin-model")

        model.settingsProvider = .lmStudio
        XCTAssertEqual(model.settingsModel, "yerel-yeni")
    }

    func testLocalProviderSuggestsDefaultAddressAndKeepsCustomOne() async {
        let source = ProviderMemoryDataSource()
        let model = DivanViewModel(dataSource: source)
        await model.bootstrap()

        model.settingsProvider = .ollama
        XCTAssertEqual(model.settingsBaseURL, "http://127.0.0.1:11434/v1")

        model.settingsBaseURL = "http://127.0.0.1:9999/v1"
        model.settingsProvider = .lmStudio
        model.settingsProvider = .ollama
        XCTAssertEqual(model.settingsBaseURL, "http://127.0.0.1:9999/v1")
    }

    func testSavingOneProviderDoesNotClearAnother() async {
        let source = ProviderMemoryDataSource()
        let model = DivanViewModel(dataSource: source)
        await model.bootstrap()

        model.settingsProvider = .deepSeek
        model.settingsModel = "deepseek-chat"
        model.settingsNewAPIKey = "gizli-anahtar"
        await model.saveSettings()

        model.settingsProvider = .lmStudio
        model.settingsModel = "auto"
        await model.saveSettings()

        let writes = await source.providerWrites()
        XCTAssertEqual(writes.count, 2)
        XCTAssertEqual(writes[0].provider, .deepSeek)
        XCTAssertEqual(writes[0].newAPIKey, "gizli-anahtar")
        XCTAssertEqual(writes[1].provider, .lmStudio)
        XCTAssertNil(writes[1].newAPIKey)

        model.settingsProvider = .deepSeek
        XCTAssertEqual(model.settingsModel, "deepseek-chat")
        XCTAssertTrue(model.providerConfigs[.deepSeek]?.keySet ?? false)
    }

    func testUseDetectedServerFillsProviderModelAndAddress() async {
        let source = ProviderMemoryDataSource()
        let model = DivanViewModel(dataSource: source)
        await model.bootstrap()

        let server = DivanLocalServer(
            id: "ollama",
            label: "Ollama",
            baseURL: "http://127.0.0.1:11434/v1",
            models: ["qwen2.5"],
            provider: .ollama
        )
        await model.useDetectedServer(server, model: "qwen2.5")

        let writes = await source.providerWrites()
        XCTAssertEqual(writes.count, 1)
        XCTAssertEqual(writes[0].provider, .ollama)
        XCTAssertEqual(writes[0].modelName, "qwen2.5")
        XCTAssertEqual(writes[0].baseURL, "http://127.0.0.1:11434/v1")
        XCTAssertEqual(model.settingsProvider, .ollama)
        XCTAssertEqual(model.settingsModel, "qwen2.5")
    }

    func testScanLocalServersPublishesDetectedList() async {
        let source = ProviderMemoryDataSource()
        await source.setScanResult([
            DivanLocalServer(
                id: "ollama",
                label: "Ollama",
                baseURL: "http://127.0.0.1:11434/v1",
                models: ["llama3.1"],
                provider: .ollama
            ),
        ])
        let model = DivanViewModel(dataSource: source)
        await model.scanLocalServers()

        XCTAssertEqual(model.detectedLocalServers.count, 1)
        XCTAssertEqual(model.detectedLocalServers[0].provider, .ollama)
        XCTAssertEqual(model.localScanMessage, "1 yerel model algılandı.")
    }

    func testScanFailureFallsBackToEmptyFriendlyState() async {
        let source = ProviderMemoryDataSource()
        await source.setScanError(ProviderMemoryTestError.unreachable)
        let model = DivanViewModel(dataSource: source)
        await model.scanLocalServers()

        XCTAssertTrue(model.detectedLocalServers.isEmpty)
        XCTAssertTrue(model.localScanMessage.contains("taranamadı"))
    }

    func testOllamaIsALocalProviderAndAllCasesIncludeIt() {
        XCTAssertTrue(DivanProviderID.ollama.isLocal)
        XCTAssertFalse(DivanProviderID.ollama.needsAPIKey)
        XCTAssertEqual(
            DivanProviderID.ollama.defaultBaseURL,
            "http://127.0.0.1:11434/v1"
        )
        XCTAssertTrue(DivanProviderID.allCases.contains(.ollama))
        XCTAssertEqual(
            DivanProviderID(rawValue: "ollama"), .ollama)
    }
}

private enum ProviderMemoryTestError: Error {
    case unused
    case unreachable
}

private actor ProviderMemoryDataSource: DivanUIDataSource {
    private var writes: [DivanSettingsInput] = []
    private var current: DivanSettingsSummary =
        ProviderMemoryDataSource.initialSummary
    private var scanResult: [DivanLocalServer] = []
    private var scanError: Error?

    func providerWrites() -> [DivanSettingsInput] { writes }
    func setScanResult(_ servers: [DivanLocalServer]) { scanResult = servers }
    func setScanError(_ error: Error?) { scanError = error }

    private static var initialSummary: DivanSettingsSummary {
        let snapshots: [DivanProviderSnapshot] = [
            DivanProviderSnapshot(
                provider: .deepSeek, label: "DeepSeek",
                model: "deepseek-chat", baseURL: nil,
                keySet: true, isLocal: false),
            DivanProviderSnapshot(
                provider: .lmStudio, label: "LM Studio",
                model: "auto", baseURL: "http://127.0.0.1:1234/v1",
                keySet: false, isLocal: true),
            DivanProviderSnapshot(
                provider: .ollama, label: "Ollama",
                model: "llama3.1", baseURL: "http://127.0.0.1:11434/v1",
                keySet: false, isLocal: true),
        ]
        return DivanSettingsSummary(
            provider: .deepSeek,
            providerName: "DeepSeek",
            modelName: "deepseek-chat",
            baseURL: "",
            connectionDetail: "API anahtarı güvenli biçimde kayıtlı",
            state: .ready,
            apiKeyStored: true,
            localOnly: false,
            providers: snapshots
        )
    }

    private func summary(for input: DivanSettingsInput) -> DivanSettingsSummary {
        let snapshots = current.providers
        var updated = snapshots.compactMap { (snapshot: DivanProviderSnapshot) -> DivanProviderSnapshot? in
            guard snapshot.provider == input.provider else { return snapshot }
            return DivanProviderSnapshot(
                provider: snapshot.provider,
                label: snapshot.label,
                model: input.modelName.isEmpty ? snapshot.model : input.modelName,
                baseURL: input.provider.isLocal
                    ? (input.baseURL.isEmpty ? snapshot.baseURL : input.baseURL)
                    : nil,
                keySet: input.newAPIKey != nil || snapshot.keySet,
                isLocal: snapshot.isLocal
            )
        }
        if !snapshots.contains(where: { $0.provider == input.provider }) {
            updated.append(DivanProviderSnapshot(
                provider: input.provider,
                label: input.provider.title,
                model: input.modelName,
                baseURL: input.provider.isLocal ? input.baseURL : nil,
                keySet: input.newAPIKey != nil,
                isLocal: input.provider.isLocal
            ))
        }
        let byID = Dictionary(uniqueKeysWithValues: updated.map { ($0.provider, $0) })
        let selected = byID[input.provider]
        return DivanSettingsSummary(
            provider: input.provider,
            providerName: input.provider.title,
            modelName: input.modelName,
            baseURL: input.baseURL,
            connectionDetail: input.provider.isLocal
                ? "Yerel sağlayıcı" : "API anahtarı kayıtlı",
            state: .ready,
            apiKeyStored: selected?.keySet ?? false,
            localOnly: input.provider.isLocal,
            providers: updated
        )
    }

    func bootstrap() async throws -> DivanUISnapshot {
        DivanUISnapshot(
            therapists: [],
            philosophers: [],
            activeConversations: [],
            archivedConversations: [],
            settings: current
        )
    }

    func masters(kind: DivanCatalogKind) async throws -> [DivanMaster] { [] }
    func conversations(archived: Bool) async throws -> [DivanConversation] { [] }

    func conversation(
        id: Int,
        limit: Int,
        beforeID: Int?
    ) async throws -> DivanConversationPage {
        throw ProviderMemoryTestError.unused
    }

    func createConversation(
        masterID: String,
        mode: DivanSessionMode
    ) async throws -> DivanNewConversation {
        throw ProviderMemoryTestError.unused
    }

    func setArchived(_ archived: Bool, conversationID: Int) async throws {}
    func setPinned(_ pinned: Bool, conversationID: Int) async throws {}
    func profileText() async throws -> String { "" }
    func updateProfileText(_ text: String) async throws {}
    func notebook(masterID: String, mode: DivanSessionMode) async throws -> LibraryNotebook {
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
    func sessionSummary(conversationID: Int) async throws -> DivanSessionSummary? { nil }
    func updateSessionSummary(
        conversationID: Int,
        action: DivanSummaryAction,
        content: String?
    ) async throws -> DivanSessionSummary? { nil }
    func deleteConversation(id: Int) async throws {}
    func endConversation(id: Int) async throws {}

    func sendMessage(
        conversationID: Int,
        text: String
    ) async -> AsyncThrowingStream<DivanChatUpdate, Error> {
        AsyncThrowingStream { continuation in continuation.finish() }
    }

    func chatStatus(requestID: String) async throws -> DivanPendingChat {
        throw ProviderMemoryTestError.unused
    }

    func portraitData(url: URL) async throws -> Data { Data() }
    func settingsSummary() async throws -> DivanSettingsSummary { current }

    func saveSettings(_ input: DivanSettingsInput) async throws
        -> DivanSettingsSummary {
        writes.append(input)
        current = summary(for: input)
        return current
    }

    func clearAPIKey(provider: DivanProviderID) async throws
        -> DivanSettingsSummary {
        current
    }

    func scanLocalModels() async throws -> [DivanLocalServer] {
        if let scanError { throw scanError }
        return scanResult
    }
}

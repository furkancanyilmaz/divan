import XCTest
@testable import DivanNative

/// Misafir modu: kapsam değişimi, kişisel yüzeylerin gizlenmesi ve
/// kapanışta yalnız misafir verisinin silinmesi (sunucu sözleşmesi).
@MainActor
final class GuestModeTests: XCTestCase {

    func testGuestModeReflectsServerStateAfterBootstrap() async {
        let source = GuestModeDataSource(guestMode: true)
        let model = DivanViewModel(dataSource: source)
        await model.bootstrap()

        XCTAssertTrue(model.guestModeActive)
    }

    func testEnteringGuestModeUpdatesStateAndReturnsToRecent() async {
        let source = GuestModeDataSource(guestMode: false)
        let model = DivanViewModel(dataSource: source)
        await model.bootstrap()
        model.selectDestination(.notebook)

        await model.setGuestMode(active: true)

        XCTAssertTrue(model.guestModeActive)
        XCTAssertEqual(model.destination, .recent)
        let toggles = await source.toggles()
        XCTAssertEqual(toggles, [true])
    }

    func testLeavingGuestModeTurnsFlagOff() async {
        let source = GuestModeDataSource(guestMode: true)
        let model = DivanViewModel(dataSource: source)
        await model.bootstrap()

        await model.setGuestMode(active: false)

        XCTAssertFalse(model.guestModeActive)
        XCTAssertEqual(model.destination, .recent)
        let toggles = await source.toggles()
        XCTAssertEqual(toggles, [false])
    }

    func testPersonalDestinationsAreHiddenInGuestMode() {
        XCTAssertEqual(
            DivanViewModel.guestHiddenDestinations,
            [.notebook, .letters, .dreams, .profile])
    }

    func testSelectingPersonalDestinationInGuestModeFallsBackToRecent() async {
        let source = GuestModeDataSource(guestMode: true)
        let model = DivanViewModel(dataSource: source)
        await model.bootstrap()

        model.selectDestination(.notebook)
        XCTAssertEqual(model.destination, .recent)

        model.selectDestination(.letters)
        XCTAssertEqual(model.destination, .recent)

        model.selectDestination(.dreams)
        XCTAssertEqual(model.destination, .recent)

        model.selectDestination(.profile)
        XCTAssertEqual(model.destination, .recent)

        // Kişisel olmayan yüzeyler misafir modunda açık kalır.
        model.selectDestination(.masters)
        XCTAssertEqual(model.destination, .masters)
        model.selectDestination(.settings)
        XCTAssertEqual(model.destination, .settings)
    }
}

private enum GuestModeTestError: Error {
    case unused
}

private actor GuestModeDataSource: DivanUIDataSource {
    private var recordedToggles: [Bool] = []
    private var currentGuestMode: Bool

    init(guestMode: Bool) {
        self.currentGuestMode = guestMode
    }

    func toggles() -> [Bool] { recordedToggles }

    private var settings: DivanSettingsSummary {
        DivanSettingsSummary(
            provider: .deepSeek,
            providerName: "DeepSeek",
            modelName: "deepseek-chat",
            baseURL: "",
            connectionDetail: "API anahtarı kayıtlı",
            state: .ready,
            apiKeyStored: true,
            localOnly: false,
            guestMode: currentGuestMode
        )
    }

    func bootstrap() async throws -> DivanUISnapshot {
        DivanUISnapshot(
            therapists: [],
            philosophers: [],
            activeConversations: [],
            archivedConversations: [],
            settings: settings
        )
    }

    func masters(kind: DivanCatalogKind) async throws -> [DivanMaster] { [] }
    func conversations(archived: Bool) async throws -> [DivanConversation] { [] }

    func conversation(
        id: Int,
        limit: Int,
        beforeID: Int?
    ) async throws -> DivanConversationPage {
        throw GuestModeTestError.unused
    }

    func createConversation(
        masterID: String,
        mode: DivanSessionMode
    ) async throws -> DivanNewConversation {
        throw GuestModeTestError.unused
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
        throw GuestModeTestError.unused
    }

    func portraitData(url: URL) async throws -> Data { Data() }
    func settingsSummary() async throws -> DivanSettingsSummary { settings }

    func saveSettings(_ input: DivanSettingsInput) async throws
        -> DivanSettingsSummary {
        settings
    }

    func clearAPIKey(provider: DivanProviderID) async throws
        -> DivanSettingsSummary {
        settings
    }

    func scanLocalModels() async throws -> [DivanLocalServer] { [] }

    func setGuestMode(_ active: Bool) async throws -> DivanSettingsSummary {
        recordedToggles.append(active)
        currentGuestMode = active
        return settings
    }
}

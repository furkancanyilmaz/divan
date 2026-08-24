import AppKit
import Foundation
import SwiftUI
import XCTest
@testable import DivanNative

@MainActor
final class DisplayPreferencesTests: XCTestCase {
    func testUserDefaultsStoreRoundTripsPresetsAndFallsBackSafely() throws {
        let suite = "DivanDisplayPreferencesTests." + UUID().uuidString
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let store = UserDefaultsDivanDisplayPreferencesStore(defaults: defaults)

        XCTAssertEqual(store.load(), .default)
        store.save(DivanDisplayPreferences(
            textSize: .extraLarge,
            appearance: .dark
        ))
        XCTAssertEqual(
            UserDefaultsDivanDisplayPreferencesStore(defaults: defaults).load(),
            DivanDisplayPreferences(textSize: .extraLarge, appearance: .dark)
        )

        defaults.set(
            "not-a-size",
            forKey: UserDefaultsDivanDisplayPreferencesStore.textSizeKey
        )
        defaults.set(
            "not-a-scheme",
            forKey: UserDefaultsDivanDisplayPreferencesStore.appearanceKey
        )
        XCTAssertEqual(store.load(), .default)
    }

    func testViewModelLoadsAndPersistsDisplayPreferencesWithoutProviderWrite()
        async throws {
        let suite = "DivanDisplayViewModelTests." + UUID().uuidString
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let store = UserDefaultsDivanDisplayPreferencesStore(defaults: defaults)
        store.save(DivanDisplayPreferences(textSize: .large, appearance: .system))
        let source = DisplayPreferencesNoopDataSource()

        let model = DivanViewModel(
            dataSource: source,
            displayPreferencesStore: store
        )
        XCTAssertEqual(model.textSizePreference, .large)
        XCTAssertEqual(model.appearancePreference, .system)
        XCTAssertEqual(model.displayPreferences.textSize.scale, 1.15)

        model.textSizePreference = .small
        model.appearancePreference = .light

        let restored = DivanViewModel(
            dataSource: source,
            displayPreferencesStore:
                UserDefaultsDivanDisplayPreferencesStore(defaults: defaults)
        )
        XCTAssertEqual(restored.textSizePreference, .small)
        XCTAssertEqual(restored.appearancePreference, .light)
        let providerWriteCount = await source.providerWriteCount()
        XCTAssertEqual(providerWriteCount, 0)
    }

    func testPresetTitlesAndScaleAreStable() {
        XCTAssertEqual(
            DivanTextSizePreference.allCases.map(\.title),
            ["Küçük", "Standart", "Büyük", "Çok büyük"]
        )
        XCTAssertEqual(
            DivanTextSizePreference.allCases.map(\.scale),
            [0.90, 1.00, 1.15, 1.30]
        )
        XCTAssertEqual(
            DivanAppearancePreference.allCases.map(\.title),
            ["Sistem", "Açık", "Koyu"]
        )
    }

    func testSettingsAcceptsSmallWindowWithExtraLargeTextInDarkAppearance()
        async {
        let source = DisplayPreferencesNoopDataSource()
        let model = DivanViewModel(dataSource: source)
        await model.bootstrap()
        model.textSizePreference = .extraLarge
        model.appearancePreference = .dark

        let size = CGSize(width: 480, height: 360)
        let hosting = NSHostingView(rootView:
            ProviderSettingsView(model: model)
                .environment(\.dynamicTypeSize, .xxLarge)
                .preferredColorScheme(.dark)
        )
        hosting.frame = CGRect(origin: .zero, size: size)
        hosting.layoutSubtreeIfNeeded()
        try? await Task.sleep(nanoseconds: 20_000_000)
        hosting.frame = CGRect(origin: .zero, size: size)
        hosting.layoutSubtreeIfNeeded()

        XCTAssertEqual(hosting.bounds.width, size.width, accuracy: 0.5)
        XCTAssertEqual(hosting.bounds.height, size.height, accuracy: 0.5)
        XCTAssertTrue(containsScrollView(hosting))
        assertFiniteFrames(in: hosting)
        let providerWriteCount = await source.providerWriteCount()
        XCTAssertEqual(providerWriteCount, 0)
    }

    func testDarkPaletteAccentMeetsNormalTextContrastOnParchment() throws {
        let appearance = try XCTUnwrap(NSAppearance(named: .darkAqua))
        let wine = try resolvedSRGB(DivanPalette.wine, appearance: appearance)
        let parchment = try resolvedSRGB(
            DivanPalette.parchment,
            appearance: appearance
        )

        XCTAssertGreaterThanOrEqual(
            contrastRatio(wine, parchment),
            4.5,
            "Koyu temadaki küçük bordo metin normal metin kontrastını korumalı"
        )
    }

    private func containsScrollView(_ view: NSView) -> Bool {
        if view is NSScrollView { return true }
        return view.subviews.contains(where: containsScrollView)
    }

    private func assertFiniteFrames(
        in view: NSView,
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        XCTAssertTrue(view.frame.origin.x.isFinite, file: file, line: line)
        XCTAssertTrue(view.frame.origin.y.isFinite, file: file, line: line)
        XCTAssertTrue(view.frame.width.isFinite, file: file, line: line)
        XCTAssertTrue(view.frame.height.isFinite, file: file, line: line)
        for child in view.subviews {
            assertFiniteFrames(in: child, file: file, line: line)
        }
    }

    private func resolvedSRGB(
        _ color: Color,
        appearance: NSAppearance
    ) throws -> NSColor {
        var resolved: NSColor?
        appearance.performAsCurrentDrawingAppearance {
            resolved = NSColor(color).usingColorSpace(NSColorSpace.sRGB)
        }
        return try XCTUnwrap(resolved)
    }

    private func contrastRatio(_ lhs: NSColor, _ rhs: NSColor) -> Double {
        let first = relativeLuminance(lhs)
        let second = relativeLuminance(rhs)
        return (max(first, second) + 0.05) / (min(first, second) + 0.05)
    }

    private func relativeLuminance(_ color: NSColor) -> Double {
        func linear(_ component: CGFloat) -> Double {
            let value = Double(component)
            if value <= 0.04045 { return value / 12.92 }
            return pow((value + 0.055) / 1.055, 2.4)
        }

        return 0.2126 * linear(color.redComponent)
            + 0.7152 * linear(color.greenComponent)
            + 0.0722 * linear(color.blueComponent)
    }
}

extension DisplayPreferencesTests {

    /// Pencereyi üstte tutma (FaceTime tarzı) yerel bir sunum tercihidir:
    /// varsayılan kapalı, açıldığında kalıcı ve diğer tercihleri bozmaz.
    func testKeepsWindowOnTopDefaultsToOffAndPersists() throws {
        XCTAssertFalse(DivanDisplayPreferences.default.keepsWindowOnTop)

        let suite = "DivanOnTopTests." + UUID().uuidString
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let store = UserDefaultsDivanDisplayPreferencesStore(defaults: defaults)
        XCTAssertFalse(store.load().keepsWindowOnTop)

        store.save(DivanDisplayPreferences(
            textSize: .large, appearance: .dark, keepsWindowOnTop: true))
        let reloaded = store.load()
        XCTAssertTrue(reloaded.keepsWindowOnTop)
        XCTAssertEqual(reloaded.textSize, .large)
        XCTAssertEqual(reloaded.appearance, .dark)
    }

    func testViewModelPersistsKeepsWindowOnTopImmediately() throws {
        let suite = "DivanOnTopModelTests." + UUID().uuidString
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let store = UserDefaultsDivanDisplayPreferencesStore(defaults: defaults)

        let model = DivanViewModel(
            dataSource: DisplayPreferencesNoopDataSource(),
            displayPreferencesStore: store
        )
        XCTAssertFalse(model.keepsWindowOnTop)

        model.keepsWindowOnTop = true
        XCTAssertTrue(store.load().keepsWindowOnTop)
        XCTAssertTrue(model.displayPreferences.keepsWindowOnTop)

        model.keepsWindowOnTop = false
        XCTAssertFalse(store.load().keepsWindowOnTop)
    }
}

private actor DisplayPreferencesNoopDataSource: DivanUIDataSource {
    private var providerWrites = 0

    func providerWriteCount() -> Int { providerWrites }

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
        throw DisplayPreferencesTestError.unused
    }

    func createConversation(
        masterID: String,
        mode: DivanSessionMode
    ) async throws -> DivanNewConversation {
        throw DisplayPreferencesTestError.unused
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
        throw DisplayPreferencesTestError.unused
    }

    func portraitData(url: URL) async throws -> Data { Data() }
    func settingsSummary() async throws -> DivanSettingsSummary { settings }

    func saveSettings(_ input: DivanSettingsInput) async throws
        -> DivanSettingsSummary {
        providerWrites += 1
        return settings
    }

    func clearAPIKey(provider: DivanProviderID) async throws
        -> DivanSettingsSummary {
        providerWrites += 1
        return settings
    }

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
}

private enum DisplayPreferencesTestError: Error {
    case unused
}

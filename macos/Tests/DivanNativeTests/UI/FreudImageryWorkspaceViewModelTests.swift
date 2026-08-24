import AppKit
import Foundation
import SwiftUI
import XCTest
@testable import DivanNative

private enum FreudImageryViewModelTestError: LocalizedError {
    case retryable
    var errorDescription: String? { "Geçici görsel çalışma hatası" }
}

private actor FreudImageryViewModelDataSource: StructuredTherapyDataSource {
    private var current = Fixture.activeWorkspace()
    private var selectionMutations: [FreudImagerySelectionMutation] = []
    private var suggestionMutations: [FreudImagerySuggestionMutation] = []
    private var failFirstSelection = false
    private var failSuggestionWithSafetyHold = false

    func freudImagery(conversationID: Int) async throws -> FreudImageryWorkspace {
        current
    }

    func mutateFreudImagerySelection(
        _ mutation: FreudImagerySelectionMutation
    ) async throws -> FreudImageryMutationResponse {
        selectionMutations.append(mutation)
        if failFirstSelection,
           case .select = mutation {
            failFirstSelection = false
            throw FreudImageryViewModelTestError.retryable
        }
        switch mutation {
        case let .select(_, _, _, cardID, association):
            let card = current.cards.first { $0.id == cardID }!
            current = Fixture.activeWorkspace(
                revision: (current.session?.revision ?? 1) + 1,
                selection: FreudImagerySelection(
                    id: 5,
                    status: "selected",
                    revision: 1,
                    stepData: .init(cardID: cardID, association: association),
                    card: card,
                    created: "2026-08-17 19:00",
                    updated: "2026-08-17 19:00"
                )
            )
        case .clear, .undo:
            current = Fixture.activeWorkspace(
                revision: (current.session?.revision ?? 1) + 1
            )
        case .stop:
            current = Fixture.blockedWorkspace(reason: "session_stopped")
        case .consent:
            current = Fixture.activeWorkspace()
        }
        return .init(ok: true, duplicate: false, imagery: current)
    }

    func suggestFreudImagery(
        _ mutation: FreudImagerySuggestionMutation
    ) async throws -> FreudImageryMutationResponse {
        suggestionMutations.append(mutation)
        if failSuggestionWithSafetyHold {
            failSuggestionWithSafetyHold = false
            current = Fixture.blockedWorkspace(reason: "safety_hold")
            throw DivanAPIError(
                message: "Güvenlik desteği sürerken bu çalışma açılamaz.",
                statusCode: 409
            )
        }
        current = Fixture.activeWorkspace(
            revision: current.session?.revision ?? 1,
            selection: current.selection,
            suggestions: Array(current.cards.prefix(3))
        )
        return .init(ok: true, duplicate: false, selected: false, imagery: current)
    }

    func freudImageryCardData(card: FreudImageryCard) async throws -> Data {
        throw FreudImageryViewModelTestError.retryable
    }

    func adhdDashboard(conversationID: Int) async throws -> ADHDWorkspaceSnapshot {
        throw FreudImageryViewModelTestError.retryable
    }
    func mutateADHDHabit(
        _ mutation: ADHDHabitMutation
    ) async throws -> ADHDHabitMutationResponse {
        throw FreudImageryViewModelTestError.retryable
    }
    func mutateADHDEvent(
        _ mutation: ADHDEventMutation
    ) async throws -> ADHDEventMutationResponse {
        throw FreudImageryViewModelTestError.retryable
    }
    func mutateADHDJournal(
        _ mutation: ADHDJournalMutation
    ) async throws -> ADHDJournalMutationResponse {
        throw FreudImageryViewModelTestError.retryable
    }
    func schemaPath(conversationID: Int) async throws -> SchemaPathSnapshot {
        throw FreudImageryViewModelTestError.retryable
    }
    func mutateSchemaPath(
        _ mutation: SchemaPathMutation
    ) async throws -> SchemaPathMutationResponse {
        throw FreudImageryViewModelTestError.retryable
    }

    func setFailFirstSelection() { failFirstSelection = true }
    func setFailSuggestionWithSafetyHold() { failSuggestionWithSafetyHold = true }
    func capturedSelections() -> [FreudImagerySelectionMutation] { selectionMutations }
    func capturedSuggestions() -> [FreudImagerySuggestionMutation] { suggestionMutations }
}

@MainActor
final class FreudImageryWorkspaceViewModelTests: XCTestCase {
    func testRealityConsentRejectsHistoricalProofCertainMemoryAndDecodingClaims() {
        let copy = FreudImageryWorkspaceViewModel.realityConsentStatement
            .localizedLowercase
        XCTAssertTrue(copy.contains("tarihsel kanıt"))
        XCTAssertTrue(copy.contains("kesin anı"))
        XCTAssertTrue(copy.contains("bastırılmış"))
        XCTAssertTrue(copy.contains("deşifre"))
    }

    func testCardChoiceIsLocalUntilSeparateSaveAndRetryKeepsRequestID() async throws {
        let source = FreudImageryViewModelDataSource()
        let model = FreudImageryWorkspaceViewModel(
            dataSource: source,
            conversationID: 42
        )
        await model.loadIfNeeded()
        let card = try XCTUnwrap(model.snapshot?.cards.first)

        model.chooseCard(card)
        model.associationDraft = "Açık bir geçidi anımsattı."
        let beforeSave = await source.capturedSelections()
        XCTAssertEqual(beforeSave.count, 0)
        XCTAssertTrue(model.canSaveAssociation)

        await source.setFailFirstSelection()
        await model.saveAssociation()
        XCTAssertEqual(model.failure?.message, "Geçici görsel çalışma hatası")
        await model.saveAssociation()

        let mutations = await source.capturedSelections()
        XCTAssertEqual(mutations.count, 2)
        guard case let .select(_, firstID, _, firstCard, firstAssociation) = mutations[0],
              case let .select(_, secondID, _, secondCard, secondAssociation) = mutations[1] else {
            return XCTFail("Yalnız açık select mutasyonları bekleniyordu")
        }
        XCTAssertEqual(firstID, secondID)
        XCTAssertEqual(firstCard, card.id)
        XCTAssertEqual(secondCard, card.id)
        XCTAssertEqual(firstAssociation, "Açık bir geçidi anımsattı.")
        XCTAssertEqual(secondAssociation, "Açık bir geçidi anımsattı.")
        XCTAssertEqual(model.snapshot?.selection?.stepData.cardID, card.id)
    }

    func testSuggestionNeedsFreshModelConsentIsBoundedAndNeverSelectsCard() async throws {
        let source = FreudImageryViewModelDataSource()
        let model = FreudImageryWorkspaceViewModel(
            dataSource: source,
            conversationID: 42
        )
        await model.loadIfNeeded()
        let chosen = try XCTUnwrap(model.snapshot?.cards.last)
        model.chooseCard(chosen)
        model.associationDraft = "Henüz kaydedilmemiş çağrışım."

        await model.requestSuggestions()
        let beforeConsent = await source.capturedSuggestions()
        XCTAssertEqual(beforeConsent.count, 0)
        XCTAssertEqual(model.failure?.title, "Model gönderimi için açık onay gerekli")

        model.dismissFailure()
        model.modelConsent = true
        await model.requestSuggestions()

        let suggestions = await source.capturedSuggestions()
        XCTAssertEqual(suggestions.count, 1)
        XCTAssertTrue(suggestions[0].modelConsent)
        XCTAssertFalse(model.modelConsent)
        XCTAssertEqual(model.snapshot?.suggestions.count, 3)
        XCTAssertNil(model.snapshot?.selection)
        XCTAssertEqual(model.selectedCardID, chosen.id)
        XCTAssertEqual(model.associationDraft, "Henüz kaydedilmemiş çağrışım.")
        XCTAssertEqual(
            model.statusMessage,
            "Öneriler geldi; hiçbir kart seçilmedi. Seçim yalnız size ait."
        )
    }

    func testSafetyHoldMutationErrorRefetchesRedactedDeckAndClearsPrivateDraft() async throws {
        let source = FreudImageryViewModelDataSource()
        let model = FreudImageryWorkspaceViewModel(
            dataSource: source,
            conversationID: 42
        )
        await model.loadIfNeeded()
        model.chooseCard(try XCTUnwrap(model.snapshot?.cards.first))
        model.associationDraft = "Görünür kalmaması gereken özel taslak."
        model.modelConsent = true
        await source.setFailSuggestionWithSafetyHold()

        await model.requestSuggestions()

        XCTAssertEqual(model.snapshot?.blockedReason, "safety_hold")
        XCTAssertEqual(model.snapshot?.cards, [])
        XCTAssertNil(model.snapshot?.session)
        XCTAssertNil(model.snapshot?.selection)
        XCTAssertNil(model.selectedCardID)
        XCTAssertEqual(model.associationDraft, "")
        XCTAssertFalse(model.modelConsent)
        XCTAssertEqual(
            model.failure?.message,
            "Güvenlik desteği sürerken bu çalışma açılamaz."
        )
    }

    func testLiteralDeckLayoutStaysFiniteAtCompactNormalAndFullscreenSizes() async throws {
        let sizes = [
            CGSize(width: 480, height: 600),
            CGSize(width: 900, height: 650),
            CGSize(width: 1_512, height: 895),
        ]
        for size in sizes {
            let source = FreudImageryViewModelDataSource()
            let model = FreudImageryWorkspaceViewModel(
                dataSource: source,
                conversationID: 42
            )
            await model.loadIfNeeded()
            let hosting = NSHostingView(rootView:
                FreudImageryWorkspaceView(model: model, dataSource: source)
                    .environment(\.dynamicTypeSize, .accessibility2)
                    .frame(width: size.width, height: size.height)
            )
            hosting.frame = CGRect(origin: .zero, size: size)
            let window = NSWindow(
                contentRect: CGRect(origin: .zero, size: size),
                styleMask: [.titled, .closable, .resizable],
                backing: .buffered,
                defer: false
            )
            window.isReleasedWhenClosed = false
            window.contentView = hosting
            window.setContentSize(size)
            window.makeKeyAndOrderFront(nil)
            for _ in 0..<5 {
                hosting.layoutSubtreeIfNeeded()
                try await Task.sleep(for: .milliseconds(20))
            }
            hosting.frame = CGRect(origin: .zero, size: size)
            hosting.layoutSubtreeIfNeeded()

            XCTAssertEqual(hosting.bounds.width, size.width, accuracy: 0.5)
            XCTAssertEqual(hosting.bounds.height, size.height, accuracy: 0.5)
            XCTAssertTrue(Self.descendants(hosting).allSatisfy { view in
                [view.frame.minX, view.frame.minY, view.frame.width, view.frame.height]
                    .allSatisfy(\.isFinite)
                    && view.frame.width >= 0
                    && view.frame.height >= 0
            }, "Görsel deste ölçüleri sonlu ve negatif olmayan kalmalı: \(size)")
            XCTAssertNotNil(hosting.hitTest(CGPoint(
                x: size.width / 2,
                y: size.height / 2
            )))

            window.orderOut(nil)
            window.close()
        }
    }

    private static func descendants(_ root: NSView) -> [NSView] {
        [root] + root.subviews.flatMap(descendants)
    }
}

private enum Fixture {
    static func card(_ index: Int) -> FreudImageryCard {
        let id = String(format: "card-%02d", index)
        return .init(
            id: id,
            file: id + ".webp",
            category: "mekan",
            title: "Görünen kart \(index)",
            description: "Yalnız görünen sahne \(index).",
            alt: "Yalnız görünen kart sahnesi \(index).",
            sha256: String(repeating: "0", count: 64),
            bytes: 1_024 + index,
            url: "/assets/imagery/\(id).webp?v=2026.08.17.5"
        )
    }

    static func activeWorkspace(
        revision: Int = 1,
        selection: FreudImagerySelection? = nil,
        suggestions: [FreudImageryCard] = []
    ) -> FreudImageryWorkspace {
        let cards = (1...24).map(card)
        return .init(
            available: true,
            blockedReason: "",
            method: .init(
                id: "visual-free-association",
                title: "Görsel Serbest Çağrışım",
                description: "Kartlar yalnız görünen sahneyi sunar."
            ),
            cards: cards,
            session: .init(
                id: 9,
                techniqueRunID: 77,
                status: "active",
                revision: revision,
                orientationConfirmed: true,
                frameConfirmed: true,
                realityConfirmed: true,
                stopSignal: "DUR",
                consentAt: "2026-08-17 19:00"
            ),
            selection: selection,
            suggestions: suggestions,
            suggestionQuestion: suggestions.isEmpty
                ? "" : "Bu kartlardan biri sende ne çağrıştırıyor?",
            capabilities: .init(
                consent: false,
                suggest: true,
                select: true,
                clear: selection != nil,
                undo: selection != nil,
                stop: true
            ),
            safetyHold: false,
            precheckComplete: true
        )
    }

    static func blockedWorkspace(reason: String) -> FreudImageryWorkspace {
        .init(
            available: false,
            blockedReason: reason,
            method: .init(
                id: "visual-free-association",
                title: "Görsel Serbest Çağrışım",
                description: "Kartlar yalnız görünen sahneyi sunar."
            ),
            cards: [],
            session: nil,
            selection: nil,
            suggestions: [],
            suggestionQuestion: "",
            capabilities: .init(
                consent: false, suggest: false, select: false,
                clear: false, undo: false, stop: false
            ),
            safetyHold: reason == "safety_hold",
            precheckComplete: true
        )
    }
}

import AppKit
import SwiftUI
import XCTest
@testable import DivanNative

@MainActor
final class ResponsiveLayoutTests: XCTestCase {
    private let acceptanceSizes = [
        CGSize(width: 480, height: 360),
        CGSize(width: 720, height: 520),
        CGSize(width: 1_280, height: 780),
    ]

    func testAdvancedChairStartAndValidationLayoutAtAcceptanceSizes() async {
        for size in acceptanceSizes {
            let source = AdvancedSafetyDataSource()
            let model = makeAdvancedModel(source, initialModule: .chairWork)
            await model.reloadWorkspace()
            model.chairGoalText = String(
                repeating: "Eleştirel ebeveyn sesi ile incinmiş çocuk parçasını güvenli biçimde ayırmak. ",
                count: 4
            )
            model.chairStopSignal = "Şimdi burada dur ve bulunduğum odaya dön"
            model.chairParticipantTitles = [
                "Görülmek ve korunmak isteyen incinmiş çocuk parçam",
                "Beni reddedilmekten korumaya çalışan talepkâr eleştirel ses",
            ]

            // The primary action must stay actionable so incomplete consent is
            // reported in the visible failure banner instead of becoming a no-op.
            await model.startChairWork()
            XCTAssertNotNil(model.failure)

            assertLayoutSmoke(
                AdvancedWorkspaceView(model: model)
                    .environment(\.dynamicTypeSize, .accessibility3),
                size: size,
                scenario: "chair start and validation"
            )
        }
    }

    func testAdvancedImageryStartAndValidationLayoutAtAcceptanceSizes() async {
        for size in acceptanceSizes {
            let source = AdvancedSafetyDataSource()
            let model = makeAdvancedModel(source, initialModule: .reparenting)
            await model.reloadWorkspace()
            model.imageryIntention = String(
                repeating: "Bugün görülme ve korunma ihtiyacıma nazik, sınırlı ve gerçeklik ayrımı açık biçimde yaklaşmak. ",
                count: 4
            )
            model.imageryStopSignal = "Burada dur ve şimdiye dön"
            model.imagerySceneBoundary = String(
                repeating: "Sahneyi uzaktan izleyeceğim; ayaklarımı ve içinde bulunduğum odayı fark etmeyi sürdüreceğim. ",
                count: 3
            )

            await model.startImagery()
            XCTAssertNotNil(model.failure)

            assertLayoutSmoke(
                AdvancedWorkspaceView(model: model)
                    .environment(\.dynamicTypeSize, .accessibility3),
                size: size,
                scenario: "imagery start and validation"
            )
        }
    }

    func testActiveChairAndImagerySafetyControlsLayoutAtAcceptanceSizes() async {
        for size in acceptanceSizes {
            let chairSource = AdvancedSafetyDataSource(
                chair: makeChairSession(phase: .active, intensity: 4, limit: 7)
            )
            let chairModel = makeAdvancedModel(chairSource, initialModule: .chairWork)
            await chairModel.reloadWorkspace()
            assertLayoutSmoke(
                AdvancedWorkspaceView(model: chairModel)
                    .environment(\.dynamicTypeSize, .accessibility3),
                size: size,
                scenario: "active chair safety controls"
            )

            let imagerySource = AdvancedSafetyDataSource(
                imagery: makeImagerySession(phase: .active, intensity: 4, limit: 7)
            )
            let imageryModel = makeAdvancedModel(imagerySource, initialModule: .reparenting)
            await imageryModel.reloadWorkspace()
            assertLayoutSmoke(
                AdvancedWorkspaceView(model: imageryModel)
                    .environment(\.dynamicTypeSize, .accessibility3),
                size: size,
                scenario: "active imagery safety controls"
            )
        }
    }

    func testPausedChairAndImageryRecoveryControlsLayoutAtAcceptanceSizes() async {
        for size in acceptanceSizes {
            let chairSource = AdvancedSafetyDataSource(
                chair: makeChairSession(phase: .paused, intensity: 6, limit: 7)
            )
            let chairModel = makeAdvancedModel(chairSource, initialModule: .chairWork)
            await chairModel.reloadWorkspace()
            assertLayoutSmoke(
                AdvancedWorkspaceView(model: chairModel)
                    .environment(\.dynamicTypeSize, .accessibility3),
                size: size,
                scenario: "paused chair orientation and stop controls"
            )

            let imagerySource = AdvancedSafetyDataSource(
                imagery: makeImagerySession(phase: .paused, intensity: 6, limit: 7)
            )
            let imageryModel = makeAdvancedModel(imagerySource, initialModule: .reparenting)
            await imageryModel.reloadWorkspace()
            assertLayoutSmoke(
                AdvancedWorkspaceView(model: imageryModel)
                    .environment(\.dynamicTypeSize, .accessibility3),
                size: size,
                scenario: "paused imagery orientation and stop controls"
            )
        }
    }

    func testLivingMapAndWiFiModulesLayoutAtAcceptanceSizes() async {
        for size in acceptanceSizes {
            let source = AdvancedSafetyDataSource()
            let mapModel = makeAdvancedModel(source, initialModule: .livingMap)
            await mapModel.reloadWorkspace()
            assertLayoutSmoke(
                AdvancedWorkspaceView(model: mapModel)
                    .environment(\.dynamicTypeSize, .accessibility3),
                size: size,
                scenario: "living map"
            )

            let syncModel = makeAdvancedModel(source, initialModule: .wifiSync)
            await syncModel.reloadWorkspace()
            assertLayoutSmoke(
                AdvancedWorkspaceView(model: syncModel)
                    .environment(\.dynamicTypeSize, .accessibility3),
                size: size,
                scenario: "Wi-Fi sync"
            )

            let safetySource = AdvancedSafetyDataSource(
                syncStatus: WorkspaceWiFiSyncStatus(
                    phase: .awaitingClinicalSafety,
                    message: "Bu cihazdaki güvenlik beklemesi sürerken Şema çalışma kayıtları alınmadı.",
                    peerName: "Android",
                    clinicalSafetyPause: true,
                    clinicalSafetyDevice: .thisDevice,
                    clinicalSafetyMessage: "Bu cihazdaki güvenlik beklemesi sürerken Şema çalışma kayıtları alınmadı."
                )
            )
            let safetyModel = makeAdvancedModel(
                safetySource,
                initialModule: .wifiSync
            )
            await safetyModel.reloadWorkspace()
            assertLayoutSmoke(
                AdvancedWorkspaceView(model: safetyModel)
                    .environment(\.dynamicTypeSize, .accessibility3),
                size: size,
                scenario: "Wi-Fi clinical safety pause"
            )
        }
    }

    func testChatAndNewSessionLayoutWithLongTurkishTextAtAcceptanceSizes() async throws {
        for size in acceptanceSizes {
            let source = ResponsiveDivanDataSource()
            let model = DivanViewModel(dataSource: source)
            await model.bootstrap()
            let conversation = try XCTUnwrap(model.activeConversations.first)
            await model.openConversation(conversation)

            assertLayoutSmoke(
                NativeChatView(model: model)
                    .environment(\.dynamicTypeSize, .accessibility3),
                size: size,
                scenario: "long Turkish chat"
            )

            let master = try XCTUnwrap(model.selectedMaster)
            assertLayoutSmoke(
                StoryComposerView(
                    master: master,
                    portraitData: nil,
                    messages: model.messages
                )
                .environment(\.dynamicTypeSize, .accessibility3),
                size: size,
                scenario: "story composer"
            )

            model.prepareNewSession(master: model.therapists.first)
            assertLayoutSmoke(
                NewSessionSheet(model: model)
                    .environment(\.dynamicTypeSize, .accessibility3),
                size: size,
                scenario: "new session sheet"
            )
        }
    }

    func testRootNavigationSplitLayoutAtAcceptanceSizes() async throws {
        for size in acceptanceSizes {
            let chatSource = ResponsiveDivanDataSource()
            let chatModel = DivanViewModel(dataSource: chatSource)
            await chatModel.bootstrap()
            let conversation = try XCTUnwrap(chatModel.activeConversations.first)
            await chatModel.openConversation(conversation)
            chatModel.columnVisibility = .all

            assertLayoutSmoke(
                DivanRootView(
                    model: chatModel,
                    advancedDataSource: AdvancedSafetyDataSource()
                )
                .environment(\.dynamicTypeSize, .accessibility3),
                size: size,
                scenario: "root navigation split with long Turkish chat"
            )

            let advancedSource = ResponsiveDivanDataSource()
            let advancedModel = DivanViewModel(dataSource: advancedSource)
            await advancedModel.bootstrap()
            advancedModel.destination = .works
            advancedModel.advancedConversationID = conversation.id
            advancedModel.advancedInitialModule = .chairWork
            advancedModel.columnVisibility = .all

            assertLayoutSmoke(
                DivanRootView(
                    model: advancedModel,
                    advancedDataSource: AdvancedSafetyDataSource()
                )
                .environment(\.dynamicTypeSize, .accessibility3),
                size: size,
                scenario: "root navigation split with advanced workspace"
            )
        }
    }

    private func makeAdvancedModel(
        _ source: AdvancedSafetyDataSource,
        initialModule: AdvancedModule
    ) -> AdvancedWorkspaceViewModel {
        AdvancedWorkspaceViewModel(
            dataSource: source,
            context: AdvancedWorkspaceContext(
                conversationID: 12,
                masterID: "young",
                masterName: "Jeffrey Young ve güncel şema terapi yaklaşımının uzun Türkçe bağlam başlığı",
                allowsClinicalWork: true
            ),
            initialModule: initialModule
        )
    }

    private func assertLayoutSmoke<Content: View>(
        _ content: Content,
        size: CGSize,
        scenario: String,
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        let hosting = NSHostingView(rootView: content)
        hosting.frame = CGRect(origin: .zero, size: size)
        hosting.layoutSubtreeIfNeeded()
        RunLoop.current.run(until: Date(timeIntervalSinceNow: 0.02))
        // NSHostingView's intrinsic fitting size describes the unscrolled
        // document, not a hard window minimum. Re-assert the acceptance
        // viewport after SwiftUI's first pass and smoke-test that layout.
        hosting.frame = CGRect(origin: .zero, size: size)
        hosting.layoutSubtreeIfNeeded()

        XCTAssertEqual(
            hosting.bounds.size.width,
            size.width,
            accuracy: 0.5,
            "\(scenario) must accept the requested viewport width",
            file: file,
            line: line
        )
        XCTAssertEqual(
            hosting.bounds.size.height,
            size.height,
            accuracy: 0.5,
            "\(scenario) must accept the requested viewport height",
            file: file,
            line: line
        )
        assertFiniteFrames(
            in: hosting,
            scenario: scenario,
            file: file,
            line: line
        )

        let fitting = hosting.fittingSize
        XCTAssertTrue(
            fitting.width.isFinite && fitting.height.isFinite,
            "\(scenario) produced a non-finite fitting size at \(Int(size.width))×\(Int(size.height))",
            file: file,
            line: line
        )
    }

    private func assertFiniteFrames(
        in root: NSView,
        scenario: String,
        file: StaticString,
        line: UInt
    ) {
        var stack = [root]
        while let view = stack.popLast() {
            let values = [
                view.frame.origin.x,
                view.frame.origin.y,
                view.frame.size.width,
                view.frame.size.height,
                view.bounds.origin.x,
                view.bounds.origin.y,
                view.bounds.size.width,
                view.bounds.size.height,
            ]
            XCTAssertTrue(
                values.allSatisfy(\.isFinite),
                "\(scenario) produced a non-finite AppKit frame in \(type(of: view))",
                file: file,
                line: line
            )
            XCTAssertGreaterThanOrEqual(view.frame.size.width, 0, file: file, line: line)
            XCTAssertGreaterThanOrEqual(view.frame.size.height, 0, file: file, line: line)
            stack.append(contentsOf: view.subviews)
        }
    }
}

private actor ResponsiveDivanDataSource: DivanUIDataSource {
    private let master = DivanMaster(
        id: "young",
        kind: .therapist,
        name: "Jeffrey E. Young ve Güncel Şema Terapi Uygulamalarının Çok Uzun Türkçe Başlığı",
        school: "Şema Terapi · Bilişsel, bağlanma, deneyimsel ve kişilerarası yaklaşım",
        subtitle: "İncinmiş çocuk, eleştirel ebeveyn, başa çıkma modları ve sağlıklı yetişkin üzerine uzun açıklama",
        isLiving: true,
        supportedModes: [.therapy, .lesson]
    )

    private var conversation: DivanConversation {
        DivanConversation(
            id: 12,
            masterID: master.id,
            title: "Eleştirel ebeveyn sesi, görülme ihtiyacı ve sınır koyma üzerine uzun görüşme başlığı",
            preview: "Bu, dar pencerede birkaç satıra yayılarak okunabilir kalması gereken uzun bir Türkçe konuşma önizlemesidir.",
            updatedAt: Date(),
            isArchived: false,
            mode: .therapy
        )
    }

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
        let text = String(
            repeating: "Bu uzun Türkçe mesaj dar ve orta boy pencerelerde okunabilir biçimde sarılmalı; kullanıcı eski mesajı okurken odak ve kaydırma konumu korunmalıdır. ",
            count: 8
        )
        let messages = [
            DivanMessage(
                id: "message-1",
                serverID: 1,
                role: .user,
                content: text,
                createdAt: Date().addingTimeInterval(-120)
            ),
            DivanMessage(
                id: "message-2",
                serverID: 2,
                role: .assistant,
                content: text,
                createdAt: Date().addingTimeInterval(-60)
            ),
        ]
        return DivanConversationPage(
            conversation: conversation,
            master: master,
            messages: messages,
            messageCount: messages.count,
            loadedMessageCount: messages.count,
            hasMoreMessages: false,
            oldestMessageID: 1
        )
    }

    func createConversation(
        masterID: String,
        mode: DivanSessionMode
    ) async throws -> DivanNewConversation {
        DivanNewConversation(conversation: conversation, greeting: "Merhaba")
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
        AsyncThrowingStream { $0.finish() }
    }

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
    func saveSettings(_ input: DivanSettingsInput) async throws -> DivanSettingsSummary { settings }
    func clearAPIKey(provider: DivanProviderID) async throws -> DivanSettingsSummary { settings }
    func scanLocalModels() async throws -> [DivanLocalServer] { [] }
}

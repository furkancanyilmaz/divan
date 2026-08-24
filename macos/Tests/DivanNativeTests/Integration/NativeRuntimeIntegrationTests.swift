import Darwin
import Foundation
import XCTest
@testable import DivanNative

final class NativeRuntimeIntegrationTests: XCTestCase {
    private struct Harness {
        let root: URL
        let dataDirectory: URL
        let databaseURL: URL
        let python: URL
        let runtime: CoreRuntime
        let endpoint: RuntimeEndpoint
        let client: APIClient
    }

    private final class FakeStreamingProvider {
        let process: Process
        let output: Pipe
        let errors: Pipe
        let port: Int
        let logURL: URL?
        private let terminationSignal: DispatchSemaphore
        private let stopLock = NSLock()
        private var stopped = false

        init(
            process: Process,
            output: Pipe,
            errors: Pipe,
            port: Int,
            logURL: URL? = nil
        ) {
            let terminationSignal = DispatchSemaphore(value: 0)
            self.process = process
            self.output = output
            self.errors = errors
            self.port = port
            self.logURL = logURL
            self.terminationSignal = terminationSignal
            process.terminationHandler = { _ in
                terminationSignal.signal()
            }
        }

        func stop() {
            stopLock.lock()
            guard !stopped else {
                stopLock.unlock()
                return
            }
            stopped = true
            stopLock.unlock()

            guard process.isRunning else { return }
            process.terminate()
            if terminationSignal.wait(timeout: .now() + 2) == .timedOut {
                Darwin.kill(process.processIdentifier, SIGKILL)
                _ = terminationSignal.wait(timeout: .now() + 2)
            }
        }

        deinit {
            stop()
            if let logURL,
               FileManager.default.fileExists(atPath: logURL.path) {
                try? FileManager.default.removeItem(at: logURL)
            }
        }
    }

    func testRealRuntimeBootstrapsEmptyIsolatedStoreWithoutLeakingSecret() async throws {
        let secret = "native-integration-secret-" + UUID().uuidString
        let coreDirectory = try sourceCoreDirectory()
        let sourceDatabase = coreDirectory.appendingPathComponent("freud.db")
        XCTAssertFalse(
            try databaseContainsMarker(sourceDatabase, marker: secret),
            "Test işareti kaynak Divan veritabanında testten önce bulunmamalı."
        )

        let harness = try await startHarness(extraEnvironment: [
            "DIVAN_LLM_PROVIDER": "openai",
            "OPENAI_API_KEY": secret,
            "OPENAI_MODEL": "gpt-native-integration-no-network",
        ])
        do {
            XCTAssertGreaterThan(harness.endpoint.baseURL.port ?? 0, 0)
            XCTAssertNotEqual(harness.endpoint.baseURL.port, 8768)
            XCTAssertEqual(harness.endpoint.baseURL.host, "127.0.0.1")
            XCTAssertEqual(harness.endpoint.sessionToken.count, 64)

            let bootstrap = try await harness.client.bootstrap()
            XCTAssertEqual(bootstrap.apiContractVersion, 1)
            XCTAssertFalse(bootstrap.appVersion.isEmpty)
            XCTAssertFalse(bootstrap.therapists.isEmpty)
            XCTAssertFalse(bootstrap.philosophers.isEmpty)
            XCTAssertEqual(
                bootstrap.settings.selectedProviderID,
                "openai"
            )
            let provider = try XCTUnwrap(
                bootstrap.settings.providers.first { $0.id == "openai" }
            )
            XCTAssertTrue(provider.keySet)
            XCTAssertEqual(provider.model, "gpt-native-integration-no-network")

            let freud = try XCTUnwrap(
                bootstrap.therapists.first { $0.id == "freud" }
            )
            XCTAssertEqual(freud.name, "Sigmund Freud")
            XCTAssertFalse(freud.school.isEmpty)
            let portraitURL = try XCTUnwrap(freud.portraitURL)
            XCTAssertEqual(portraitURL.host, harness.endpoint.baseURL.host)
            XCTAssertEqual(portraitURL.port, harness.endpoint.baseURL.port)
            let portraitData = try await harness.client.portraitData(url: portraitURL)
            XCTAssertFalse(portraitData.isEmpty)
            XCTAssertTrue(
                isSupportedPortraitImage(portraitData),
                "Freud portresi geçerli bir JPEG, PNG veya WebP imzası taşımalı."
            )

            let confucius = try XCTUnwrap(
                bootstrap.philosophers.first { $0.id == "confucius" }
            )
            XCTAssertEqual(confucius.kind, .philosopher)
            XCTAssertEqual(confucius.supportedModes, ["ders"])

            let therapists = try await harness.client.masters(kind: .therapist)
            let philosophers = try await harness.client.masters(kind: .philosopher)
            let active = try await harness.client.conversations(archived: false)
            let archived = try await harness.client.conversations(archived: true)
            XCTAssertEqual(therapists, bootstrap.therapists)
            XCTAssertEqual(philosophers, bootstrap.philosophers)
            XCTAssertEqual(active, [])
            XCTAssertEqual(archived, [])

            await harness.runtime.stop()

            XCTAssertTrue(FileManager.default.fileExists(
                atPath: harness.databaseURL.path))
            XCTAssertEqual(try permissions(harness.dataDirectory), 0o700)
            XCTAssertEqual(try permissions(harness.databaseURL), 0o600)
            XCTAssertFalse(
                try directoryContainsMarker(harness.root, marker: secret),
                "Ortamdan verilen API anahtarı DB, günlük veya metadata içine yazılmamalı."
            )
            XCTAssertFalse(
                try databaseContainsMarker(sourceDatabase, marker: secret),
                "Preview çalışma zamanı kaynak/kişisel Divan DB'sine yazmamalı."
            )
        } catch {
            await harness.runtime.stop()
            try? FileManager.default.removeItem(at: harness.root)
            throw error
        }
        try FileManager.default.removeItem(at: harness.root)
    }

    func testConversationLifecyclePagingArchiveDeleteAndStatusTransport() async throws {
        let harness = try await startHarness(extraEnvironment: [
            "DIVAN_LLM_PROVIDER": "lmstudio",
            "LMSTUDIO_BASE_URL": "http://127.0.0.1:65534/v1",
            "LMSTUDIO_MODEL": "auto",
        ])
        do {
            _ = try await harness.client.bootstrap()
            let created = try await harness.client.createConversation(
                masterID: "freud",
                mode: "terapi",
                submode: nil
            )
            XCTAssertGreaterThan(created.id, 0)
            XCTAssertEqual(created.title, "Yeni seans")
            XCTAssertFalse(created.greeting.isEmpty)

            var active = try await harness.client.conversations(archived: false)
            XCTAssertEqual(active.map(\.id), [created.id])
            XCTAssertEqual(active[0].masterID, "freud")
            XCTAssertEqual(active[0].messageCount, 0)
            let initiallyArchived = try await harness.client.conversations(archived: true)
            XCTAssertEqual(initiallyArchived, [])

            let marker = "native-page-" + UUID().uuidString
            try seedMessages(
                database: harness.databaseURL,
                conversationID: created.id,
                count: 95,
                marker: marker,
                python: harness.python
            )

            active = try await harness.client.conversations(archived: false)
            XCTAssertEqual(active.count, 1)
            XCTAssertEqual(active[0].messageCount, 95)
            XCTAssertTrue(active[0].preview.contains("094"))

            let newest = try await harness.client.conversation(
                id: created.id,
                limit: 80,
                beforeID: nil
            )
            XCTAssertEqual(newest.messageCount, 95)
            XCTAssertEqual(newest.loadedMessageCount, 80)
            XCTAssertEqual(newest.messages.count, 80)
            XCTAssertTrue(newest.hasMoreMessages)
            XCTAssertEqual(newest.messages.map(\.id), newest.messages.map(\.id).sorted())
            XCTAssertTrue(newest.messages.first?.content.contains("015") == true)
            XCTAssertTrue(newest.messages.last?.content.contains("094") == true)

            let oldestLoadedID = try XCTUnwrap(newest.oldestMessageID)
            let older = try await harness.client.conversation(
                id: created.id,
                limit: 80,
                beforeID: oldestLoadedID
            )
            XCTAssertEqual(older.messageCount, 95)
            XCTAssertEqual(older.loadedMessageCount, 15)
            XCTAssertEqual(older.messages.count, 15)
            XCTAssertFalse(older.hasMoreMessages)
            XCTAssertTrue(older.messages.first?.content.contains("000") == true)
            XCTAssertTrue(older.messages.last?.content.contains("014") == true)
            XCTAssertTrue(Set(newest.messages.map(\.id)).isDisjoint(
                with: Set(older.messages.map(\.id))))

            do {
                _ = try await harness.client.chatStatus(
                    requestID: "native-integration-missing-" +
                        UUID().uuidString.replacingOccurrences(of: "-", with: "")
                )
                XCTFail("Olmayan dayanıklı mesaj isteği 404 dönmeli.")
            } catch let error as DivanAPIError {
                XCTAssertEqual(error.statusCode, 404)
            }

            try await harness.client.setArchived(true, id: created.id)
            let activeAfterArchive = try await harness.client.conversations(archived: false)
            XCTAssertEqual(activeAfterArchive, [])
            let archived = try await harness.client.conversations(archived: true)
            XCTAssertEqual(archived.map(\.id), [created.id])
            XCTAssertTrue(archived[0].isArchived)

            try await harness.client.setArchived(false, id: created.id)
            active = try await harness.client.conversations(archived: false)
            XCTAssertEqual(active.map(\.id), [created.id])

            try await harness.client.deleteConversation(id: created.id)
            let activeAfterDelete = try await harness.client.conversations(archived: false)
            let archivedAfterDelete = try await harness.client.conversations(archived: true)
            XCTAssertEqual(activeAfterDelete, [])
            XCTAssertEqual(archivedAfterDelete, [])
            do {
                _ = try await harness.client.conversation(id: created.id, limit: 80)
                XCTFail("Silinen sohbet tekrar okunamamalı.")
            } catch let error as DivanAPIError {
                XCTAssertEqual(error.statusCode, 404)
            }

            await harness.runtime.stop()
        } catch {
            await harness.runtime.stop()
            try? FileManager.default.removeItem(at: harness.root)
            throw error
        }
        try FileManager.default.removeItem(at: harness.root)
    }

    func testRealRuntimeAdvancedChairImageryStartConflictAndStop() async throws {
        let harness = try await startHarness(extraEnvironment: [
            "DIVAN_LLM_PROVIDER": "lmstudio",
            "LMSTUDIO_BASE_URL": "http://127.0.0.1:65534/v1",
            "LMSTUDIO_MODEL": "auto",
        ])
        let controller = await MainActor.run {
            RuntimeController(runtime: harness.runtime)
        }
        let loader = await MainActor.run {
            DivanRuntimeLoader(controller: controller)
        }
        let adapter = CoreAdvancedWorkspaceDataSource(loader: loader)
        do {
            let (client, _) = try await loader.service()
            let created = try await client.createConversation(
                masterID: "young", mode: "terapi", submode: nil
            )
            let context = AdvancedWorkspaceContext(
                conversationID: created.id,
                masterID: "young",
                masterName: "Jeffrey Young",
                allowsClinicalWork: true
            )
            let initial = try await adapter.advancedWorkspaceSnapshot(
                context: context
            )
            XCTAssertFalse(initial.clinicalSafetyHold)
            XCTAssertNil(initial.chairSession)
            XCTAssertNil(initial.imagerySession)

            let catalog = try await client.techniqueCatalog(
                therapistID: "young",
                conversationID: created.id
            )
            let chairMethods = catalog.methods.filter(\.isChairWork)
            let chairMethod = try XCTUnwrap(
                chairMethods.first(where: \.recommended) ?? chairMethods.first
            )
            let proposedChair = try await client.mutateTechniqueRun(
                TechniqueRunMutation(
                    conversationID: created.id,
                    action: .propose,
                    methodKey: chairMethod.key,
                    intensity: 4
                )
            )
            XCTAssertEqual(proposedChair.run.status, "proposed")
            XCTAssertNil(proposedChair.run.consentAt)

            var participantTitles = initial.chairConfiguration
                .defaultParticipantTitles
            while participantTitles.count < initial.chairConfiguration
                .minimumParticipants {
                participantTitles.append("Parça \(participantTitles.count + 1)")
            }
            XCTAssertFalse(participantTitles.isEmpty)
            let confirmedParticipantTitles = participantTitles
            let workspaceModel = await MainActor.run {
                AdvancedWorkspaceViewModel(
                    dataSource: adapter,
                    context: context,
                    initialModule: .chairWork
                )
            }
            await workspaceModel.loadIfNeeded()
            await MainActor.run {
                workspaceModel.chairGoalText = "İç çatışmayı iki taraftan duymak"
                workspaceModel.chairStopSignal = "şimdi dur"
                workspaceModel.chairParticipantTitles = confirmedParticipantTitles
                workspaceModel.chairIntensity = 4
                workspaceModel.chairOrientationConfirmed = true
                workspaceModel.chairFrameConfirmed = true
                workspaceModel.chairRealityConfirmed = true
                workspaceModel.chairSleepActivationClear = true
                workspaceModel.chairSupportAvailable = true
            }
            // Exact native CTA path: the view's button invokes this method.
            await workspaceModel.startChairWork()
            let visibleChair = await MainActor.run { workspaceModel.chairSession }
            let visibleFailure = await MainActor.run { workspaceModel.failure }
            XCTAssertNil(
                visibleFailure,
                "Geçerli Başlat tıklaması görünür bir hata üretmemeli: "
                    + (visibleFailure?.message ?? "")
            )
            let chair = try XCTUnwrap(
                visibleChair,
                "Başlat tıklaması aktif sandalye oturumunu UI modeline taşımalı."
            )
            XCTAssertEqual(chair.phase, .active)
            XCTAssertEqual(chair.goalText, "İç çatışmayı iki taraftan duymak")
            XCTAssertEqual(chair.stopSignal, "şimdi dur")
            XCTAssertGreaterThanOrEqual(
                chair.participants.count,
                initial.chairConfiguration.minimumParticipants
            )
            let activeChairRuns = try await client.techniqueRuns(
                conversationID: created.id
            )
            XCTAssertEqual(activeChairRuns.runs.filter(\.isOpen).count, 1)
            let activeChairRun = try XCTUnwrap(
                activeChairRuns.runs.first(where: \.isOpen)
            )
            XCTAssertEqual(activeChairRun.id, proposedChair.run.id)
            XCTAssertNotNil(activeChairRun.consentAt)

            do {
                _ = try await adapter.startImagery(
                    request: WorkspaceImageryStartRequest(
                        conversationID: created.id,
                        intention: "Kırılgan parçaya yaklaşmak",
                        intensity: 4,
                        orientationConfirmed: true,
                        frameConfirmed: true,
                        realityConfirmed: true,
                        stopSignal: "şimdi dur",
                        sceneBoundary: "Yalnız seçtiğim kısa sahne",
                        sleepActivationClear: true,
                        supportAvailable: true
                    )
                )
                XCTFail("Açık sandalye çalışması varken ikinci yöntem başlamamalı.")
            } catch {
                XCTAssertTrue(
                    error.localizedDescription.localizedCaseInsensitiveContains(
                        "diğer çalışmayı bitirin"
                    ),
                    "Çakışma kullanıcıya görünür bir hata olmalı: \(error)"
                )
            }

            let stoppedChair = try await adapter.stopChairWork(
                sessionID: chair.id
            )
            XCTAssertEqual(stoppedChair.phase, .completed)
            let afterChairStop = try await client.techniqueRuns(
                conversationID: created.id
            )
            XCTAssertTrue(afterChairStop.runs.allSatisfy { !$0.isOpen })

            let imageryMethods = catalog.methods.filter(\.isLimitedReparenting)
            let imageryMethod = try XCTUnwrap(
                imageryMethods.first(where: \.recommended) ?? imageryMethods.first
            )
            let proposedImagery = try await client.mutateTechniqueRun(
                TechniqueRunMutation(
                    conversationID: created.id,
                    action: .propose,
                    methodKey: imageryMethod.key,
                    intensity: 4
                )
            )
            XCTAssertEqual(proposedImagery.run.status, "proposed")
            let imageryBeforeStart = try await client.imageryWork(
                conversationID: created.id
            )
            XCTAssertNil(imageryBeforeStart)

            let imagery = try await adapter.startImagery(
                request: WorkspaceImageryStartRequest(
                    conversationID: created.id,
                    intention: "Kırılgan parçaya güvenli bir cümle söylemek",
                    intensity: 4,
                    orientationConfirmed: true,
                    frameConfirmed: true,
                    realityConfirmed: true,
                    stopSignal: "şimdi dur",
                    sceneBoundary: "Yalnız seçtiğim kısa sahne",
                    sleepActivationClear: true,
                    supportAvailable: true
                )
            )
            XCTAssertEqual(imagery.phase, .active)
            XCTAssertEqual(imagery.stopSignal, "şimdi dur")
            XCTAssertTrue(imagery.entries.contains(where: {
                $0.content == "Kırılgan parçaya güvenli bir cümle söylemek"
            }))
            let loadedImagery = try await client.imageryWork(
                conversationID: created.id
            )
            let storedImagery = try XCTUnwrap(loadedImagery)
            XCTAssertEqual(String(storedImagery.id), imagery.id)
            XCTAssertEqual(storedImagery.techniqueRunID, proposedImagery.run.id)
            XCTAssertTrue(storedImagery.consentComplete)

            let stoppedImagery = try await adapter.stopImagery(
                sessionID: imagery.id
            )
            XCTAssertEqual(stoppedImagery.phase, .completed)
            let afterImageryStop = try await client.techniqueRuns(
                conversationID: created.id
            )
            XCTAssertTrue(afterImageryStop.runs.allSatisfy { !$0.isOpen })
            await loader.stop()
        } catch {
            await loader.stop()
            try? FileManager.default.removeItem(at: harness.root)
            throw error
        }
        try FileManager.default.removeItem(at: harness.root)
    }

    func testRealRuntimeStructuredADHDAndSchemaContractsRoundTrip() async throws {
        let harness = try await startHarness(extraEnvironment: [
            "DIVAN_LLM_PROVIDER": "lmstudio",
            "LMSTUDIO_BASE_URL": "http://127.0.0.1:65534/v1",
            "LMSTUDIO_MODEL": "auto",
        ])
        do {
            let adhdConversation = try await harness.client.createConversation(
                masterID: "adhd", mode: "terapi", submode: nil
            )
            let emptyDashboard = try await harness.client.adhdDashboard(
                conversationID: adhdConversation.id
            )
            XCTAssertEqual(emptyDashboard.conversationID, adhdConversation.id)
            XCTAssertEqual(emptyDashboard.defaultTargetPerWeek, 2)
            XCTAssertTrue(emptyDashboard.habits.isEmpty)

            let createID = "native-test-adhd-habit-0001"
            let created = try await harness.client.mutateADHDHabit(
                ADHDHabitMutation(
                    action: .create,
                    conversationID: adhdConversation.id,
                    requestID: createID,
                    title: "Defteri aç",
                    cue: "Kahveden sonra",
                    tinyAction: "Tek satır yaz",
                    targetPerWeek: 2,
                    preferredDays: [1, 4],
                    reminderLocalTime: "",
                    timezone: "Europe/Istanbul"
                )
            )
            XCTAssertFalse(created.duplicate)
            XCTAssertEqual(created.habit.title, "Defteri aç")
            XCTAssertEqual(created.habit.preferredDays, [1, 4])

            let duplicate = try await harness.client.mutateADHDHabit(
                ADHDHabitMutation(
                    action: .create,
                    conversationID: adhdConversation.id,
                    requestID: createID,
                    title: "Defteri aç",
                    cue: "Kahveden sonra",
                    tinyAction: "Tek satır yaz",
                    targetPerWeek: 2,
                    preferredDays: [1, 4],
                    reminderLocalTime: "",
                    timezone: "Europe/Istanbul"
                )
            )
            XCTAssertTrue(duplicate.duplicate)
            XCTAssertEqual(duplicate.habit.id, created.habit.id)

            let started = try await harness.client.mutateADHDHabit(
                ADHDHabitMutation(
                    action: .startNow,
                    conversationID: adhdConversation.id,
                    requestID: "native-test-adhd-start-0001",
                    habitID: created.habit.id
                )
            )
            let event = try XCTUnwrap(started.event)
            XCTAssertEqual(event.status, "started")
            XCTAssertNil(started.reminder)

            let completed = try await harness.client.mutateADHDEvent(
                ADHDEventMutation(
                    action: .done,
                    conversationID: adhdConversation.id,
                    eventID: event.id,
                    requestID: "native-test-adhd-event-0001",
                    effortMinutes: 5,
                    friction: "start",
                    note: "Başlamak en zor adımdı."
                )
            )
            XCTAssertEqual(completed.event.status, "done")
            XCTAssertEqual(completed.event.effortMinutes, 5)

            let journal = try await harness.client.mutateADHDJournal(
                ADHDJournalMutation(
                    action: .create,
                    conversationID: adhdConversation.id,
                    requestID: "native-test-adhd-journal-0001",
                    content: "Bugün tek satır yeterliydi.",
                    entryType: .dailyPage,
                    shareWithCoach: false,
                    sensitive: true,
                    habitID: created.habit.id,
                    eventID: event.id
                )
            )
            XCTAssertTrue(try XCTUnwrap(journal.journalEntry).sensitive)
            XCTAssertFalse(try XCTUnwrap(journal.journalEntry).shareWithCoach)

            let populated = try await harness.client.adhdDashboard(
                conversationID: adhdConversation.id
            )
            XCTAssertEqual(populated.habits.map(\.id), [created.habit.id])
            XCTAssertEqual(populated.events.first?.status, "done")
            XCTAssertEqual(populated.journalEntries.first?.content,
                           "Bugün tek satır yeterliydi.")

            let schemaConversation = try await harness.client.createConversation(
                masterID: "young", mode: "terapi", submode: nil
            )
            let schema = try await harness.client.schemaPath(
                conversationID: schemaConversation.id
            )
            XCTAssertEqual(schema.version, 5)
            XCTAssertEqual(schema.protocol, "schema_path_chat_v5")
            XCTAssertNil(schema.activePath)
            XCTAssertEqual(schema.minimumListeningTurns, 1)
            XCTAssertEqual(schema.schemaMode?.enabled, false)
            XCTAssertEqual(schema.schemaMode?.preferenceEnabled, true)
            XCTAssertEqual(schema.schemaMode?.pendingDeviceConfirmation, true)
            XCTAssertEqual(
                schema.schemaMode?.reason,
                "device_confirmation_required"
            )
            XCTAssertEqual(schema.turnAnalysis?.analysisUnit,
                           "completed_user_assistant_turn")
            XCTAssertNotNil(schema.turnAnalysis?.provider)
            XCTAssertEqual(schema.allowedActions, ["set_mode"])

            let enabled = try await harness.client.mutateSchemaTurnAnalysis(
                SchemaTurnAnalysisMutation(
                    action: .setMode,
                    conversationID: schemaConversation.id,
                    requestID: "native-test-schema-mode-0001",
                    enabled: true,
                    providerID: schema.turnAnalysis?.provider?.id,
                    modelID: schema.turnAnalysis?.provider?.model
                )
            )
            XCTAssertTrue(try XCTUnwrap(enabled.schemaMode).enabled)
            let activeSchema = try await harness.client.schemaPath(
                conversationID: schemaConversation.id
            )
            XCTAssertTrue(activeSchema.allowedActions.contains("review_candidate"))
            XCTAssertTrue(activeSchema.allowedActions.contains("start"))
            XCTAssertEqual(activeSchema.turnAnalysis?.eligibleTurns, 0)

            await harness.runtime.stop()
        } catch {
            await harness.runtime.stop()
            try? FileManager.default.removeItem(at: harness.root)
            throw error
        }
        try FileManager.default.removeItem(at: harness.root)
    }

    func testRealRuntimeADHDTUSPlannerLifecycleIsResumableAndBounded() async throws {
        let harness = try await startHarness(extraEnvironment: [
            "DIVAN_LLM_PROVIDER": "lmstudio",
            "LMSTUDIO_BASE_URL": "http://127.0.0.1:65534/v1",
            "LMSTUDIO_MODEL": "auto",
        ])
        do {
            let conversation = try await harness.client.createConversation(
                masterID: "adhd", mode: "terapi", submode: nil
            )
            var snapshot = try await harness.client.adhdTUSPlanner(
                conversationID: conversation.id
            )
            XCTAssertTrue(snapshot.contractIsSupported)
            XCTAssertFalse(snapshot.enabled)
            XCTAssertEqual(snapshot.state, "disabled")
            XCTAssertTrue(snapshot.catalog.available)
            XCTAssertGreaterThan(snapshot.catalog.questionAreas, 0)
            XCTAssertGreaterThan(snapshot.catalog.readingAreas, 0)

            snapshot = try await harness.client.mutateADHDTUS(.init(
                action: .setMode,
                conversationID: conversation.id,
                expectedRevision: snapshot.revision,
                requestID: "native-tus-integration-mode-on-0001",
                enabled: true
            ))
            XCTAssertEqual(snapshot.question?.id, "activity")

            var turn = 0
            while let question = snapshot.question {
                turn += 1
                XCTAssertLessThanOrEqual(turn, 6)
                let option: ADHDTUSOption
                if question.id == "activity" {
                    option = try XCTUnwrap(
                        question.options.first { $0.id == "mixed" }
                            ?? question.options.first
                    )
                } else if question.id == "available_time" {
                    option = try XCTUnwrap(
                        question.options.first { $0.id == "5" }
                    )
                } else if question.id == "start_friction" {
                    option = try XCTUnwrap(
                        question.options.first { $0.id == "hard" }
                    )
                } else {
                    option = try XCTUnwrap(question.options.first)
                }
                snapshot = try await harness.client.mutateADHDTUS(.init(
                    action: .answer,
                    conversationID: conversation.id,
                    expectedRevision: snapshot.revision,
                    requestID: "native-tus-integration-answer-\(turn)-0001",
                    questionID: question.id,
                    optionID: option.id
                ))
            }

            XCTAssertEqual(snapshot.state, "plan_ready")
            let ready = try XCTUnwrap(snapshot.plan)
            XCTAssertTrue((1...20).contains(ready.steps.count))
            XCTAssertTrue(ready.steps.allSatisfy {
                (1...20).contains($0.durationMinutes)
            })
            XCTAssertEqual(
                ready.steps.reduce(0) { $0 + $1.durationMinutes },
                ready.availableMinutes
            )
            XCTAssertEqual(ready.currentStep?.status, "pending")
            XCTAssertEqual(ready.steps.filter(\.visible).count, 1)

            snapshot = try await harness.client.mutateADHDTUS(.init(
                action: .start,
                conversationID: conversation.id,
                expectedRevision: snapshot.revision,
                requestID: "native-tus-integration-start-0001",
                planID: ready.id
            ))
            XCTAssertEqual(snapshot.state, "active")
            XCTAssertEqual(snapshot.plan?.currentStep?.status, "active")

            snapshot = try await harness.client.mutateADHDTUS(.init(
                action: .pause,
                conversationID: conversation.id,
                expectedRevision: snapshot.revision,
                requestID: "native-tus-integration-pause-0001"
            ))
            XCTAssertEqual(snapshot.state, "paused")
            snapshot = try await harness.client.mutateADHDTUS(.init(
                action: .resume,
                conversationID: conversation.id,
                expectedRevision: snapshot.revision,
                requestID: "native-tus-integration-resume-0001"
            ))
            XCTAssertEqual(snapshot.state, "active")

            let activePlan = try XCTUnwrap(snapshot.plan)
            let activeStep = try XCTUnwrap(activePlan.currentStep)
            snapshot = try await harness.client.mutateADHDTUS(.init(
                action: .completeStep,
                conversationID: conversation.id,
                expectedRevision: snapshot.revision,
                requestID: "native-tus-integration-step-0001",
                planID: activePlan.id,
                stepID: activeStep.id
            ))
            XCTAssertEqual(snapshot.plan?.progress.completed, 1)
            let reloaded = try await harness.client.adhdTUSPlanner(
                conversationID: conversation.id
            )
            XCTAssertEqual(reloaded.revision, snapshot.revision)
            XCTAssertEqual(reloaded.plan?.currentStep, snapshot.plan?.currentStep)

            let finishRevision = snapshot.revision
            let finish = ADHDTUSMutation(
                action: .finish,
                conversationID: conversation.id,
                expectedRevision: finishRevision,
                requestID: "native-tus-integration-finish-0001",
                planID: try XCTUnwrap(snapshot.plan?.id)
            )
            snapshot = try await harness.client.mutateADHDTUS(finish)
            XCTAssertEqual(snapshot.state, "completed")
            XCTAssertEqual(snapshot.plan?.status, "finished")
            XCTAssertNil(snapshot.plan?.currentStep)
            XCTAssertTrue(snapshot.plan?.steps.contains(where: {
                $0.status == "pending"
            }) == true)

            let duplicate = try await harness.client.mutateADHDTUS(finish)
            XCTAssertEqual(duplicate.duplicate, true)
            XCTAssertEqual(duplicate.revision, finishRevision + 1)
            XCTAssertEqual(duplicate.plan?.id, snapshot.plan?.id)

            let disabled = try await harness.client.mutateADHDTUS(.init(
                action: .setMode,
                conversationID: conversation.id,
                expectedRevision: duplicate.revision,
                requestID: "native-tus-integration-mode-off-0001",
                enabled: false
            ))
            XCTAssertEqual(disabled.state, "disabled")
            XCTAssertFalse(disabled.enabled)
            XCTAssertEqual(disabled.plan?.status, "finished")

            await harness.runtime.stop()
        } catch {
            await harness.runtime.stop()
            try? FileManager.default.removeItem(at: harness.root)
            throw error
        }
        try FileManager.default.removeItem(at: harness.root)
    }

    func testRealRuntimeSchemaAnalyzesExactlyOneCompletedTurnIdempotently() async throws {
        let python = try XCTUnwrap(
            CoreRuntime.discoverPython(),
            "Entegrasyon testi için Python 3.9+ gerekli."
        )
        let provider = try startFakeSchemaTurnProvider(python: python)
        let harness: Harness
        do {
            harness = try await startHarness(extraEnvironment: [
                "DIVAN_LLM_PROVIDER": "lmstudio",
                "LMSTUDIO_BASE_URL": "http://127.0.0.1:\(provider.port)/v1",
                "LMSTUDIO_MODEL": "divan-schema-turn-test",
            ])
        } catch {
            provider.stop()
            throw error
        }
        do {
            let conversation = try await harness.client.createConversation(
                masterID: "young", mode: "terapi", submode: nil
            )

            // The completed, authoritative chat-request pair predates consent.
            // Enabling future analysis must not silently consume it; the
            // explicit one-turn action below does.
            let userMessageID = try seedCompletedChatTurn(
                database: harness.databaseURL,
                conversationID: conversation.id,
                python: harness.python
            )

            let beforeConsent = try await harness.client.schemaPath(
                conversationID: conversation.id
            )
            XCTAssertEqual(beforeConsent.schemaMode?.enabled, false)
            XCTAssertEqual(beforeConsent.schemaMode?.preferenceEnabled, true)
            XCTAssertEqual(
                beforeConsent.schemaMode?.pendingDeviceConfirmation,
                true
            )
            XCTAssertEqual(beforeConsent.turnAnalysis?.eligibleTurns, 1)
            XCTAssertEqual(beforeConsent.turnAnalysis?.analyzedTurns, 0)
            let providerCallsBeforeLocalConsent = provider.logURL.flatMap {
                try? String(contentsOf: $0, encoding: .utf8)
            } ?? ""
            XCTAssertTrue(
                providerCallsBeforeLocalConsent.isEmpty,
                "Cihazdaki sağlayıcı/model açıkça onaylanmadan şema metni modele gönderilmemeli."
            )

            _ = try await harness.client.mutateSchemaTurnAnalysis(.init(
                action: .setMode,
                conversationID: conversation.id,
                requestID: "native-schema-turn-mode-0001",
                enabled: true,
                providerID: beforeConsent.turnAnalysis?.provider?.id,
                modelID: beforeConsent.turnAnalysis?.provider?.model
            ))
            let enabledButUnscanned = try await harness.client.schemaPath(
                conversationID: conversation.id
            )
            XCTAssertEqual(enabledButUnscanned.turnAnalysis?.analyzedTurns, 0)
            XCTAssertEqual(enabledButUnscanned.turnAnalysis?.remainingTurns, 1)

            let queued = try await harness.client.mutateSchemaTurnAnalysis(.init(
                action: .analyzeTurn,
                conversationID: conversation.id,
                requestID: "native-schema-turn-single-0001",
                userMessageID: userMessageID,
                consent: true,
                providerID: enabledButUnscanned.turnAnalysis?.provider?.id,
                modelID: enabledButUnscanned.turnAnalysis?.provider?.model
            ))
            XCTAssertTrue(queued.ok)
            XCTAssertEqual(queued.userMessageId, userMessageID)

            var analyzed = try await harness.client.schemaPath(
                conversationID: conversation.id
            )
            for _ in 0..<100 where
                analyzed.turnAnalysis?.analyzedTurns != 1
                    || analyzed.turnAnalysis?.processing == true {
                try await Task.sleep(for: .milliseconds(100))
                analyzed = try await harness.client.schemaPath(
                    conversationID: conversation.id
                )
            }
            let providerLog = provider.logURL.flatMap {
                try? String(contentsOf: $0, encoding: .utf8)
            } ?? "sağlayıcı günlüğü yok"
            let analysisDetail = String(describing: analyzed.turnAnalysis)
                + "\nProvider:\n" + providerLog
            XCTAssertEqual(analyzed.turnAnalysis?.analyzedTurns, 1, analysisDetail)
            XCTAssertEqual(analyzed.turnAnalysis?.remainingTurns, 0, analysisDetail)
            XCTAssertEqual(
                analyzed.turnAnalysis?.throughMessageId,
                userMessageID,
                analysisDetail
            )
            XCTAssertEqual(analyzed.turnAnalysis?.provider?.id, "lmstudio")
            XCTAssertEqual(analyzed.turnAnalysis?.provider?.model,
                           "divan-schema-turn-test")
            XCTAssertFalse(analyzed.turnAnalysis?.provider?.local == false)

            let candidate = try XCTUnwrap(analyzed.candidates.first, analysisDetail)
            XCTAssertEqual(candidate.schema?.id, "schema_abandonment")
            XCTAssertEqual(candidate.mode?.id, "vulnerable_child")
            XCTAssertEqual(candidate.sourceTurn?.userMessageId, userMessageID)
            XCTAssertNotNil(candidate.sourceTurn?.assistantMessageId)
            XCTAssertEqual(candidate.decisionState, "pending")
            let decisions = try XCTUnwrap(candidate.availableDecisions)
            XCTAssertTrue(decisions.contains("accept"))
            XCTAssertTrue(decisions.contains("defer"))
            XCTAssertTrue(decisions.contains("dismiss"))

            let duplicate = try await harness.client.mutateSchemaTurnAnalysis(.init(
                action: .analyzeTurn,
                conversationID: conversation.id,
                requestID: "native-schema-turn-single-0002",
                userMessageID: userMessageID,
                consent: true,
                providerID: analyzed.turnAnalysis?.provider?.id,
                modelID: analyzed.turnAnalysis?.provider?.model
            ))
            XCTAssertTrue(duplicate.alreadyAnalyzed == true)
            XCTAssertFalse(duplicate.processing == true)

            // Inline mode cards are created beside the exact third durable
            // assistant turn. They are pathless: accepting one may approve a
            // candidate, but it must never start a path implicitly.
            _ = try seedCompletedChatTurn(
                database: harness.databaseURL,
                conversationID: conversation.id,
                python: harness.python
            )
            let inlineStream = try await harness.client.sendMessage(
                conversationID: conversation.id,
                text: "Eleştiri gelince içimde küçük ve korkmuş bir yan geri çekiliyor."
            )
            var inlineUserMessageID: Int?
            var inlineAssistantMessageID: Int?
            var visibleInlineReply = ""
            for try await event in inlineStream {
                if event.kind == .accepted {
                    inlineUserMessageID = event.userMessageID
                } else if event.kind == .delta {
                    visibleInlineReply += event.text
                } else if event.kind == .replace {
                    visibleInlineReply = event.text
                } else if event.kind == .done {
                    inlineAssistantMessageID = event.assistantMessageID
                }
            }
            XCTAssertNotNil(inlineUserMessageID)
            XCTAssertNotNil(inlineAssistantMessageID)
            XCTAssertFalse(visibleInlineReply.contains("[[MOD]]"))

            let withInlineCard = try await harness.client.schemaPath(
                conversationID: conversation.id
            )
            XCTAssertGreaterThanOrEqual(withInlineCard.completedTurns, 3)
            let inlineProviderLog = provider.logURL.flatMap {
                try? String(contentsOf: $0, encoding: .utf8)
            } ?? "sağlayıcı günlüğü yok"
            let inlineDetail = String(describing: withInlineCard)
                + "\nProvider:\n" + inlineProviderLog
            let inlineSuggestion = try XCTUnwrap(
                withInlineCard.inlineSuggestions?.first {
                    $0.assistantMessageId == inlineAssistantMessageID
                }, inlineDetail
            )
            XCTAssertEqual(inlineSuggestion.modeKey, "vulnerable_child")
            let inlineAccepted = try await harness.client.mutateSchemaPath(.init(
                action: .acceptSuggestion,
                conversationID: conversation.id,
                requestID: "native-schema-inline-accept-0001",
                suggestionID: inlineSuggestion.id
            ))
            XCTAssertNil(inlineAccepted.activePath)
            XCTAssertTrue(try XCTUnwrap(inlineAccepted.candidate).approvedForPath)

            let accepted = try await harness.client.mutateSchemaPath(.init(
                action: .reviewCandidate,
                conversationID: conversation.id,
                requestID: "native-schema-turn-accept-0001",
                claimID: candidate.id,
                decision: .accept
            ))
            XCTAssertEqual(accepted.candidate?.decisionState, "accepted")
            XCTAssertNil(accepted.activePath)

            // The old multi-screen start and reducer mutations remain server
            // compatibility shims only.  A new path may begin exclusively via
            // the compact Evet action attached to the exact assistant bubble.
            do {
                _ = try await harness.client.mutateSchemaPath(.init(
                    action: .start,
                    conversationID: conversation.id,
                    requestID: "native-schema-turn-start-0001",
                    claimID: candidate.id,
                    userConfirmed: true
                ))
                XCTFail("Legacy start yeni bir sohbet-içi Şema yolu açmamalı.")
            } catch let error as DivanAPIError {
                XCTAssertEqual(error.statusCode, 409)
                XCTAssertEqual(error.errorCode, "schema_v4_action_required")
            }
            let chatOnlyReady = try await harness.client.schemaPath(
                conversationID: conversation.id
            )
            XCTAssertNil(chatOnlyReady.activePath)
            XCTAssertEqual(chatOnlyReady.nextCard?.kind, "candidate_prompt")
            XCTAssertEqual(
                chatOnlyReady.nextCard?.actions.map(\.action),
                ["accept_candidate_chat", "reject_candidate_chat"]
            )

            let historyConversation = try await harness.client.createConversation(
                masterID: "young", mode: "terapi", submode: nil
            )
            for _ in 0..<3 {
                _ = try seedCompletedChatTurn(
                    database: harness.databaseURL,
                    conversationID: historyConversation.id,
                    python: harness.python
                )
            }
            let historyBeforeConsent = try await harness.client.schemaPath(
                conversationID: historyConversation.id
            )
            let historyProvider = try XCTUnwrap(
                historyBeforeConsent.turnAnalysis?.provider
            )
            _ = try await harness.client.mutateSchemaTurnAnalysis(.init(
                action: .setMode,
                conversationID: historyConversation.id,
                requestID: "native-schema-history-mode-0001",
                enabled: true,
                providerID: historyProvider.id,
                modelID: historyProvider.model
            ))
            let historyQueued = try await harness.client.mutateSchemaTurnAnalysis(.init(
                action: .scanHistory,
                conversationID: historyConversation.id,
                requestID: "native-schema-history-scan-0001",
                consent: true,
                providerID: historyProvider.id,
                modelID: historyProvider.model
            ))
            XCTAssertTrue(historyQueued.queued == true)

            var history = try await harness.client.schemaPath(
                conversationID: historyConversation.id
            )
            for _ in 0..<150 where
                history.turnAnalysis?.analyzedTurns != 3
                    || history.turnAnalysis?.processing == true {
                try await Task.sleep(for: .milliseconds(100))
                history = try await harness.client.schemaPath(
                    conversationID: historyConversation.id
                )
            }
            let historyDetail = String(describing: history.turnAnalysis)
            XCTAssertEqual(history.turnAnalysis?.eligibleTurns, 3, historyDetail)
            XCTAssertEqual(history.turnAnalysis?.analyzedTurns, 3, historyDetail)
            XCTAssertEqual(history.turnAnalysis?.remainingTurns, 0, historyDetail)
            XCTAssertEqual(history.turnAnalysis?.failedTurns, 0, historyDetail)

            let syncedConversation = try await harness.client.createConversation(
                masterID: "young", mode: "terapi", submode: nil
            )
            try seedSyncedSchemaModePreference(
                database: harness.databaseURL,
                conversationID: syncedConversation.id,
                python: harness.python
            )
            let awaitingDevice = try await harness.client.schemaPath(
                conversationID: syncedConversation.id
            )
            XCTAssertFalse(try XCTUnwrap(awaitingDevice.schemaMode).enabled)
            XCTAssertTrue(try XCTUnwrap(awaitingDevice.schemaMode).preferenceEnabled)
            XCTAssertTrue(
                try XCTUnwrap(awaitingDevice.schemaMode).pendingDeviceConfirmation
            )
            XCTAssertEqual(
                awaitingDevice.schemaMode?.reason,
                "device_confirmation_required"
            )
            let syncedProvider = try XCTUnwrap(
                awaitingDevice.turnAnalysis?.provider
            )
            _ = try await harness.client.mutateSchemaTurnAnalysis(.init(
                action: .setMode,
                conversationID: syncedConversation.id,
                requestID: "native-schema-device-confirm-0001",
                enabled: true,
                providerID: syncedProvider.id,
                modelID: syncedProvider.model
            ))
            let deviceConfirmed = try await harness.client.schemaPath(
                conversationID: syncedConversation.id
            )
            XCTAssertTrue(try XCTUnwrap(deviceConfirmed.schemaMode).enabled)
            XCTAssertFalse(
                try XCTUnwrap(deviceConfirmed.schemaMode).pendingDeviceConfirmation
            )

            await harness.runtime.stop()
            provider.stop()
        } catch {
            await harness.runtime.stop()
            provider.stop()
            try? FileManager.default.removeItem(at: harness.root)
            throw error
        }
        try FileManager.default.removeItem(at: harness.root)
    }

    func testRealRuntimeSchemaV5UsesOnlyDurableProviderPromptAndTypedControls()
        async throws {
        let python = try XCTUnwrap(
            CoreRuntime.discoverPython(),
            "Entegrasyon testi için Python 3.9+ gerekli."
        )
        let provider = try startFakeSchemaTurnProvider(
            python: python,
            includeSecondCandidate: true
        )
        let harness: Harness
        do {
            harness = try await startHarness(extraEnvironment: [
                "DIVAN_LLM_PROVIDER": "lmstudio",
                "LMSTUDIO_BASE_URL": "http://127.0.0.1:\(provider.port)/v1",
                "LMSTUDIO_MODEL": "divan-schema-turn-test",
            ])
        } catch {
            provider.stop()
            throw error
        }
        var conversationID = 0

        func providerStreamCallCount() -> Int {
            guard let logURL = provider.logURL,
                  let text = try? String(contentsOf: logURL, encoding: .utf8)
            else { return 0 }
            return max(0, text.components(
                separatedBy: "POST stream=True"
            ).count - 1)
        }

        func candidateMutation(
            card: SchemaCardEnvelope,
            action expectedAction: SchemaChatCardAction,
            requestID: String
        ) throws -> SchemaCardMutation {
            XCTAssertEqual(card.kind, "candidate_prompt")
            XCTAssertEqual(card.presentation, "chat_only")
            XCTAssertTrue(card.fields.isEmpty)
            XCTAssertNil(card.pathId)
            XCTAssertNil(card.pathPublicId)
            XCTAssertNil(card.revision)
            let action = try XCTUnwrap(card.actions.first {
                $0.action == expectedAction.rawValue
            })
            let sourceUserID = try XCTUnwrap(card.source.userMessageId)
            let sourceUserPublicID = try XCTUnwrap(
                card.source.userMessagePublicId
            )
            let sourceAssistantID = try XCTUnwrap(
                card.source.assistantMessageId
            )
            let sourceAssistantPublicID = try XCTUnwrap(
                card.source.assistantMessagePublicId
            )
            XCTAssertEqual(
                action.payload["source_user_message_id"],
                .number(Double(sourceUserID))
            )
            XCTAssertEqual(
                action.payload["source_user_message_public_id"],
                .string(sourceUserPublicID)
            )
            XCTAssertEqual(
                action.payload["source_assistant_message_id"],
                .number(Double(sourceAssistantID))
            )
            XCTAssertEqual(
                action.payload["source_assistant_message_public_id"],
                .string(sourceAssistantPublicID)
            )
            let claim = try XCTUnwrap(action.payload["claim_id"])
            let candidate = try XCTUnwrap(
                action.payload["candidate_public_id"]
            )
            return SchemaCardMutation(
                action: expectedAction,
                conversationID: conversationID,
                requestID: requestID,
                pathID: nil,
                expectedRevision: nil,
                sourceUserMessageID: sourceUserID,
                sourceUserMessagePublicID: sourceUserPublicID,
                sourceAssistantMessageID: sourceAssistantID,
                sourceAssistantMessagePublicID: sourceAssistantPublicID,
                values: [
                    "claim_id": claim,
                    "candidate_public_id": candidate,
                ]
            )
        }

        func controlMutation(
            _ snapshot: SchemaPathSnapshot,
            action expectedAction: SchemaChatCardAction,
            requestID: String
        ) throws -> SchemaCardMutation {
            let path = try XCTUnwrap(snapshot.activePath)
            let pathPublicID = try XCTUnwrap(path.publicId)
            let card = try XCTUnwrap(snapshot.nextCard)
            XCTAssertEqual(card.presentation, "chat_only")
            XCTAssertTrue(card.fields.isEmpty)
            XCTAssertEqual(card.pathId, path.id)
            XCTAssertEqual(card.pathPublicId, pathPublicID)
            let action = try XCTUnwrap(card.actions.first {
                $0.action == expectedAction.rawValue
            })
            var values = action.payload
            let stepID: String?
            if case .string(let value)? = values.removeValue(
                forKey: "step_id"
            ) {
                stepID = value
            } else {
                stepID = nil
            }
            let techniqueRevision: Int?
            if case .number(let value)? = values.removeValue(
                forKey: "expected_technique_revision"
            ), value.isFinite, value.rounded() == value {
                techniqueRevision = Int(value)
            } else {
                techniqueRevision = nil
            }
            let techniqueAction = expectedAction == .groundChatTechnique
            return SchemaCardMutation(
                action: expectedAction,
                conversationID: conversationID,
                requestID: requestID,
                pathID: path.id,
                pathPublicID: pathPublicID,
                expectedRevision: try XCTUnwrap(card.revision),
                stepID: stepID,
                clientEventID: nil,
                expectedTechniqueRevision: techniqueAction
                    ? techniqueRevision : nil,
                values: values
            )
        }

        func submitBound(
            _ snapshot: SchemaPathSnapshot,
            text: String
        ) async throws -> (
            result: SchemaChatBindingResult,
            snapshot: SchemaPathSnapshot,
            userID: Int,
            assistantID: Int
        ) {
            XCTAssertEqual(snapshot.presentation, "chat_only")
            XCTAssertEqual(snapshot.interactionPolicy?.composerMode, .bound)
            XCTAssertEqual(
                snapshot.interactionPolicy?.composerSurface,
                "ordinary_chat"
            )
            XCTAssertTrue(snapshot.interactionPolicy?.composerAllowed == true)
            let path = try XCTUnwrap(snapshot.activePath)
            let pathPublicID = try XCTUnwrap(path.publicId)
            let card = try XCTUnwrap(snapshot.nextCard)
            XCTAssertEqual(card.kind, "chat_prompt")
            XCTAssertEqual(card.presentation, "chat_only")
            XCTAssertTrue(card.fields.isEmpty)
            XCTAssertTrue(Set(card.actions.map(\.action)).isSubset(of: [
                "pause", "stop", "ground_chat_technique",
            ]))
            let binding = try XCTUnwrap(card.chatBinding)
            XCTAssertEqual(binding.pathId, path.id)
            XCTAssertEqual(binding.pathPublicId, pathPublicID)
            XCTAssertEqual(binding.expectedRevision, snapshot.revision)
            XCTAssertEqual(
                binding.stepId,
                snapshot.interactionPolicy?.boundStepId
            )
            XCTAssertEqual(
                binding.sourceUserMessageId,
                card.source.userMessageId
            )
            XCTAssertEqual(
                binding.sourceUserMessagePublicId,
                card.source.userMessagePublicId
            )
            XCTAssertEqual(
                binding.sourceAssistantMessageId,
                card.source.assistantMessageId
            )
            XCTAssertEqual(
                binding.sourceAssistantMessagePublicId,
                card.source.assistantMessagePublicId
            )
            let encodedBinding = String(
                decoding: try JSONEncoder().encode(binding),
                as: UTF8.self
            )
            XCTAssertFalse(encodedBinding.contains("step_data"))
            XCTAssertFalse(encodedBinding.contains("stepData"))

            let stream = try await harness.client.sendMessage(
                conversationID: conversationID,
                text: text,
                schemaBinding: binding
            )
            var acceptedUserID: Int?
            var terminal: ChatEvent?
            for try await event in stream {
                if event.kind == .accepted {
                    acceptedUserID = event.userMessageID
                } else if event.kind == .done {
                    terminal = event
                }
            }
            let done = try XCTUnwrap(terminal)
            let result = try XCTUnwrap(done.schemaBindingResult)
            let refreshed = try await harness.client.schemaPath(
                conversationID: conversationID
            )
            XCTAssertEqual(done.nextCard?.id, refreshed.nextCard?.id)
            return (
                result,
                refreshed,
                try XCTUnwrap(acceptedUserID),
                try XCTUnwrap(done.assistantMessageID)
            )
        }

        do {
            let conversation = try await harness.client.createConversation(
                masterID: "young", mode: "terapi", submode: nil
            )
            conversationID = conversation.id
            let analyzedUserID = try seedCompletedChatTurn(
                database: harness.databaseURL,
                conversationID: conversation.id,
                python: harness.python
            )
            for _ in 0..<2 {
                _ = try seedCompletedChatTurn(
                    database: harness.databaseURL,
                    conversationID: conversation.id,
                    python: harness.python
                )
            }

            let pendingConsent = try await harness.client.schemaPath(
                conversationID: conversation.id
            )
            XCTAssertEqual(pendingConsent.protocol, "schema_path_chat_v5")
            XCTAssertEqual(pendingConsent.version, 5)
            XCTAssertEqual(pendingConsent.presentation, "chat_only")
            XCTAssertFalse(try XCTUnwrap(pendingConsent.schemaMode).enabled)
            XCTAssertTrue(
                try XCTUnwrap(pendingConsent.schemaMode)
                    .pendingDeviceConfirmation
            )
            XCTAssertEqual(pendingConsent.turnAnalysis?.eligibleTurns, 3)
            XCTAssertFalse(try XCTUnwrap(pendingConsent.clinicalSync).enabled)
            XCTAssertEqual(providerStreamCallCount(), 0)

            let providerPin = try XCTUnwrap(
                pendingConsent.turnAnalysis?.provider
            )
            _ = try await harness.client.mutateSchemaTurnAnalysis(.init(
                action: .setMode,
                conversationID: conversation.id,
                requestID: "native-schema-chat-consent-0001",
                enabled: true,
                providerID: providerPin.id,
                modelID: providerPin.model
            ))
            _ = try await harness.client.mutateSchemaTurnAnalysis(.init(
                action: .analyzeTurn,
                conversationID: conversation.id,
                requestID: "native-schema-chat-analyze-0001",
                userMessageID: analyzedUserID,
                consent: true,
                providerID: providerPin.id,
                modelID: providerPin.model
            ))
            var analyzed = try await harness.client.schemaPath(
                conversationID: conversation.id
            )
            for _ in 0..<100 where
                analyzed.turnAnalysis?.analyzedTurns != 1
                    || analyzed.turnAnalysis?.processing == true {
                try await Task.sleep(for: .milliseconds(100))
                analyzed = try await harness.client.schemaPath(
                    conversationID: conversation.id
                )
            }
            XCTAssertEqual(analyzed.turnAnalysis?.analyzedTurns, 1)
            XCTAssertGreaterThanOrEqual(analyzed.candidates.count, 2)
            let firstCandidate = try XCTUnwrap(analyzed.nextCard)
            XCTAssertEqual(firstCandidate.kind, "candidate_prompt")
            XCTAssertEqual(firstCandidate.body, "Bunu çalışmak ister misin?")
            XCTAssertEqual(
                firstCandidate.actions.map(\.action),
                ["accept_candidate_chat", "reject_candidate_chat"]
            )
            XCTAssertEqual(
                firstCandidate.actions.map(\.label),
                ["Evet", "Hayır"]
            )
            let rejected = try await harness.client.mutateSchemaCard(
                candidateMutation(
                    card: firstCandidate,
                    action: .rejectCandidateChat,
                    requestID: "native-schema-chat-candidate-no-0001"
                )
            )
            let secondCandidate = try XCTUnwrap(rejected.nextCard)
            XCTAssertEqual(secondCandidate.kind, "candidate_prompt")
            XCTAssertNotEqual(secondCandidate.id, firstCandidate.id)

            _ = try seedCompletedChatTurn(
                database: harness.databaseURL,
                conversationID: conversation.id,
                python: harness.python
            )
            let beforeAccept = try await harness.client.conversation(
                id: conversation.id
            )
            let latestAssistantID = try XCTUnwrap(
                beforeAccept.messages.last { $0.role == "assistant" }?.id
            )
            XCTAssertNotEqual(
                secondCandidate.source.assistantMessageId,
                latestAssistantID
            )
            let accepted = try await harness.client.mutateSchemaCard(
                candidateMutation(
                    card: secondCandidate,
                    action: .acceptCandidateChat,
                    requestID: "native-schema-chat-candidate-yes-0001"
                )
            )
            let afterAccept = try await harness.client.conversation(
                id: conversation.id
            )
            XCTAssertGreaterThanOrEqual(
                afterAccept.messageCount,
                beforeAccept.messageCount
            )
            XCTAssertEqual(accepted.step, "variable_explore")
            XCTAssertEqual(accepted.nextCard?.kind, "chat_state")
            XCTAssertEqual(accepted.nextCard?.body, "")
            XCTAssertTrue(accepted.nextCard?.fields.isEmpty == true)
            XCTAssertTrue(accepted.nextCard?.actions.isEmpty == true)

            var ready = accepted.snapshot
            for _ in 0..<100 {
                let delivery = ready.nextCard?.promptDelivery
                if delivery?.status == "completed" { break }
                if delivery?.status == "failed" {
                    let providerLog = provider.logURL.flatMap {
                        try? String(contentsOf: $0, encoding: .utf8)
                    } ?? ""
                    XCTFail(
                        "İlk v5 Kerem sorusu üretilemedi: "
                            + (delivery?.errorCode ?? "")
                            + "\nProvider log:\n" + String(providerLog.suffix(16_000))
                    )
                    break
                }
                try await Task.sleep(for: .milliseconds(100))
                ready = try await harness.client.schemaPath(
                    conversationID: conversation.id
                )
            }
            let readyCard = try XCTUnwrap(ready.nextCard)
            let readyDelivery = try XCTUnwrap(readyCard.promptDelivery)
            let readyBinding = try XCTUnwrap(readyCard.chatBinding)
            XCTAssertEqual(ready.protocol, "schema_path_chat_v5")
            XCTAssertEqual(ready.version, 5)
            XCTAssertEqual(ready.step, "variable_explore")
            XCTAssertEqual(readyCard.kind, "chat_state")
            XCTAssertEqual(readyCard.title, "")
            XCTAssertEqual(readyCard.contextLine ?? "", "")
            XCTAssertEqual(readyCard.body, "")
            XCTAssertTrue(readyCard.fields.isEmpty)
            XCTAssertTrue(readyCard.actions.isEmpty)
            XCTAssertEqual(readyDelivery.status, "completed")
            XCTAssertNil(readyDelivery.errorCode)
            XCTAssertNil(readyBinding.syncImportControl)
            XCTAssertEqual(
                readyBinding.promptRequestId,
                readyDelivery.requestId
            )
            XCTAssertEqual(
                readyBinding.promptAssistantMessageId,
                readyDelivery.promptAssistantMessageId
            )
            XCTAssertEqual(
                readyBinding.promptAssistantMessagePublicId,
                readyDelivery.promptAssistantMessagePublicId
            )
            XCTAssertEqual(
                readyBinding.sourceAssistantMessageId,
                readyDelivery.promptAssistantMessageId
            )
            XCTAssertEqual(
                readyBinding.sourceAssistantMessagePublicId,
                readyDelivery.promptAssistantMessagePublicId
            )
            XCTAssertEqual(ready.interactionPolicy?.composerMode, .bound)
            XCTAssertTrue(ready.interactionPolicy?.composerAllowed == true)
            XCTAssertEqual(ready.interactionPolicy?.inlineControlsOnly, false)
            XCTAssertEqual(providerStreamCallCount(), 1)

            let promptRequestID = try XCTUnwrap(readyDelivery.requestId)
            let promptStatus = try await harness.client.chatStatus(
                requestID: promptRequestID
            )
            XCTAssertEqual(promptStatus.status, "completed")
            XCTAssertEqual(
                promptStatus.schemaPromptProtocol,
                "schema_path_chat_v5"
            )
            XCTAssertEqual(promptStatus.schemaPromptIntent, "variable_scenario")

            let deliveredPage = try await harness.client.conversation(
                id: conversation.id,
                limit: 200
            )
            let promptID = try XCTUnwrap(
                readyDelivery.promptAssistantMessageId
            )
            let promptRow = try XCTUnwrap(
                deliveredPage.messages.first { $0.id == promptID }
            )
            XCTAssertEqual(promptRow.role, "assistant")
            XCTAssertEqual(promptRow.deliveryStatus, "completed")
            XCTAssertEqual(
                promptRow.publicID,
                readyDelivery.promptAssistantMessagePublicId
            )
            XCTAssertEqual(
                promptRow.content,
                "En son yaşadığın somut bir anı kısaca anlatır mısın?"
            )
            XCTAssertEqual(deliveredPage.messages.last?.id, promptID)
            let initialAssistantCount = deliveredPage.messages.filter {
                $0.role == "assistant"
            }.count

            let callsBeforePause = providerStreamCallCount()
            let pauseStream = try await harness.client.sendMessage(
                conversationID: conversation.id,
                text: "Dur",
                schemaBinding: readyBinding
            )
            var pauseDone: ChatEvent?
            var pauseDeltaCount = 0
            for try await event in pauseStream {
                if event.kind == .delta { pauseDeltaCount += 1 }
                if event.kind == .done { pauseDone = event }
            }
            let pausedEvent = try XCTUnwrap(pauseDone)
            XCTAssertEqual(pausedEvent.schemaBindingResult?.action, "pause")
            XCTAssertNil(pausedEvent.assistantMessageID)
            XCTAssertEqual(pauseDeltaCount, 0)
            XCTAssertEqual(providerStreamCallCount(), callsBeforePause)

            let paused = try await harness.client.schemaPath(
                conversationID: conversation.id
            )
            XCTAssertEqual(paused.activePath?.status, "paused")
            XCTAssertEqual(paused.nextCard?.kind, "chat_state")
            XCTAssertEqual(paused.nextCard?.status, "paused")
            XCTAssertEqual(paused.nextCard?.body, "")
            XCTAssertTrue(paused.nextCard?.actions.isEmpty == true)
            let pausedBinding = try XCTUnwrap(paused.nextCard?.chatBinding)
            XCTAssertNil(pausedBinding.syncImportControl)
            XCTAssertEqual(paused.interactionPolicy?.composerMode, .bound)

            let callsBeforeResume = providerStreamCallCount()
            let resumeStream = try await harness.client.sendMessage(
                conversationID: conversation.id,
                text: "Devam",
                schemaBinding: pausedBinding
            )
            var resumeDone: ChatEvent?
            for try await event in resumeStream where event.kind == .done {
                resumeDone = event
            }
            let resumedEvent = try XCTUnwrap(resumeDone)
            let resumedAssistantID = try XCTUnwrap(
                resumedEvent.assistantMessageID
            )
            XCTAssertEqual(providerStreamCallCount(), callsBeforeResume + 1)

            let resumed = try await harness.client.schemaPath(
                conversationID: conversation.id
            )
            XCTAssertEqual(resumed.activePath?.status, "active")
            XCTAssertEqual(resumed.nextCard?.kind, "chat_state")
            XCTAssertEqual(
                resumed.nextCard?.promptDelivery?.status,
                "completed"
            )
            XCTAssertEqual(
                resumed.nextCard?.promptDelivery?.promptAssistantMessageId,
                resumedAssistantID
            )
            XCTAssertEqual(resumed.nextCard?.body, "")
            XCTAssertTrue(resumed.nextCard?.actions.isEmpty == true)
            XCTAssertEqual(resumed.interactionPolicy?.composerMode, .bound)

            let finalPage = try await harness.client.conversation(
                id: conversation.id,
                limit: 200
            )
            XCTAssertEqual(
                finalPage.messages.filter { $0.role == "assistant" }.count,
                initialAssistantCount + 1,
                "Dur için sentetik asistan balonu oluşmamalı; Devam yalnız bir gerçek Kerem sorusu üretmeli."
            )
            XCTAssertEqual(finalPage.messages.last?.id, resumedAssistantID)
            XCTAssertEqual(
                finalPage.messages.last?.content,
                "En son yaşadığın somut bir anı kısaca anlatır mısın?"
            )

#if false // Historical flow-v4 end-to-end sequence; v5 no longer reaches it.

            var turn = try await submitBound(
                accepted.snapshot,
                text: "Oldukça ağır"
            )
            XCTAssertFalse(turn.result.applied)
            XCTAssertTrue(turn.result.followupRequired)
            XCTAssertEqual(turn.result.missing, ["burden"])
            XCTAssertEqual(turn.snapshot.step, "current_impact")

            let stageOne: [(String, String)] = [
                ("7", "current_impact"),
                ("Gün içinde ilişkiden geri çekilmeme yol açıyor.",
                 "current_impact"),
                ("Şimdi", "variable_check"),
                ("Karşımdakinin sakin kalması", "variable_check"),
                ("Aynı konu sakin biçimde konuşuluyor.",
                 "variable_check"),
                ("4", "variable_check"),
                ("Kısmen", "focus_confirm"),
                ("Evet", "method_confirm"),
            ]
            for (text, expectedStep) in stageOne {
                turn = try await submitBound(turn.snapshot, text: text)
                XCTAssertTrue(turn.result.applied, "\(text): \(turn.result)")
                XCTAssertEqual(turn.snapshot.step, expectedStep)
                XCTAssertEqual(
                    turn.snapshot.nextCard?.source.assistantMessageId,
                    turn.assistantID
                )
            }

            // Focus confirmation may propose a stable default, but it does
            // not select or start that method.  Backtracking is a local,
            // provider-free ordinary-chat command and appends a new cursor.
            let firstProposal = try XCTUnwrap(turn.snapshot.nextCard?.checkpoint)
            XCTAssertEqual(
                firstProposal.methodId,
                "young:method:imagery-rescripting"
            )
            XCTAssertNil(turn.snapshot.activePath?.methodId)
            XCTAssertNil(turn.snapshot.activePath?.techniqueRunId)
            XCTAssertEqual(
                turn.snapshot.nextCard?.body,
                "Bu odağı bugün şu yöntemle çalışalım mı: İmgeleme ile yeniden senaryolama? Evet ya da hayır diyebilirsin."
            )
            let callsBeforeBacktrack = providerStreamCallCount()
            turn = try await submitBound(turn.snapshot, text: "geri dön")
            XCTAssertTrue(turn.result.applied)
            XCTAssertTrue(turn.result.backtracked)
            XCTAssertEqual(turn.result.action, "backtrack_step")
            XCTAssertEqual(turn.snapshot.step, "focus_confirm")
            XCTAssertGreaterThan(
                try XCTUnwrap(turn.snapshot.nextCard?.checkpoint?.seq),
                firstProposal.seq
            )
            XCTAssertEqual(providerStreamCallCount(), callsBeforeBacktrack)

            turn = try await submitBound(turn.snapshot, text: "Evet")
            XCTAssertTrue(turn.result.applied)
            XCTAssertEqual(turn.snapshot.step, "method_confirm")
            XCTAssertNil(turn.snapshot.activePath?.methodId)
            XCTAssertNil(turn.snapshot.activePath?.techniqueRunId)

            // Declining a proposal opens method selection.  Ambiguity never
            // chooses a branch; an exact choice only proposes it, and a
            // separate Evet performs the single durable selection.
            turn = try await submitBound(turn.snapshot, text: "Hayır")
            XCTAssertTrue(turn.result.applied)
            XCTAssertEqual(turn.snapshot.step, "method_select")
            XCTAssertNil(turn.snapshot.nextCard?.checkpoint?.methodId)
            XCTAssertNil(turn.snapshot.activePath?.methodId)
            turn = try await submitBound(
                turn.snapshot,
                text: "İmgeleme ve sandalye arasında kaldım"
            )
            XCTAssertFalse(turn.result.applied)
            XCTAssertEqual(turn.result.errorCode, "schema_method_ambiguous")
            XCTAssertEqual(turn.snapshot.step, "method_select")
            XCTAssertNil(turn.snapshot.activePath?.methodId)
            turn = try await submitBound(
                turn.snapshot,
                text: "İmgeleme ile yeniden senaryolama"
            )
            XCTAssertTrue(turn.result.applied)
            XCTAssertEqual(turn.snapshot.step, "method_confirm")
            XCTAssertEqual(
                turn.snapshot.nextCard?.checkpoint?.methodId,
                "young:method:imagery-rescripting"
            )
            XCTAssertNil(turn.snapshot.activePath?.methodId)
            XCTAssertNil(turn.snapshot.activePath?.techniqueRunId)
            turn = try await submitBound(turn.snapshot, text: "Evet")
            XCTAssertTrue(turn.result.applied)
            XCTAssertEqual(turn.snapshot.step, "origin_or_unknown")
            XCTAssertEqual(
                turn.snapshot.activePath?.methodId,
                "young:method:imagery-rescripting"
            )
            XCTAssertEqual(
                turn.snapshot.nextCard?.checkpoint?.methodId,
                "young:method:imagery-rescripting"
            )
            XCTAssertNil(turn.snapshot.activePath?.techniqueRunId)

            let providerCallsBeforePause = providerStreamCallCount()
            turn = try await submitBound(turn.snapshot, text: "dur")
            XCTAssertTrue(turn.result.applied)
            XCTAssertEqual(turn.result.action, "pause")
            XCTAssertEqual(providerStreamCallCount(), providerCallsBeforePause)
            XCTAssertEqual(turn.snapshot.nextCard?.kind, "resume")
            XCTAssertEqual(turn.snapshot.interactionPolicy?.composerMode, .disabled)
            let resumed = try await harness.client.mutateSchemaCard(
                controlMutation(
                    turn.snapshot,
                    action: .resumePath,
                    requestID: "native-schema-chat-resume-0001"
                )
            )
            XCTAssertEqual(resumed.step, "origin_or_unknown")
            XCTAssertEqual(resumed.interactionPolicy?.composerMode, .bound)

            turn = try await submitBound(
                resumed.snapshot,
                text: "İlkokul yıllarında koridorda yalnız beklediğim bir an."
            )
            XCTAssertTrue(turn.result.applied)
            XCTAssertTrue(turn.result.followupRequired)
            turn = try await submitBound(
                turn.snapshot,
                text: "Yanımda sakin ve güvenilir bir yetişkin olmasına ihtiyacım vardı."
            )
            XCTAssertTrue(turn.result.applied)
            XCTAssertEqual(turn.snapshot.step, "imagery_precheck")

            turn = try await submitBound(turn.snapshot, text: "Emin değilim")
            XCTAssertFalse(turn.result.applied)
            XCTAssertEqual(
                turn.result.errorCode,
                "schema_chat_followup_required"
            )
            XCTAssertEqual(turn.result.missing, ["orientation_confirmed"])
            for answer in [
                "Evet", "Evet", "Evet", "Yoğunluk 3", "Hayır",
                "Durma işaretim dur olsun",
            ] {
                turn = try await submitBound(turn.snapshot, text: answer)
                XCTAssertTrue(turn.result.applied, "\(answer): \(turn.result)")
            }
            XCTAssertEqual(turn.snapshot.step, "imagery_work")
            XCTAssertNotNil(turn.snapshot.activePath?.activeTechniqueLink)
            XCTAssertTrue(turn.snapshot.nextCard?.fields.isEmpty == true)

            let callsBeforeGround = providerStreamCallCount()
            let grounded = try await harness.client.mutateSchemaCard(
                controlMutation(
                    turn.snapshot,
                    action: .groundChatTechnique,
                    requestID: "native-schema-chat-ground-0001"
                )
            )
            XCTAssertEqual(providerStreamCallCount(), callsBeforeGround)
            XCTAssertEqual(grounded.step, "grounding_review")
            XCTAssertEqual(grounded.interactionPolicy?.composerMode, .bound)
            turn = try await submitBound(
                grounded.snapshot,
                text: "Şimdi buradayım; bunun bir çalışma olduğunu biliyorum; yoğunluk 2. Çevremde masayı görüyorum."
            )
            XCTAssertTrue(turn.result.applied)
            XCTAssertEqual(turn.result.action, "complete_chat_technique")
            XCTAssertEqual(turn.snapshot.step, "healthy_adult_voice")

            turn = try await submitBound(
                turn.snapshot,
                text: "Bugün sınırımı sakin biçimde söyleyebilir ve kendimi koruyabilirim."
            )
            XCTAssertEqual(turn.result.action, "mark_healthy_adult")
            XCTAssertEqual(turn.snapshot.step, "age_ladder")
            let healthyUserID = turn.userID

            for (text, expectedStep) in [
                ("8 yaşındaydım", "age_ladder"),
                ("O zaman saklanırdım.", "age_ladder"),
                ("Bugün sakin biçimde konuşabilirim.", "age_ladder"),
                ("Artık seçim yapabildiğimi biliyorum.", "age_ladder"),
                ("Çevreyi yeniden resmetmeye devam edelim.",
                 "environment_rescript"),
            ] {
                turn = try await submitBound(turn.snapshot, text: text)
                XCTAssertTrue(turn.result.applied, "\(text): \(turn.result)")
                XCTAssertEqual(turn.snapshot.step, expectedStep)
            }
            for answer in [
                "O zaman çevre sessiz ve kapalıydı.",
                "Yanımda güvenilir biri ve açık bir kapı olsun isterdim.",
                "Sağlıklı Yetişkin yanım yalnız olmadığımı söylerdi.",
            ] {
                turn = try await submitBound(turn.snapshot, text: answer)
                XCTAssertTrue(turn.result.applied, "\(answer): \(turn.result)")
            }
            XCTAssertEqual(turn.snapshot.step, "present_transfer")

            var transferSourceIDs: [(Int, Int)] = []
            for answer in [
                "Bugün mesajıma geç yanıt gelmesi tetikledi.",
                "Sağlıklı Yetişkin yanım bekleyebileceğimi söyler.",
                "Bir kez sakin bir soru soracağım.",
                "Gerekirse bir arkadaşımdan destek alırım.",
                "Konuşmanın daha açık olacağını tahmin ediyorum.",
            ] {
                turn = try await submitBound(turn.snapshot, text: answer)
                XCTAssertTrue(turn.result.applied, "\(answer): \(turn.result)")
                transferSourceIDs.append((turn.userID, turn.assistantID))
            }
            XCTAssertEqual(turn.snapshot.step, "optional_practice")
            let transfer = try XCTUnwrap(turn.snapshot.presentTransfer)
            XCTAssertTrue(transfer.recorded)
            XCTAssertEqual(
                transfer.triggerSourceUserMessageId,
                transferSourceIDs.first?.0
            )
            XCTAssertEqual(
                transfer.triggerSourceAssistantMessageId,
                transferSourceIDs.first?.1
            )
            XCTAssertEqual(transfer.sourceUserMessageId, transferSourceIDs.last?.0)
            XCTAssertEqual(
                transfer.sourceAssistantMessageId,
                transferSourceIDs.last?.1
            )

            turn = try await submitBound(turn.snapshot, text: "Geç")
            XCTAssertEqual(turn.snapshot.step, "followup")
            turn = try await submitBound(
                turn.snapshot,
                text: "Kendi cümlemi kurmak yardımcı oldu; yoğunluk kısmı zordu."
            )
            XCTAssertTrue(turn.result.followupRequired)
            XCTAssertEqual(turn.snapshot.step, "followup")
            turn = try await submitBound(turn.snapshot, text: "Evet")
            XCTAssertTrue(turn.result.applied)
            XCTAssertTrue(turn.result.progressed)
            XCTAssertEqual(turn.result.step, "complete")
            XCTAssertEqual(turn.snapshot.step, "listen")
            XCTAssertNil(turn.snapshot.activePath)

            let page = try await harness.client.conversation(
                id: conversation.id,
                limit: 200
            )
            XCTAssertEqual(
                page.messages.first { $0.id == healthyUserID }?
                    .schemaBindingResult?.action,
                "mark_healthy_adult"
            )
            XCTAssertTrue(page.messages.flatMap(\.metaEvents).contains {
                $0.kind == "technique"
            })
#endif

            await harness.runtime.stop()
            provider.stop()
        } catch {
            await harness.runtime.stop()
            provider.stop()
            try? FileManager.default.removeItem(at: harness.root)
            throw error
        }
        try FileManager.default.removeItem(at: harness.root)
    }

    func testRealRuntimeFreudImageryConsentSelectionUndoAndAssetIntegrity() async throws {
        let harness = try await startHarness(extraEnvironment: [
            "DIVAN_LLM_PROVIDER": "lmstudio",
            "LMSTUDIO_BASE_URL": "http://127.0.0.1:65534/v1",
            "LMSTUDIO_MODEL": "auto",
        ])
        do {
            let conversation = try await harness.client.createConversation(
                masterID: "freud", mode: "terapi", submode: nil
            )
            try await harness.client.recordExperientialPrecheck(
                conversationID: conversation.id,
                intensity: 3,
                intensityLimit: 7
            )
            let catalog = try await harness.client.techniqueCatalog(
                therapistID: "freud",
                conversationID: conversation.id
            )
            let method = try XCTUnwrap(catalog.methods.first {
                $0.nodeID == "freud:method:free-association"
            })
            let proposed = try await harness.client.mutateTechniqueRun(.init(
                conversationID: conversation.id,
                action: .propose,
                methodKey: method.key,
                intensity: 3
            ))
            let consented = try await harness.client.mutateTechniqueRun(.init(
                conversationID: conversation.id,
                action: .consent,
                runID: proposed.run.id,
                consentConfirmed: true
            ))
            XCTAssertEqual(consented.run.status, "active")
            XCTAssertNotNil(consented.run.consentAt)

            let unopened = try await harness.client.freudImagery(
                conversationID: conversation.id
            )
            XCTAssertTrue(unopened.available)
            XCTAssertEqual(unopened.cards.count, 24)
            XCTAssertTrue(unopened.capabilities.consent)
            XCTAssertNil(unopened.session)
            let firstCard = try XCTUnwrap(unopened.cards.first)
            let cardData = try await harness.client.freudImageryCardData(
                card: firstCard
            )
            XCTAssertEqual(cardData.count, firstCard.bytes)

            let opened = try await harness.client.mutateFreudImagerySelection(.consent(
                conversationID: conversation.id,
                requestID: "native-real-freud-consent-0001",
                orientationConfirmed: true,
                frameConfirmed: true,
                realityConfirmed: true,
                stopSignal: "Şimdi dur"
            ))
            let revision = try XCTUnwrap(opened.imagery.session).revision
            XCTAssertTrue(opened.imagery.capabilities.select)

            let association = "Açık bir geçidi anımsattı."
            let selected = try await harness.client.mutateFreudImagerySelection(.select(
                conversationID: conversation.id,
                requestID: "native-real-freud-select-0001",
                revision: revision,
                cardID: firstCard.id,
                association: association
            ))
            XCTAssertEqual(selected.imagery.selection?.stepData.cardID, firstCard.id)
            XCTAssertEqual(selected.imagery.selection?.stepData.association, association)

            let selectedRevision = try XCTUnwrap(selected.imagery.session).revision
            let undone = try await harness.client.mutateFreudImagerySelection(.undo(
                conversationID: conversation.id,
                requestID: "native-real-freud-undo-0001",
                revision: selectedRevision
            ))
            XCTAssertNil(undone.imagery.selection)

            let undoRevision = try XCTUnwrap(undone.imagery.session).revision
            let stopped = try await harness.client.mutateFreudImagerySelection(.stop(
                conversationID: conversation.id,
                requestID: "native-real-freud-stop-0001",
                revision: undoRevision
            ))
            XCTAssertFalse(stopped.imagery.available)
            XCTAssertEqual(stopped.imagery.blockedReason, "session_stopped")
            XCTAssertEqual(stopped.imagery.cards, [])
            XCTAssertNil(stopped.imagery.session)
            XCTAssertNil(stopped.imagery.selection)

            await harness.runtime.stop()
        } catch {
            await harness.runtime.stop()
            try? FileManager.default.removeItem(at: harness.root)
            throw error
        }
        try FileManager.default.removeItem(at: harness.root)
    }

    func testRealRuntimeRepairsLegacyConsentedChairWithoutWorkspace() async throws {
        let harness = try await startHarness(extraEnvironment: [
            "DIVAN_LLM_PROVIDER": "lmstudio",
            "LMSTUDIO_BASE_URL": "http://127.0.0.1:65534/v1",
            "LMSTUDIO_MODEL": "auto",
        ])
        let controller = await MainActor.run {
            RuntimeController(runtime: harness.runtime)
        }
        let loader = await MainActor.run {
            DivanRuntimeLoader(controller: controller)
        }
        let adapter = CoreAdvancedWorkspaceDataSource(loader: loader)
        do {
            let (client, _) = try await loader.service()
            let created = try await client.createConversation(
                masterID: "perls", mode: "terapi", submode: nil
            )
            let context = AdvancedWorkspaceContext(
                conversationID: created.id,
                masterID: "perls",
                masterName: "Fritz Perls",
                allowsClinicalWork: true
            )
            let snapshot = try await adapter.advancedWorkspaceSnapshot(
                context: context
            )
            let catalog = try await client.techniqueCatalog(
                therapistID: "perls",
                conversationID: created.id
            )
            let method = try XCTUnwrap(catalog.methods.first(where: \.isChairWork))
            let proposed = try await client.mutateTechniqueRun(
                TechniqueRunMutation(
                    conversationID: created.id,
                    action: .propose,
                    methodKey: method.key,
                    intensity: 3
                )
            )
            if method.riskLevel == "enhanced" {
                try await client.recordExperientialPrecheck(
                    conversationID: created.id,
                    intensity: 3,
                    intensityLimit: min(catalog.intensityLimit, 7)
                )
            }
            let consented = try await client.mutateTechniqueRun(
                TechniqueRunMutation(
                    conversationID: created.id,
                    action: .consent,
                    runID: proposed.run.id,
                    consentConfirmed: true
                )
            )
            XCTAssertEqual(consented.run.status, "active")
            XCTAssertNotNil(consented.chairWork)

            // Reproduce a legacy install that persisted technique consent but
            // did not materialize the structured chair side-workspace.
            try removeChairWorkspace(
                database: harness.databaseURL,
                techniqueRunID: proposed.run.id,
                python: harness.python
            )
            let missingCollection = try await client.chairWork(
                conversationID: created.id,
                chairRunID: nil,
                includeFullHistory: false
            )
            XCTAssertNil(missingCollection.chairWork)

            var participantTitles = snapshot.chairConfiguration
                .defaultParticipantTitles
            while participantTitles.count < snapshot.chairConfiguration
                .minimumParticipants {
                participantTitles.append("Sandalye \(participantTitles.count + 1)")
            }
            let repaired = try await adapter.startChairWork(
                request: WorkspaceChairStartRequest(
                    conversationID: created.id,
                    goalText: "İki kutbu ayrı ayrı duymak",
                    stopSignal: "burada dur",
                    participantTitles: participantTitles,
                    startingParticipantIndex: 0,
                    intensity: 3,
                    orientationConfirmed: true,
                    frameConfirmed: true,
                    realityConfirmed: true,
                    sleepActivationClear: true,
                    supportAvailable: true
                )
            )
            XCTAssertEqual(repaired.phase, .active)
            let runs = try await client.techniqueRuns(conversationID: created.id)
            XCTAssertEqual(runs.runs.filter(\.isOpen).map(\.id), [proposed.run.id])
            let restoredCollection = try await client.chairWork(
                conversationID: created.id,
                chairRunID: nil,
                includeFullHistory: false
            )
            let restored = try XCTUnwrap(restoredCollection.chairWork)
            XCTAssertEqual(restored.techniqueRunID, proposed.run.id)
            _ = try await adapter.stopChairWork(sessionID: repaired.id)
            await loader.stop()
        } catch {
            await loader.stop()
            try? FileManager.default.removeItem(at: harness.root)
            throw error
        }
        try FileManager.default.removeItem(at: harness.root)
    }

    func testRealRuntimeUnsupportedMasterExplainsWhyStartIsUnavailable() async throws {
        let harness = try await startHarness(extraEnvironment: [
            "DIVAN_LLM_PROVIDER": "lmstudio",
            "LMSTUDIO_BASE_URL": "http://127.0.0.1:65534/v1",
            "LMSTUDIO_MODEL": "auto",
        ])
        let controller = await MainActor.run {
            RuntimeController(runtime: harness.runtime)
        }
        let loader = await MainActor.run {
            DivanRuntimeLoader(controller: controller)
        }
        let adapter = CoreAdvancedWorkspaceDataSource(loader: loader)
        do {
            let (client, _) = try await loader.service()
            let created = try await client.createConversation(
                masterID: "kohut", mode: "terapi", submode: nil
            )
            let context = AdvancedWorkspaceContext(
                conversationID: created.id,
                masterID: "kohut",
                masterName: "Heinz Kohut",
                allowsClinicalWork: true
            )
            let model = await MainActor.run {
                AdvancedWorkspaceViewModel(
                    dataSource: adapter,
                    context: context,
                    initialModule: .chairWork
                )
            }
            await model.loadIfNeeded()
            let availability = await MainActor.run {
                (
                    model.chairAvailable,
                    model.imageryAvailable,
                    model.unavailableReason(for: .chairWork),
                    model.unavailableReason(for: .reparenting)
                )
            }
            XCTAssertFalse(availability.0)
            XCTAssertFalse(availability.1)
            XCTAssertTrue(availability.2?.contains("sandalye") == true)
            XCTAssertTrue(availability.3?.contains("imgeleme") == true)

            // A stale/programmatic CTA cannot silently mutate an unrelated
            // school; it yields a visible explanation and no technique row.
            await model.startChairWork()
            let failure = await MainActor.run { model.failure }
            XCTAssertEqual(failure?.title, "Bu çalışma bu ustada bulunmuyor")
            XCTAssertTrue(failure?.message.contains("sandalye") == true)
            let runs = try await client.techniqueRuns(conversationID: created.id)
            XCTAssertTrue(runs.runs.isEmpty)
            await loader.stop()
        } catch {
            await loader.stop()
            try? FileManager.default.removeItem(at: harness.root)
            throw error
        }
        try FileManager.default.removeItem(at: harness.root)
    }

    func testRealRuntimeLivingMapGenerateReviewAndWiFiHostLifecycle() async throws {
        let harness = try await startHarness(extraEnvironment: [
            "DIVAN_LLM_PROVIDER": "lmstudio",
            "LMSTUDIO_BASE_URL": "http://127.0.0.1:65534/v1",
            "LMSTUDIO_MODEL": "auto",
        ])
        let controller = await MainActor.run {
            RuntimeController(runtime: harness.runtime)
        }
        let loader = await MainActor.run {
            DivanRuntimeLoader(controller: controller)
        }
        let adapter = CoreAdvancedWorkspaceDataSource(loader: loader)
        do {
            let (client, _) = try await loader.service()
            let created = try await client.createConversation(
                masterID: "young", mode: "terapi", submode: nil
            )
            let context = AdvancedWorkspaceContext(
                conversationID: created.id,
                masterID: "young",
                masterName: "Jeffrey Young",
                allowsClinicalWork: true
            )
            _ = try await adapter.advancedWorkspaceSnapshot(context: context)

            let accepted = try await client.generateLivingMap(
                conversationID: created.id
            )
            XCTAssertTrue(accepted.processing)
            XCTAssertGreaterThan(accepted.jobID, 0)
            XCTAssertEqual(accepted.conversationID, created.id)

            let claimReference = try seedLivingMapCandidate(
                database: harness.databaseURL,
                conversationID: created.id,
                therapistID: "young",
                python: harness.python
            )
            let cards = try await adapter.livingMap(
                conversationID: created.id
            )
            let candidate = try XCTUnwrap(
                cards.first { $0.id == claimReference }
            )
            XCTAssertFalse(candidate.evidence.isEmpty)
            let reviewed = try await adapter.reviewLivingMap(
                cardID: candidate.id,
                action: .confirm,
                note: "Bu kayıt bana uyuyor."
            )
            XCTAssertEqual(reviewed.reviewStatus, "confirmed")

            let initialSync = try await adapter.wifiSyncStatus()
            XCTAssertEqual(initialSync.phase, .idle)
            XCTAssertTrue(initialSync.secretsExcluded)
            let offer = try await adapter.createWiFiSyncOffer()
            XCTAssertEqual(offer.phase, .waitingForScan)
            XCTAssertFalse((offer.pairingCode ?? "").isEmpty)
            XCTAssertNotNil(offer.qrMatrix)
            let running = try await client.deviceSyncStatus()
            XCTAssertTrue(running.hostRunning)
            XCTAssertTrue(running.secretsExcluded)
            let cancelled = try await adapter.cancelWiFiSync()
            XCTAssertEqual(cancelled.phase, .cancelled)
            let finalSync = try await client.deviceSyncStatus()
            XCTAssertFalse(finalSync.hostRunning)
            await loader.stop()
        } catch {
            await loader.stop()
            try? FileManager.default.removeItem(at: harness.root)
            throw error
        }
        try FileManager.default.removeItem(at: harness.root)
    }

    func testRealRuntimeChatShowsFirstDeltaBeforeProviderCompletes() async throws {
        let python = try XCTUnwrap(
            CoreRuntime.discoverPython(),
            "Entegrasyon testi için Python 3.9+ gerekli."
        )
        let provider = try startFakeStreamingProvider(python: python)
        let harness: Harness
        do {
            harness = try await startHarness(extraEnvironment: [
                "DIVAN_LLM_PROVIDER": "lmstudio",
                "LMSTUDIO_BASE_URL": "http://127.0.0.1:\(provider.port)/v1",
                "LMSTUDIO_MODEL": "divan-stream-test",
            ])
        } catch {
            provider.stop()
            throw error
        }
        let controller = await MainActor.run {
            RuntimeController(runtime: harness.runtime)
        }
        let loader = await MainActor.run {
            DivanRuntimeLoader(controller: controller)
        }
        let dataSource = CoreDivanUIDataSource(loader: loader)
        do {
            let (client, _) = try await loader.service()
            let conversation = try await client.createConversation(
                masterID: "freud", mode: "terapi", submode: nil
            )
            let stream = await dataSource.sendMessage(
                conversationID: conversation.id,
                text: "İlk metni bekletmeden göster."
            )
            var acceptedAt: Date?
            var firstDeltaAt: Date?
            var completedAt: Date?
            var acceptedUserMessageID: Int?
            var completedAssistantMessageID: Int?
            var content = ""
            var observedEvents: [String] = []
            for try await update in stream {
                switch update {
                case .accepted(_, let userMessageID):
                    observedEvents.append("accepted")
                    if acceptedAt == nil { acceptedAt = Date() }
                    acceptedUserMessageID = userMessageID
                case .assistantDelta(let text):
                    observedEvents.append("delta:\(text)")
                    if firstDeltaAt == nil { firstDeltaAt = Date() }
                    content += text
                case .assistantReplaced(let text):
                    observedEvents.append("replace:\(text)")
                    if firstDeltaAt == nil { firstDeltaAt = Date() }
                    content = text
                case .assistantCompleted(
                    let messageID, _, _, _, _, _, _, _, _
                ):
                    observedEvents.append("completed")
                    completedAt = Date()
                    completedAssistantMessageID = messageID
                case .failed(let message, _):
                    throw NSError(
                        domain: "DivanNativeIntegration",
                        code: 4,
                        userInfo: [NSLocalizedDescriptionKey:
                            "Gerçek stream tamamlanamadı: \(message)"]
                    )
                case .assistantStarted:
                    observedEvents.append("started")
                case .status(let text):
                    observedEvents.append("status:\(text)")
                    break
                }
            }
            let eventTrace = observedEvents.joined(separator: " | ")
            let accepted = try XCTUnwrap(acceptedAt, eventTrace)
            let firstDelta = try XCTUnwrap(firstDeltaAt, eventTrace)
            let completed = try XCTUnwrap(completedAt, eventTrace)
            let firstVisibleLatency = firstDelta.timeIntervalSince(accepted)
            let visibleStreamingSpan = completed.timeIntervalSince(firstDelta)
            print(String(
                format: "Divan stream timing: first-visible %.3fs, visible-before-done %.3fs",
                firstVisibleLatency,
                visibleStreamingSpan
            ))
            XCTAssertEqual(content, "Bu gerçek yanıt.")
            XCTAssertGreaterThan(acceptedUserMessageID ?? 0, 0)
            XCTAssertGreaterThan(completedAssistantMessageID ?? 0, 0)
            XCTAssertLessThan(
                firstVisibleLatency,
                2.0,
                "İlk güvenli metin provider tamamlanmasını beklememeli."
            )
            XCTAssertGreaterThan(
                visibleStreamingSpan,
                0.35,
                "İlk delta terminal olaydan önce görünür olmalı."
            )
            await loader.stop()
            provider.stop()
        } catch {
            await loader.stop()
            provider.stop()
            try? FileManager.default.removeItem(at: harness.root)
            throw error
        }
        try FileManager.default.removeItem(at: harness.root)
    }

    private func startFakeStreamingProvider(
        python: URL
    ) throws -> FakeStreamingProvider {
        let script = #"""
import json, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args):
        pass

    def _json(self, value):
        body = json.dumps(value).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()

    def do_GET(self):
        self._json({"data": [{"id": "divan-stream-test"}]})

    def do_POST(self):
        size = int(self.headers.get("Content-Length") or 0)
        payload = json.loads(self.rfile.read(size) or b"{}")
        if not payload.get("stream"):
            self._json({
                "choices": [{
                    "message": {"content": "Bu gerçek yanıt."},
                    "finish_reason": "stop",
                }]
            })
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        chunks = [
            (0.0, {"choices": [{
                "delta": {"content": "Bu"},
                "finish_reason": None,
            }]}),
            (0.30, {"choices": [{
                "delta": {"content": " gerçek"},
                "finish_reason": None,
            }]}),
            (0.30, {"choices": [{
                "delta": {"content": " yanıt."},
                "finish_reason": None,
            }]}),
            (0.10, {"choices": [{
                "delta": {},
                "finish_reason": "stop",
            }]}),
        ]
        for delay, chunk in chunks:
            if delay:
                time.sleep(delay)
            line = "data: " + json.dumps(chunk, ensure_ascii=False) + "\n\n"
            self.wfile.write(line.encode("utf-8"))
            self.wfile.flush()
        self.close_connection = True

server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
print(server.server_address[1], flush=True)
server.serve_forever()
"""#
        let process = Process()
        let output = Pipe()
        let errors = Pipe()
        process.executableURL = python
        process.arguments = ["-u", "-c", script]
        process.standardInput = FileHandle.nullDevice
        process.standardOutput = output
        process.standardError = errors
        try process.run()

        var line = Data()
        while line.count < 32 {
            let byte = output.fileHandleForReading.readData(ofLength: 1)
            guard !byte.isEmpty else {
                let detail = errors.fileHandleForReading.readDataToEndOfFile()
                throw NSError(
                    domain: "DivanNativeIntegration",
                    code: 2,
                    userInfo: [NSLocalizedDescriptionKey:
                        "Sahte sağlayıcı başlatılamadı: "
                        + String(decoding: detail, as: UTF8.self)]
                )
            }
            if byte == Data([0x0a]) { break }
            line.append(byte)
        }
        guard let port = Int(
            String(decoding: line, as: UTF8.self)
                .trimmingCharacters(in: .whitespacesAndNewlines)
        ), port > 0 else {
            process.terminate()
            process.waitUntilExit()
            throw NSError(
                domain: "DivanNativeIntegration",
                code: 3,
                userInfo: [NSLocalizedDescriptionKey:
                    "Sahte sağlayıcı geçerli bir port bildirmedi."]
            )
        }
        return FakeStreamingProvider(
            process: process,
            output: output,
            errors: errors,
            port: port
        )
    }

    private func startFakeSchemaTurnProvider(
        python: URL,
        includeSecondCandidate: Bool = false
    ) throws -> FakeStreamingProvider {
        let logURL = URL(fileURLWithPath: NSTemporaryDirectory())
            .appendingPathComponent("divan-schema-provider-\(UUID().uuidString).log")
        let script = #"""
import json, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOG = sys.argv[1]
INCLUDE_SECOND_CANDIDATE = len(sys.argv) > 2 and sys.argv[2] == "two"

def log(line):
    with open(LOG, "a", encoding="utf-8") as handle:
        handle.write(line + "\n")

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args):
        pass

    def _json(self, value):
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()
        self.close_connection = True

    def do_GET(self):
        self._json({"data": [{"id": "divan-schema-turn-test"}]})

    def do_POST(self):
        size = int(self.headers.get("Content-Length") or 0)
        payload = json.loads(self.rfile.read(size) or b"{}")
        log("POST stream={} messages={}".format(
            bool(payload.get("stream")), len(payload.get("messages") or [])))
        log(json.dumps(payload, ensure_ascii=False)[:12000])
        if payload.get("stream"):
            all_content = "\n".join(
                str(message.get("content") or "")
                for message in payload.get("messages") or [])
            is_schema_v5_prompt = (
                "intent_id tam olarak" in all_content
                or "Şema v5 mesaj sözleşmesi" in all_content)
            log("schema_v5_prompt={}".format(is_schema_v5_prompt))
            has_inline_prompt = any(
                "[[MOD]]" in str(message.get("content") or "")
                for message in payload.get("messages") or [])
            log("inline_prompt={}".format(has_inline_prompt))
            inline_marker = (
                "\n[[MOD]] vulnerable_child | küçük ve korkmuş bir yan"
                if has_inline_prompt else "")
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()
            if is_schema_v5_prompt:
                visible = json.dumps({
                    "intent_id": "variable_scenario",
                    "assistant_text": (
                        "En son yaşadığın somut bir anı kısaca anlatır mısın?")
                }, ensure_ascii=False)
                split = max(1, len(visible) // 2)
                chunks = [
                    {"choices": [{"delta": {"content": visible[:split]},
                                  "finish_reason": None}]},
                    {"choices": [{"delta": {"content": visible[split:]},
                                  "finish_reason": None}]},
                    {"choices": [{"delta": {}, "finish_reason": "stop"}]},
                ]
            else:
                # Keep the inline marker intact in one provider delta so the
                # production streaming sanitizer exercises its real boundary.
                chunks = [
                    {"choices": [{"delta": {"content": "Bunu birlikte "},
                                  "finish_reason": None}]},
                    {"choices": [{"delta": {"content":
                        "inceleyebiliriz." + inline_marker},
                                  "finish_reason": None}]},
                    {"choices": [{"delta": {}, "finish_reason": "stop"}]},
                ]
            for chunk in chunks:
                line = "data: " + json.dumps(chunk, ensure_ascii=False) + "\n\n"
                self.wfile.write(line.encode("utf-8"))
                self.wfile.flush()
            self.close_connection = True
            return

        source_id = None
        schema_mode = False
        for message in payload.get("messages") or []:
            content = message.get("content") or ""
            if message.get("role") != "user" or "USER_MESSAGES" not in content:
                continue
            try:
                context = json.loads(content.split("\n\n", 1)[-1])
                source_id = context["USER_MESSAGES"][0]["id"]
                schema_mode = "SCHEMA_CATALOG" in context
                log("analysis source={} schema={}".format(
                    source_id, schema_mode))
            except (KeyError, IndexError, TypeError, ValueError):
                source_id = None
            break
        if source_id is None:
            content = "Hazır."
        elif not schema_mode:
            content = json.dumps({"insights": []}, ensure_ascii=False)
        else:
            candidates = [{
                    "existing_claim_id": None,
                    "schema_id": "schema_abandonment",
                    "mode_id": "vulnerable_child",
                    "statement": "Terk edilme kaygısı ve geri çekilme arasında erken bir çalışma hipotezi olabilir.",
                    "trigger": "Eleştiri duymak",
                    "experience": "Terk edilme korkusu",
                    "response": "Geri çekilmek",
                    "short_term_effect": "Teması azaltmak",
                    "long_term_effect": "Yakınlık ihtiyacını karşılamayı zorlaştırmak",
                    "need": "Güvenli bağ ve anlaşılma",
                    "context": "Eleştiri algılanan anlar",
                    "counterexample": "",
                    "supporting_message_ids": [source_id],
                    "counterexample_message_ids": [],
                }]
            if INCLUDE_SECOND_CANDIDATE:
                candidates.append({
                    "existing_claim_id": None,
                    "schema_id": "schema_defectiveness",
                    "mode_id": "punitive_parent",
                    "statement": "Eleştiri karşısında kusurluluk duygusu ve sert iç ses arasında ikinci bir çalışma hipotezi olabilir.",
                    "trigger": "Eleştiri duymak",
                    "experience": "Kusurlu hissetmek",
                    "response": "Kendini sertçe eleştirmek",
                    "short_term_effect": "Hata yapmaktan kaçınmak",
                    "long_term_effect": "Kendine şefkatli yaklaşmayı zorlaştırmak",
                    "need": "Kabul ve adil bir iç sınır",
                    "context": "Eleştiri algılanan anlar",
                    "counterexample": "",
                    "supporting_message_ids": [source_id],
                    "counterexample_message_ids": [],
                })
            content = json.dumps({
                "insights": [],
                "schema_candidates": candidates,
            }, ensure_ascii=False)
        self._json({
            "choices": [{
                "message": {"content": content},
                "finish_reason": "stop",
            }]
        })

server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
print(server.server_address[1], flush=True)
server.serve_forever()
"""#
        let process = Process()
        let output = Pipe()
        let errors = Pipe()
        process.executableURL = python
        process.arguments = [
            "-u", "-c", script, logURL.path,
            includeSecondCandidate ? "two" : "one",
        ]
        process.standardInput = FileHandle.nullDevice
        process.standardOutput = output
        process.standardError = errors
        try process.run()

        var line = Data()
        while line.count < 32 {
            let byte = output.fileHandleForReading.readData(ofLength: 1)
            guard !byte.isEmpty else {
                let detail = errors.fileHandleForReading.readDataToEndOfFile()
                throw NSError(
                    domain: "DivanNativeIntegration",
                    code: 5,
                    userInfo: [NSLocalizedDescriptionKey:
                        "Sahte şema sağlayıcısı başlatılamadı: "
                        + String(decoding: detail, as: UTF8.self)]
                )
            }
            if byte == Data([0x0a]) { break }
            line.append(byte)
        }
        guard let port = Int(
            String(decoding: line, as: UTF8.self)
                .trimmingCharacters(in: .whitespacesAndNewlines)
        ), port > 0 else {
            process.terminate()
            process.waitUntilExit()
            throw NSError(
                domain: "DivanNativeIntegration",
                code: 6,
                userInfo: [NSLocalizedDescriptionKey:
                    "Sahte şema sağlayıcısı geçerli bir port bildirmedi."]
            )
        }
        return FakeStreamingProvider(
            process: process,
            output: output,
            errors: errors,
            port: port,
            logURL: logURL
        )
    }

    private func startHarness(
        extraEnvironment: [String: String]
    ) async throws -> Harness {
        let root = URL(fileURLWithPath: NSTemporaryDirectory(), isDirectory: true)
            .appendingPathComponent("divan-native-integration-" + UUID().uuidString,
                                    isDirectory: true)
        let dataDirectory = root.appendingPathComponent("data", isDirectory: true)
        try FileManager.default.createDirectory(
            at: root,
            withIntermediateDirectories: true
        )
        let python = try XCTUnwrap(
            CoreRuntime.discoverPython(),
            "Entegrasyon testi için Python 3.9+ gerekli."
        )
        let runtime = CoreRuntime(configuration: RuntimeConfiguration(
            coreDirectory: try sourceCoreDirectory(),
            dataDirectory: dataDirectory,
            pythonExecutable: python,
            startupTimeout: 30,
            extraEnvironment: extraEnvironment
        ))
        do {
            let endpoint = try await runtime.start()
            let client = try APIClient(endpoint: endpoint)
            return Harness(
                root: root,
                dataDirectory: dataDirectory,
                databaseURL: dataDirectory.appendingPathComponent("freud.db"),
                python: python,
                runtime: runtime,
                endpoint: endpoint,
                client: client
            )
        } catch {
            let logURL = dataDirectory.appendingPathComponent("runtime-native.log")
            let log = (try? String(contentsOf: logURL, encoding: .utf8)) ?? ""
            await runtime.stop()
            try? FileManager.default.removeItem(at: root)
            if !log.isEmpty {
                throw NSError(
                    domain: "DivanNativeIntegration",
                    code: 1,
                    userInfo: [
                        NSUnderlyingErrorKey: error,
                        NSLocalizedDescriptionKey:
                            "\(error.localizedDescription)\nRuntime log:\n\(log.suffix(8_000))",
                    ]
                )
            }
            throw error
        }
    }

    private func sourceCoreDirectory() throws -> URL {
        if let packaged = ProcessInfo.processInfo.environment[
            "DIVAN_TEST_CORE_ROOT"
        ]?.trimmingCharacters(in: .whitespacesAndNewlines),
           !packaged.isEmpty {
            let core = URL(fileURLWithPath: packaged, isDirectory: true)
                .standardizedFileURL
            guard FileManager.default.fileExists(
                atPath: core.appendingPathComponent("server.py").path
            ) else {
                throw XCTSkip("Paketlenmiş test çekirdeği bulunamadı: \(core.path)")
            }
            return core
        }
        var project = URL(fileURLWithPath: #filePath)
        for _ in 0..<4 { project.deleteLastPathComponent() }
        let core = project.deletingLastPathComponent()
            .appendingPathComponent("freud-dev", isDirectory: true)
            .standardizedFileURL
        guard FileManager.default.fileExists(
            atPath: core.appendingPathComponent("server.py").path) else {
            throw XCTSkip("Ortak freud-dev çekirdeği bulunamadı: \(core.path)")
        }
        return core
    }

    private func seedMessages(
        database: URL,
        conversationID: Int,
        count: Int,
        marker: String,
        python: URL
    ) throws {
        let script = #"""
import sqlite3, sys
path, conv, count, marker = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
db = sqlite3.connect(path, timeout=10)
db.executemany(
    "INSERT INTO messages(conv,role,content,created) VALUES(?,?,?,?)",
    [(conv, "user" if i % 2 == 0 else "assistant", f"{marker}-{i:03d}",
      f"2026-08-11 10:{i % 60:02d}:{i % 60:02d}") for i in range(count)]
)
db.commit()
db.close()
"""#
        _ = try run(
            python,
            arguments: [
                "-c", script, database.path, String(conversationID),
                String(count), marker,
            ]
        )
    }

    private func seedCompletedChatTurn(
        database: URL,
        conversationID: Int,
        python: URL
    ) throws -> Int {
        let requestID = "native-seeded-turn-" + UUID().uuidString
            .replacingOccurrences(of: "-", with: "")
            .lowercased()
        let script = #"""
import sqlite3, sys
path, conv, request_id = sys.argv[1], int(sys.argv[2]), sys.argv[3]
db = sqlite3.connect(path, timeout=10)
db.execute("PRAGMA foreign_keys=ON")
stamp = "2026-08-17 12:00:00"
user = db.execute(
    "INSERT INTO messages(conv,role,content,created,delivery_status) "
    "VALUES(?,'user',?,?,'completed')",
    (conv, "Eleştiri duyduğumda terk edileceğimden korkup geri çekiliyorum.", stamp)
).lastrowid
assistant = db.execute(
    "INSERT INTO messages(conv,role,content,created,reply_to,delivery_status) "
    "VALUES(?,'assistant',?,?,?,'completed')",
    (conv, "Bu korkunun neyi korumaya çalıştığını birlikte inceleyebiliriz.",
     stamp, user)
).lastrowid
job = db.execute(
    "INSERT INTO jobs(kind,conv,status,stage,progress,provider,model,created,"
    "started,finished,updated) VALUES('chat_response',?,'completed',"
    "'yanıt tamamlandı',100,'lmstudio','divan-schema-turn-test',?,?,?,?)",
    (conv, stamp, stamp, stamp, stamp)
).lastrowid
db.execute(
    "INSERT INTO chat_requests(request_id,job,conv,user_message,"
    "assistant_message,status,provider,model,partial_content,"
    "best_partial_content,created,started,finished,updated) "
    "VALUES(?,?,?,?,?,'completed','lmstudio','divan-schema-turn-test',"
    "'','',?,?,?,?)",
    (request_id, job, conv, user, assistant, stamp, stamp, stamp, stamp)
)
db.commit()
db.close()
print(user)
"""#
        let output = try run(
            python,
            arguments: [
                "-c", script, database.path, String(conversationID), requestID,
            ]
        ).trimmingCharacters(in: .whitespacesAndNewlines)
        return try XCTUnwrap(Int(output))
    }

    private func seedSyncedSchemaModePreference(
        database: URL,
        conversationID: Int,
        python: URL
    ) throws {
        let script = #"""
import sqlite3, sys
db = sqlite3.connect(sys.argv[1], timeout=10)
conv = int(sys.argv[2])
db.execute(
    "INSERT OR IGNORE INTO session_meta(conv,updated) VALUES(?,?)",
    (conv, "2026-08-17 12:00:00")
)
db.execute(
    "UPDATE session_meta SET schema_mode_enabled=1,"
    "schema_mode_initialized=0,schema_mode_enrolled_after_message_id=0,"
    "schema_mode_provider='',schema_mode_model='',updated=? WHERE conv=?",
    ("2026-08-17 12:00:00", conv)
)
db.commit()
db.close()
"""#
        _ = try run(
            python,
            arguments: ["-c", script, database.path, String(conversationID)]
        )
    }

    private func seedLivingMapCandidate(
        database: URL,
        conversationID: Int,
        therapistID: String,
        python: URL
    ) throws -> String {
        let reference = "native-map-" + UUID().uuidString
            .replacingOccurrences(of: "-", with: "")
            .lowercased()
        let script = #"""
import sqlite3, sys
path, conv = sys.argv[1], int(sys.argv[2])
therapist, public_id = sys.argv[3], sys.argv[4]
db = sqlite3.connect(path, timeout=10)
stamp = "2026-08-11 12:00:00"
message = db.execute(
    "INSERT INTO messages(conv,role,content,created,delivery_status) "
    "VALUES(?,'user',?,?,'completed')",
    (conv, "Aynı eleştiri geldiğinde kendimi geri çekiyorum.", stamp)
).lastrowid
observation = db.execute(
    "INSERT INTO psych_observations("
    "conv,source_message,therapist,dimension,content,source_created,created"
    ") VALUES(?,?,?,'user_report',?,?,?)",
    (conv, message, therapist, "Eleştiri sonrası geri çekilme", stamp, stamp)
).lastrowid
claim = db.execute(
    "INSERT INTO psych_claims("
    "public_id,source_conv,therapist,lens,claim_type,title,statement,"
    "status,scope,created,updated"
    ") VALUES(?,?,?,'neutral','pattern',?,?,'candidate','therapist',?,?)",
    (public_id, conv, therapist, "Eleştiri ve geri çekilme",
     "Eleştiri algılandığında geri çekilme eğilimi olabilir.", stamp, stamp)
).lastrowid
db.execute(
    "INSERT INTO psych_claim_evidence("
    "claim,observation,relation,review_status,created"
    ") VALUES(?,?,'supports','pending',?)",
    (claim, observation, stamp)
)
db.commit()
db.close()
print(public_id)
"""#
        return try run(
            python,
            arguments: [
                "-c", script, database.path, String(conversationID),
                therapistID, reference,
            ]
        ).trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private func removeChairWorkspace(
        database: URL,
        techniqueRunID: Int,
        python: URL
    ) throws {
        let script = #"""
import sqlite3, sys
db = sqlite3.connect(sys.argv[1], timeout=10)
db.execute("PRAGMA foreign_keys=ON")
db.execute("DELETE FROM chair_runs WHERE technique_run=?", (int(sys.argv[2]),))
db.commit()
db.close()
"""#
        _ = try run(
            python,
            arguments: [
                "-c", script, database.path, String(techniqueRunID),
            ]
        )
    }

    private func databaseContainsMarker(_ database: URL, marker: String) throws -> Bool {
        guard FileManager.default.fileExists(atPath: database.path) else { return false }
        let python = try XCTUnwrap(CoreRuntime.discoverPython())
        let script = #"""
import sqlite3, sys
db = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True, timeout=5)
exists = db.execute(
    "SELECT 1 FROM messages WHERE content LIKE ? LIMIT 1", ("%" + sys.argv[2] + "%",)
).fetchone()
db.close()
print("1" if exists else "0")
"""#
        return try run(
            python,
            arguments: ["-c", script, database.path, marker]
        ).trimmingCharacters(in: .whitespacesAndNewlines) == "1"
    }

    private func directoryContainsMarker(_ directory: URL, marker: String) throws -> Bool {
        let needle = Data(marker.utf8)
        guard let enumerator = FileManager.default.enumerator(
            at: directory,
            includingPropertiesForKeys: [.isRegularFileKey, .fileSizeKey],
            options: [.skipsHiddenFiles]
        ) else { return false }
        for case let file as URL in enumerator {
            let values = try file.resourceValues(forKeys: [.isRegularFileKey, .fileSizeKey])
            guard values.isRegularFile == true,
                  (values.fileSize ?? 0) <= 64 * 1024 * 1024 else { continue }
            if try Data(contentsOf: file).range(of: needle) != nil { return true }
        }
        return false
    }

    private func permissions(_ url: URL) throws -> Int {
        let attributes = try FileManager.default.attributesOfItem(atPath: url.path)
        return (attributes[.posixPermissions] as? NSNumber)?.intValue ?? -1
    }

    private func isSupportedPortraitImage(_ data: Data) -> Bool {
        let bytes = [UInt8](data.prefix(12))
        let jpegSignature: [UInt8] = [0xff, 0xd8, 0xff]
        let pngSignature: [UInt8] = [
            0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a,
        ]

        if bytes.starts(with: jpegSignature) || bytes.starts(with: pngSignature) {
            return true
        }
        guard bytes.count >= 12 else { return false }
        return Array(bytes[0..<4]) == Array("RIFF".utf8)
            && Array(bytes[8..<12]) == Array("WEBP".utf8)
    }

    @discardableResult
    private func run(_ executable: URL, arguments: [String]) throws -> String {
        let process = Process()
        let stdout = Pipe()
        let stderr = Pipe()
        process.executableURL = executable
        process.arguments = arguments
        process.standardInput = FileHandle.nullDevice
        process.standardOutput = stdout
        process.standardError = stderr
        try process.run()
        process.waitUntilExit()
        let output = stdout.fileHandleForReading.readDataToEndOfFile()
        let errorOutput = stderr.fileHandleForReading.readDataToEndOfFile()
        guard process.terminationStatus == 0 else {
            throw NSError(
                domain: "DivanNativeIntegration",
                code: Int(process.terminationStatus),
                userInfo: [NSLocalizedDescriptionKey:
                    String(decoding: errorOutput, as: UTF8.self)]
            )
        }
        return String(decoding: output, as: UTF8.self)
    }
}

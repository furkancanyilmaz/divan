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

        init(process: Process, output: Pipe, errors: Pipe, port: Int) {
            self.process = process
            self.output = output
            self.errors = errors
            self.port = port
        }

        func stop() {
            guard process.isRunning else { return }
            process.terminate()
            process.waitUntilExit()
        }

        deinit { stop() }
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
                        sceneBoundary: "Yalnız seçtiğim kısa sahne"
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
                    sceneBoundary: "Yalnız seçtiğim kısa sahne"
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
                    frameConfirmed: true
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
            var content = ""
            var observedEvents: [String] = []
            for try await update in stream {
                switch update {
                case .accepted:
                    observedEvents.append("accepted")
                    if acceptedAt == nil { acceptedAt = Date() }
                case .assistantDelta(let text):
                    observedEvents.append("delta:\(text)")
                    if firstDeltaAt == nil { firstDeltaAt = Date() }
                    content += text
                case .assistantReplaced(let text):
                    observedEvents.append("replace:\(text)")
                    if firstDeltaAt == nil { firstDeltaAt = Date() }
                    content = text
                case .assistantCompleted:
                    observedEvents.append("completed")
                    completedAt = Date()
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
        var project = URL(fileURLWithPath: #filePath)
        for _ in 0..<4 { project.deleteLastPathComponent() }
        let core = project.deletingLastPathComponent()
            .appendingPathComponent("core", isDirectory: true)
            .standardizedFileURL
        guard FileManager.default.fileExists(
            atPath: core.appendingPathComponent("server.py").path) else {
            throw XCTSkip("Ortak core çekirdeği bulunamadı: \(core.path)")
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

import Foundation

/// Bridges the native advanced-work views to Divan's authenticated local core.
///
/// The adapter deliberately keeps protocol revisions and server capabilities in
/// the loop. It never invents a consent value, a user utterance, or a sync peer.
public actor CoreAdvancedWorkspaceDataSource: AdvancedWorkspaceDataSource {
    private let loader: DivanRuntimeLoader

    private var contextsByConversation: [Int: AdvancedWorkspaceContext] = [:]
    private var chairConversationBySession: [String: Int] = [:]
    private var imageryConversationBySession: [String: Int] = [:]
    private var chairMethodByConversation: [Int: TechniqueMethod] = [:]
    private var imageryMethodByConversation: [Int: TechniqueMethod] = [:]
    private var activeInvitation: DeviceSyncInvitation?

    public init(loader: DivanRuntimeLoader) {
        self.loader = loader
    }

    // MARK: - Workspace

    public func advancedWorkspaceSnapshot(
        context: AdvancedWorkspaceContext
    ) async throws -> AdvancedWorkspaceSnapshot {
        let (client, _) = try await loader.service()
        if let conversationID = context.conversationID {
            contextsByConversation[conversationID] = context
        }

        let sync = try await client.deviceSyncStatus()
        let syncStatus = Self.workspaceSyncStatus(sync, invitation: activeInvitation)

        guard context.allowsClinicalWork,
              let conversationID = context.conversationID,
              let masterID = context.masterID else {
            return AdvancedWorkspaceSnapshot(syncStatus: syncStatus)
        }

        let catalog = try await client.techniqueCatalog(
            therapistID: masterID,
            conversationID: conversationID
        )
        let publishedChairMethod = Self.preferredChairMethod(in: catalog)
        let publishedImageryMethod = Self.preferredImageryMethod(in: catalog)
        if let method = publishedChairMethod {
            chairMethodByConversation[conversationID] = method
        }
        if let method = publishedImageryMethod {
            imageryMethodByConversation[conversationID] = method
        }

        let chairCollection = try await client.chairWork(
            conversationID: conversationID,
            chairRunID: nil,
            includeFullHistory: false
        )
        let chair = chairCollection.chairWork
        if let chair,
           let method = catalog.methods.first(where: {
               $0.nodeID == chair.methodNodeID
           }) {
            chairMethodByConversation[conversationID] = method
        }
        let chairConfiguration = Self.chairConfiguration(
            method: chairMethodByConversation[conversationID]
        )
        let chairSession: WorkspaceChairSession?
        if let chair, chair.consentComplete {
            chairConversationBySession[String(chair.id)] = conversationID
            chairSession = Self.workspaceChairSession(
                chair,
                configuration: chairConfiguration
            )
        } else {
            chairSession = nil
        }

        let imagery = try await client.imageryWork(conversationID: conversationID)
        let imagerySession: WorkspaceImagerySession?
        if let imagery, imagery.consentComplete {
            imageryConversationBySession[String(imagery.id)] = conversationID
            imagerySession = Self.workspaceImagerySession(imagery)
        } else {
            imagerySession = nil
        }

        let living = try await loadLivingMap(
            client: client,
            therapistID: masterID
        )
        return AdvancedWorkspaceSnapshot(
            clinicalIntensityLimit: catalog.intensityLimit,
            clinicalSafetyHold: catalog.safetyHold,
            chairAvailable: publishedChairMethod != nil || chair != nil,
            chairUnavailableReason: publishedChairMethod == nil && chair == nil
                ? "Bu ustanın yayımlanmış yöntem kataloğunda sandalye çalışması bulunmuyor."
                : nil,
            imageryAvailable: publishedImageryMethod != nil || imagery != nil,
            imageryUnavailableReason: publishedImageryMethod == nil && imagery == nil
                ? "Bu ustanın yayımlanmış yöntem kataloğunda sınırlı yeniden ebeveynlik-imgeleme çalışması bulunmuyor."
                : nil,
            chairConfiguration: chairConfiguration,
            chairSession: chairSession,
            imagerySession: imagerySession,
            livingMap: living,
            syncStatus: syncStatus
        )
    }

    // MARK: - Chair work

    public func startChairWork(
        request: WorkspaceChairStartRequest
    ) async throws -> WorkspaceChairSession {
        guard request.orientationConfirmed, request.frameConfirmed else {
            throw AdvancedWorkspaceValidationError.explicitConsentRequired
        }
        let conversationID = try Self.requiredConversation(request.conversationID)
        let context = try requiredContext(conversationID)
        guard let masterID = context.masterID else {
            throw AdvancedWorkspaceValidationError.clinicalWorkUnavailable
        }
        let (client, _) = try await loader.service()

        let catalog = try await client.techniqueCatalog(
            therapistID: masterID,
            conversationID: conversationID
        )
        guard let selectedMethod = Self.preferredChairMethod(in: catalog) else {
            throw DivanUIClientError(
                "Bu ustanın yayımlanmış bir sandalye çalışması bulunmuyor."
            )
        }
        chairMethodByConversation[conversationID] = selectedMethod

        var work = try await reusableChairWork(
            client: client,
            conversationID: conversationID,
            selectedMethod: selectedMethod,
            intensity: request.intensity
        )
        let configuration = Self.chairConfiguration(method: selectedMethod)
        guard request.participantTitles.count >= configuration.minimumParticipants,
              request.participantTitles.count <= configuration.maximumParticipants,
              request.participantTitles.count >= work.participants.count else {
            throw DivanUIClientError(
                "Bu protokoldeki mevcut sandalyeler kaldırılamaz; adlarını değiştirebilirsiniz."
            )
        }

        for (index, title) in request.participantTitles.enumerated() {
            if index < work.participants.count {
                let participant = work.participants[index]
                if participant.label != title {
                    work = try await client.mutateChairWork(ChairWorkMutation(
                        conversationID: conversationID,
                        chairRunID: work.id,
                        action: .rename,
                        expectedRevision: work.revision,
                        participantID: participant.id,
                        label: title
                    )).chairWork
                }
            } else {
                work = try await client.mutateChairWork(ChairWorkMutation(
                    conversationID: conversationID,
                    chairRunID: work.id,
                    action: .add,
                    expectedRevision: work.revision,
                    label: title
                )).chairWork
            }
        }

        let startIndex = min(
            max(0, request.startingParticipantIndex),
            max(0, work.participants.count - 1)
        )
        if !work.participants.isEmpty,
           work.activeParticipantID != work.participants[startIndex].id {
            work = try await client.mutateChairWork(ChairWorkMutation(
                conversationID: conversationID,
                chairRunID: work.id,
                action: .select,
                expectedRevision: work.revision,
                participantID: work.participants[startIndex].id
            )).chairWork
        }

        work = try await client.mutateChairWork(ChairWorkMutation(
            conversationID: conversationID,
            chairRunID: work.id,
            action: .begin,
            expectedRevision: work.revision,
            orientationOK: request.orientationConfirmed,
            frameOK: request.frameConfirmed,
            stopSignal: request.stopSignal,
            goalText: request.goalText
        )).chairWork
        chairConversationBySession[String(work.id)] = conversationID
        return Self.workspaceChairSession(work, configuration: configuration)
    }

    public func addChairTurn(
        sessionID: String,
        chairID: String,
        content: String,
        intensity: Int
    ) async throws -> WorkspaceChairSession {
        let (conversationID, work, client) = try await currentChairWork(sessionID)
        guard let participantID = Int(chairID),
              work.participants.contains(where: { $0.id == participantID }) else {
            throw DivanUIClientError("Seçilen sandalye artık bulunmuyor.")
        }
        let result = try await client.addChairTurn(ChairTurnInput(
            conversationID: conversationID,
            chairRunID: work.id,
            participantID: participantID,
            content: content,
            intensity: intensity,
            expectedRevision: work.revision
        ))
        return mappedChair(result.chairWork, conversationID: conversationID)
    }

    public func selectChair(
        sessionID: String,
        chairID: String
    ) async throws -> WorkspaceChairSession {
        let (conversationID, work, client) = try await currentChairWork(sessionID)
        guard let participantID = Int(chairID) else {
            throw DivanUIClientError("Sandalye seçimi geçersiz.")
        }
        let updated = try await client.mutateChairWork(ChairWorkMutation(
            conversationID: conversationID,
            chairRunID: work.id,
            action: .select,
            expectedRevision: work.revision,
            participantID: participantID
        )).chairWork
        return mappedChair(updated, conversationID: conversationID)
    }

    public func addChairParticipant(
        sessionID: String,
        title: String
    ) async throws -> WorkspaceChairSession {
        let (conversationID, work, client) = try await currentChairWork(sessionID)
        let updated = try await client.mutateChairWork(ChairWorkMutation(
            conversationID: conversationID,
            chairRunID: work.id,
            action: .add,
            expectedRevision: work.revision,
            label: title
        )).chairWork
        return mappedChair(updated, conversationID: conversationID)
    }

    public func requestChairGuidance(
        sessionID: String
    ) async throws -> WorkspaceChairSession {
        let (conversationID, work, client) = try await currentChairWork(sessionID)
        let latestUserSequence = work.turns.last(where: {
            $0.actorKind == "part" && $0.authoredBy == "user" && $0.revertedAt == nil
        })?.sequence ?? work.lastSequence
        let result = try await client.requestChairGuidance(ChairGuidanceInput(
            conversationID: conversationID,
            chairRunID: work.id,
            afterSequence: latestUserSequence,
            revision: work.revision
        ))
        return mappedChair(result.chairWork, conversationID: conversationID)
    }

    public func resumeChairWork(
        request: WorkspaceChairResumeRequest
    ) async throws -> WorkspaceChairSession {
        guard request.orientationConfirmed else {
            throw AdvancedWorkspaceValidationError.orientationConfirmationRequired
        }
        guard request.groundingConfirmed else {
            throw AdvancedWorkspaceValidationError.groundingConfirmationRequired
        }
        guard request.currentIntensity < 8 else {
            throw AdvancedWorkspaceValidationError.resumeIntensityTooHigh
        }
        let (conversationID, work, client) = try await currentChairWork(
            request.sessionID
        )
        let updated = try await client.mutateChairWork(ChairWorkMutation(
            conversationID: conversationID,
            chairRunID: work.id,
            action: .resume,
            expectedRevision: work.revision,
            orientationOK: request.orientationConfirmed,
            checkpointConfirmed: request.groundingConfirmed,
            intensity: request.currentIntensity
        )).chairWork
        return mappedChair(updated, conversationID: conversationID)
    }

    public func advanceChairClosure(
        request: WorkspaceChairClosureRequest
    ) async throws -> WorkspaceChairSession {
        guard request.checkpointConfirmed else {
            throw AdvancedWorkspaceValidationError.closureCheckpointRequired
        }
        if request.action == .ground, !request.orientationConfirmed {
            throw AdvancedWorkspaceValidationError.orientationConfirmationRequired
        }
        if request.action == .reflect,
           request.note.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            throw AdvancedWorkspaceValidationError.emptyResponse
        }
        let (conversationID, work, client) = try await currentChairWork(
            request.sessionID
        )
        let coreAction: ChairWorkAction
        switch request.action {
        case .ground: coreAction = .ground
        case .reflect: coreAction = .reflect
        case .complete: coreAction = .complete
        }
        let updated = try await client.mutateChairWork(ChairWorkMutation(
            conversationID: conversationID,
            chairRunID: work.id,
            action: coreAction,
            expectedRevision: work.revision,
            orientationOK: request.orientationConfirmed,
            checkpointConfirmed: request.checkpointConfirmed,
            checkpointNote: request.note,
            intensity: request.currentIntensity
        )).chairWork
        return mappedChair(updated, conversationID: conversationID)
    }

    public func stopChairWork(
        sessionID: String
    ) async throws -> WorkspaceChairSession {
        let (conversationID, work, client) = try await currentChairWork(sessionID)
        let updated = try await client.mutateChairWork(ChairWorkMutation(
            conversationID: conversationID,
            chairRunID: work.id,
            action: .stop,
            expectedRevision: work.revision
        )).chairWork
        return mappedChair(updated, conversationID: conversationID)
    }

    // MARK: - Imagery and limited reparenting

    public func startImagery(
        request: WorkspaceImageryStartRequest
    ) async throws -> WorkspaceImagerySession {
        guard request.orientationConfirmed,
              request.frameConfirmed,
              request.realityConfirmed else {
            throw AdvancedWorkspaceValidationError.explicitConsentRequired
        }
        guard request.intensity < 8 else {
            throw DivanUIClientError(
                "Yoğunluk 8 veya üzerindeyken imgeleme başlatılmaz; önce şimdiye dönme adımını kullanın."
            )
        }
        let conversationID = try Self.requiredConversation(request.conversationID)
        let context = try requiredContext(conversationID)
        guard let masterID = context.masterID else {
            throw AdvancedWorkspaceValidationError.clinicalWorkUnavailable
        }
        let (client, _) = try await loader.service()
        let catalog = try await client.techniqueCatalog(
            therapistID: masterID,
            conversationID: conversationID
        )
        guard let method = Self.preferredImageryMethod(in: catalog) else {
            throw DivanUIClientError(
                "Bu ustanın yayımlanmış sınırlı yeniden ebeveynlik protokolü bulunmuyor."
            )
        }
        imageryMethodByConversation[conversationID] = method

        var work = try await reusableImageryWork(
            client: client,
            conversationID: conversationID,
            method: method,
            intensity: request.intensity
        )
        if !work.consentComplete {
            work = try await client.mutateImageryWork(ImageryWorkMutation(
                conversationID: conversationID,
                action: .consent,
                imageryRunID: work.id,
                revision: work.revision,
                orientationOK: request.orientationConfirmed,
                frameOK: request.frameConfirmed,
                realityClear: request.realityConfirmed,
                stopSignal: request.stopSignal,
                sceneBoundary: request.sceneBoundary
            )).imageryWork
        }
        if work.capabilities.begin {
            work = try await client.mutateImageryWork(ImageryWorkMutation(
                conversationID: conversationID,
                action: .begin,
                imageryRunID: work.id,
                revision: work.revision
            )).imageryWork
        }

        // The intention is user-authored content, so preserve it as the first
        // explicit protocol entry instead of smuggling it into hidden state.
        if !request.intention.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
           work.capabilities.write,
           work.steps.allSatisfy({ $0.authoredBy != "user" }) {
            work = try await client.addImageryTurn(ImageryTurnInput(
                conversationID: conversationID,
                imageryRunID: work.id,
                content: request.intention,
                intensity: request.intensity,
                orientationOK: request.orientationConfirmed,
                realityClear: request.realityConfirmed,
                expectedRevision: work.revision
            )).imageryWork
        }

        imageryConversationBySession[String(work.id)] = conversationID
        return Self.workspaceImagerySession(work)
    }

    public func respondToImageryCheckpoint(
        response: WorkspaceImageryCheckpointResponse
    ) async throws -> WorkspaceImagerySession {
        let (conversationID, current, client) = try await currentImageryWork(
            response.sessionID
        )
        let expectedCheckpoint = Self.checkpointID(for: current)
        let selectedDescriptor = current.choiceDescriptors.first(where: {
            $0.id == response.choiceID
        })
        let isFallbackChoice = current.choices.isEmpty &&
            current.choiceDescriptors.isEmpty &&
            response.choiceID == "continue"
        guard response.checkpointID == expectedCheckpoint,
              selectedDescriptor != nil ||
              current.choices.contains(response.choiceID) || isFallbackChoice else {
            throw DivanUIClientError(
                "Bu seçim noktası değişti; güncel adımı yeniden açın."
            )
        }
        let choiceAction = Self.imageryChoiceAction(
            choiceID: response.choiceID,
            descriptors: current.choiceDescriptors
        )
        if choiceAction == .stop {
            let stopped = try await client.mutateImageryWork(
                ImageryWorkMutation(
                    conversationID: conversationID,
                    action: .stop,
                    imageryRunID: current.id,
                    revision: current.revision
                )
            ).imageryWork
            return mappedImagery(stopped, conversationID: conversationID)
        }
        guard response.confirmed else {
            throw AdvancedWorkspaceValidationError.checkpointConfirmationRequired
        }
        guard response.orientationConfirmed else {
            throw AdvancedWorkspaceValidationError.orientationConfirmationRequired
        }
        guard response.realityConfirmed else {
            throw AdvancedWorkspaceValidationError.realityConfirmationRequired
        }
        switch choiceAction {
        case .ground:
            let grounded = try await client.mutateImageryWork(
                ImageryWorkMutation(
                    conversationID: conversationID,
                    action: .ground,
                    imageryRunID: current.id,
                    revision: current.revision,
                    orientationOK: response.orientationConfirmed,
                    intensity: response.currentIntensity
                )
            ).imageryWork
            return mappedImagery(grounded, conversationID: conversationID)
        case .stop:
            break // Handled before confirmation gates above.
        case .advance, .none:
            break
        }
        let note = response.note.trimmingCharacters(in: .whitespacesAndNewlines)
        let content = note.isEmpty
            ? "Seçimim: \(selectedDescriptor?.title ?? Self.choiceTitle(response.choiceID))"
            : note
        var work = try await client.addImageryTurn(ImageryTurnInput(
            conversationID: conversationID,
            imageryRunID: current.id,
            content: content,
            intensity: response.currentIntensity,
            orientationOK: response.orientationConfirmed,
            realityClear: response.realityConfirmed,
            expectedRevision: current.revision,
            stepData: isFallbackChoice ? [:] : ["choice": response.choiceID]
        )).imageryWork

        if work.capabilities.guidance {
            if let guided = try? await client.requestImageryGuidance(
                conversationID: conversationID,
                imageryRunID: work.id,
                revision: work.revision
            ) {
                work = guided.imageryWork
            }
        }
        if work.capabilities.advance {
            work = try await client.mutateImageryWork(ImageryWorkMutation(
                conversationID: conversationID,
                action: .advance,
                imageryRunID: work.id,
                revision: work.revision
            )).imageryWork
        }
        return mappedImagery(work, conversationID: conversationID)
    }

    public func groundImagery(
        request: WorkspaceImageryGroundRequest
    ) async throws -> WorkspaceImagerySession {
        guard request.roomOrientationConfirmed else {
            throw AdvancedWorkspaceValidationError.orientationConfirmationRequired
        }
        let (conversationID, work, client) = try await currentImageryWork(
            request.sessionID
        )
        let updated = try await client.mutateImageryWork(ImageryWorkMutation(
            conversationID: conversationID,
            action: .ground,
            imageryRunID: work.id,
            revision: work.revision,
            orientationOK: request.roomOrientationConfirmed,
            intensity: request.currentIntensity
        )).imageryWork
        return mappedImagery(updated, conversationID: conversationID)
    }

    public func resumeImagery(
        request: WorkspaceImageryResumeRequest
    ) async throws -> WorkspaceImagerySession {
        guard request.orientationConfirmed else {
            throw AdvancedWorkspaceValidationError.orientationConfirmationRequired
        }
        guard request.currentIntensity < 8 else {
            throw AdvancedWorkspaceValidationError.resumeIntensityTooHigh
        }
        let (conversationID, work, client) = try await currentImageryWork(
            request.sessionID
        )
        let updated = try await client.mutateImageryWork(ImageryWorkMutation(
            conversationID: conversationID,
            action: .resume,
            imageryRunID: work.id,
            revision: work.revision,
            orientationOK: request.orientationConfirmed,
            intensity: request.currentIntensity
        )).imageryWork
        return mappedImagery(updated, conversationID: conversationID)
    }

    public func finishImagery(
        request: WorkspaceImageryFinishRequest
    ) async throws -> WorkspaceImagerySession {
        guard request.groundingConfirmed else {
            throw AdvancedWorkspaceValidationError.groundingConfirmationRequired
        }
        guard request.orientationConfirmed else {
            throw AdvancedWorkspaceValidationError.orientationConfirmationRequired
        }
        guard request.realityConfirmed else {
            throw AdvancedWorkspaceValidationError.realityConfirmationRequired
        }
        guard request.currentIntensity < 8 else {
            throw AdvancedWorkspaceValidationError.resumeIntensityTooHigh
        }
        let (conversationID, work, client) = try await currentImageryWork(
            request.sessionID
        )
        let updated = try await client.mutateImageryWork(ImageryWorkMutation(
            conversationID: conversationID,
            action: .complete,
            imageryRunID: work.id,
            revision: work.revision,
            orientationOK: request.orientationConfirmed,
            realityClear: request.realityConfirmed,
            intensity: request.currentIntensity,
            groundingConfirmed: request.groundingConfirmed,
            summary: "Kullanıcı açık kapanış doğrulamalarıyla çalışmayı kapattı."
        )).imageryWork
        return mappedImagery(updated, conversationID: conversationID)
    }

    public func stopImagery(
        sessionID: String
    ) async throws -> WorkspaceImagerySession {
        let (conversationID, work, client) = try await currentImageryWork(sessionID)
        let updated = try await client.mutateImageryWork(ImageryWorkMutation(
            conversationID: conversationID,
            action: .stop,
            imageryRunID: work.id,
            revision: work.revision
        )).imageryWork
        return mappedImagery(updated, conversationID: conversationID)
    }

    // MARK: - Living map

    public func livingMap(
        conversationID: Int?
    ) async throws -> [WorkspaceLivingMapCard] {
        let (client, _) = try await loader.service()
        let therapistID = conversationID.flatMap {
            contextsByConversation[$0]?.masterID
        }
        return try await loadLivingMap(client: client, therapistID: therapistID)
    }

    public func reviewLivingMap(
        cardID: String,
        action: WorkspaceLivingMapReviewAction,
        note: String
    ) async throws -> WorkspaceLivingMapCard {
        let (client, _) = try await loader.service()
        let coreAction: LivingMapReviewAction
        switch action {
        case .confirm: coreAction = .confirm
        case .partial: coreAction = .partial
        case .context: coreAction = .context
        case .rejectEvidence: coreAction = .rejectEvidence
        }
        let detail = try await client.reviewLivingMap(LivingMapReviewRequest(
            claimReference: cardID,
            action: coreAction,
            edits: LivingMapClaimEdits(note: note.isEmpty ? nil : note)
        ))
        return Self.workspaceLivingMapCard(
            detail.claim,
            evidence: detail.evidence
        )
    }

    // MARK: - Same-Wi-Fi sync

    public func wifiSyncStatus() async throws -> WorkspaceWiFiSyncStatus {
        let (client, _) = try await loader.service()
        let status = try await client.deviceSyncStatus()
        if !status.hostRunning { activeInvitation = nil }
        return Self.workspaceSyncStatus(status, invitation: activeInvitation)
    }

    public func createWiFiSyncOffer() async throws -> WorkspaceWiFiSyncStatus {
        let (client, _) = try await loader.service()
        // Çekirdek, açık bir davet varken ikinci `start` çağrısını reddeder
        // ("Bu cihaz zaten eşleşme bekliyor."). Davetin kendisi yalnızca
        // bellekte tutulduğu için, ekran kapanıp açıldığında kullanıcı ne
        // QR'ı görebiliyor ne de yeni davet üretebiliyordu: süre dolana
        // kadar kilitleniyordu. Artık önce eski oturum kapatılır.
        if try await client.deviceSyncStatus().hostRunning {
            _ = try? await client.stopDeviceSyncHost()
            activeInvitation = nil
        }
        let invitation = try await client.startDeviceSyncHost()
        activeInvitation = invitation
        let status = try await client.deviceSyncStatus()
        return Self.workspaceSyncStatus(status, invitation: invitation)
    }

    public func joinWiFiSync(
        code: String,
        deviceName: String
    ) async throws -> WorkspaceWiFiSyncStatus {
        let (client, _) = try await loader.service()
        let result = try await client.pairAndApplyDeviceSync(
            code: code,
            deviceName: deviceName,
            platform: "macos"
        )
        activeInvitation = nil
        return WorkspaceWiFiSyncStatus(
            phase: .completed,
            message: "Eşitleme tamamlandı. \(result.summary.received) kayıt alındı, \(result.summary.sent) kayıt gönderildi.",
            peerName: deviceName,
            progress: 1,
            recordsTransferred: result.summary.received + result.summary.sent,
            conflicts: result.conflicts.map(Self.workspaceConflict),
            secretsExcluded: true,
            updatedAt: Self.date(result.lastSyncAt)
        )
    }

    public func cancelWiFiSync() async throws -> WorkspaceWiFiSyncStatus {
        let (client, _) = try await loader.service()
        _ = try await client.stopDeviceSyncHost()
        activeInvitation = nil
        return WorkspaceWiFiSyncStatus(
            phase: .cancelled,
            message: "Yerel eşitleme daveti iptal edildi."
        )
    }

    public func resolveWiFiSyncConflict(
        conflictID: String,
        resolution: WorkspaceSyncConflictResolution
    ) async throws -> WorkspaceWiFiSyncStatus {
        guard let id = Int(conflictID), id > 0 else {
            throw DivanUIClientError("Çakışma kaydı geçersiz.")
        }
        let (client, _) = try await loader.service()
        _ = try await client.resolveDeviceSyncConflict(
            id: id,
            resolution: resolution == .keepThisMac ? .local : .remote
        )
        let status = try await client.deviceSyncStatus()
        return Self.workspaceSyncStatus(status, invitation: activeInvitation)
    }

    // MARK: - Core lifecycle helpers

    private func reusableChairWork(
        client: APIClient,
        conversationID: Int,
        selectedMethod: TechniqueMethod,
        intensity: Int
    ) async throws -> ChairWork {
        var collection = try await client.chairWork(
            conversationID: conversationID,
            chairRunID: nil,
            includeFullHistory: false
        )
        if var work = collection.chairWork,
           ["proposed", "active", "paused"].contains(work.techniqueStatus) {
            if work.methodNodeID != selectedMethod.nodeID {
                throw DivanUIClientError(
                    DivanStrings.finishOpenWorkFirst
                )
            }
            if work.techniqueStatus == "proposed" {
                _ = try await client.mutateTechniqueRun(TechniqueRunMutation(
                    conversationID: conversationID,
                    action: .consent,
                    runID: work.techniqueRunID,
                    consentConfirmed: true
                ))
                collection = try await client.chairWork(
                    conversationID: conversationID,
                    chairRunID: work.id,
                    includeFullHistory: false
                )
                guard let refreshed = collection.chairWork else {
                    throw DivanUIClientError("Sandalye alanı hazırlanamadı.")
                }
                work = refreshed
            }
            return work
        }

        // A generic method proposal does not create its chair_runs row until
        // explicit consent.  Reopening that proposal must consent the same
        // durable run, not issue a second propose that the server correctly
        // rejects as an active-run conflict.
        let runs = try await client.techniqueRuns(
            conversationID: conversationID
        )
        if let open = runs.runs.first(where: \.isOpen) {
            guard open.methodKey == selectedMethod.key else {
                throw DivanUIClientError(
                    DivanStrings.finishOpenWorkFirst
                )
            }
            if open.status == "proposed" {
                _ = try await client.mutateTechniqueRun(TechniqueRunMutation(
                    conversationID: conversationID,
                    action: .consent,
                    runID: open.id,
                    consentConfirmed: true
                ))
            } else {
                // Older cores could leave a consented/open structured method
                // without its chair_runs side-workspace. Re-applying the
                // already stored intensity is an idempotent lifecycle refresh;
                // the core then materializes the missing published protocol
                // without proposing a second technique or inventing consent.
                _ = try await client.mutateTechniqueRun(TechniqueRunMutation(
                    conversationID: conversationID,
                    action: .intensity,
                    runID: open.id,
                    intensity: open.intensityCurrent ?? intensity
                ))
            }
            collection = try await client.chairWork(
                conversationID: conversationID,
                chairRunID: nil,
                includeFullHistory: false
            )
            guard let refreshed = collection.chairWork,
                  refreshed.techniqueRunID == open.id else {
                throw DivanUIClientError("Sandalye alanı hazırlanamadı.")
            }
            return refreshed
        }

        let proposed = try await client.mutateTechniqueRun(TechniqueRunMutation(
            conversationID: conversationID,
            action: .propose,
            methodKey: selectedMethod.key,
            intensity: intensity
        ))
        let consented = try await client.mutateTechniqueRun(TechniqueRunMutation(
            conversationID: conversationID,
            action: .consent,
            runID: proposed.run.id,
            consentConfirmed: true
        ))
        if let work = consented.chairWork { return work }
        collection = try await client.chairWork(
            conversationID: conversationID,
            chairRunID: nil,
            includeFullHistory: false
        )
        guard let work = collection.chairWork else {
            throw DivanUIClientError("Sandalye alanı hazırlanamadı.")
        }
        return work
    }

    private func reusableImageryWork(
        client: APIClient,
        conversationID: Int,
        method: TechniqueMethod,
        intensity: Int
    ) async throws -> ImageryWork {
        if let existing = try await client.imageryWork(conversationID: conversationID),
           ["proposed", "active", "paused"].contains(existing.techniqueStatus) {
            guard existing.methodNodeID == method.nodeID else {
                throw DivanUIClientError(DivanStrings.finishOpenWorkFirst)
            }
            if existing.techniqueStatus == "proposed" {
                _ = try await client.mutateTechniqueRun(TechniqueRunMutation(
                    conversationID: conversationID,
                    action: .consent,
                    runID: existing.techniqueRunID,
                    consentConfirmed: true
                ))
                guard let refreshed = try await client.imageryWork(
                    conversationID: conversationID
                ) else {
                    throw DivanUIClientError("İmgeleme alanı hazırlanamadı.")
                }
                return refreshed
            }
            return existing
        }

        let runs = try await client.techniqueRuns(conversationID: conversationID)
        if let open = runs.runs.first(where: { $0.isOpen }) {
            guard open.methodKey == method.key else {
                throw DivanUIClientError(DivanStrings.finishOpenWorkFirst)
            }
            if open.status == "proposed" {
                _ = try await client.mutateTechniqueRun(TechniqueRunMutation(
                    conversationID: conversationID,
                    action: .consent,
                    runID: open.id,
                    consentConfirmed: true
                ))
            }
            let created = try await client.mutateImageryWork(ImageryWorkMutation(
                conversationID: conversationID,
                action: .create,
                techniqueRunID: open.id
            ))
            return created.imageryWork
        }

        let proposed = try await client.mutateTechniqueRun(TechniqueRunMutation(
            conversationID: conversationID,
            action: .propose,
            methodKey: method.key,
            intensity: intensity
        ))
        let consented = try await client.mutateTechniqueRun(TechniqueRunMutation(
            conversationID: conversationID,
            action: .consent,
            runID: proposed.run.id,
            consentConfirmed: true
        ))
        return try await client.mutateImageryWork(ImageryWorkMutation(
            conversationID: conversationID,
            action: .create,
            techniqueRunID: consented.run.id
        )).imageryWork
    }

    private func currentChairWork(
        _ sessionID: String
    ) async throws -> (Int, ChairWork, APIClient) {
        guard let chairID = Int(sessionID),
              let conversationID = chairConversationBySession[sessionID] else {
            throw DivanUIClientError("Sandalye çalışması yeniden açılmalı.")
        }
        let (client, _) = try await loader.service()
        let collection = try await client.chairWork(
            conversationID: conversationID,
            chairRunID: chairID,
            includeFullHistory: false
        )
        guard let work = collection.chairWork else {
            throw DivanUIClientError("Sandalye çalışması bulunamadı.")
        }
        return (conversationID, work, client)
    }

    private func currentImageryWork(
        _ sessionID: String
    ) async throws -> (Int, ImageryWork, APIClient) {
        guard let imageryID = Int(sessionID),
              let conversationID = imageryConversationBySession[sessionID] else {
            throw DivanUIClientError("İmgeleme çalışması yeniden açılmalı.")
        }
        let (client, _) = try await loader.service()
        guard let work = try await client.imageryWork(
            conversationID: conversationID
        ), work.id == imageryID else {
            throw DivanUIClientError("İmgeleme çalışması bulunamadı.")
        }
        return (conversationID, work, client)
    }

    private func requiredContext(
        _ conversationID: Int
    ) throws -> AdvancedWorkspaceContext {
        guard let context = contextsByConversation[conversationID],
              context.allowsClinicalWork else {
            throw AdvancedWorkspaceValidationError.clinicalWorkUnavailable
        }
        return context
    }

    private func mappedChair(
        _ work: ChairWork,
        conversationID: Int
    ) -> WorkspaceChairSession {
        chairConversationBySession[String(work.id)] = conversationID
        return Self.workspaceChairSession(
            work,
            configuration: Self.chairConfiguration(
                method: chairMethodByConversation[conversationID]
            )
        )
    }

    private func mappedImagery(
        _ work: ImageryWork,
        conversationID: Int
    ) -> WorkspaceImagerySession {
        imageryConversationBySession[String(work.id)] = conversationID
        return Self.workspaceImagerySession(work)
    }

    // MARK: - Mapping

    private func loadLivingMap(
        client: APIClient,
        therapistID: String?
    ) async throws -> [WorkspaceLivingMapCard] {
        let snapshot = try await client.livingMap(therapistID: therapistID)
        let claims = Self.orderedClaims(snapshot)
        var cards: [WorkspaceLivingMapCard] = []
        cards.reserveCapacity(claims.count)
        for claim in claims {
            let detail = try? await client.livingMapDetail(reference: claim.publicID)
            cards.append(Self.workspaceLivingMapCard(
                claim,
                evidence: detail?.evidence ?? []
            ))
        }
        return cards
    }

    private static func preferredChairMethod(
        in catalog: TechniqueCatalog
    ) -> TechniqueMethod? {
        let methods = catalog.methods.filter(\.isChairWork)
        return methods.first(where: \.recommended) ?? methods.first
    }

    private static func preferredImageryMethod(
        in catalog: TechniqueCatalog
    ) -> TechniqueMethod? {
        let methods = catalog.methods.filter(\.isLimitedReparenting)
        return methods.first(where: \.recommended) ?? methods.first
    }

    private static func chairConfiguration(
        method: TechniqueMethod?
    ) -> WorkspaceChairConfiguration {
        guard let config = method?.chairConfiguration else {
            return .twoPartDefault
        }
        // The core currently supports adding and renaming, not deleting a
        // published protocol participant. Expose that as the true minimum.
        let trueMinimum = max(
            config.minimumParticipants,
            config.defaultParticipants.count
        )
        return WorkspaceChairConfiguration(
            title: config.title,
            frame: config.frame,
            minimumParticipants: trueMinimum,
            maximumParticipants: config.maximumParticipants,
            allowsAddingParticipants: config.allowsAddingParticipants,
            defaultParticipantTitles: config.defaultParticipants.map(\.label)
        )
    }

    private static func workspaceChairSession(
        _ work: ChairWork,
        configuration: WorkspaceChairConfiguration
    ) -> WorkspaceChairSession {
        let participantByID = Dictionary(
            uniqueKeysWithValues: work.participants.map { ($0.id, $0) }
        )
        let participants = work.participants.map {
            WorkspaceChairIdentity(
                id: String($0.id),
                title: $0.label,
                prompt: [$0.purpose, $0.starter]
                    .filter { !$0.isEmpty }
                    .joined(separator: " · "),
                sortOrder: $0.sortOrder
            )
        }
        let turns = work.turns.compactMap { turn -> WorkspaceChairTurn? in
            guard turn.revertedAt == nil,
                  turn.actorKind == "part",
                  let participantID = turn.participantID,
                  let participant = participantByID[participantID] else {
                return nil
            }
            return WorkspaceChairTurn(
                id: String(turn.id),
                chairID: String(participantID),
                chairTitle: turn.participantLabel ?? participant.label,
                content: turn.content,
                createdAt: date(turn.createdAt)
            )
        }
        let guidance = work.turns.compactMap { turn -> WorkspaceChairGuidance? in
            guard turn.revertedAt == nil,
                  turn.turnKind == "guidance",
                  turn.actorKind == "therapist" else { return nil }
            let observation = turn.guidance?.observation ?? turn.content
            let nextStep = [
                turn.guidance?.instruction ?? "",
                turn.guidance?.checkIn ?? "",
            ].filter { !$0.isEmpty }.joined(separator: "\n")
            return WorkspaceChairGuidance(
                id: String(turn.id),
                observation: observation,
                nextStep: turn.guidance?.instruction ?? nextStep,
                checkIn: turn.guidance?.checkIn ?? "",
                createdAt: date(turn.createdAt)
            )
        }
        let phase: WorkspaceWorkPhase
        if work.techniqueStatus == "completed" ||
            work.techniqueStatus == "stopped" || work.status == "closed" {
            phase = .completed
        } else if work.techniqueStatus == "paused" ||
                    work.phase == "grounding" || work.status == "grounding" {
            phase = .paused
        } else if work.consentComplete {
            phase = .active
        } else {
            phase = .notStarted
        }
        let completedClosureActions: Set<WorkspaceChairClosureAction>
        let availableClosureActions: [WorkspaceChairClosureAction]
        if work.techniqueStatus == "completed" || work.phase == "end" {
            completedClosureActions = [.ground, .reflect, .complete]
            availableClosureActions = []
        } else if work.phase == "reflect" {
            completedClosureActions = [.ground, .reflect]
            availableClosureActions = work.capabilities.complete ? [.complete] : []
        } else if work.phase == "grounding" {
            completedClosureActions = [.ground]
            availableClosureActions = work.capabilities.reflect ? [.reflect] : []
        } else {
            completedClosureActions = []
            availableClosureActions = work.capabilities.ground ? [.ground] : []
        }
        return WorkspaceChairSession(
            id: String(work.id),
            title: work.title,
            frame: work.frame,
            goalText: work.goalText,
            stopSignal: work.stopSignal,
            participants: participants,
            minimumParticipants: configuration.minimumParticipants,
            maximumParticipants: configuration.maximumParticipants,
            allowsAddingParticipants: configuration.allowsAddingParticipants,
            orientationConfirmed: work.orientationConfirmed,
            frameConfirmed: work.frameConfirmed,
            stages: work.stages.map {
                WorkspaceProtocolStage(
                    id: $0.id,
                    label: $0.label,
                    aim: $0.aim,
                    prompt: $0.prompt
                )
            },
            currentStageID: work.currentStage,
            currentStageIndex: max(0, work.currentStageIndex),
            availableClosureActions: availableClosureActions,
            completedClosureActions: completedClosureActions,
            activeChairID: String(
                work.activeParticipantID ?? work.participants.first?.id ?? 0
            ),
            turns: turns,
            guidance: guidance,
            phase: phase,
            intensity: work.intensity ?? 0,
            intensityLimit: work.intensityLimit,
            updatedAt: date(work.updatedAt)
        )
    }

    private static func workspaceImagerySession(
        _ work: ImageryWork
    ) -> WorkspaceImagerySession {
        let stages = work.stages.map {
            WorkspaceProtocolStage(
                id: $0.id,
                label: $0.label,
                aim: $0.aim,
                prompt: $0.prompt
            )
        }
        let indexedCurrent = work.stages.indices.contains(work.currentStageIndex)
            ? work.stages[work.currentStageIndex] : nil
        let current = work.stages.first(where: { $0.id == work.currentStage })
            ?? indexedCurrent ?? work.stages.first
        let typedChoices = work.choiceDescriptors.map {
            WorkspaceImageryChoice(
                id: $0.id,
                title: $0.title,
                requiresExplicitConfirmation: true
            )
        }
        let choices = typedChoices.isEmpty ? work.choices.map {
            WorkspaceImageryChoice(
                id: $0,
                title: choiceTitle($0),
                requiresExplicitConfirmation: true
            )
        } : typedChoices
        let safeChoices = choices.isEmpty
            ? [WorkspaceImageryChoice(
                id: "continue",
                title: "Bu adımda kendi sözlerimle devam et",
                requiresExplicitConfirmation: true
            )]
            : choices
        let checkpoint = WorkspaceImageryCheckpoint(
            id: checkpointID(for: work),
            stageID: work.currentStage,
            title: current?.label ?? "Bir sonraki adım",
            prompt: current?.prompt ?? "Şu anda neye ihtiyaç duyduğunuzu kendi sözlerinizle yazın.",
            safetyNote: work.safetyNote,
            choices: safeChoices
        )
        let entries = work.steps.compactMap { step -> WorkspaceImageryEntry? in
            guard step.revertedAt == nil else { return nil }
            return WorkspaceImageryEntry(
                id: String(step.id),
                stageID: step.stage,
                stageLabel: work.stages.first(where: {
                    $0.id == step.stage
                })?.label ?? step.stage,
                content: step.content,
                createdAt: date(step.createdAt)
            )
        }
        let phase: WorkspaceWorkPhase
        if work.techniqueStatus == "completed" ||
            work.techniqueStatus == "stopped" ||
            ["completed", "closed"].contains(work.status) {
            phase = .completed
        } else if work.techniqueStatus == "paused" ||
                    work.phase == "grounding" {
            phase = .paused
        } else if work.techniqueStatus == "active" {
            phase = .active
        } else {
            phase = .notStarted
        }
        return WorkspaceImagerySession(
            id: String(work.id),
            phase: phase,
            title: work.title,
            frame: work.frame,
            stages: stages,
            currentStageID: work.currentStage,
            currentStageIndex: max(0, work.currentStageIndex),
            checkpoint: checkpoint,
            entries: entries,
            sceneBoundary: work.sceneBoundary,
            stopSignal: work.stopSignal,
            orientationConfirmed: work.orientationConfirmed,
            frameConfirmed: work.frameConfirmed,
            realityConfirmed: work.realityConfirmed,
            intensity: work.intensity ?? 0,
            intensityLimit: work.intensityLimit,
            updatedAt: entries.last?.createdAt ?? Date()
        )
    }

    static func imageryChoiceAction(
        choiceID: String,
        descriptors: [ImageryChoiceDescriptor]
    ) -> ImageryChoiceAction? {
        descriptors.first(where: { $0.id == choiceID })?.action
    }

    private static func checkpointID(for work: ImageryWork) -> String {
        "\(work.id):\(work.revision):\(work.currentStage)"
    }

    private static func choiceTitle(_ raw: String) -> String {
        let known: [String: String] = [
            "continue": "Kendi sözlerimle devam et",
            "unsure": "Emin değilim; yavaş ilerle",
            "yes": "Evet, bu bana uyuyor",
            "partly": "Kısmen uyuyor",
            "no": "Hayır, bu bana uymuyor",
            "ground": "Şimdiye dön",
            "pause": "Burada duraklat",
        ]
        if let title = known[raw.localizedLowercase] { return title }
        let value = raw.replacingOccurrences(of: "_", with: " ")
            .replacingOccurrences(of: "-", with: " ")
        return value.prefix(1).uppercased() + value.dropFirst()
    }

    private static func orderedClaims(
        _ snapshot: LivingMapSnapshot
    ) -> [LivingMapClaim] {
        let raw = snapshot.pending + snapshot.pendingEvidenceReviews +
            snapshot.sections.cycles + snapshot.sections.valuesAndNeeds +
            snapshot.sections.strengthsAndExceptions +
            snapshot.sections.goalsAndHelpfulPatterns
        var seen = Set<String>()
        return raw.filter { seen.insert($0.publicID).inserted }
    }

    private static func workspaceLivingMapCard(
        _ claim: LivingMapClaim,
        evidence: [LivingMapEvidence]
    ) -> WorkspaceLivingMapCard {
        let domain = livingDomain(claim)
        let count = max(claim.sourceCount, claim.evidenceCount)
        let confidence: WorkspaceLivingMapConfidence = count >= 4
            ? .wellSupported : count >= 2 ? .repeated : .emerging
        let mappedEvidence = evidence.map {
            WorkspaceLivingMapEvidence(
                id: String($0.id),
                sourceTitle: $0.sourceLabel.isEmpty
                    ? ($0.conversationTitle.isEmpty ? "Konuşma dayanağı" : $0.conversationTitle)
                    : $0.sourceLabel,
                excerpt: $0.excerpt,
                observedAt: date($0.observedAt),
                conversationID: $0.conversationID,
                reviewStatus: $0.reviewStatus
            )
        }
        let actions = claim.reviewActions.compactMap {
            switch $0 {
            case "confirm": WorkspaceLivingMapReviewAction.confirm
            case "partial": WorkspaceLivingMapReviewAction.partial
            case "context": WorkspaceLivingMapReviewAction.context
            case "reject", "reject_evidence": WorkspaceLivingMapReviewAction.rejectEvidence
            default: nil
            }
        }
        return WorkspaceLivingMapCard(
            id: claim.publicID,
            domain: domain,
            title: claim.title.isEmpty ? domain.title : claim.title,
            hypothesis: claim.statement.isEmpty
                ? [claim.trigger, claim.response, claim.need]
                    .filter { !$0.isEmpty }.joined(separator: " → ")
                : claim.statement,
            confidence: confidence,
            evidence: mappedEvidence,
            reviewPrompt: claim.reviewPrompt,
            allowedReviewActions: actions.isEmpty
                ? [.confirm, .partial, .context, .rejectEvidence] : actions,
            reviewStatus: claim.status,
            updatedAt: date(claim.lastSeen ?? claim.updatedAt)
        )
    }

    private static func livingDomain(
        _ claim: LivingMapClaim
    ) -> WorkspaceLivingMapDomain {
        let text = [claim.claimType, claim.lens, claim.title, claim.statement]
            .joined(separator: " ")
            .folding(options: [.diacriticInsensitive, .caseInsensitive], locale: Locale(identifier: "tr_TR"))
            .localizedLowercase
        if text.contains("ofkeli") || text.contains("angry") { return .angryChild }
        if text.contains("kirılgan") || text.contains("kirilgan") ||
            text.contains("incinmis") || text.contains("vulnerable") {
            return .vulnerableChild
        }
        if text.contains("elestirel") || text.contains("critic") ||
            text.contains("parent") || text.contains("ebeveyn") {
            return .criticalParent
        }
        if text.contains("tetik") || text.contains("trigger") { return .trigger }
        if text.contains("deger") || text.contains("value") ||
            text.contains("ihtiyac") || text.contains("need") ||
            text.contains("goal") || text.contains("hedef") {
            return .value
        }
        if text.contains("saglikli") || text.contains("healthy") ||
            text.contains("strength") || text.contains("guclu") {
            return .healthyAdult
        }
        return .coping
    }

    private static func workspaceSyncStatus(
        _ status: DeviceSyncStatus,
        invitation: DeviceSyncInvitation?
    ) -> WorkspaceWiFiSyncStatus {
        let phase: WorkspaceWiFiSyncPhase
        let message: String
        if status.busy {
            phase = .transferring
            message = "Kayıtlar aynı Wi-Fi üzerinden eşitleniyor."
        } else if status.hostRunning {
            phase = .waitingForScan
            message = "QR kod diğer cihazdan taranmayı bekliyor."
        } else if status.lastSyncAt != nil {
            phase = .completed
            message = "Son yerel eşitleme tamamlandı."
        } else {
            phase = .idle
            message = "Bu Mac aynı Wi-Fi ağındaki telefonla eşitlemeye hazır."
        }
        let seconds = status.secondsRemaining > 0
            ? status.secondsRemaining : (invitation?.secondsRemaining ?? 0)
        return WorkspaceWiFiSyncStatus(
            phase: phase,
            message: message,
            pairingCode: status.hostRunning ? invitation?.pairingCode : nil,
            qrMatrix: status.hostRunning ? invitation.map {
                WorkspaceQRMatrix(size: $0.qrMatrix.size, rows: $0.qrMatrix.rows)
            } : nil,
            expiresAt: status.hostRunning ? Date().addingTimeInterval(
                TimeInterval(max(0, seconds))
            ) : nil,
            peerName: status.lastPeerName,
            progress: status.busy ? nil : (phase == .completed ? 1 : nil),
            recordsTransferred: status.lastSummary.sent + status.lastSummary.received,
            conflicts: status.conflicts.map(workspaceConflict),
            secretsExcluded: status.secretsExcluded,
            updatedAt: status.lastSyncAt.map(date) ?? Date()
        )
    }

    private static func workspaceConflict(
        _ conflict: SyncConflict
    ) -> WorkspaceSyncConflict {
        WorkspaceSyncConflict(
            id: String(conflict.id),
            title: conflict.title,
            summary: conflict.summary,
            reason: conflict.reason
        )
    }

    private static func requiredConversation(_ value: Int?) throws -> Int {
        guard let value, value > 0 else {
            throw AdvancedWorkspaceValidationError.clinicalWorkUnavailable
        }
        return value
    }

    private static func date(_ value: String) -> Date {
        guard !value.isEmpty else { return Date() }
        let fractional = ISO8601DateFormatter()
        fractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let parsed = fractional.date(from: value) { return parsed }
        let standard = ISO8601DateFormatter()
        if let parsed = standard.date(from: value) { return parsed }
        let sqlite = DateFormatter()
        sqlite.locale = Locale(identifier: "en_US_POSIX")
        sqlite.timeZone = TimeZone.current
        sqlite.dateFormat = "yyyy-MM-dd HH:mm:ss"
        if let parsed = sqlite.date(from: value) { return parsed }
        sqlite.dateFormat = "yyyy-MM-dd HH:mm"
        return sqlite.date(from: value) ?? Date()
    }
}

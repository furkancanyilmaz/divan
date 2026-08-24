import Foundation
import XCTest
@testable import DivanNative

@MainActor
final class SchemaChatOnlyViewModelTests: XCTestCase {
    func testCandidatePromptIsExactlyAnchoredAndComposerIsLocked() async throws {
        let (model, _) = try await openModel(snapshot: candidateSnapshot())

        XCTAssertTrue(model.usesSchemaChatOnlyPresentation)
        let card = try XCTUnwrap(
            model.schemaCandidatePrompt(forAssistantMessageID: 102)
        )
        XCTAssertEqual(
            card.source.candidateQuoteForDisplay,
            "Bugün aynı döngü tekrarlandı."
        )
        XCTAssertEqual(
            card.candidatePatternForDisplay,
            "Kusurluluk / İncinmiş Çocuk"
        )
        XCTAssertEqual(card.body, "Bunu çalışmak ister misin?")
        XCTAssertNil(model.schemaCandidatePrompt(forAssistantMessageID: 999))
        XCTAssertNil(model.schemaComposerBinding)
        XCTAssertTrue(model.schemaComposerLockedByCard)
        XCTAssertFalse(model.canSend)
    }

    func testCandidateContextFailsClosedWhenQuotePatternOrLineageIsUnsafe()
        async throws {
        let emptyQuote = SchemaCardSource(
            userMessageId: 101,
            userMessagePublicId: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            assistantMessageId: 102,
            assistantMessagePublicId: "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            quote: "  \n\t "
        )
        let (emptyModel, _) = try await openModel(
            snapshot: candidateSnapshot(source: emptyQuote)
        )
        XCTAssertNil(emptyModel.schemaCandidatePrompt(
            forAssistantMessageID: 102
        ))

        let oversizedQuote = SchemaCardSource(
            userMessageId: 101,
            userMessagePublicId: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            assistantMessageId: 102,
            assistantMessagePublicId: "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            quote: String(repeating: "a", count: 701)
        )
        let (oversizedModel, _) = try await openModel(
            snapshot: candidateSnapshot(source: oversizedQuote)
        )
        XCTAssertNil(oversizedModel.schemaCandidatePrompt(
            forAssistantMessageID: 102
        ))

        let (patternModel, _) = try await openModel(snapshot: candidateSnapshot(
            contextLine: "Bu örüntü olabilir."
        ))
        XCTAssertNil(patternModel.schemaCandidatePrompt(
            forAssistantMessageID: 102
        ))

        let mismatchedRows = [
            DivanMessage(
                id: "schema-source-user", serverID: 101, role: .user,
                content: "Bugün aynı döngü tekrarlandı.", createdAt: Date(),
                publicID: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                deliveryStatus: "completed"
            ),
            DivanMessage(
                id: "schema-source-assistant", serverID: 102,
                role: .assistant, content: "Bunu birlikte sınayabiliriz.",
                createdAt: Date(),
                publicID: "ffffffffffffffffffffffffffffffff",
                deliveryStatus: "completed"
            ),
        ]
        let mismatchedSource = SchemaChatV4DataSource(
            snapshot: candidateSnapshot(),
            conversationMessages: mismatchedRows
        )
        let mismatchedModel = try await openModel(source: mismatchedSource)
        XCTAssertNil(mismatchedModel.schemaCandidatePrompt(
            forAssistantMessageID: 102
        ))
    }

    func testCandidateContextFailsClosedWhenQuoteDiffersFromBoundUserMessage()
        async throws {
        let differentQuote = SchemaCardSource(
            userMessageId: 101,
            userMessagePublicId: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            assistantMessageId: 102,
            assistantMessagePublicId: "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            quote: "Bu cümle kullanıcı mesajında yok."
        )
        let source = SchemaChatV4DataSource(
            snapshot: candidateSnapshot(source: differentQuote)
        )
        let model = try await openModel(source: source)

        XCTAssertNil(model.schemaCandidatePrompt(forAssistantMessageID: 102))
    }

    func testCandidateContextFailsClosedForControlAndBidiQuotes()
        async throws {
        for unsafeContent in [
            "Bugün\u{0007} aynı döngü tekrarlandı.",
            "Bugün \u{202E}aynı döngü tekrarlandı.",
        ] {
            let unsafeSource = SchemaCardSource(
                userMessageId: 101,
                userMessagePublicId: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                assistantMessageId: 102,
                assistantMessagePublicId: "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                quote: unsafeContent
            )
            let source = SchemaChatV4DataSource(
                snapshot: candidateSnapshot(source: unsafeSource),
                conversationMessages: candidateMessages(
                    userContent: unsafeContent
                )
            )
            let model = try await openModel(source: source)

            XCTAssertNil(
                model.schemaCandidatePrompt(forAssistantMessageID: 102),
                "Kontrol/Bidi içeren aday kartı gösterilmemeli."
            )
        }
    }

    func testCandidateContextMatchesServerSevenHundredCodePointExcerpt()
        async throws {
        // 449 ASCII scalar + decomposed é = the server's exact 451-code-point
        // head. The middle is discarded and the final 213 scalars are kept.
        let head = String(repeating: "a", count: 449) + "e\u{301}"
        let tail = String(repeating: "z", count: 213)
        let longUserContent = head + String(repeating: "m", count: 91) + tail
        let serverQuote = head
            + "\n… [kayıt bağlam için kısaltıldı] …\n"
            + tail
        XCTAssertEqual(longUserContent.unicodeScalars.count, 755)
        XCTAssertEqual(serverQuote.unicodeScalars.count, 700)

        let exactSource = SchemaCardSource(
            userMessageId: 101,
            userMessagePublicId: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            assistantMessageId: 102,
            assistantMessagePublicId: "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            quote: serverQuote
        )
        let exactDataSource = SchemaChatV4DataSource(
            snapshot: candidateSnapshot(source: exactSource),
            conversationMessages: candidateMessages(
                userContent: longUserContent
            )
        )
        let exactModel = try await openModel(source: exactDataSource)
        XCTAssertNotNil(exactModel.schemaCandidatePrompt(
            forAssistantMessageID: 102
        ))

        let wrongSource = SchemaCardSource(
            userMessageId: 101,
            userMessagePublicId: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            assistantMessageId: 102,
            assistantMessagePublicId: "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            quote: String(serverQuote.dropLast()) + "x"
        )
        let wrongDataSource = SchemaChatV4DataSource(
            snapshot: candidateSnapshot(source: wrongSource),
            conversationMessages: candidateMessages(
                userContent: longUserContent
            )
        )
        let wrongModel = try await openModel(source: wrongDataSource)
        XCTAssertNil(wrongModel.schemaCandidatePrompt(
            forAssistantMessageID: 102
        ))
    }

    func testCandidateYesPostsOneAtomicPathlessIntentWithExactLineage() async throws {
        let snapshot = candidateSnapshot()
        let (model, source) = try await openModel(snapshot: snapshot)
        let card = try XCTUnwrap(model.activeSchemaCard)
        let action = try XCTUnwrap(card.actions.first {
            $0.action == "accept_candidate_chat"
        })

        await model.submitSchemaCard(card, action: action, fieldValues: [:])

        let mutations = await source.capturedCardMutations()
        let mutation = try XCTUnwrap(mutations.only)
        XCTAssertEqual(mutation.action, .acceptCandidateChat)
        XCTAssertNil(mutation.pathID)
        XCTAssertNil(mutation.expectedRevision)
        XCTAssertEqual(mutation.values["claim_id"], .number(44))
        XCTAssertEqual(
            mutation.values["candidate_public_id"],
            .string("11111111111111111111111111111111")
        )
        XCTAssertEqual(mutation.sourceUserMessageID, 101)
        XCTAssertEqual(
            mutation.sourceUserMessagePublicID,
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        )
        XCTAssertEqual(mutation.sourceAssistantMessageID, 102)
        XCTAssertEqual(
            mutation.sourceAssistantMessagePublicID,
            "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        )
        let legacyPathMutations = await source.capturedPathMutations()
        XCTAssertTrue(legacyPathMutations.isEmpty)
    }

    func testCandidateNoUsesRejectAndNeverSynthesizesASecondStart() async throws {
        let (model, source) = try await openModel(snapshot: candidateSnapshot())
        let card = try XCTUnwrap(model.activeSchemaCard)
        let action = try XCTUnwrap(card.actions.first {
            $0.action == "reject_candidate_chat"
        })

        await model.submitSchemaCard(card, action: action, fieldValues: [:])

        let mutations = await source.capturedCardMutations()
        XCTAssertEqual(mutations.map(\.action), [.rejectCandidateChat])
        let legacyPathMutations = await source.capturedPathMutations()
        XCTAssertTrue(legacyPathMutations.isEmpty)
    }

    func testV5CandidateKeepsOnlyTheTinyYesNoSurface() async throws {
        let (model, _) = try await openModel(snapshot: v5CandidateSnapshot())

        XCTAssertTrue(model.usesSchemaChatProtocolV5)
        XCTAssertTrue(model.usesSchemaChatOnlyPresentation)
        let card = try XCTUnwrap(
            model.schemaCandidatePrompt(forAssistantMessageID: 102)
        )
        XCTAssertEqual(card.body, "Bunu çalışmak ister misin?")
        XCTAssertEqual(card.actions.map(\.label), ["Evet", "Hayır"])
        XCTAssertNil(model.schemaComposerBinding)
        XCTAssertTrue(model.schemaComposerLockedByCard)
    }

    func testV5ComposerRequiresExactCompletedDurablePromptBubble()
        async throws {
        let (model, source) = try await openModel(snapshot: v5Snapshot())

        XCTAssertTrue(model.usesSchemaChatProtocolV5)
        XCTAssertEqual(model.activeSchemaCard?.kind, "chat_state")
        XCTAssertEqual(model.activeSchemaCard?.body, "")
        XCTAssertTrue(model.activeSchemaCard?.actions.isEmpty == true)
        let binding = try XCTUnwrap(model.schemaComposerBinding)
        XCTAssertEqual(binding.protocol, "schema_path_chat_v5")
        XCTAssertEqual(
            binding.promptRequestId, "schema-v5-prompt-0001"
        )
        XCTAssertEqual(binding.promptAssistantMessageId, 102)
        XCTAssertEqual(
            binding.promptAssistantMessagePublicId,
            "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        )
        XCTAssertFalse(model.schemaComposerLockedByCard)
        model.composerText = "Dün toplantıda sözüm kesildi."
        XCTAssertTrue(model.canSend)

        await model.sendComposerMessage()

        let bindings = await source.capturedBindings()
        let sentBinding = try XCTUnwrap(bindings.only ?? nil)
        XCTAssertEqual(sentBinding.promptRequestId, binding.promptRequestId)
        XCTAssertEqual(
            sentBinding.deviceLocalDraftFingerprint(
                conversationID: SchemaChatV4DataSource.conversationID
            ),
            binding.deviceLocalDraftFingerprint(
                conversationID: SchemaChatV4DataSource.conversationID
            )
        )
    }

    func testV5PendingTamperedOrNonDurablePromptFailsClosed()
        async throws {
        let (pending, _) = try await openModel(
            snapshot: v5Snapshot(deliveryStatus: "running")
        )
        XCTAssertNil(pending.schemaComposerBinding)
        XCTAssertTrue(pending.schemaComposerLockedByCard)

        let (tampered, _) = try await openModel(snapshot: v5Snapshot(
            bindingPromptRequestID: "schema-v5-prompt-tampered"
        ))
        XCTAssertNil(tampered.schemaComposerBinding)
        XCTAssertTrue(tampered.schemaComposerLockedByCard)

        let pendingBubble = [
            DivanMessage(
                id: "schema-source-user", serverID: 101, role: .user,
                content: "Dün toplantıda sözüm kesildi.", createdAt: Date()
            ),
            DivanMessage(
                id: "schema-source-assistant", serverID: 102,
                role: .assistant,
                content: "O anı biraz anlatır mısın?", createdAt: Date(),
                isPending: true
            ),
        ]
        let pendingSource = SchemaChatV4DataSource(
            snapshot: v5Snapshot(), conversationMessages: pendingBubble
        )
        let pendingBubbleModel = try await openModel(source: pendingSource)
        XCTAssertNil(pendingBubbleModel.schemaComposerBinding)
        XCTAssertTrue(pendingBubbleModel.schemaComposerLockedByCard)
    }

    func testV5ImportedWaitingOpensOnlyOrdinaryTypedControlComposer()
        async throws {
        let (model, source) = try await openModel(
            snapshot: v5ImportedWaitingSnapshot()
        )

        let card = try XCTUnwrap(model.activeSchemaCard)
        XCTAssertEqual(card.kind, "chat_state")
        XCTAssertEqual(card.status, "paused")
        XCTAssertEqual(card.body, "")
        XCTAssertTrue(card.actions.isEmpty)
        XCTAssertTrue(card.fields.isEmpty)
        XCTAssertNil(card.progress)
        XCTAssertTrue(card.isSupportedByNativeContract)
        XCTAssertNil(model.schemaSafetyControls(forAssistantMessageID: 102))
        XCTAssertNil(model.schemaChatPromptContinuation(for:
            try XCTUnwrap(model.messages.last)))

        let binding = try XCTUnwrap(model.schemaComposerBinding)
        XCTAssertEqual(binding.syncImportControl, true)
        XCTAssertNil(binding.promptRequestId)
        XCTAssertNil(binding.promptAssistantMessageId)
        XCTAssertNil(binding.promptAssistantMessagePublicId)
        XCTAssertFalse(model.schemaComposerLockedByCard)

        model.composerText = "Devam"
        XCTAssertTrue(model.canSend)
        await model.sendComposerMessage()
        let capturedBindings = await source.capturedBindings()
        let capturedTexts = await source.capturedSentTexts()
        let sent = try XCTUnwrap(capturedBindings.only ?? nil)
        XCTAssertEqual(sent.syncImportControl, true)
        XCTAssertEqual(capturedTexts, ["Devam"])
    }

    func testV5ImportedWaitingFailsClosedOnManualPauseOrFabricatedDelivery()
        async throws {
        let (manualPause, _) = try await openModel(snapshot:
            v5ImportedWaitingSnapshot(pauseReason: "manual_pause")
        )
        XCTAssertNil(manualPause.schemaComposerBinding)
        XCTAssertTrue(manualPause.schemaComposerLockedByCard)

        let (fabricated, _) = try await openModel(snapshot:
            v5ImportedWaitingSnapshot(
                bindingPromptRequestID: "schema-v5-prompt-old-0001"
            )
        )
        XCTAssertNil(fabricated.schemaComposerBinding)
        XCTAssertTrue(fabricated.schemaComposerLockedByCard)

        let (falseMarker, _) = try await openModel(snapshot:
            v5ImportedWaitingSnapshot(syncImportControl: false)
        )
        XCTAssertNil(falseMarker.schemaComposerBinding)
        XCTAssertTrue(falseMarker.schemaComposerLockedByCard)
    }

    func testV5ImportControlSurvivesProcessReopenOnlyAtExactFingerprint()
        async throws {
        let source = SchemaChatV4DataSource(
            snapshot: v5ImportedWaitingSnapshot()
        )
        let store = MemorySchemaChatDraftStore()
        let first = try await openModel(source: source, draftStore: store)
        let original = try XCTUnwrap(first.schemaComposerBinding)
        first.composerText = "Devam"

        let encoded = try JSONEncoder().encode(original)
        let revived = try JSONDecoder().decode(
            SchemaChatBinding.self, from: encoded
        )
        XCTAssertEqual(revived.syncImportControl, true)
        XCTAssertNil(revived.promptRequestId)
        XCTAssertNil(revived.promptAssistantMessageId)
        XCTAssertNil(revived.promptAssistantMessagePublicId)
        let originalFingerprint = original.deviceLocalDraftFingerprint(
            conversationID: SchemaChatV4DataSource.conversationID
        )
        XCTAssertEqual(
            revived.deviceLocalDraftFingerprint(
                conversationID: SchemaChatV4DataSource.conversationID
            ),
            originalFingerprint
        )

        let reopened = try await openModel(source: source, draftStore: store)
        XCTAssertEqual(reopened.composerText, "Devam")
        XCTAssertEqual(
            reopened.schemaComposerBinding?.deviceLocalDraftFingerprint(
                conversationID: SchemaChatV4DataSource.conversationID
            ),
            originalFingerprint
        )

        await source.replaceSnapshot(v5ImportedWaitingSnapshot(
            checkpointSeq: 2
        ))
        let stale = try await openModel(source: source, draftStore: store)
        XCTAssertTrue(stale.composerText.isEmpty)
        XCTAssertNil(store.record(
            conversationID: SchemaChatV4DataSource.conversationID
        ))
    }

    func testV5ActiveClinicalPromptMustBeLatestAdjacentDurablePair()
        async throws {
        let rows = [
            DivanMessage(
                id: "source-user", serverID: 101, role: .user,
                content: "Somut an.", createdAt: Date(),
                publicID: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                deliveryStatus: "completed"
            ),
            DivanMessage(
                id: "prompt", serverID: 102, role: .assistant,
                content: "O anda ne oldu?", createdAt: Date(),
                publicID: "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                deliveryStatus: "completed"
            ),
            DivanMessage(
                id: "later-user", serverID: 103, role: .user,
                content: "Geç gelen başka yanıt.", createdAt: Date(),
                publicID: "cccccccccccccccccccccccccccccccc",
                deliveryStatus: "completed"
            ),
        ]
        let source = SchemaChatV4DataSource(
            snapshot: v5Snapshot(), conversationMessages: rows
        )
        let model = try await openModel(source: source)

        XCTAssertNil(model.schemaComposerBinding)
        XCTAssertTrue(model.schemaComposerLockedByCard)
    }

    func testV5SendNeverRendersPartialOrPlaceholderAssistantBubble()
        async throws {
        let source = SchemaChatV4DataSource(
            snapshot: v5Snapshot(),
            streamDelayNanoseconds: 250_000_000
        )
        let model = try await openModel(source: source)
        model.composerText = "Toplantıdaki anı anlatıyorum."

        let send = Task { await model.sendComposerMessage() }
        for _ in 0..<100 {
            if model.isSending { break }
            await Task.yield()
        }
        XCTAssertTrue(model.isSending)
        XCTAssertFalse(model.messages.contains {
            $0.role == .assistant && $0.serverID == nil && $0.isPending
        })
        XCTAssertEqual(model.messages.last?.role, .user)
        await send.value
        XCTAssertFalse(model.messages.contains {
            $0.role == .assistant && $0.serverID == nil
        })
    }

    func testV5ProcessDeathPendingRequestRestoresWithoutAssistantPlaceholder()
        async throws {
        let pending = DivanPendingChat(
            requestID: "schema-v5-process-0001",
            status: "running",
            content: "Kısmi ve görünmemesi gereken içerik",
            retryable: false,
            isPending: true,
            waitingForProvider: false,
            schemaPromptProtocol: "schema_path_chat_v5",
            schemaPromptIntent: "variable_counterfactual"
        )
        let source = SchemaChatV4DataSource(
            snapshot: v5Snapshot(deliveryStatus: "running"),
            pendingChat: pending
        )
        let model = try await openModel(source: source)

        XCTAssertTrue(model.isSending)
        XCTAssertFalse(model.messages.contains {
            $0.id == "background-schema-v5-process-0001"
        })
        XCTAssertFalse(model.messages.contains {
            $0.content == "Kısmi ve görünmemesi gereken içerik"
        })
    }

    func testActivePromptBuildsHiddenIdentityOnlyBindingForOrdinaryComposer() async throws {
        let (model, _) = try await openModel(snapshot: activeSnapshot())
        model.composerText = "O anda kendimi çok küçük hissettim."

        let binding = try XCTUnwrap(model.schemaComposerBinding)
        XCTAssertEqual(binding.pathId, 9)
        XCTAssertEqual(
            binding.pathPublicId, "33333333333333333333333333333333"
        )
        XCTAssertEqual(binding.stepId, "origin_or_unknown")
        XCTAssertEqual(binding.expectedRevision, 12)
        XCTAssertEqual(binding.sourceUserMessageId, 101)
        XCTAssertEqual(
            binding.sourceUserMessagePublicId,
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        )
        XCTAssertEqual(binding.sourceAssistantMessageId, 102)
        XCTAssertEqual(
            binding.sourceAssistantMessagePublicId,
            "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        )
        let encoded = try JSONEncoder().encode(binding)
        XCTAssertFalse(String(decoding: encoded, as: UTF8.self).contains("stepData"))
        XCTAssertFalse(model.schemaComposerLockedByCard)
        XCTAssertTrue(model.canSend)
    }

    func testPromptMetadataNeverAppendsTextUnderAssistantBubble() async throws {
        let (model, _) = try await openModel(snapshot: activeSnapshot())
        let sourceMessage = try XCTUnwrap(model.messages.first {
            $0.serverID == 102
        })
        XCTAssertNil(model.schemaChatPromptContinuation(for: sourceMessage))
        XCTAssertEqual(sourceMessage.content, "Bunu birlikte sınayabiliriz.")
        let duplicate = DivanMessage(
            id: "duplicate-assistant",
            serverID: 102,
            role: .assistant,
            content: "Bunu birlikte sınayabiliriz. Bu duygunun ilk tanıdık geldiği anı hatırlıyor musunuz?",
            createdAt: Date()
        )
        XCTAssertNil(model.schemaChatPromptContinuation(for: duplicate))
    }

    func testMissingPublicLineageAndUnknownKindFailClosed() async throws {
        var card = activeCard()
        card = SchemaCardEnvelope(
            id: card.id,
            kind: card.kind,
            presentation: card.presentation,
            status: card.status,
            stage: card.stage,
            step: card.step,
            pathId: card.pathId,
            pathPublicId: card.pathPublicId,
            revision: card.revision,
            title: card.title,
            contextLine: card.contextLine,
            body: card.body,
            source: .init(
                userMessageId: 101,
                assistantMessageId: 102,
                assistantMessagePublicId:
                    "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
            ),
            fields: [],
            actions: card.actions,
            progress: card.progress
        )
        let (missingModel, _) = try await openModel(
            snapshot: activeSnapshot(card: card)
        )
        XCTAssertNil(missingModel.schemaComposerBinding)
        XCTAssertTrue(missingModel.schemaComposerLockedByCard)

        let tamperedBinding = SchemaChatBinding(
            pathId: 9,
            pathPublicId: "33333333333333333333333333333333",
            stepId: "origin_or_unknown",
            expectedRevision: 12,
            checkpointPublicId: String(repeating: "6", count: 32),
            expectedCheckpointSeq: 12,
            sourceUserMessageId: 101,
            sourceUserMessagePublicId:
                "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            sourceAssistantMessageId: 102,
            sourceAssistantMessagePublicId: "wrong-assistant-public-id"
        )
        let (tamperedModel, _) = try await openModel(snapshot: activeSnapshot(
            card: replacingBinding(activeCard(), with: tamperedBinding)
        ))
        XCTAssertNil(tamperedModel.schemaComposerBinding)
        XCTAssertTrue(tamperedModel.schemaComposerLockedByCard)

        let missingCardPath = replacingPathLineage(
            activeCard(), pathID: nil, pathPublicID: nil
        )
        let (missingPathModel, _) = try await openModel(
            snapshot: activeSnapshot(card: missingCardPath)
        )
        XCTAssertNil(missingPathModel.schemaComposerBinding)
        XCTAssertTrue(missingPathModel.schemaComposerLockedByCard)

        let unknown = replacingKind(activeCard(), with: "future_workspace")
        let (unknownModel, _) = try await openModel(
            snapshot: activeSnapshot(card: unknown)
        )
        XCTAssertNil(unknownModel.schemaComposerBinding)
        XCTAssertNil(unknownModel.schemaSafetyControls(
            forAssistantMessageID: 102
        ))
        XCTAssertTrue(unknownModel.schemaComposerLockedByCard)
    }

    func testHiddenBindingRequiresItsExactSourcePairInTheLoadedChat() async throws {
        let source = SchemaCardSource(
            userMessageId: 901,
            userMessagePublicId: "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
            assistantMessageId: 902,
            assistantMessagePublicId: "ffffffffffffffffffffffffffffffff",
            quote: ""
        )
        let binding = SchemaChatBinding(
            pathId: 9,
            pathPublicId: "33333333333333333333333333333333",
            stepId: "origin_or_unknown",
            expectedRevision: 12,
            checkpointPublicId: String(repeating: "6", count: 32),
            expectedCheckpointSeq: 12,
            sourceUserMessageId: 901,
            sourceUserMessagePublicId:
                "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
            sourceAssistantMessageId: 902,
            sourceAssistantMessagePublicId:
                "ffffffffffffffffffffffffffffffff"
        )
        let original = activeCard()
        let detached = SchemaCardEnvelope(
            id: original.id,
            kind: original.kind,
            presentation: original.presentation,
            status: original.status,
            stage: original.stage,
            step: original.step,
            pathId: original.pathId,
            pathPublicId: original.pathPublicId,
            revision: original.revision,
            title: original.title,
            contextLine: original.contextLine,
            body: original.body,
            source: source,
            checkpoint: original.checkpoint,
            chatBinding: binding,
            fields: original.fields,
            actions: original.actions,
            progress: original.progress
        )
        let (model, _) = try await openModel(
            snapshot: activeSnapshot(card: detached)
        )

        XCTAssertNil(model.schemaComposerBinding)
        XCTAssertTrue(model.schemaComposerLockedByCard)
        XCTAssertFalse(model.canSend)
        XCTAssertNil(model.schemaChatPromptContinuation(for:
            try XCTUnwrap(model.messages.last)))
    }

    func testTransientRetryReusesIdempotencyKey() async throws {
        let (model, source) = try await openModel(
            snapshot: candidateSnapshot(), failures: [.transient]
        )
        let card = try XCTUnwrap(model.activeSchemaCard)
        let action = try XCTUnwrap(card.actions.first)

        await model.submitSchemaCard(card, action: action, fieldValues: [:])
        XCTAssertEqual(model.schemaFailedCardID, card.id)
        await model.retryFailedSchemaCard()

        let mutations = await source.capturedCardMutations()
        XCTAssertEqual(mutations.count, 2)
        XCTAssertEqual(mutations[0].requestID, mutations[1].requestID)
        XCTAssertNil(model.schemaFailedCardID)
    }

    func testStaleCandidateRefreshesToAuthoritativeActivePrompt() async throws {
        let replacement = activeSnapshot(revision: 13)
        let (model, source) = try await openModel(
            snapshot: candidateSnapshot(),
            failures: [.stale],
            staleReplacement: replacement
        )
        let card = try XCTUnwrap(model.activeSchemaCard)
        let action = try XCTUnwrap(card.actions.first)

        await model.submitSchemaCard(card, action: action, fieldValues: [:])

        XCTAssertEqual(model.activeSchemaCard?.kind, "chat_prompt")
        XCTAssertEqual(model.activeSchemaCard?.revision, 13)
        let mutations = await source.capturedCardMutations()
        XCTAssertEqual(mutations.count, 1)
    }

    func testProcessReopenRestoresProtectedDraftOnlyForExactAuthoritativeBinding() async throws {
        let source = SchemaChatV4DataSource(snapshot: activeSnapshot())
        let store = MemorySchemaChatDraftStore()
        let first = try await openModel(source: source, draftStore: store)
        let firstBinding = try XCTUnwrap(first.schemaComposerBinding)
        first.composerText = "Yarım kalan, yalnız bu cihazda tutulan taslak."
        XCTAssertEqual(
            store.record(conversationID: SchemaChatV4DataSource.conversationID)?
                .bindingFingerprint,
            firstBinding.deviceLocalDraftFingerprint(
                conversationID: SchemaChatV4DataSource.conversationID
            )
        )

        let reopened = try await openModel(source: source, draftStore: store)
        XCTAssertEqual(reopened.schemaComposerBinding, firstBinding)
        XCTAssertEqual(
            reopened.composerText,
            "Yarım kalan, yalnız bu cihazda tutulan taslak."
        )
    }

    func testProcessReopenDiscardsDraftWhenAuthoritativeBindingChanged() async throws {
        let source = SchemaChatV4DataSource(snapshot: activeSnapshot())
        let store = MemorySchemaChatDraftStore()
        let first = try await openModel(source: source, draftStore: store)
        first.composerText = "Artık eski revizyona ait taslak."
        XCTAssertNotNil(store.record(
            conversationID: SchemaChatV4DataSource.conversationID
        ))

        await source.replaceSnapshot(activeSnapshot(revision: 13))
        let reopened = try await openModel(source: source, draftStore: store)

        XCTAssertEqual(reopened.schemaComposerBinding?.expectedRevision, 13)
        XCTAssertTrue(reopened.composerText.isEmpty)
        XCTAssertNil(store.record(
            conversationID: SchemaChatV4DataSource.conversationID
        ))
    }

    func testProcessReopenDiscardsDraftWhenOnlyCheckpointSequenceChanged()
        async throws {
        let store = MemorySchemaChatDraftStore()
        let original = chatStepSnapshot(
            step: "current_impact",
            stage: "listen",
            checkpoint: checkpoint(seq: 4, promptKey: "impact")
        )
        let source = SchemaChatV4DataSource(snapshot: original)
        let first = try await openModel(source: source, draftStore: store)
        first.composerText = "Eski checkpoint'e bağlı yerel taslak."
        XCTAssertNotNil(store.record(
            conversationID: SchemaChatV4DataSource.conversationID
        ))

        await source.replaceSnapshot(chatStepSnapshot(
            step: "current_impact",
            stage: "listen",
            checkpoint: checkpoint(seq: 5, promptKey: "impact-clarify")
        ))
        let reopened = try await openModel(source: source, draftStore: store)

        XCTAssertEqual(reopened.schemaComposerBinding?.expectedRevision, 12)
        XCTAssertEqual(reopened.schemaComposerBinding?.expectedCheckpointSeq, 5)
        XCTAssertTrue(reopened.composerText.isEmpty)
        XCTAssertNil(store.record(
            conversationID: SchemaChatV4DataSource.conversationID
        ))
    }

    func testSameRevisionStreamUsesHigherCheckpointSequenceAndIgnoresOlderGET()
        async throws {
        let older = chatStepSnapshot(
            step: "current_impact",
            stage: "listen",
            checkpoint: checkpoint(seq: 4, promptKey: "impact")
        )
        let newerSource = lineage(userID: 103, assistantID: 104)
        let newer = chatStepSnapshot(
            step: "current_impact",
            stage: "listen",
            checkpoint: checkpoint(seq: 5, promptKey: "impact-clarify"),
            source: newerSource
        )
        let source = SchemaChatV4DataSource(
            snapshot: older,
            postSendSnapshot: older,
            streamNextCardOverride: .some(newer.nextCard)
        )
        let model = try await openModel(source: source)
        model.composerText = "Biraz daha açık anlatıyorum."

        await model.sendComposerMessage()

        XCTAssertEqual(model.activeSchemaCard?.revision, 12)
        XCTAssertEqual(model.activeSchemaCard?.checkpoint?.seq, 5)
        XCTAssertEqual(model.schemaComposerBinding?.expectedCheckpointSeq, 5)
        XCTAssertEqual(model.schemaComposerBinding?.sourceAssistantMessageId, 104)
    }

    func testSameRevisionHigherSequenceKeepsAtomicSSEStepAgainstOlderGET()
        async throws {
        let older = chatStepSnapshot(
            step: "current_impact",
            stage: "listen",
            checkpoint: checkpoint(seq: 4, promptKey: "impact")
        )
        let newer = chatStepSnapshot(
            step: "focus_confirm",
            stage: "listen",
            checkpoint: checkpoint(seq: 5, promptKey: "focus-confirm"),
            source: lineage(userID: 103, assistantID: 104)
        )
        let source = SchemaChatV4DataSource(
            snapshot: older,
            postSendSnapshot: older,
            streamProjectionSnapshot: newer
        )
        let model = try await openModel(source: source)
        model.composerText = "Yükü ve etkisini daha açık anlatıyorum."

        await model.sendComposerMessage()

        XCTAssertEqual(model.activeSchemaCard?.step, "focus_confirm")
        XCTAssertEqual(model.activeSchemaCard?.checkpoint?.seq, 5)
        XCTAssertEqual(model.schemaPathSnapshot?.activePath?.step,
                       "focus_confirm")
        XCTAssertEqual(model.schemaPathSnapshot?.step, "focus_confirm")
        XCTAssertEqual(model.schemaComposerBinding?.stepId, "focus_confirm")
        XCTAssertEqual(model.schemaComposerBinding?.expectedCheckpointSeq, 5)
        XCTAssertFalse(model.schemaComposerLockedByCard)
    }

    func testMethodSelectionAndConfirmationStayInOrdinaryBoundComposer()
        async throws {
        let select = chatStepSnapshot(
            step: "method_select",
            stage: "depth",
            checkpoint: checkpoint(seq: 6, promptKey: "method_select")
        )
        let (selectModel, _) = try await openModel(snapshot: select)
        XCTAssertEqual(selectModel.schemaComposerBinding?.stepId, "method_select")
        XCTAssertFalse(selectModel.schemaComposerLockedByCard)

        let method = "young:method:imagery-rescripting"
        let confirm = chatStepSnapshot(
            step: "method_confirm",
            stage: "depth",
            checkpoint: checkpoint(
                seq: 7, promptKey: "method_confirm", methodID: method
            )
        )
        let (confirmModel, _) = try await openModel(snapshot: confirm)
        XCTAssertEqual(confirmModel.schemaComposerBinding?.stepId, "method_confirm")
        XCTAssertNil(confirmModel.schemaPathSnapshot?.activePath?.methodId)
        XCTAssertNil(confirmModel.schemaPathSnapshot?.activePath?.techniqueRunId)
        XCTAssertTrue(confirmModel.activeSchemaCard?.body.hasPrefix(
            "Bu odağı bugün şu yöntemle çalışalım mı: "
        ) == true)
    }

    func testMethodProposalFailsClosedIfTechniqueExistsBeforeConfirmation()
        async throws {
        let method = "young:method:imagery-rescripting"
        let snapshot = chatStepSnapshot(
            step: "method_confirm",
            stage: "depth",
            checkpoint: checkpoint(
                seq: 7, promptKey: "method_confirm", methodID: method
            ),
            prematureMethodID: method
        )
        let (model, _) = try await openModel(snapshot: snapshot)

        XCTAssertNil(model.schemaComposerBinding)
        XCTAssertTrue(model.schemaComposerLockedByCard)
    }

    func testMethodLineageRejectsSelectedMethodBeforeFocusAndMissingAfterward()
        async throws {
        let method = "young:method:imagery-rescripting"
        let premature = chatStepSnapshot(
            step: "current_impact",
            stage: "listen",
            checkpoint: checkpoint(
                seq: 4, promptKey: "impact", methodID: method
            ),
            prematureMethodID: method
        )
        let (prematureModel, _) = try await openModel(snapshot: premature)
        XCTAssertNil(prematureModel.schemaComposerBinding)
        XCTAssertTrue(prematureModel.schemaComposerLockedByCard)

        let missing = chatStepSnapshot(
            step: "origin_or_unknown",
            stage: "depth",
            checkpoint: checkpoint(seq: 8, promptKey: "origin")
        )
        let (missingModel, _) = try await openModel(snapshot: missing)
        XCTAssertNil(missingModel.schemaComposerBinding)
        XCTAssertTrue(missingModel.schemaComposerLockedByCard)
    }

    func testLiveTechniqueRequiresExactActivePointerRunAndBindingTriple()
        async throws {
        let good = activeSnapshot(includeTechnique: true)
        let originalPath = try XCTUnwrap(good.activePath)
        let malformedPath = SchemaPath(
            id: originalPath.id,
            convId: originalPath.convId,
            therapist: originalPath.therapist,
            claimId: originalPath.claimId,
            phase: originalPath.phase,
            status: originalPath.status,
            methodId: originalPath.methodId,
            method: originalPath.method,
            techniqueRunId: originalPath.techniqueRunId,
            techniqueLinks: originalPath.techniqueLinks,
            activeTechniqueLink: nil,
            revision: originalPath.revision,
            publicId: originalPath.publicId,
            flowVersion: originalPath.flowVersion,
            stage: originalPath.stage,
            step: originalPath.step
        )
        let malformed = snapshot(
            card: good.nextCard,
            revision: good.revision,
            path: malformedPath,
            policy: try XCTUnwrap(good.interactionPolicy)
        )
        let (model, _) = try await openModel(snapshot: malformed)

        XCTAssertNil(model.schemaComposerBinding)
        XCTAssertTrue(model.schemaComposerLockedByCard)
    }

    func testSnapshotAndPathRevisionOrStepDriftLocksHiddenBinding()
        async throws {
        let good = activeSnapshot(revision: 12)
        let (snapshotDrift, _) = try await openModel(snapshot: snapshot(
            card: good.nextCard,
            revision: 13,
            path: good.activePath,
            policy: try XCTUnwrap(good.interactionPolicy)
        ))
        XCTAssertNil(snapshotDrift.schemaComposerBinding)
        XCTAssertTrue(snapshotDrift.schemaComposerLockedByCard)

        let original = try XCTUnwrap(good.activePath)
        let stepDriftPath = SchemaPath(
            id: original.id,
            convId: original.convId,
            therapist: original.therapist,
            claimId: original.claimId,
            phase: original.phase,
            status: original.status,
            methodId: original.methodId,
            method: original.method,
            techniqueRunId: original.techniqueRunId,
            techniqueLinks: original.techniqueLinks,
            activeTechniqueLink: original.activeTechniqueLink,
            revision: original.revision,
            publicId: original.publicId,
            flowVersion: original.flowVersion,
            stage: original.stage,
            step: "environment_rescript"
        )
        let (stepDrift, _) = try await openModel(snapshot: snapshot(
            card: good.nextCard,
            revision: good.revision,
            path: stepDriftPath,
            policy: try XCTUnwrap(good.interactionPolicy)
        ))
        XCTAssertNil(stepDrift.schemaComposerBinding)
        XCTAssertTrue(stepDrift.schemaComposerLockedByCard)
    }

    func testNewerDashboardRevisionWithNoCardClearsOlderStreamedPrompt()
        async throws {
        let initial = activeSnapshot(revision: 12)
        let finished = stoppedSnapshot(revision: 13)
        let source = SchemaChatV4DataSource(
            snapshot: initial,
            postSendSnapshot: finished,
            streamNextCardOverride: .some(activeCard(revision: 12))
        )
        let model = try await openModel(source: source)
        model.composerText = "Bu adımı tamamlıyorum."

        await model.sendComposerMessage()

        XCTAssertNil(model.activeSchemaCard)
        XCTAssertNil(model.schemaComposerBinding)
    }

    func testImportedStageThreeCheckpointHasNoInventedTechniqueOrBacktrack()
        async throws {
        let method = "young:method:imagery-rescripting"
        let imported = chatStepSnapshot(
            step: "age_ladder",
            stage: "integrate",
            checkpoint: checkpoint(
                seq: 0, promptKey: "age_ladder", methodID: method,
                canBacktrack: false
            ),
            prematureMethodID: method
        )
        let (model, _) = try await openModel(snapshot: imported)

        XCTAssertEqual(model.schemaComposerBinding?.expectedCheckpointSeq, 0)
        XCTAssertNil(model.schemaComposerBinding?.techniqueLinkId)
        XCTAssertEqual(model.schemaPathSnapshot?.activePath?.methodId, method)
        XCTAssertNil(model.schemaPathSnapshot?.activePath?.techniqueRunId)

        let forged = chatStepSnapshot(
            step: "age_ladder",
            stage: "integrate",
            checkpoint: checkpoint(
                seq: 0, promptKey: "age_ladder", methodID: method,
                canBacktrack: true
            ),
            prematureMethodID: method
        )
        let (forgedModel, _) = try await openModel(snapshot: forged)
        XCTAssertNil(forgedModel.schemaComposerBinding)
        XCTAssertTrue(forgedModel.schemaComposerLockedByCard)
    }

    func testExactBackPhraseUsesOrdinaryChatWithExactHiddenCheckpoint()
        async throws {
        let (model, source) = try await openModel(snapshot: chatStepSnapshot(
            step: "current_impact",
            stage: "listen",
            checkpoint: checkpoint(seq: 4, promptKey: "impact")
        ))
        model.composerText = "geri dön"

        await model.sendComposerMessage()

        let sentTexts = await source.capturedSentTexts()
        let bindings = await source.capturedBindings()
        XCTAssertEqual(sentTexts, ["geri dön"])
        let binding = try XCTUnwrap(bindings.only ?? nil)
        XCTAssertEqual(binding.checkpointPublicId,
                       "44444444444444444444444444444444")
        XCTAssertEqual(binding.expectedCheckpointSeq, 4)
    }

    func testSuccessfulSendAndSafetyPauseEraseProtectedDraft() async throws {
        let store = MemorySchemaChatDraftStore()
        let source = SchemaChatV4DataSource(snapshot: activeSnapshot())
        let model = try await openModel(source: source, draftStore: store)
        model.composerText = "Gönderilecek taslak."
        XCTAssertNotNil(store.record(
            conversationID: SchemaChatV4DataSource.conversationID
        ))

        await model.sendComposerMessage()
        XCTAssertNil(store.record(
            conversationID: SchemaChatV4DataSource.conversationID
        ))

        await source.replaceSnapshot(activeSnapshot())
        await model.refreshSchemaRecommendations()
        model.composerText = "Duraklatılınca silinecek taslak."
        let card = try XCTUnwrap(model.activeSchemaCard)
        let pause = try XCTUnwrap(card.actions.first { $0.action == "pause" })
        await model.submitSchemaCard(card, action: pause, fieldValues: [:])

        XCTAssertTrue(model.composerText.isEmpty)
        XCTAssertNil(store.record(
            conversationID: SchemaChatV4DataSource.conversationID
        ))
    }

    func testProviderConfigurationChangeErasesProtectedDraft() async throws {
        let store = MemorySchemaChatDraftStore()
        let source = SchemaChatV4DataSource(snapshot: activeSnapshot())
        let model = try await openModel(source: source, draftStore: store)
        model.composerText = "Sağlayıcı değişirse kalmaması gereken taslak."
        XCTAssertNotNil(store.record(
            conversationID: SchemaChatV4DataSource.conversationID
        ))

        model.settingsProvider = .ollama
        model.settingsModel = "başka-yerel-model"
        model.settingsBaseURL = "http://127.0.0.1:11434/v1"
        await model.saveSettings()

        XCTAssertTrue(model.composerText.isEmpty)
        XCTAssertNil(store.record(
            conversationID: SchemaChatV4DataSource.conversationID
        ))
    }

    func testOlderCandidateAcceptsThenReanchorsPromptToLatestSafeKeremPair()
        async throws {
        let olderSource = lineage(
            userID: 101, assistantID: 102, quote: "İlk kanıt"
        )
        let latestSource = lineage(userID: 201, assistantID: 202)
        let messages = [
            DivanMessage(
                id: "older-user", serverID: 101, role: .user,
                content: "İlk kanıt", createdAt: Date(timeIntervalSince1970: 1),
                publicID: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                deliveryStatus: "completed"
            ),
            DivanMessage(
                id: "older-assistant", serverID: 102, role: .assistant,
                content: "İlk değerlendirme", createdAt: Date(timeIntervalSince1970: 2),
                publicID: "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                deliveryStatus: "completed"
            ),
            DivanMessage(
                id: "latest-user", serverID: 201, role: .user,
                content: "Daha yeni güvenli tur", createdAt: Date(timeIntervalSince1970: 3),
                publicID: "cccccccccccccccccccccccccccccccc",
                deliveryStatus: "completed"
            ),
            DivanMessage(
                id: "latest-assistant", serverID: 202, role: .assistant,
                content: "Buradan devam edebiliriz.", createdAt: Date(timeIntervalSince1970: 4),
                publicID: "dddddddddddddddddddddddddddddddd",
                deliveryStatus: "completed"
            ),
        ]
        let source = SchemaChatV4DataSource(
            snapshot: candidateSnapshot(source: olderSource),
            mutationSnapshot: activeSnapshot(source: latestSource),
            conversationMessages: messages
        )
        let model = try await openModel(source: source)
        XCTAssertNotNil(model.schemaCandidatePrompt(forAssistantMessageID: 102))
        XCTAssertNil(model.schemaCandidatePrompt(forAssistantMessageID: 202))
        let candidate = try XCTUnwrap(model.activeSchemaCard)
        let yes = try XCTUnwrap(candidate.actions.first {
            $0.action == "accept_candidate_chat"
        })

        await model.submitSchemaCard(candidate, action: yes, fieldValues: [:])

        XCTAssertEqual(model.activeSchemaCard?.source.assistantMessageId, 202)
        XCTAssertEqual(model.schemaComposerBinding?.sourceAssistantMessageId, 202)
        XCTAssertNil(model.schemaChatPromptContinuation(
            for: try XCTUnwrap(model.messages.first { $0.serverID == 202 })
        ))
        XCTAssertFalse(model.schemaComposerLockedByCard)
    }

    func testProviderReconfirmationKeepsBubbleButExplainsNoClinicalAdvance() async throws {
        let result = SchemaChatBindingResult(
            applied: false,
            progressed: false,
            followupRequired: true,
            missing: ["provider_confirmation"],
            errorCode: "schema_provider_reconfirm",
            pathRevision: 12,
            step: "origin_or_unknown"
        )
        let (model, source) = try await openModel(
            snapshot: activeSnapshot(),
            streamBindingResult: result
        )
        model.composerText = "Bu anıyı anlatmak istiyorum."

        await model.sendComposerMessage()

        let sentTexts = await source.capturedSentTexts()
        XCTAssertEqual(sentTexts, [
            "Bu anıyı anlatmak istiyorum."
        ])
        XCTAssertTrue(model.schemaStatusText.contains("model onayı"))
        XCTAssertTrue(model.messages.contains {
            $0.role == .user && $0.content == "Bu anıyı anlatmak istiyorum."
        })
        XCTAssertEqual(
            model.messages.first {
                $0.role == .user
                    && $0.content == "Bu anıyı anlatmak istiyorum."
            }?.schemaBindingResult?.errorCode,
            "schema_provider_reconfirm"
        )
        XCTAssertNil(
            model.messages.first { $0.role == .assistant && $0.serverID == 104 }?
                .schemaBindingResult
        )
    }

    func testPauseStopAndGroundRemainOnlyDirectDeepControls() async throws {
        for expected in [
            SchemaChatCardAction.pause,
            .stop,
            .groundChatTechnique,
        ] {
            let (model, source) = try await openModel(
                snapshot: activeSnapshot(includeTechnique: true)
            )
            let card = try XCTUnwrap(model.activeSchemaCard)
            let action = try XCTUnwrap(card.actions.first {
                $0.action == expected.rawValue
            })

            await model.submitSchemaCard(card, action: action, fieldValues: [:])

            let mutations = await source.capturedCardMutations()
            XCTAssertEqual(mutations.only?.action, expected)
            XCTAssertEqual(mutations.only?.pathID, 9)
            XCTAssertEqual(
                mutations.only?.pathPublicID,
                "33333333333333333333333333333333"
            )
            XCTAssertNil(mutations.only?.sourceUserMessageID)
            XCTAssertNil(mutations.only?.sourceAssistantMessageID)
            XCTAssertNil(mutations.only?.clientEventID)
            XCTAssertNil(mutations.only?.values["checkpoint_public_id"])
            XCTAssertNil(mutations.only?.values["expected_checkpoint_seq"])
            if expected == .groundChatTechnique {
                XCTAssertEqual(
                    mutations.only?.values,
                    [
                        "technique_link_id": .number(5),
                        "technique_link_public_id":
                            .string("55555555555555555555555555555555"),
                        "control_only": .bool(true),
                    ]
                )
                XCTAssertNil(mutations.only?.values["intensity"])
                XCTAssertNil(mutations.only?.values["orientation_ok"])
                XCTAssertEqual(mutations.only?.stepID, "origin_or_unknown")
            } else {
                XCTAssertNil(mutations.only?.stepID)
            }
        }
    }

    func testPausedPathShowsNoSchemaSpecificControls() async throws {
        let source = SchemaChatV4DataSource(
            snapshot: pausedSnapshot(),
            mutationSnapshot: activeSnapshot(revision: 13)
        )
        let model = try await openModel(source: source)
        XCTAssertNil(model.schemaSafetyControls(forAssistantMessageID: 102))
        XCTAssertNil(model.schemaComposerBinding)
        XCTAssertTrue(model.schemaComposerLockedByCard)
        XCTAssertNil(model.schemaChatPromptContinuation(for:
            try XCTUnwrap(model.messages.last)))
        let mutations = await source.capturedCardMutations()
        XCTAssertTrue(mutations.isEmpty)
    }

    func testPausedRecoveryMetadataNeverCreatesDetachedButtonRow() async throws {
        let detachedSource = SchemaCardSource(
            userMessageId: 901,
            userMessagePublicId: "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
            assistantMessageId: 902,
            assistantMessagePublicId: "ffffffffffffffffffffffffffffffff",
            quote: ""
        )
        let (model, _) = try await openModel(
            snapshot: pausedSnapshot(source: detachedSource)
        )

        XCTAssertNil(model.schemaSafetyControls(forAssistantMessageID: 102))
        XCTAssertNil(model.schemaSafetyControls(forAssistantMessageID: 902))
        XCTAssertTrue(model.schemaComposerLockedByCard)
    }

    func testStopPreemptsLateChatCardProjection() async throws {
        let stopped = stoppedSnapshot(revision: 13)
        let source = SchemaChatV4DataSource(
            snapshot: activeSnapshot(includeTechnique: true),
            streamNextCardOverride: .some(activeCard(revision: 12)),
            streamBindingResult: .init(
                applied: false,
                progressed: false,
                followupRequired: false,
                missing: [],
                errorCode: "schema_safety_pause",
                pathRevision: 13,
                step: "complete"
            ),
            streamDelayNanoseconds: 180_000_000,
            mutationSnapshot: stopped
        )
        let model = try await openModel(source: source)
        model.composerText = "Biraz daha anlatıyorum."
        let send = Task { await model.sendComposerMessage() }
        try await Task.sleep(nanoseconds: 30_000_000)
        XCTAssertTrue(model.isSending)
        let card = try XCTUnwrap(model.activeSchemaCard)
        let stop = try XCTUnwrap(card.actions.first { $0.action == "stop" })

        await model.submitSchemaCard(card, action: stop, fieldValues: [:])
        await send.value

        XCTAssertNil(model.activeSchemaCard)
        let mutations = await source.capturedCardMutations()
        XCTAssertEqual(mutations.last?.action, .stop)
    }

    func testLateOldPathSSECannotReplaceNewDurablePath() async throws {
        let pathA = activeSnapshot(revision: 12)
        let source = SchemaChatV4DataSource(
            snapshot: pathA,
            streamProjectionSnapshot: pathA,
            streamDelayNanoseconds: 180_000_000
        )
        let model = try await openModel(source: source)
        model.composerText = "A yolundaki yanıt gecikiyor."
        let send = Task { await model.sendComposerMessage() }
        try await Task.sleep(nanoseconds: 30_000_000)
        XCTAssertTrue(model.isSending)

        let pathB = pathIdentitySnapshot(
            pathID: 10,
            pathPublicID: "88888888888888888888888888888888",
            revision: 1,
            source: lineage(userID: 103, assistantID: 104)
        )
        await source.replaceSnapshot(pathB)
        await model.refreshSchemaRecommendations()
        XCTAssertEqual(model.schemaPathSnapshot?.activePath?.id, 10)
        await source.setFailSchemaReadsAfterSend(true)

        await send.value

        XCTAssertEqual(model.schemaPathSnapshot?.activePath?.id, 10)
        XCTAssertEqual(
            model.schemaPathSnapshot?.activePath?.publicId,
            "88888888888888888888888888888888"
        )
        XCTAssertEqual(model.activeSchemaCard?.pathId, 10)
        XCTAssertEqual(model.schemaComposerBinding?.pathId, 10)
        XCTAssertEqual(model.schemaComposerBinding?.sourceAssistantMessageId,
                       104)
    }

    func testLateOrdinarySSECannotReplaceNewDurablePath() async throws {
        let ordinary = ordinarySnapshot()
        let source = SchemaChatV4DataSource(
            snapshot: ordinary,
            streamProjectionSnapshot: ordinary,
            streamNextCardOverride: .some(nil),
            streamBindingResult: nil,
            streamDelayNanoseconds: 180_000_000
        )
        let model = try await openModel(source: source)
        model.composerText = "Sıradan sohbet yanıtı gecikiyor."
        XCTAssertFalse(model.schemaComposerLockedByCard)
        XCTAssertTrue(model.canSend)
        let pathB = pathIdentitySnapshot(
            pathID: 10,
            pathPublicID: "88888888888888888888888888888888",
            revision: 1,
            source: lineage(userID: 103, assistantID: 104)
        )
        let publishNewPath = Task.detached {
            try await Task.sleep(nanoseconds: 30_000_000)
            await source.replaceSnapshot(pathB)
            await model.refreshSchemaRecommendations()
            let installedPathID = await model.schemaPathSnapshot?.activePath?.id
            await source.setFailSchemaReadsAfterSend(true)
            return installedPathID
        }

        await model.sendComposerMessage()
        let installedPathID = try await publishNewPath.value

        XCTAssertEqual(installedPathID, 10)
        XCTAssertEqual(model.schemaPathSnapshot?.activePath?.id, 10)
        XCTAssertEqual(model.activeSchemaCard?.pathId, 10)
        XCTAssertEqual(model.schemaComposerBinding?.pathId, 10)
    }

    func testOnlyTechniqueAndLivingMapMetaRemainUnderBubbles() async throws {
        let events = [
            meta(kind: "candidate", id: 1),
            meta(kind: "progress", id: 2),
            meta(kind: "technique", id: 3),
            meta(kind: "map_update", id: 4),
        ]
        let (model, _) = try await openModel(
            snapshot: activeSnapshot(messageMeta: events)
        )
        let message = try XCTUnwrap(model.messages.first { $0.serverID == 102 })
        XCTAssertEqual(
            Set(model.schemaMetaEvents(for: message).map(\.kind)),
            Set(["technique", "map_update"])
        )
    }

    func testLegacyBindingResultDecodesWithoutInventingProgress() throws {
        let value = try JSONDecoder().decode(
            SchemaChatBindingResult.self,
            from: Data(#"{"applied":true,"action":"record_origin","path_id":9,"revision":7,"stage":"depth","step":"origin_or_unknown"}"#.utf8)
        )
        XCTAssertTrue(value.applied)
        XCTAssertFalse(value.progressed)
        XCTAssertFalse(value.followupRequired)
        XCTAssertTrue(value.missing.isEmpty)
        XCTAssertEqual(value.pathRevision, 7)
    }

    func testStrictChatControlsAndProtocolFailuresLockTheComposer()
        async throws {
        let base = activeCard()
        let pauseOnly = replacingActions(
            base,
            with: [try XCTUnwrap(base.actions.first {
                $0.action == "pause"
            })]
        )
        let (missingStop, _) = try await openModel(
            snapshot: activeSnapshot(card: pauseOnly)
        )
        XCTAssertNil(missingStop.schemaComposerBinding)
        XCTAssertNil(missingStop.schemaChatPromptContinuation(
            for: try XCTUnwrap(missingStop.messages.last)
        ))
        XCTAssertTrue(missingStop.schemaComposerLockedByCard)

        let (futureVersion, _) = try await openModel(
            snapshot: activeSnapshot(version: 5)
        )
        XCTAssertFalse(futureVersion.usesSchemaChatProtocolV4)
        XCTAssertNil(futureVersion.schemaComposerBinding)
        XCTAssertTrue(futureVersion.schemaComposerLockedByCard)

        let (wrongStage, _) = try await openModel(
            snapshot: activeSnapshot(stage: "listen")
        )
        XCTAssertNil(wrongStage.schemaComposerBinding)
        XCTAssertNil(wrongStage.schemaChatPromptContinuation(
            for: try XCTUnwrap(wrongStage.messages.last)
        ))
        XCTAssertTrue(wrongStage.schemaComposerLockedByCard)
    }

    func testGroundingReviewKeepsBoundComposerWithoutDuplicateGroundControl()
        async throws {
        let snapshot = activeSnapshot(
            includeTechnique: true,
            includeGroundControl: false,
            step: "grounding_review"
        )
        let (model, _) = try await openModel(snapshot: snapshot)

        XCTAssertEqual(
            model.activeSchemaCard?.actions.map(\.action),
            ["pause", "stop"]
        )
        XCTAssertNotNil(model.schemaComposerBinding)
        XCTAssertFalse(model.schemaComposerLockedByCard)
    }

    func testRecoveryMetadataNeverCreatesPauseOrStopButtonRows()
        async throws {
        let pause = SchemaCardActionEnvelope(
            id: "schema-pause", action: "pause", label: "Duraklat",
            style: "secondary", requiresConfirm: false
        )
        let stop = SchemaCardActionEnvelope(
            id: "schema-stop", action: "stop", label: "Çalışmayı bitir",
            style: "danger", requiresConfirm: true
        )
        let activeRecovery = recoverySnapshot(
            kind: "resume",
            pathStatus: "active",
            checkpointStatus: "active",
            actions: [pause, stop]
        )
        let (activeModel, activeSource) = try await openModel(
            snapshot: activeRecovery
        )
        XCTAssertNil(activeModel.schemaSafetyControls(
            forAssistantMessageID: 102
        ))
        let activeMutations = await activeSource.capturedCardMutations()
        XCTAssertTrue(activeMutations.isEmpty)

        let pausedConflict = recoverySnapshot(
            kind: "blocked",
            pathStatus: "paused",
            checkpointStatus: "paused",
            actions: [pause, stop]
        )
        let (pausedModel, pausedSource) = try await openModel(
            snapshot: pausedConflict
        )
        XCTAssertNil(pausedModel.schemaSafetyControls(
            forAssistantMessageID: 102
        ))
        let pausedMutations = await pausedSource.capturedCardMutations()
        XCTAssertTrue(pausedMutations.isEmpty)
    }

    func testSSEAppliesAtomicPathPolicyAndCheckpointWhenGETFails()
        async throws {
        let newer = activeSnapshot(
            revision: 13,
            source: lineage(userID: 103, assistantID: 104)
        )
        let source = SchemaChatV4DataSource(
            snapshot: activeSnapshot(),
            postSendSnapshot: newer,
            failSchemaReadsAfterSend: true,
            streamBindingResult: .init(
                applied: true,
                progressed: true,
                followupRequired: true,
                missing: [],
                pathId: 9,
                pathRevision: 13,
                stage: "depth",
                step: "origin_or_unknown",
                checkpointPublicId: String(repeating: "7", count: 32),
                checkpointSeq: 13,
                backtracked: false
            )
        )
        let model = try await openModel(source: source)
        model.composerText = "Yeni checkpoint'e ilerliyorum."

        await model.sendComposerMessage()

        XCTAssertEqual(model.schemaPathSnapshot?.activePath?.revision, 13)
        XCTAssertEqual(model.schemaPathSnapshot?.interactionPolicy?.composerMode,
                       .bound)
        XCTAssertEqual(model.schemaComposerBinding?.expectedRevision, 13)
        XCTAssertEqual(model.schemaComposerBinding?.expectedCheckpointSeq, 13)
    }

    func testStreamOrderingIsScopedToPathAndCheckpointIdentity()
        async throws {
        let pathA = pathIdentitySnapshot(
            pathID: 9,
            pathPublicID: "33333333333333333333333333333333",
            revision: 12,
            source: sourceLineage
        )
        let source = SchemaChatV4DataSource(snapshot: pathA)
        let model = try await openModel(source: source)
        model.composerText = "A yolundaki son yanıt."
        await model.sendComposerMessage()

        let pathB = pathIdentitySnapshot(
            pathID: 10,
            pathPublicID: "88888888888888888888888888888888",
            revision: 1,
            source: lineage(userID: 103, assistantID: 104)
        )
        await source.replaceSnapshot(pathB)
        await model.refreshSchemaRecommendations()
        XCTAssertEqual(
            model.activeSchemaCard?.pathPublicId,
            "88888888888888888888888888888888"
        )
        XCTAssertEqual(model.schemaComposerBinding?.pathId, 10)

        let durable = chatStepSnapshot(
            step: "current_impact",
            stage: "listen",
            checkpoint: checkpoint(seq: 4, promptKey: "impact")
        )
        let conflictingCheckpoint = SchemaPathCheckpoint(
            publicId: String(repeating: "5", count: 32),
            seq: 4,
            promptKey: "impact-clarification",
            status: "active",
            canBacktrack: true,
            backtrackPending: false
        )
        let conflictSource = SchemaChatV4DataSource(
            snapshot: durable,
            streamNextCardOverride: .some(replacingCheckpoint(
                try XCTUnwrap(durable.nextCard),
                with: conflictingCheckpoint
            ))
        )
        let conflictModel = try await openModel(source: conflictSource)
        conflictModel.composerText = "Aynı sıra numarası çakışıyor."
        await conflictModel.sendComposerMessage()
        XCTAssertNil(conflictModel.activeSchemaCard)
        XCTAssertNil(conflictModel.schemaComposerBinding)
        XCTAssertTrue(conflictModel.schemaComposerLockedByCard)
    }

    func testStreamedNullYieldsToGenuinelyNewPathIdentity() async throws {
        let source = SchemaChatV4DataSource(
            snapshot: activeSnapshot(),
            postSendSnapshot: stoppedSnapshot(revision: 13),
            streamNextCardOverride: .some(nil),
            streamBindingResult: .init(
                applied: true,
                progressed: true,
                followupRequired: false,
                missing: [],
                pathId: 9,
                pathRevision: 13,
                stage: "complete",
                step: "complete",
                checkpointPublicId: String(repeating: "7", count: 32),
                checkpointSeq: 13,
                backtracked: false
            )
        )
        let model = try await openModel(source: source)
        model.composerText = "Bu yolu kapatıyorum."
        await model.sendComposerMessage()
        XCTAssertNil(model.activeSchemaCard)

        await source.replaceSnapshot(pathIdentitySnapshot(
            pathID: 10,
            pathPublicID: "88888888888888888888888888888888",
            revision: 1,
            source: lineage(userID: 103, assistantID: 104)
        ))
        await model.refreshSchemaRecommendations()
        XCTAssertEqual(model.activeSchemaCard?.pathId, 10)
        XCTAssertEqual(model.schemaComposerBinding?.pathId, 10)
    }

    func testPathlessCandidateAppearsAfterOrdinaryChatNullCatchesUp()
        async throws {
        let source = SchemaChatV4DataSource(
            snapshot: ordinarySnapshot(),
            streamNextCardOverride: .some(nil),
            streamBindingResult: nil
        )
        let model = try await openModel(source: source)
        model.composerText = "Bugün olanı biraz daha anlatıyorum."

        await model.sendComposerMessage()
        XCTAssertNil(model.activeSchemaCard)

        await source.replaceSnapshot(candidateSnapshot())
        await model.refreshSchemaRecommendations()

        XCTAssertEqual(model.activeSchemaCard?.kind, "candidate_prompt")
        XCTAssertNotNil(model.schemaCandidatePrompt(forAssistantMessageID: 102))
    }

    func testCurrentPairCandidateSupersedesPathlessNullWithoutNilGET()
        async throws {
        let currentSource = lineage(
            userID: 103,
            assistantID: 104,
            quote: "Bu yeni durumda kendimi yine aynı yerde buldum."
        )
        let source = SchemaChatV4DataSource(
            snapshot: ordinarySnapshot(),
            postSendSnapshot: candidateSnapshot(source: currentSource),
            streamNextCardOverride: .some(nil),
            streamBindingResult: nil
        )
        let model = try await openModel(source: source)
        model.composerText = "Bu yeni durumda kendimi yine aynı yerde buldum."

        await model.sendComposerMessage()

        XCTAssertEqual(model.activeSchemaCard?.kind, "candidate_prompt")
        XCTAssertEqual(model.activeSchemaCard?.source.assistantMessageId, 104)
        XCTAssertNotNil(model.schemaCandidatePrompt(forAssistantMessageID: 104))
    }

    func testStreamedNullSuppressesLaggingCardUntilMatchingDurableNil()
        async throws {
        let lagging = activeSnapshot(revision: 12)
        let source = SchemaChatV4DataSource(
            snapshot: lagging,
            postSendSnapshot: lagging,
            streamNextCardOverride: .some(nil),
            streamBindingResult: .init(
                applied: true,
                progressed: true,
                followupRequired: false,
                missing: [],
                pathId: 9,
                pathRevision: 13,
                stage: "complete",
                step: "complete",
                checkpointPublicId: String(repeating: "7", count: 32),
                checkpointSeq: 13,
                backtracked: false
            )
        )
        let model = try await openModel(source: source)
        model.composerText = "Bu adımı bitiriyorum."

        await model.sendComposerMessage()
        XCTAssertNil(model.activeSchemaCard)

        await source.replaceSnapshot(stoppedSnapshot(revision: 13))
        await model.refreshSchemaRecommendations()
        XCTAssertNil(model.activeSchemaCard)

        await source.replaceSnapshot(candidateSnapshot())
        await model.refreshSchemaRecommendations()
        XCTAssertEqual(model.activeSchemaCard?.kind, "candidate_prompt")
    }

    func testNullCursorConflictingCheckpointIdentityFailsClosed()
        async throws {
        let initial = activeSnapshot(revision: 12)
        let conflictingCheckpoint = SchemaPathCheckpoint(
            publicId: String(repeating: "5", count: 32),
            seq: 12,
            promptKey: "origin-conflict",
            methodId: "young:method:imagery-rescripting",
            status: "active",
            canBacktrack: true,
            backtrackPending: false
        )
        let conflicting = activeSnapshot(card: replacingCheckpoint(
            try XCTUnwrap(initial.nextCard),
            with: conflictingCheckpoint
        ))
        let source = SchemaChatV4DataSource(
            snapshot: initial,
            postSendSnapshot: conflicting,
            streamNextCardOverride: .some(nil),
            streamBindingResult: .init(
                applied: true,
                progressed: true,
                followupRequired: false,
                missing: [],
                pathId: 9,
                pathRevision: 12,
                stage: "depth",
                step: "origin_or_unknown",
                checkpointPublicId: String(repeating: "6", count: 32),
                checkpointSeq: 12,
                backtracked: false
            )
        )
        let model = try await openModel(source: source)
        model.composerText = "Bu adımı tamamlıyorum."

        await model.sendComposerMessage()

        XCTAssertNil(model.activeSchemaCard)
        XCTAssertNil(model.schemaComposerBinding)
        XCTAssertTrue(model.schemaComposerLockedByCard)
    }

    func testChatOnlySourceKeepsA11yAndRemovesWorkspaceEntry() throws {
        let root = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let conversation = try String(
            contentsOf: root.appendingPathComponent(
                "Sources/DivanNative/UI/Views/ConversationViews.swift"
            ),
            encoding: .utf8
        )
        let draftStore = try String(
            contentsOf: root.appendingPathComponent(
                "Sources/DivanNative/Core/SchemaChatDraftStore.swift"
            ),
            encoding: .utf8
        )
        let app = try String(
            contentsOf: root.appendingPathComponent(
                "Sources/DivanNative/App/DivanNativePreviewApp.swift"
            ),
            encoding: .utf8
        )
        let viewModel = try String(
            contentsOf: root.appendingPathComponent(
                "Sources/DivanNative/UI/ViewModels/DivanViewModel.swift"
            ),
            encoding: .utf8
        )
        XCTAssertTrue(conversation.contains(
            "divan.chat.schemaCandidatePrompt"
        ))
        XCTAssertTrue(conversation.contains(
            "Üzerinde çalışabileceğimiz konu: "
        ))
        XCTAssertTrue(conversation.contains("Olası örüntü: "))
        XCTAssertTrue(conversation.contains(
            "card.source.candidateQuoteForDisplay"
        ))
        XCTAssertTrue(conversation.contains(
            "card.candidatePatternForDisplay"
        ))
        XCTAssertFalse(conversation.contains(
            "Text(context + \" \" + card.body)"
        ))
        XCTAssertFalse(conversation.contains(
            "divan.chat.schemaSafetyControls"
        ))
        XCTAssertFalse(conversation.contains(
            "divan.chat.schemaPromptContinuation"
        ))
        XCTAssertTrue(conversation.contains("ViewThatFits(in: .horizontal)"))
        XCTAssertEqual(
            conversation.components(
                separatedBy: ".frame(minWidth: 44, minHeight: 44)"
            ).count - 1,
            1,
            "Yalnız aday Evet/Hayır satırı 44×44 hedefi korumalı."
        )
        XCTAssertGreaterThanOrEqual(
            conversation.components(
                separatedBy: ".contentShape(Rectangle())"
            ).count - 1,
            1
        )
        XCTAssertFalse(conversation.contains(
            "model.openAdvancedModule(.schemaPath)"
        ))
        XCTAssertFalse(conversation.contains("NativeSchemaInlineCard"))
        XCTAssertFalse(conversation.contains("schemaV4StatusSurface"))
        XCTAssertFalse(conversation.contains("schemaComposerDraft"))
        XCTAssertTrue(conversation.contains(
            "message.schemaBindingResult?.failureMessage"
        ))
        XCTAssertFalse(conversation.contains(
            "message.role == .assistant,\n                   let bindingMessage"
        ))
        XCTAssertGreaterThanOrEqual(
            viewModel.components(
                separatedBy: "schemaDurableProjectionDecision("
            ).count - 1,
            3,
            "SSE checkpoint sırası hem normal yenilemede hem analiz anketinde korunmalı."
        )
        XCTAssertTrue(draftStore.contains(
            "kSecAttrAccessibleWhenUnlockedThisDeviceOnly"
        ))
        XCTAssertTrue(draftStore.contains(
            "kSecAttrSynchronizable as String: false"
        ))
        XCTAssertFalse(draftStore.contains("UserDefaults"))
        XCTAssertTrue(app.contains(
            "schemaChatDraftStore: KeychainSchemaChatDraftStore()"
        ))
        XCTAssertFalse(
            FileManager.default.fileExists(atPath: root.appendingPathComponent(
                "Sources/DivanNative/UI/Advanced/Views/SchemaPathWorkspaceView.swift"
            ).path)
        )
        let sourceRoot = root.appendingPathComponent("Sources/DivanNative")
        let sourceFiles = try XCTUnwrap(
            FileManager.default.enumerator(
                at: sourceRoot,
                includingPropertiesForKeys: nil
            )
        ).compactMap { $0 as? URL }.filter { $0.pathExtension == "swift" }
        let allSource = try sourceFiles.map {
            try String(contentsOf: $0, encoding: .utf8)
        }.joined(separator: "\n")
        XCTAssertFalse(allSource.contains(
            "Önceki görüşmede yarım kalan bir düzeltme var"
        ))
    }

    // MARK: Fixtures

    private func openModel(
        snapshot: SchemaPathSnapshot,
        failures: [SchemaChatV4FakeFailure] = [],
        staleReplacement: SchemaPathSnapshot? = nil,
        streamBindingResult: SchemaChatBindingResult? = .init(
            applied: true,
            progressed: true,
            followupRequired: true,
            missing: [],
            pathRevision: 12,
            step: "origin_or_unknown"
        )
    ) async throws -> (DivanViewModel, SchemaChatV4DataSource) {
        let source = SchemaChatV4DataSource(
            snapshot: snapshot,
            failures: failures,
            staleReplacement: staleReplacement,
            streamBindingResult: streamBindingResult
        )
        return (try await openModel(source: source), source)
    }

    private func openModel(
        source: SchemaChatV4DataSource,
        draftStore: (any SchemaChatDraftStore)? = nil
    ) async throws -> DivanViewModel {
        let model = DivanViewModel(
            dataSource: source,
            displayPreferencesStore: MemorySchemaDisplayPreferencesStore(),
            schemaChatDraftStore: draftStore
        )
        await model.bootstrap()
        await model.openConversation(try XCTUnwrap(
            model.activeConversations.first
        ))
        await model.refreshSchemaRecommendations()
        return model
    }

    private func candidateMessages(userContent: String) -> [DivanMessage] {
        [
            DivanMessage(
                id: "schema-source-user", serverID: 101, role: .user,
                content: userContent,
                createdAt: Date(timeIntervalSince1970: 1_787_334_340),
                publicID: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                deliveryStatus: "completed"
            ),
            DivanMessage(
                id: "schema-source-assistant", serverID: 102,
                role: .assistant, content: "Bunu birlikte sınayabiliriz.",
                createdAt: Date(timeIntervalSince1970: 1_787_334_400),
                publicID: "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                deliveryStatus: "completed"
            ),
        ]
    }

    private func candidateSnapshot(
        source: SchemaCardSource? = nil,
        contextLine: String =
            "Kusurluluk / İncinmiş Çocuk tetiklenmiş olabilir."
    ) -> SchemaPathSnapshot {
        let source = source ?? sourceLineage
        func action(
            id: String,
            action: String,
            label: String
        ) -> SchemaCardActionEnvelope {
            .init(
                id: id,
                action: action,
                label: label,
                style: action == "accept_candidate_chat"
                    ? "primary" : "secondary",
                requiresConfirm: false,
                payload: [
                    "claim_id": .number(44),
                    "candidate_public_id":
                        .string("11111111111111111111111111111111"),
                    "source_user_message_id":
                        .number(Double(source.userMessageId ?? 0)),
                    "source_user_message_public_id":
                        .string(source.userMessagePublicId ?? ""),
                    "source_assistant_message_id":
                        .number(Double(source.assistantMessageId ?? 0)),
                    "source_assistant_message_public_id":
                        .string(source.assistantMessagePublicId ?? ""),
                ]
            )
        }
        let card = SchemaCardEnvelope(
            id: "schema-candidate-public-44",
            kind: "candidate_prompt",
            presentation: "chat_only",
            status: "active",
            stage: "listen",
            step: "candidate_review",
            revision: nil,
            title: "",
            contextLine: contextLine,
            body: "Bunu çalışmak ister misin?",
            source: source,
            fields: [],
            actions: [
                action(
                    id: "candidate-yes",
                    action: "accept_candidate_chat",
                    label: "Evet"
                ),
                action(
                    id: "candidate-no",
                    action: "reject_candidate_chat",
                    label: "Hayır"
                ),
            ],
            progress: progress(stage: 1, step: 1, label: "Dinleme")
        )
        return snapshot(
            card: card,
            revision: nil,
            path: nil,
            policy: .init(
                requiresInApp: true,
                remoteReplyAllowed: false,
                composerBindingRequired: false,
                composerAllowed: false,
                composerMode: .disabled,
                composerSurface: "ordinary_chat",
                boundStepId: nil,
                reason: "focus_decision"
            )
        )
    }

    private func v5CandidateSnapshot() -> SchemaPathSnapshot {
        let current = candidateSnapshot()
        return SchemaPathSnapshot(
            version: 5,
            protocol: "schema_path_chat_v5",
            presentation: "chat_only",
            stage: current.stage,
            step: current.step,
            revision: nil,
            nextCard: current.nextCard,
            messageMeta: [],
            interactionPolicy: current.interactionPolicy,
            resumeState: current.resumeState,
            clinicalSync: current.clinicalSync,
            activePath: nil,
            candidates: [],
            methods: [],
            notices: [],
            allowedActions: current.allowedActions,
            completedTurns: 5,
            minimumListeningTurns: 1
        )
    }

    private func v5Snapshot(
        deliveryStatus: String = "completed",
        bindingPromptRequestID: String = "schema-v5-prompt-0001"
    ) -> SchemaPathSnapshot {
        let requestID = "schema-v5-prompt-0001"
        let completed = deliveryStatus == "completed"
        let delivery = SchemaPromptDelivery(
            requestId: deliveryStatus == "missing" ? nil : requestID,
            status: deliveryStatus,
            promptAssistantMessageId: completed ? 102 : nil,
            promptAssistantMessagePublicId: completed
                ? "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb" : nil,
            errorCode: deliveryStatus == "missing"
                ? "schema_prompt_missing"
                : ["failed", "interrupted", "cancelled"].contains(
                    deliveryStatus
                ) ? "schema_prompt_failed" : nil
        )
        let checkpoint = SchemaPathCheckpoint(
            publicId: "99999999999999999999999999999999",
            seq: 1,
            promptKey: "variable_scenario",
            methodId: "young:method:imagery-rescripting",
            status: "active",
            canBacktrack: false,
            backtrackPending: false
        )
        let source = completed ? sourceLineage : SchemaCardSource()
        let binding = completed ? SchemaChatBinding(
            protocol: "schema_path_chat_v5",
            pathId: 9,
            pathPublicId: "33333333333333333333333333333333",
            stepId: "variable_explore",
            expectedRevision: 2,
            checkpointPublicId: checkpoint.publicId,
            expectedCheckpointSeq: checkpoint.seq,
            promptRequestId: bindingPromptRequestID,
            promptAssistantMessageId: 102,
            promptAssistantMessagePublicId:
                "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            sourceUserMessageId: 101,
            sourceUserMessagePublicId:
                "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            sourceAssistantMessageId: 102,
            sourceAssistantMessagePublicId:
                "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        ) : nil
        let card = SchemaCardEnvelope(
            id: "schema-chat-v5-33333333333333333333333333333333-r2",
            kind: "chat_state",
            presentation: "chat_only",
            status: "active",
            stage: "explore",
            step: "variable_explore",
            pathId: 9,
            pathPublicId: "33333333333333333333333333333333",
            revision: 2,
            title: "",
            contextLine: "",
            body: "",
            source: source,
            checkpoint: checkpoint,
            promptDelivery: delivery,
            chatBinding: binding,
            fields: [],
            actions: [],
            progress: nil
        )
        let path = SchemaPath(
            id: 9,
            convId: SchemaChatV4DataSource.conversationID,
            therapist: "young",
            claimId: 44,
            phase: "explore",
            status: "active",
            methodId: "young:method:imagery-rescripting",
            method: SchemaSelectedMethod(
                methodId: "young:method:imagery-rescripting",
                nodeId: "young:method:imagery-rescripting",
                name: "İmgeleme ile yeniden senaryolama",
                requiresPrecheck: false
            ),
            revision: 2,
            publicId: "33333333333333333333333333333333",
            flowVersion: 5,
            stage: "explore",
            step: "variable_explore"
        )
        let ready = completed
        return SchemaPathSnapshot(
            version: 5,
            protocol: "schema_path_chat_v5",
            presentation: "chat_only",
            stage: "explore",
            step: "variable_explore",
            revision: 2,
            nextCard: card,
            messageMeta: [],
            interactionPolicy: .init(
                requiresInApp: true,
                remoteReplyAllowed: false,
                composerBindingRequired: ready,
                composerAllowed: ready,
                composerMode: ready ? .bound : .disabled,
                composerSurface: "ordinary_chat",
                boundStepId: ready ? "variable_explore" : "",
                inlineControlsOnly: false,
                reason: ready
                    ? "bound_schema_step"
                    : "prompt_delivery_\(deliveryStatus)"
            ),
            resumeState: .init(required: false, reason: "none"),
            activePath: path,
            candidates: [],
            methods: [],
            notices: [],
            allowedActions: [],
            completedTurns: 5,
            minimumListeningTurns: 1
        )
    }

    private func v5ImportedWaitingSnapshot(
        checkpointSeq: Int = 1,
        pauseReason: String = "sync_import_resume_required",
        syncImportControl: Bool? = true,
        bindingPromptRequestID: String? = nil
    ) -> SchemaPathSnapshot {
        let checkpoint = SchemaPathCheckpoint(
            publicId: "99999999999999999999999999999999",
            seq: checkpointSeq,
            promptKey: "scenario",
            status: "paused",
            canBacktrack: false,
            backtrackPending: false
        )
        let binding = SchemaChatBinding(
            protocol: "schema_path_chat_v5",
            syncImportControl: syncImportControl,
            pathId: 9,
            pathPublicId: "33333333333333333333333333333333",
            stepId: "variable_explore",
            expectedRevision: 7,
            checkpointPublicId: checkpoint.publicId,
            expectedCheckpointSeq: checkpoint.seq,
            promptRequestId: bindingPromptRequestID,
            promptAssistantMessageId: nil,
            promptAssistantMessagePublicId: nil,
            sourceUserMessageId: 101,
            sourceUserMessagePublicId:
                "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            sourceAssistantMessageId: 102,
            sourceAssistantMessagePublicId:
                "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        )
        let card = SchemaCardEnvelope(
            id: "schema-chat-v5-33333333333333333333333333333333-r7",
            kind: "chat_state",
            presentation: "chat_only",
            status: "paused",
            stage: "explore",
            step: "variable_explore",
            pathId: 9,
            pathPublicId: "33333333333333333333333333333333",
            revision: 7,
            title: "",
            contextLine: "",
            body: "",
            source: sourceLineage,
            checkpoint: checkpoint,
            promptDelivery: .init(
                requestId: nil,
                status: "imported_waiting",
                promptAssistantMessageId: nil,
                promptAssistantMessagePublicId: nil,
                errorCode: nil
            ),
            chatBinding: binding,
            fields: [],
            actions: [],
            progress: nil
        )
        let path = SchemaPath(
            id: 9,
            convId: SchemaChatV4DataSource.conversationID,
            therapist: "young",
            claimId: 44,
            phase: "explore",
            status: "paused",
            revision: 7,
            publicId: "33333333333333333333333333333333",
            flowVersion: 5,
            stage: "explore",
            step: "variable_explore",
            pauseReason: pauseReason,
            resumeRequired: true
        )
        return SchemaPathSnapshot(
            version: 5,
            protocol: "schema_path_chat_v5",
            presentation: "chat_only",
            stage: "explore",
            step: "variable_explore",
            revision: 7,
            nextCard: card,
            messageMeta: [],
            interactionPolicy: .init(
                requiresInApp: true,
                remoteReplyAllowed: false,
                composerBindingRequired: true,
                composerAllowed: true,
                composerMode: .bound,
                composerSurface: "ordinary_chat",
                boundStepId: "variable_explore",
                inlineControlsOnly: false,
                reason: "prompt_delivery_imported_waiting"
            ),
            resumeState: .init(
                required: true,
                reason: pauseReason,
                stage: "explore",
                step: "variable_explore",
                cardId: card.id
            ),
            activePath: path,
            candidates: [],
            methods: [],
            notices: [],
            allowedActions: [],
            completedTurns: 5,
            minimumListeningTurns: 1
        )
    }

    private func ordinarySnapshot() -> SchemaPathSnapshot {
        snapshot(
            card: nil,
            revision: nil,
            path: nil,
            policy: .init(
                requiresInApp: false,
                remoteReplyAllowed: true,
                composerBindingRequired: false,
                composerAllowed: true,
                composerMode: .ordinary,
                composerSurface: "ordinary_chat",
                boundStepId: nil,
                reason: "ordinary_chat"
            )
        )
    }

    private func activeSnapshot(
        card: SchemaCardEnvelope? = nil,
        revision: Int = 12,
        version: Int = 4,
        includeTechnique: Bool = false,
        includeGroundControl: Bool? = nil,
        step: String = "origin_or_unknown",
        stage: String = "depth",
        messageMeta: [SchemaMessageMetaEvent] = [],
        source: SchemaCardSource? = nil
    ) -> SchemaPathSnapshot {
        let technique = includeTechnique ? SchemaTechniqueLink(
            id: 5,
            publicId: "55555555555555555555555555555555",
            step: step,
            methodId: "young:method:imagery-rescripting",
            techniqueRunId: 7,
            techniqueRevision: 3,
            status: "active",
            protocol: "imagery_rescripting_v2",
            currentStage: "work",
            requiresPrecheck: false
        ) : nil
        let path = SchemaPath(
            id: 9,
            convId: SchemaChatV4DataSource.conversationID,
            therapist: "young",
            claimId: 44,
            phase: "work",
            status: "active",
            methodId: "young:method:imagery-rescripting",
            method: SchemaSelectedMethod(
                methodId: "young:method:imagery-rescripting",
                nodeId: "young:method:imagery-rescripting",
                name: "İmgeleme ile yeniden senaryolama",
                requiresPrecheck: true
            ),
            techniqueRunId: includeTechnique ? 7 : nil,
            techniqueLinks: technique.map { [$0] },
            activeTechniqueLink: technique,
            revision: revision,
            publicId: "33333333333333333333333333333333",
            flowVersion: 4,
            stage: stage,
            step: step
        )
        return snapshot(
            card: card ?? activeCard(
                revision: revision,
                includeTechnique: includeTechnique,
                includeGroundControl: includeGroundControl,
                step: step,
                stage: stage,
                source: source
            ),
            revision: revision,
            version: version,
            path: path,
            policy: .init(
                requiresInApp: true,
                remoteReplyAllowed: false,
                composerBindingRequired: true,
                composerAllowed: true,
                composerMode: .bound,
                composerSurface: "ordinary_chat",
                boundStepId: step,
                reason: "bound_schema_step"
            ),
            messageMeta: messageMeta
        )
    }

    private func checkpoint(
        seq: Int,
        promptKey: String,
        methodID: String? = nil,
        canBacktrack: Bool = true
    ) -> SchemaPathCheckpoint {
        SchemaPathCheckpoint(
            publicId: String(repeating: String(seq % 10), count: 32),
            seq: seq,
            promptKey: promptKey,
            methodId: methodID,
            status: "active",
            canBacktrack: canBacktrack,
            backtrackPending: false
        )
    }

    private func chatStepSnapshot(
        step: String,
        stage: String,
        checkpoint: SchemaPathCheckpoint,
        source: SchemaCardSource? = nil,
        prematureMethodID: String? = nil
    ) -> SchemaPathSnapshot {
        let source = source ?? sourceLineage
        let body = step == "method_confirm"
            ? "Bu odağı bugün şu yöntemle çalışalım mı: İmgeleme ile yeniden senaryolama? Evet ya da hayır diyebilirsin."
            : "Burada kendi sözlerinizle ne fark ediyorsunuz?"
        let binding = SchemaChatBinding(
            pathId: 9,
            pathPublicId: "33333333333333333333333333333333",
            stepId: step,
            expectedRevision: 12,
            checkpointPublicId: checkpoint.publicId,
            expectedCheckpointSeq: checkpoint.seq,
            sourceUserMessageId: source.userMessageId ?? 0,
            sourceUserMessagePublicId: source.userMessagePublicId ?? "",
            sourceAssistantMessageId: source.assistantMessageId ?? 0,
            sourceAssistantMessagePublicId:
                source.assistantMessagePublicId ?? ""
        )
        let card = SchemaCardEnvelope(
            id: "schema-chat-\(step)-c\(checkpoint.seq)",
            kind: "chat_prompt",
            presentation: "chat_only",
            status: "active",
            stage: stage,
            step: step,
            pathId: 9,
            pathPublicId: "33333333333333333333333333333333",
            revision: 12,
            title: "",
            contextLine: "",
            body: body,
            source: source,
            checkpoint: checkpoint,
            chatBinding: binding,
            fields: [],
            actions: [
                .init(
                    id: "schema-pause", action: "pause",
                    label: "Duraklat", style: "secondary",
                    requiresConfirm: false
                ),
                .init(
                    id: "schema-stop", action: "stop",
                    label: "Çalışmayı bitir", style: "danger",
                    requiresConfirm: true
                ),
            ],
            progress: progress(stage: 2, step: 2, label: "")
        )
        let selected = prematureMethodID.map {
            SchemaSelectedMethod(
                methodId: $0, nodeId: $0,
                name: "İmgeleme ile yeniden senaryolama",
                requiresPrecheck: true
            )
        }
        let path = SchemaPath(
            id: 9,
            convId: SchemaChatV4DataSource.conversationID,
            therapist: "young",
            claimId: 44,
            phase: "work",
            status: "active",
            methodId: prematureMethodID,
            method: selected,
            revision: 12,
            publicId: "33333333333333333333333333333333",
            flowVersion: 4,
            stage: stage,
            step: step
        )
        return snapshot(
            card: card,
            revision: 12,
            path: path,
            policy: .init(
                requiresInApp: true,
                remoteReplyAllowed: false,
                composerBindingRequired: true,
                composerAllowed: true,
                composerMode: .bound,
                composerSurface: "ordinary_chat",
                boundStepId: step,
                reason: "bound_schema_step"
            )
        )
    }

    private func activeCard(
        revision: Int = 12,
        includeTechnique: Bool = false,
        includeGroundControl: Bool? = nil,
        step: String = "origin_or_unknown",
        stage: String = "depth",
        source: SchemaCardSource? = nil
    ) -> SchemaCardEnvelope {
        let source = source ?? sourceLineage
        return SchemaCardEnvelope(
            id: "schema-chat-\(step)-r\(revision)",
            kind: "chat_prompt",
            presentation: "chat_only",
            status: "active",
            stage: stage,
            step: step,
            pathId: 9,
            pathPublicId: "33333333333333333333333333333333",
            revision: revision,
            title: "",
            contextLine: "",
            body: "Bu duygunun ilk tanıdık geldiği anı hatırlıyor musunuz?",
            source: source,
            checkpoint: SchemaPathCheckpoint(
                publicId: String(repeating: revision.isMultiple(of: 2)
                    ? "6" : "7", count: 32),
                seq: revision,
                promptKey: "origin",
                methodId: "young:method:imagery-rescripting",
                status: "active",
                canBacktrack: true,
                backtrackPending: false
            ),
            chatBinding: SchemaChatBinding(
                pathId: 9,
                pathPublicId: "33333333333333333333333333333333",
                stepId: step,
                expectedRevision: revision,
                checkpointPublicId: String(
                    repeating: revision.isMultiple(of: 2) ? "6" : "7",
                    count: 32
                ),
                expectedCheckpointSeq: revision,
                sourceUserMessageId: source.userMessageId ?? 0,
                sourceUserMessagePublicId:
                    source.userMessagePublicId ?? "",
                sourceAssistantMessageId: source.assistantMessageId ?? 0,
                sourceAssistantMessagePublicId:
                    source.assistantMessagePublicId ?? "",
                techniqueLinkId: includeTechnique ? 5 : nil,
                techniqueLinkPublicId:
                    includeTechnique
                        ? "55555555555555555555555555555555" : nil,
                expectedTechniqueRevision: includeTechnique ? 3 : nil
            ),
            fields: [],
            actions: ((includeGroundControl ?? includeTechnique) ? [
                .init(
                    id: "technique-ground",
                    action: "ground_chat_technique",
                    label: "Şimdiye dön",
                    style: "secondary",
                    requiresConfirm: false,
                    payload: [
                        "step_id": .string(step),
                        "technique_link_id": .number(5),
                        "technique_link_public_id":
                            .string("55555555555555555555555555555555"),
                        "expected_technique_revision": .number(3),
                        "control_only": .bool(true),
                    ]
                ),
            ] : []) + [
                .init(
                    id: "schema-pause",
                    action: "pause",
                    label: "Duraklat",
                    style: "secondary",
                    requiresConfirm: false
                ),
                .init(
                    id: "schema-stop",
                    action: "stop",
                    label: "Çalışmayı bitir",
                    style: "danger",
                    requiresConfirm: true
                ),
            ],
            progress: progress(stage: 2, step: 2, label: "Kökü anlama")
        )
    }

    private func stoppedSnapshot(revision: Int) -> SchemaPathSnapshot {
        snapshot(
            card: nil,
            revision: revision,
            path: SchemaPath(
                id: 9,
                convId: SchemaChatV4DataSource.conversationID,
                therapist: "young",
                claimId: 44,
                phase: "complete",
                status: "stopped",
                revision: revision,
                publicId: "33333333333333333333333333333333",
                flowVersion: 4,
                stage: "complete",
                step: "complete"
            ),
            policy: .init(
                requiresInApp: true,
                remoteReplyAllowed: false,
                composerBindingRequired: false,
                composerAllowed: true,
                composerMode: .ordinary,
                composerSurface: "ordinary_chat",
                reason: "stopped"
            )
        )
    }

    private func pausedSnapshot(
        source: SchemaCardSource? = nil
    ) -> SchemaPathSnapshot {
        let path = SchemaPath(
            id: 9,
            convId: SchemaChatV4DataSource.conversationID,
            therapist: "young",
            claimId: 44,
            phase: "work",
            status: "paused",
            revision: 12,
            publicId: "33333333333333333333333333333333",
            flowVersion: 4,
            stage: "depth",
            step: "origin_or_unknown",
            pauseReason: "manual_pause",
            resumeRequired: true
        )
        let card = SchemaCardEnvelope(
            id: "schema-resume-r12",
            kind: "resume",
            presentation: "chat_only",
            status: "active",
            stage: "depth",
            step: "origin_or_unknown",
            pathId: 9,
            pathPublicId: "33333333333333333333333333333333",
            revision: 12,
            title: "",
            body: "Hazır olduğunuzda devam edebilirsiniz.",
            source: source ?? sourceLineage,
            checkpoint: SchemaPathCheckpoint(
                publicId: String(repeating: "6", count: 32),
                seq: 12,
                promptKey: "origin",
                status: "paused",
                canBacktrack: true,
                backtrackPending: false
            ),
            fields: [],
            actions: [
                .init(
                    id: "schema-resume",
                    action: "resume_path",
                    label: "Sürdür",
                    style: "primary",
                    requiresConfirm: false
                ),
                .init(
                    id: "schema-stop",
                    action: "stop",
                    label: "Bitir",
                    style: "danger",
                    requiresConfirm: true
                ),
            ],
            progress: progress(stage: 2, step: 2, label: "Kökü anlama")
        )
        return snapshot(
            card: card,
            revision: 12,
            path: path,
            policy: .init(
                requiresInApp: true,
                remoteReplyAllowed: false,
                composerBindingRequired: false,
                composerAllowed: false,
                composerMode: .disabled,
                composerSurface: "ordinary_chat",
                boundStepId: nil,
                reason: "manual_pause"
            )
        )
    }

    private func snapshot(
        card: SchemaCardEnvelope?,
        revision: Int?,
        version: Int = 4,
        path: SchemaPath?,
        policy: SchemaPathInteractionPolicy,
        messageMeta: [SchemaMessageMetaEvent] = []
    ) -> SchemaPathSnapshot {
        SchemaPathSnapshot(
            version: version,
            protocol: "schema_path_chat_v4",
            presentation: "chat_only",
            stage: card?.stage ?? path?.stage,
            step: card?.step ?? path?.step,
            revision: revision,
            progress: card?.progress,
            nextCard: card,
            messageMeta: messageMeta,
            interactionPolicy: policy,
            resumeState: .init(required: false, reason: "none"),
            clinicalSync: .init(
                enabled: false,
                canEnable: true,
                reason: "disabled",
                notice: "Bu çalışma yalnız bu cihazda tutuluyor."
            ),
            activePath: path,
            candidates: [],
            methods: [],
            notices: [],
            allowedActions: card?.actions.map(\.action) ?? [],
            completedTurns: 5,
            minimumListeningTurns: 3
        )
    }

    private var sourceLineage: SchemaCardSource {
        lineage(userID: 101, assistantID: 102)
    }

    private func lineage(
        userID: Int,
        assistantID: Int,
        quote: String? = nil
    ) -> SchemaCardSource {
        .init(
            userMessageId: userID,
            userMessagePublicId: userID == 101
                ? "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
                : "cccccccccccccccccccccccccccccccc",
            assistantMessageId: assistantID,
            assistantMessagePublicId: assistantID == 102
                ? "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
                : "dddddddddddddddddddddddddddddddd",
            quote: quote ?? (userID == 101
                ? "Bugün aynı döngü tekrarlandı."
                : "Daha yeni güvenli tur")
        )
    }

    private func progress(
        stage: Int,
        step: Int,
        label: String
    ) -> SchemaPathProgress {
        .init(
            stageNumber: stage,
            stageTotal: 3,
            stepNumber: step,
            stepTotal: 8,
            label: label
        )
    }

    private func replacingKind(
        _ card: SchemaCardEnvelope,
        with kind: String
    ) -> SchemaCardEnvelope {
        .init(
            id: card.id,
            kind: kind,
            presentation: card.presentation,
            status: card.status,
            stage: card.stage,
            step: card.step,
            pathId: card.pathId,
            pathPublicId: card.pathPublicId,
            revision: card.revision,
            title: card.title,
            contextLine: card.contextLine,
            body: card.body,
            source: card.source,
            checkpoint: card.checkpoint,
            chatBinding: card.chatBinding,
            fields: card.fields,
            actions: card.actions,
            progress: card.progress
        )
    }

    private func replacingBinding(
        _ card: SchemaCardEnvelope,
        with binding: SchemaChatBinding?
    ) -> SchemaCardEnvelope {
        .init(
            id: card.id,
            kind: card.kind,
            presentation: card.presentation,
            status: card.status,
            stage: card.stage,
            step: card.step,
            pathId: card.pathId,
            pathPublicId: card.pathPublicId,
            revision: card.revision,
            title: card.title,
            contextLine: card.contextLine,
            body: card.body,
            source: card.source,
            checkpoint: card.checkpoint,
            chatBinding: binding,
            fields: card.fields,
            actions: card.actions,
            progress: card.progress
        )
    }

    private func replacingPathLineage(
        _ card: SchemaCardEnvelope,
        pathID: Int?,
        pathPublicID: String?
    ) -> SchemaCardEnvelope {
        .init(
            id: card.id,
            kind: card.kind,
            presentation: card.presentation,
            status: card.status,
            stage: card.stage,
            step: card.step,
            pathId: pathID,
            pathPublicId: pathPublicID,
            revision: card.revision,
            title: card.title,
            contextLine: card.contextLine,
            body: card.body,
            source: card.source,
            checkpoint: card.checkpoint,
            chatBinding: card.chatBinding,
            fields: card.fields,
            actions: card.actions,
            progress: card.progress
        )
    }

    private func replacingActions(
        _ card: SchemaCardEnvelope,
        with actions: [SchemaCardActionEnvelope]
    ) -> SchemaCardEnvelope {
        .init(
            id: card.id,
            kind: card.kind,
            presentation: card.presentation,
            status: card.status,
            stage: card.stage,
            step: card.step,
            pathId: card.pathId,
            pathPublicId: card.pathPublicId,
            revision: card.revision,
            title: card.title,
            contextLine: card.contextLine,
            body: card.body,
            source: card.source,
            checkpoint: card.checkpoint,
            chatBinding: card.chatBinding,
            fields: card.fields,
            actions: actions,
            progress: card.progress
        )
    }

    private func replacingCheckpoint(
        _ card: SchemaCardEnvelope,
        with checkpoint: SchemaPathCheckpoint
    ) -> SchemaCardEnvelope {
        let binding = card.chatBinding.map {
            SchemaChatBinding(
                protocol: $0.protocol,
                pathId: $0.pathId,
                pathPublicId: $0.pathPublicId,
                stepId: $0.stepId,
                expectedRevision: $0.expectedRevision,
                checkpointPublicId: checkpoint.publicId,
                expectedCheckpointSeq: checkpoint.seq,
                sourceUserMessageId: $0.sourceUserMessageId,
                sourceUserMessagePublicId: $0.sourceUserMessagePublicId,
                sourceAssistantMessageId: $0.sourceAssistantMessageId,
                sourceAssistantMessagePublicId:
                    $0.sourceAssistantMessagePublicId,
                techniqueLinkId: $0.techniqueLinkId,
                techniqueLinkPublicId: $0.techniqueLinkPublicId,
                expectedTechniqueRevision: $0.expectedTechniqueRevision
            )
        }
        return .init(
            id: card.id,
            kind: card.kind,
            presentation: card.presentation,
            status: card.status,
            stage: card.stage,
            step: card.step,
            pathId: card.pathId,
            pathPublicId: card.pathPublicId,
            revision: card.revision,
            title: card.title,
            contextLine: card.contextLine,
            body: card.body,
            source: card.source,
            checkpoint: checkpoint,
            chatBinding: binding,
            fields: card.fields,
            actions: card.actions,
            progress: card.progress
        )
    }

    private func pathIdentitySnapshot(
        pathID: Int,
        pathPublicID: String,
        revision: Int,
        source: SchemaCardSource
    ) -> SchemaPathSnapshot {
        let original = activeCard(revision: revision, source: source)
        let originalBinding = original.chatBinding!
        let binding = SchemaChatBinding(
            pathId: pathID,
            pathPublicId: pathPublicID,
            stepId: originalBinding.stepId,
            expectedRevision: revision,
            checkpointPublicId: originalBinding.checkpointPublicId,
            expectedCheckpointSeq: originalBinding.expectedCheckpointSeq,
            sourceUserMessageId: originalBinding.sourceUserMessageId,
            sourceUserMessagePublicId:
                originalBinding.sourceUserMessagePublicId,
            sourceAssistantMessageId: originalBinding.sourceAssistantMessageId,
            sourceAssistantMessagePublicId:
                originalBinding.sourceAssistantMessagePublicId
        )
        let card = replacingBinding(
            replacingPathLineage(
                original,
                pathID: pathID,
                pathPublicID: pathPublicID
            ),
            with: binding
        )
        let path = SchemaPath(
            id: pathID,
            convId: SchemaChatV4DataSource.conversationID,
            therapist: "young",
            claimId: 44,
            phase: "work",
            status: "active",
            methodId: "young:method:imagery-rescripting",
            method: SchemaSelectedMethod(
                methodId: "young:method:imagery-rescripting",
                nodeId: "young:method:imagery-rescripting",
                name: "İmgeleme ile yeniden senaryolama",
                requiresPrecheck: true
            ),
            revision: revision,
            publicId: pathPublicID,
            flowVersion: 4,
            stage: "depth",
            step: "origin_or_unknown"
        )
        return snapshot(
            card: card,
            revision: revision,
            path: path,
            policy: .init(
                requiresInApp: true,
                remoteReplyAllowed: false,
                composerBindingRequired: true,
                composerAllowed: true,
                composerMode: .bound,
                composerSurface: "ordinary_chat",
                boundStepId: "origin_or_unknown",
                reason: "bound_schema_step"
            )
        )
    }

    private func recoverySnapshot(
        kind: String,
        pathStatus: String,
        checkpointStatus: String,
        actions: [SchemaCardActionEnvelope]
    ) -> SchemaPathSnapshot {
        let path = SchemaPath(
            id: 9,
            convId: SchemaChatV4DataSource.conversationID,
            therapist: "young",
            claimId: 44,
            phase: "work",
            status: pathStatus,
            methodId: "young:method:imagery-rescripting",
            method: SchemaSelectedMethod(
                methodId: "young:method:imagery-rescripting",
                nodeId: "young:method:imagery-rescripting",
                name: "İmgeleme ile yeniden senaryolama",
                requiresPrecheck: true
            ),
            revision: 12,
            publicId: "33333333333333333333333333333333",
            flowVersion: 4,
            stage: "depth",
            step: "origin_or_unknown"
        )
        let card = SchemaCardEnvelope(
            id: "schema-recovery-\(kind)-\(pathStatus)",
            kind: kind,
            presentation: "chat_only",
            status: "active",
            stage: "depth",
            step: "origin_or_unknown",
            pathId: 9,
            pathPublicId: "33333333333333333333333333333333",
            revision: 12,
            title: "",
            body: "Çalışma otomatik ilerletilmedi.",
            source: sourceLineage,
            checkpoint: SchemaPathCheckpoint(
                publicId: String(repeating: "6", count: 32),
                seq: 12,
                promptKey: "origin",
                methodId: "young:method:imagery-rescripting",
                status: checkpointStatus,
                canBacktrack: true,
                backtrackPending: false
            ),
            fields: [],
            actions: actions,
            progress: nil
        )
        return snapshot(
            card: card,
            revision: 12,
            path: path,
            policy: .init(
                requiresInApp: true,
                remoteReplyAllowed: false,
                composerBindingRequired: false,
                composerAllowed: false,
                composerMode: .disabled,
                composerSurface: "ordinary_chat",
                reason: "recovery"
            )
        )
    }

    private func meta(kind: String, id: Int) -> SchemaMessageMetaEvent {
        .init(
            databaseId: id,
            publicId: "meta-public-\(id)",
            kind: kind,
            status: "active",
            messageId: 102,
            sourceUserMessageId: 101,
            sourceAssistantMessageId: 102,
            pathId: 9,
            pathPublicId: "33333333333333333333333333333333",
            expectedRevision: 12,
            clinicalGeneration: 1,
            stage: "depth",
            step: "origin_or_unknown",
            title: kind,
            summary: "Kısa meta"
        )
    }
}

private extension Array {
    var only: Element? { count == 1 ? first : nil }
}

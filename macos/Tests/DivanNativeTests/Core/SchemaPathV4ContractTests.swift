import CryptoKit
import Foundation
import XCTest
@testable import DivanNative

/// The filename remains stable because the fixture is shared with older
/// release tooling. Its contents are the frozen v5/v8 public contract.
final class SchemaPathV4ContractTests: XCTestCase {
    private struct Fixture: Decodable {
        let fixtureVersion: Int
        let `protocol`: String
        let version: Int
        let presentation: String
        let stage: String
        let step: String
        let revision: Int?
        let progress: SchemaPathProgress
        let nextCard: SchemaCardEnvelope
        let interactionPolicy: SchemaPathInteractionPolicy
        let resumeState: SchemaPathResumeState
        let clinicalSync: SchemaClinicalSyncState
        let activePath: SchemaPath?
        let messageMeta: [SchemaMessageMetaEvent]
        let contract: [String: JSONValue]
        let cardExamples: CardExamples
        let chatSchemaBinding: SchemaChatBinding
        let importControlBinding: SchemaChatBinding
        let schemaBindingResults: BindingResults
        let actionRequests: [String: JSONValue]
        let errors: [String]
        let syncWire: [String: JSONValue]
    }

    private struct CardExamples: Decodable {
        let candidatePrompt: SchemaCardEnvelope
        let queuedChatState: SchemaCardEnvelope
        let completedChatState: SchemaCardEnvelope
        let failedChatState: SchemaCardEnvelope
        let importedWaitingChatState: SchemaCardEnvelope
        let completeChatState: SchemaCardEnvelope
    }

    private struct BindingResults: Decodable {
        let success: SchemaChatBindingResult
        let terminal: SchemaChatBindingResult
        let sourceInvalid: SchemaChatBindingResult
        let stale: SchemaChatBindingResult
        let totalKeys: [String]
    }

    func testSharedFixtureHashAndInitialCandidateEnvelope() throws {
        let (fixture, data) = try loadFixture()
        XCTAssertEqual(
            SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined(),
            "30e2cac7c8ced6e58a3f8860ea887f1f1e6f42cb888d21da6bcaad7803294197"
        )
        XCTAssertEqual(fixture.fixtureVersion, 8)
        XCTAssertEqual(fixture.protocol, "schema_path_chat_v5")
        XCTAssertEqual(fixture.version, 5)
        XCTAssertEqual(fixture.presentation, "chat_only")
        XCTAssertEqual(fixture.stage, "listen")
        XCTAssertEqual(fixture.step, "candidate_review")
        XCTAssertNil(fixture.revision)
        XCTAssertNil(fixture.activePath)
        XCTAssertTrue(fixture.messageMeta.isEmpty)

        let card = fixture.nextCard
        XCTAssertEqual(card, fixture.cardExamples.candidatePrompt)
        XCTAssertEqual(card.kind, "candidate_prompt")
        XCTAssertEqual(card.contextLine,
                       "Terk Edilme / İstikrarsızlık tetiklenmiş olabilir.")
        XCTAssertEqual(
            card.source.candidateQuoteForDisplay,
            "Böyle olunca geri çekiliyorum."
        )
        XCTAssertEqual(
            card.candidatePatternForDisplay,
            "Terk Edilme / İstikrarsızlık"
        )
        XCTAssertEqual(card.body, "Bunu çalışmak ister misin?")
        XCTAssertEqual(card.title, "")
        XCTAssertTrue(card.fields.isEmpty)
        XCTAssertNil(card.pathId)
        XCTAssertNil(card.pathPublicId)
        XCTAssertNil(card.revision)
        XCTAssertNil(card.chatBinding)
        XCTAssertNil(card.promptDelivery)
        XCTAssertTrue(card.isActive)
        XCTAssertTrue(card.isSupportedByNativeContract)
        XCTAssertEqual(card.actions.map(\.action), [
            "accept_candidate_chat", "reject_candidate_chat",
        ])
        XCTAssertEqual(card.actions.map(\.label), ["Evet", "Hayır"])

        XCTAssertTrue(fixture.interactionPolicy.requiresInApp)
        XCTAssertFalse(fixture.interactionPolicy.remoteReplyAllowed)
        XCTAssertEqual(fixture.interactionPolicy.composerMode, .disabled)
        XCTAssertFalse(fixture.interactionPolicy.composerAllowed == true)
        XCTAssertEqual(fixture.interactionPolicy.composerSurface, "ordinary_chat")
        XCTAssertFalse(fixture.interactionPolicy.composerBindingRequired)
        XCTAssertEqual(fixture.interactionPolicy.inlineControlsOnly, false)
        XCTAssertFalse(fixture.resumeState.required)
    }

    func testPostYesCardsAreMetadataOnlyAndExposeNoControlsOrQuestions() throws {
        let examples = try loadFixture().fixture.cardExamples
        let states = [
            examples.queuedChatState,
            examples.completedChatState,
            examples.failedChatState,
            examples.importedWaitingChatState,
            examples.completeChatState,
        ]
        for state in states {
            XCTAssertEqual(state.kind, "chat_state")
            XCTAssertEqual(state.presentation, "chat_only")
            XCTAssertEqual(state.title, "")
            XCTAssertEqual(state.contextLine ?? "", "")
            XCTAssertEqual(state.body, "")
            XCTAssertTrue(state.fields.isEmpty)
            XCTAssertTrue(state.actions.isEmpty)
            XCTAssertNil(state.progress)
        }
        XCTAssertFalse(examples.queuedChatState.isSupportedByNativeContract)
        XCTAssertFalse(examples.failedChatState.isSupportedByNativeContract)
        XCTAssertTrue(examples.completedChatState.isSupportedByNativeContract)
        XCTAssertTrue(examples.importedWaitingChatState.isSupportedByNativeContract)
        XCTAssertTrue(examples.completeChatState.isSupportedByNativeContract)
    }

    func testCompletedPromptBindsExactDurableAssistantIdentity() throws {
        let fixture = try loadFixture().fixture
        let card = fixture.cardExamples.completedChatState
        let delivery = try XCTUnwrap(card.promptDelivery)
        let binding = try XCTUnwrap(card.chatBinding)
        XCTAssertEqual(binding, fixture.chatSchemaBinding)
        XCTAssertEqual(delivery.status, "completed")
        XCTAssertEqual(delivery.requestId, "schema-v5-prompt-0001")
        XCTAssertEqual(delivery.promptAssistantMessageId, 204)
        XCTAssertEqual(
            delivery.promptAssistantMessagePublicId,
            "dddddddddddddddddddddddddddddddd"
        )
        XCTAssertNil(delivery.errorCode)
        XCTAssertTrue(delivery.isSupportedByNativeContract)
        XCTAssertNil(binding.syncImportControl)
        XCTAssertEqual(binding.promptRequestId, delivery.requestId)
        XCTAssertEqual(
            binding.promptAssistantMessageId,
            delivery.promptAssistantMessageId
        )
        XCTAssertEqual(
            binding.promptAssistantMessagePublicId,
            delivery.promptAssistantMessagePublicId
        )
        XCTAssertEqual(binding.sourceAssistantMessageId, 204)
        XCTAssertEqual(
            binding.sourceAssistantMessagePublicId,
            "dddddddddddddddddddddddddddddddd"
        )
        XCTAssertEqual(binding.checkpointPublicId, card.checkpoint?.publicId)
        XCTAssertEqual(binding.expectedCheckpointSeq, card.checkpoint?.seq)
    }

    func testImportedWaitingRequiresExactControlMarkerAndExplicitNullIdentity()
        throws {
        let fixture = try loadFixture().fixture
        let card = fixture.cardExamples.importedWaitingChatState
        let delivery = try XCTUnwrap(card.promptDelivery)
        let binding = try XCTUnwrap(card.chatBinding)
        XCTAssertEqual(binding, fixture.importControlBinding)
        XCTAssertEqual(card.status, "paused")
        XCTAssertEqual(card.checkpoint?.status, "paused")
        XCTAssertFalse(card.checkpoint?.canBacktrack == true)
        XCTAssertEqual(delivery.status, "imported_waiting")
        XCTAssertNil(delivery.requestId)
        XCTAssertNil(delivery.promptAssistantMessageId)
        XCTAssertNil(delivery.promptAssistantMessagePublicId)
        XCTAssertNil(delivery.errorCode)
        XCTAssertEqual(binding.syncImportControl, true)
        XCTAssertNil(binding.promptRequestId)
        XCTAssertNil(binding.promptAssistantMessageId)
        XCTAssertNil(binding.promptAssistantMessagePublicId)

        let encoder = JSONEncoder()
        let bindingObject = try XCTUnwrap(
            JSONSerialization.jsonObject(with: encoder.encode(binding))
                as? [String: Any]
        )
        XCTAssertEqual(bindingObject["syncImportControl"] as? Bool, true)
        XCTAssertTrue(bindingObject["promptRequestId"] is NSNull)
        XCTAssertTrue(bindingObject["promptAssistantMessageId"] is NSNull)
        XCTAssertTrue(bindingObject["promptAssistantMessagePublicId"] is NSNull)

        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let malformedBinding = Data(#"""
        {
          "protocol":"schema_path_chat_v5",
          "sync_import_control":true,
          "path_id":91,
          "path_public_id":"55555555555555555555555555555555",
          "step_id":"variable_explore",
          "expected_revision":41,
          "checkpoint_public_id":"77777777777777777777777777777777",
          "expected_checkpoint_seq":1,
          "prompt_assistant_message_id":null,
          "prompt_assistant_message_public_id":null,
          "source_user_message_id":301,
          "source_user_message_public_id":"eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
          "source_assistant_message_id":302,
          "source_assistant_message_public_id":"ffffffffffffffffffffffffffffffff"
        }
        """#.utf8)
        XCTAssertThrowsError(
            try decoder.decode(SchemaChatBinding.self, from: malformedBinding)
        )

        let malformedDelivery = Data(#"""
        {
          "status":"imported_waiting",
          "request_id":null,
          "prompt_assistant_message_id":null,
          "prompt_assistant_message_public_id":null
        }
        """#.utf8)
        XCTAssertThrowsError(
            try decoder.decode(SchemaPromptDelivery.self, from: malformedDelivery)
        )
    }

    func testPendingFailedAndCompleteStatesNeverInventComposerBinding() throws {
        let examples = try loadFixture().fixture.cardExamples
        XCTAssertNil(examples.queuedChatState.checkpoint)
        XCTAssertNil(examples.queuedChatState.chatBinding)
        XCTAssertEqual(examples.queuedChatState.promptDelivery?.status, "queued")
        XCTAssertNil(examples.failedChatState.checkpoint)
        XCTAssertNil(examples.failedChatState.chatBinding)
        XCTAssertEqual(examples.failedChatState.promptDelivery?.status, "failed")
        XCTAssertEqual(
            examples.failedChatState.promptDelivery?.errorCode,
            "provider_unavailable"
        )
        XCTAssertEqual(examples.completeChatState.status, "completed")
        XCTAssertNil(examples.completeChatState.chatBinding)
        XCTAssertTrue(examples.completeChatState.actions.isEmpty)
    }

    func testV5BindingResultsRemainTotalAndExplicit() throws {
        let values = try loadFixture().fixture.schemaBindingResults
        XCTAssertEqual(Set(values.totalKeys), Set([
            "applied", "progressed", "followup_required", "error_code",
            "missing", "path_id", "path_revision", "revision", "stage",
            "step", "action", "checkpoint_public_id", "checkpoint_seq",
            "prompt_request_id", "backtracked",
        ]))
        XCTAssertTrue(values.success.applied)
        XCTAssertTrue(values.success.progressed)
        XCTAssertTrue(values.success.followupRequired)
        XCTAssertEqual(values.success.missing, ["hypothetical_response"])
        XCTAssertEqual(values.success.action, "ask_counterfactual")
        XCTAssertEqual(values.success.step, "variable_explore")
        XCTAssertEqual(values.success.checkpointSeq, 5)
        XCTAssertFalse(values.success.backtracked)

        XCTAssertTrue(values.terminal.applied)
        XCTAssertTrue(values.terminal.progressed)
        XCTAssertFalse(values.terminal.followupRequired)
        XCTAssertEqual(values.terminal.step, "complete")

        XCTAssertFalse(values.sourceInvalid.applied)
        XCTAssertFalse(values.sourceInvalid.followupRequired)
        XCTAssertEqual(values.sourceInvalid.errorCode, "schema_source_invalid")
        XCTAssertFalse(values.stale.applied)
        XCTAssertEqual(values.stale.errorCode, "schema_chat_binding_stale")
    }

    func testTypedControlsAreProviderFreeAndImportResumeUsesRealProvider()
        throws {
        let fixture = try loadFixture().fixture
        let localNames = [
            "exact_pause_chat", "exact_stop_chat", "exact_back_chat",
            "exact_ground_chat",
        ]
        for name in localNames {
            let command = try object(fixture.actionRequests[name])
            XCTAssertEqual(command["endpoint"], .string("/api/chat"))
            XCTAssertEqual(command["schema_binding"], .string("<chat_schema_binding>"))
            XCTAssertEqual(command["provider_calls"], .number(0))
            XCTAssertEqual(command["assistant_messages"], .number(0))
        }
        let resume = try object(fixture.actionRequests["exact_import_resume_chat"])
        XCTAssertEqual(resume["message"], .string("Devam"))
        XCTAssertEqual(resume["schema_binding"], .string("<import_control_binding>"))
        XCTAssertEqual(resume["provider_calls_after_worker"], .number(1))
        XCTAssertEqual(resume["durable_assistant_messages_after_worker"], .number(1))
    }

    func testV5FlowRemovesRatingsPrechecksAndUserMethodApproval() throws {
        let fixture = try loadFixture().fixture
        let runtime = try object(fixture.contract["runtime"])
        XCTAssertEqual(runtime["schema_version"], .number(5))
        XCTAssertEqual(runtime["path_flow_version"], .number(5))
        XCTAssertEqual(runtime["sync_batch_version"], .number(8))

        let flow = try object(fixture.contract["reachable_flow"])
        guard case .array(let removed)? = flow["removed_from_v5"] else {
            return XCTFail("v5 kaldırılan adım listesi eksik")
        }
        let removedNames = Set<String>(removed.compactMap {
            guard case .string(let value) = $0 else { return nil }
            return value
        })
        XCTAssertTrue(Set([
            "current_impact", "variable_check", "focus_confirm",
            "method_select", "method_confirm", "imagery_precheck",
            "reparent_or_chair_precheck",
        ]).isSubset(of: removedNames))
        XCTAssertEqual(flow["no_rating_or_precheck_question"], .bool(true))

        let method = try object(fixture.contract["method_flow"])
        XCTAssertEqual(method["user_method_approval_question"], .bool(false))
        XCTAssertEqual(method["method_selected_before_session"], .bool(true))
        XCTAssertEqual(method["one_selected_branch_only"], .bool(true))

        let controls = try object(fixture.contract["controls"])
        XCTAssertEqual(controls["visible_controls_after_yes"], .array([]))
        XCTAssertEqual(controls["synthetic_acknowledgement"], .bool(false))
    }

    func testSyncWirePinsBatchEightAndV5Capability() throws {
        let fixture = try loadFixture().fixture
        XCTAssertEqual(fixture.syncWire["batch_version"], .number(8))
        let capability = try object(fixture.syncWire["capability_gate"])
        XCTAssertEqual(capability["protocol_version"], .number(8))
        XCTAssertEqual(
            capability["ordered_capabilities"],
            .array([
                .string("schema_checkpoint_v1"),
                .string("schema_path_chat_v5"),
            ])
        )
        XCTAssertTrue(fixture.errors.contains("schema_protocol_update_required"))
        XCTAssertTrue(fixture.errors.contains("sync_protocol_update_required"))
    }

    func testClinicalSyncPreferenceCannotMasqueradeAsEffectiveDeviceConsent()
        throws {
        let fixture = try loadFixture().fixture
        XCTAssertTrue(fixture.clinicalSync.enabled)
        XCTAssertTrue(fixture.clinicalSync.preferenceEnabled == true)
        XCTAssertTrue(fixture.clinicalSync.initialized == true)
        XCTAssertEqual(fixture.clinicalSync.generation, 2)
        XCTAssertFalse(fixture.clinicalSync.needsDeviceConfirmation)

        let data = Data(#"""
        {
          "enabled": false,
          "preference_enabled": true,
          "initialized": false,
          "pending_device_confirmation": true,
          "can_enable": true,
          "reason": "device_confirmation_required",
          "notice": "Bu cihazda açık onay gerekli."
        }
        """#.utf8)
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let pending = try decoder.decode(SchemaClinicalSyncState.self, from: data)
        XCTAssertFalse(pending.enabled)
        XCTAssertTrue(pending.preferenceEnabled == true)
        XCTAssertFalse(pending.initialized == true)
        XCTAssertTrue(pending.needsDeviceConfirmation)
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

    private func loadFixture() throws -> (fixture: Fixture, data: Data) {
        let url = try XCTUnwrap(Bundle.module.url(
            forResource: "schema_path_v4_contract",
            withExtension: "json",
            subdirectory: "Fixtures"
        ))
        let data = try Data(contentsOf: url)
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return (try decoder.decode(Fixture.self, from: data), data)
    }

    private func object(_ value: JSONValue?) throws -> [String: JSONValue] {
        guard case .object(let object)? = value else {
            throw NSError(
                domain: "SchemaPathV4ContractTests",
                code: 1,
                userInfo: [NSLocalizedDescriptionKey: "Fixture nesnesi eksik."]
            )
        }
        return object
    }
}

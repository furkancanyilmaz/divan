import CryptoKit
import Foundation
import Security

/// A device-local draft is usable only with the exact authoritative hidden
/// Schema binding that was active when the user wrote it. The text itself is
/// stored in Keychain, never in a preferences or synchronizable container.
public struct SchemaChatDraftRecord: Codable, Equatable, Sendable {
    public let conversationID: Int
    public let bindingFingerprint: String
    public let text: String

    public init(
        conversationID: Int,
        bindingFingerprint: String,
        text: String
    ) {
        self.conversationID = conversationID
        self.bindingFingerprint = bindingFingerprint
        self.text = text
    }
}

@MainActor
public protocol SchemaChatDraftStore: AnyObject {
    func load(conversationID: Int) -> SchemaChatDraftRecord?
    func save(_ record: SchemaChatDraftRecord)
    func remove(conversationID: Int)
}

/// Default for previews/tests that do not explicitly opt into persistence.
public final class DisabledSchemaChatDraftStore: SchemaChatDraftStore {
    public static let shared = DisabledSchemaChatDraftStore()
    private init() {}
    public func load(conversationID: Int) -> SchemaChatDraftRecord? { nil }
    public func save(_ record: SchemaChatDraftRecord) {}
    public func remove(conversationID: Int) {}
}

public final class KeychainSchemaChatDraftStore: SchemaChatDraftStore {
    public static let service = "com.divan.macos.schema-chat-draft.v1"
    private let encoder = JSONEncoder()
    private let decoder = JSONDecoder()

    public init() {}

    public func load(conversationID: Int) -> SchemaChatDraftRecord? {
        guard conversationID > 0 else { return nil }
        var query = baseQuery(conversationID: conversationID)
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &result)
                == errSecSuccess,
              let data = result as? Data else { return nil }
        guard let record = try? decoder.decode(
                SchemaChatDraftRecord.self, from: data
              ),
              record.conversationID == conversationID,
              record.bindingFingerprint.count == 64,
              !record.text.isEmpty,
              record.text.count <= 20_000 else {
            remove(conversationID: conversationID)
            return nil
        }
        return record
    }

    public func save(_ record: SchemaChatDraftRecord) {
        guard record.conversationID > 0,
              record.bindingFingerprint.count == 64,
              !record.text.isEmpty,
              record.text.count <= 20_000,
              let data = try? encoder.encode(record) else {
            remove(conversationID: record.conversationID)
            return
        }
        let query = baseQuery(conversationID: record.conversationID)
        let update: [String: Any] = [
            kSecValueData as String: data,
            kSecAttrAccessible as String:
                kSecAttrAccessibleWhenUnlockedThisDeviceOnly,
        ]
        let status = SecItemUpdate(
            query as CFDictionary, update as CFDictionary
        )
        guard status == errSecItemNotFound else { return }
        var item = query
        update.forEach { item[$0.key] = $0.value }
        _ = SecItemAdd(item as CFDictionary, nil)
    }

    public func remove(conversationID: Int) {
        guard conversationID > 0 else { return }
        _ = SecItemDelete(
            baseQuery(conversationID: conversationID) as CFDictionary
        )
    }

    private func baseQuery(conversationID: Int) -> [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: Self.service,
            kSecAttrAccount as String: "conversation-\(conversationID)",
            kSecAttrSynchronizable as String: false,
        ]
    }
}

public extension SchemaChatBinding {
    func deviceLocalDraftFingerprint(conversationID: Int) -> String {
        let parts: [String] = [
            `protocol`,
            syncImportControl.map { $0 ? "import" : "invalid-false" } ?? "-",
            String(conversationID),
            String(pathId), pathPublicId,
            stepId, String(expectedRevision),
            checkpointPublicId, String(expectedCheckpointSeq),
            promptRequestId ?? "-",
            promptAssistantMessageId.map(String.init) ?? "-",
            promptAssistantMessagePublicId ?? "-",
            String(sourceUserMessageId), sourceUserMessagePublicId,
            String(sourceAssistantMessageId), sourceAssistantMessagePublicId,
            techniqueLinkId.map(String.init) ?? "-",
            techniqueLinkPublicId ?? "-",
            expectedTechniqueRevision.map(String.init) ?? "-",
        ]
        let data = Data(parts.joined(separator: "\u{0}").utf8)
        return SHA256.hash(data: data)
            .map { String(format: "%02x", $0) }
            .joined()
    }
}

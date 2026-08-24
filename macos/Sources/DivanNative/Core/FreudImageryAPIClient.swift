import Foundation

/// Exact bindings for the shared Freud visual free-association contract.
///
/// Suggestions are returned only as bounded card references. They never flow
/// into the selection mutation unless the user later chooses a card and saves
/// a non-empty association in a separate action.
public extension APIClient {
    func freudImagery(
        conversationID: Int
    ) async throws -> FreudImageryWorkspace {
        guard conversationID > 0 else {
            throw Self.freudImageryInvalid("Görüşme kimliği geçersiz.")
        }
        let response: FreudImagerySnapshot = try await get(
            "/api/freud-imagery",
            query: [URLQueryItem(name: "conv_id", value: String(conversationID))]
        )
        return try Self.validatedFreudImagery(response.imagery)
    }

    func mutateFreudImagerySelection(
        _ mutation: FreudImagerySelectionMutation
    ) async throws -> FreudImageryMutationResponse {
        let body: [String: JSONValue]
        switch mutation {
        case let .consent(
            conversationID,
            requestID,
            orientationConfirmed,
            frameConfirmed,
            realityConfirmed,
            stopSignal
        ):
            try Self.validateFreudImageryConversation(conversationID)
            guard orientationConfirmed, frameConfirmed, realityConfirmed else {
                throw Self.freudImageryInvalid(
                    "Yönelim, çalışma çerçevesi ve gerçeklik ayrımı açıkça doğrulanmalı."
                )
            }
            let signal = stopSignal
                .split(whereSeparator: \.isWhitespace)
                .joined(separator: " ")
            guard (2...24).contains(signal.count) else {
                throw Self.freudImageryInvalid(
                    "Durma sözcüğü 2–24 karakter olmalı."
                )
            }
            body = [
                "action": .string("consent"),
                "conv_id": .number(Double(conversationID)),
                "request_id": .string(try Self.freudImageryRequestID(requestID)),
                "orientation_confirmed": .bool(true),
                "frame_confirmed": .bool(true),
                "reality_confirmed": .bool(true),
                "stop_signal": .string(signal),
            ]

        case let .select(conversationID, requestID, revision, cardID, association):
            try Self.validateFreudImageryConversation(conversationID)
            try Self.validateFreudImageryRevision(revision)
            try Self.validateFreudImageryCardID(cardID)
            let text = association.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !text.isEmpty else {
                throw Self.freudImageryInvalid(
                    "Kartı kaydetmek için kendi çağrışımınızı yazın."
                )
            }
            guard text.count <= 2_400 else {
                throw Self.freudImageryInvalid("Çağrışım metni çok uzun.")
            }
            body = [
                "action": .string("select"),
                "conv_id": .number(Double(conversationID)),
                "request_id": .string(try Self.freudImageryRequestID(requestID)),
                "revision": .number(Double(revision)),
                "card_id": .string(cardID),
                "association": .string(text),
            ]

        case let .clear(conversationID, requestID, revision):
            body = try Self.freudImageryRevisionBody(
                action: "clear",
                conversationID: conversationID,
                requestID: requestID,
                revision: revision
            )

        case let .undo(conversationID, requestID, revision):
            body = try Self.freudImageryRevisionBody(
                action: "undo",
                conversationID: conversationID,
                requestID: requestID,
                revision: revision
            )

        case let .stop(conversationID, requestID, revision):
            body = try Self.freudImageryRevisionBody(
                action: "stop",
                conversationID: conversationID,
                requestID: requestID,
                revision: revision
            )
        }

        var response: FreudImageryMutationResponse = try await post(
            "/api/freud-imagery/selection",
            body: body
        )
        response = FreudImageryMutationResponse(
            ok: response.ok,
            duplicate: response.duplicate,
            selected: response.selected,
            imagery: try Self.validatedFreudImagery(response.imagery)
        )
        return response
    }

    func suggestFreudImagery(
        _ mutation: FreudImagerySuggestionMutation
    ) async throws -> FreudImageryMutationResponse {
        try Self.validateFreudImageryConversation(mutation.conversationID)
        try Self.validateFreudImageryRevision(mutation.revision)
        guard mutation.modelConsent else {
            throw Self.freudImageryInvalid(
                "Kart önerisi için seçili modele gönderimi açıkça onaylayın."
            )
        }
        let response: FreudImageryMutationResponse = try await post(
            "/api/freud-imagery/suggest",
            body: [
                "conv_id": .number(Double(mutation.conversationID)),
                "request_id": .string(try Self.freudImageryRequestID(
                    mutation.requestID
                )),
                "revision": .number(Double(mutation.revision)),
                "model_consent": .bool(true),
            ]
        )
        let imagery = try Self.validatedFreudImagery(response.imagery)
        guard response.selected == false else {
            throw Self.freudImageryInvalid(
                "Kart önerisi beklenmedik biçimde seçim yaptı."
            )
        }
        return FreudImageryMutationResponse(
            ok: response.ok,
            duplicate: response.duplicate,
            selected: false,
            imagery: imagery
        )
    }
}

private extension APIClient {
    static func freudImageryInvalid(_ message: String) -> DivanAPIError {
        DivanAPIError(message: message, errorCode: "invalid_freud_imagery")
    }

    static func validateFreudImageryConversation(_ conversationID: Int) throws {
        guard conversationID > 0 else {
            throw freudImageryInvalid("Görüşme kimliği geçersiz.")
        }
    }

    static func validateFreudImageryRevision(_ revision: Int) throws {
        guard revision >= 1 else {
            throw freudImageryInvalid("Görsel kart paneli sürümü geçersiz.")
        }
    }

    static func freudImageryRequestID(_ requestID: String) throws -> String {
        let value = requestID.trimmingCharacters(in: .whitespacesAndNewlines)
        guard (8...128).contains(value.count),
              let first = value.unicodeScalars.first,
              CharacterSet.alphanumerics.contains(first),
              value.unicodeScalars.allSatisfy({
                  CharacterSet.alphanumerics
                      .union(CharacterSet(charactersIn: "._:-"))
                      .contains($0)
              }) else {
            throw freudImageryInvalid("Geçerli bir işlem kimliği gerekli.")
        }
        return value
    }

    static func validateFreudImageryCardID(_ cardID: String) throws {
        guard (1...64).contains(cardID.count),
              cardID.unicodeScalars.allSatisfy({
                  CharacterSet(charactersIn: "abcdefghijklmnopqrstuvwxyz0123456789-")
                      .contains($0)
              }),
              cardID.first != "-", cardID.last != "-" else {
            throw freudImageryInvalid("Görsel kart kimliği geçersiz.")
        }
    }

    static func freudImageryRevisionBody(
        action: String,
        conversationID: Int,
        requestID: String,
        revision: Int
    ) throws -> [String: JSONValue] {
        try validateFreudImageryConversation(conversationID)
        try validateFreudImageryRevision(revision)
        return [
            "action": .string(action),
            "conv_id": .number(Double(conversationID)),
            "request_id": .string(try freudImageryRequestID(requestID)),
            "revision": .number(Double(revision)),
        ]
    }

    static func validatedFreudImagery(
        _ value: FreudImageryWorkspace
    ) throws -> FreudImageryWorkspace {
        guard value.method.id == "visual-free-association" else {
            throw freudImageryInvalid("Görsel çalışma yöntemi doğrulanamadı.")
        }
        guard value.cards.count <= 24,
              Set(value.cards.map(\.id)).count == value.cards.count,
              Set(value.cards.map(\.file)).count == value.cards.count,
              value.suggestions.count <= 3,
              Set(value.suggestions.map(\.id)).count == value.suggestions.count else {
            throw freudImageryInvalid("Görsel kart destesi doğrulanamadı.")
        }
        if value.available {
            guard value.cards.count == 24 else {
                throw freudImageryInvalid("Görsel kart destesi eksik.")
            }
        } else if !value.cards.isEmpty || value.session != nil
                    || value.selection != nil || !value.suggestions.isEmpty {
            throw freudImageryInvalid("Kapalı görsel çalışma veri gösterdi.")
        }

        let cardsByID = Dictionary(uniqueKeysWithValues: value.cards.map { ($0.id, $0) })
        for card in value.cards {
            try validateFreudImageryCard(card)
        }
        for suggestion in value.suggestions {
            guard cardsByID[suggestion.id] == suggestion else {
                throw freudImageryInvalid("Kart önerisi desteyle uyuşmuyor.")
            }
        }
        if let selection = value.selection {
            guard selection.status == "selected",
                  selection.stepData.cardID == selection.card.id,
                  cardsByID[selection.card.id] == selection.card else {
                throw freudImageryInvalid("Kayıtlı görsel seçim doğrulanamadı.")
            }
        }
        return value
    }

    static func validateFreudImageryCard(_ card: FreudImageryCard) throws {
        try validateFreudImageryCardID(card.id)
        guard card.file == card.id + ".webp",
              card.mime == "image/webp",
              card.width == 768,
              card.height == 512,
              (1...(500 * 1_024)).contains(card.bytes),
              card.sha256.count == 64,
              card.sha256.unicodeScalars.allSatisfy({
                  CharacterSet(charactersIn: "0123456789abcdef").contains($0)
              }),
              !card.title.isEmpty,
              !card.description.isEmpty,
              !card.alt.isEmpty,
              card.url.hasPrefix("/assets/imagery/") else {
            throw freudImageryInvalid("Görsel kart kaydı doğrulanamadı.")
        }
    }
}

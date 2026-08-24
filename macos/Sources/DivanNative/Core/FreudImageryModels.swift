import Foundation

/// Server-owned state for Freud's literal visual free-association deck.
///
/// Card copy is deliberately rendered as received. It is descriptive rather
/// than interpretive: the native client never adds a symbol, diagnosis or
/// psychological label to a card.
public struct FreudImagerySnapshot: Decodable, Equatable, Sendable {
    public let imagery: FreudImageryWorkspace

    public init(imagery: FreudImageryWorkspace) {
        self.imagery = imagery
    }
}

public struct FreudImageryWorkspace: Decodable, Equatable, Sendable {
    public let available: Bool
    public let blockedReason: String
    public let method: FreudImageryMethod
    public let cards: [FreudImageryCard]
    public let session: FreudImagerySession?
    public let selection: FreudImagerySelection?
    public let suggestions: [FreudImageryCard]
    public let suggestionQuestion: String
    public let capabilities: FreudImageryCapabilities
    public let safetyHold: Bool
    public let precheckComplete: Bool

    public init(
        available: Bool,
        blockedReason: String,
        method: FreudImageryMethod,
        cards: [FreudImageryCard],
        session: FreudImagerySession?,
        selection: FreudImagerySelection?,
        suggestions: [FreudImageryCard],
        suggestionQuestion: String,
        capabilities: FreudImageryCapabilities,
        safetyHold: Bool,
        precheckComplete: Bool
    ) {
        self.available = available
        self.blockedReason = blockedReason
        self.method = method
        self.cards = cards
        self.session = session
        self.selection = selection
        self.suggestions = suggestions
        self.suggestionQuestion = suggestionQuestion
        self.capabilities = capabilities
        self.safetyHold = safetyHold
        self.precheckComplete = precheckComplete
    }
}

public struct FreudImageryMethod: Decodable, Equatable, Sendable {
    public let id: String
    public let title: String
    public let description: String

    public init(id: String, title: String, description: String) {
        self.id = id
        self.title = title
        self.description = description
    }
}

public struct FreudImageryCard: Decodable, Identifiable, Hashable, Sendable {
    public let id: String
    public let file: String
    public let category: String
    public let title: String
    public let description: String
    public let alt: String
    public let mime: String
    public let sha256: String
    public let width: Int
    public let height: Int
    public let bytes: Int
    public let url: String

    public init(
        id: String,
        file: String,
        category: String,
        title: String,
        description: String,
        alt: String,
        mime: String = "image/webp",
        sha256: String,
        width: Int = 768,
        height: Int = 512,
        bytes: Int,
        url: String
    ) {
        self.id = id
        self.file = file
        self.category = category
        self.title = title
        self.description = description
        self.alt = alt
        self.mime = mime
        self.sha256 = sha256
        self.width = width
        self.height = height
        self.bytes = bytes
        self.url = url
    }
}

public struct FreudImagerySession: Decodable, Equatable, Sendable {
    public let id: Int
    public let techniqueRunID: Int
    public let status: String
    public let revision: Int
    public let orientationConfirmed: Bool
    public let frameConfirmed: Bool
    public let realityConfirmed: Bool
    public let stopSignal: String
    public let consentAt: String?

    public init(
        id: Int,
        techniqueRunID: Int,
        status: String,
        revision: Int,
        orientationConfirmed: Bool,
        frameConfirmed: Bool,
        realityConfirmed: Bool,
        stopSignal: String,
        consentAt: String?
    ) {
        self.id = id
        self.techniqueRunID = techniqueRunID
        self.status = status
        self.revision = revision
        self.orientationConfirmed = orientationConfirmed
        self.frameConfirmed = frameConfirmed
        self.realityConfirmed = realityConfirmed
        self.stopSignal = stopSignal
        self.consentAt = consentAt
    }

    private enum CodingKeys: String, CodingKey {
        case id, status, revision, orientationConfirmed, frameConfirmed
        case realityConfirmed, stopSignal, consentAt
        // APIClient's decoder converts `technique_run_id` to this spelling.
        case techniqueRunID = "techniqueRunId"
    }
}

public struct FreudImagerySelection: Decodable, Equatable, Sendable {
    public let id: Int
    public let status: String
    public let revision: Int
    public let stepData: FreudImageryStepData
    public let card: FreudImageryCard
    public let created: String
    public let updated: String

    public init(
        id: Int,
        status: String,
        revision: Int,
        stepData: FreudImageryStepData,
        card: FreudImageryCard,
        created: String,
        updated: String
    ) {
        self.id = id
        self.status = status
        self.revision = revision
        self.stepData = stepData
        self.card = card
        self.created = created
        self.updated = updated
    }
}

public struct FreudImageryStepData: Decodable, Equatable, Sendable {
    public let cardID: String
    public let association: String

    public init(cardID: String, association: String) {
        self.cardID = cardID
        self.association = association
    }

    private enum CodingKeys: String, CodingKey {
        // APIClient's decoder converts `card_id` to this spelling.
        case cardID = "cardId"
        case association
    }
}

public struct FreudImageryCapabilities: Decodable, Equatable, Sendable {
    public let consent: Bool
    public let suggest: Bool
    public let select: Bool
    public let clear: Bool
    public let undo: Bool
    public let stop: Bool

    public init(
        consent: Bool,
        suggest: Bool,
        select: Bool,
        clear: Bool,
        undo: Bool,
        stop: Bool
    ) {
        self.consent = consent
        self.suggest = suggest
        self.select = select
        self.clear = clear
        self.undo = undo
        self.stop = stop
    }
}

/// The associated values make it impossible to accidentally attach a card or
/// private association to consent, clear, undo or stop requests.
public enum FreudImagerySelectionMutation: Equatable, Sendable {
    case consent(
        conversationID: Int,
        requestID: String,
        orientationConfirmed: Bool,
        frameConfirmed: Bool,
        realityConfirmed: Bool,
        stopSignal: String
    )
    case select(
        conversationID: Int,
        requestID: String,
        revision: Int,
        cardID: String,
        association: String
    )
    case clear(conversationID: Int, requestID: String, revision: Int)
    case undo(conversationID: Int, requestID: String, revision: Int)
    case stop(conversationID: Int, requestID: String, revision: Int)
}

public struct FreudImagerySuggestionMutation: Equatable, Sendable {
    public let conversationID: Int
    public let requestID: String
    public let revision: Int
    public let modelConsent: Bool

    public init(
        conversationID: Int,
        requestID: String,
        revision: Int,
        modelConsent: Bool
    ) {
        self.conversationID = conversationID
        self.requestID = requestID
        self.revision = revision
        self.modelConsent = modelConsent
    }
}

public struct FreudImageryMutationResponse: Decodable, Equatable, Sendable {
    public let ok: Bool
    public let duplicate: Bool
    public let selected: Bool?
    public let imagery: FreudImageryWorkspace

    public init(
        ok: Bool,
        duplicate: Bool,
        selected: Bool? = nil,
        imagery: FreudImageryWorkspace
    ) {
        self.ok = ok
        self.duplicate = duplicate
        self.selected = selected
        self.imagery = imagery
    }
}

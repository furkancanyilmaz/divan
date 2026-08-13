import Foundation

// Divan'ın "defter" yüzeyleri: seans notları, damıtılmış formülasyonlar,
// veda mektupları, sevkler, rüya defteri ve tam metin arama.
//
// Hepsi salt okunur birikimlerdir: kullanıcı bunları düzenlemez, ustalar
// seans sonrası arka planda üretir. Bu yüzden modeller değişmez (`let`).

public struct LibraryNote: Identifiable, Equatable, Sendable {
    public let id: Int
    public let conversationID: Int
    public let conversationTitle: String
    public let content: String
    public let createdAt: String

    public init(
        id: Int, conversationID: Int, conversationTitle: String,
        content: String, createdAt: String
    ) {
        self.id = id
        self.conversationID = conversationID
        self.conversationTitle = conversationTitle
        self.content = content
        self.createdAt = createdAt
    }
}

/// Notlar biriktikçe ustanın damıttığı kalıcı vaka formülasyonu.
public struct LibraryFormulation: Identifiable, Equatable, Sendable {
    public let id: Int
    public let content: String
    public let createdAt: String
    public let noteCount: Int

    public init(id: Int, content: String, createdAt: String, noteCount: Int) {
        self.id = id
        self.content = content
        self.createdAt = createdAt
        self.noteCount = noteCount
    }
}

public struct LibraryNotebook: Equatable, Sendable {
    public let notes: [LibraryNote]
    public let formulations: [LibraryFormulation]

    public init(notes: [LibraryNote], formulations: [LibraryFormulation]) {
        self.notes = notes
        self.formulations = formulations
    }

    public var isEmpty: Bool { notes.isEmpty && formulations.isEmpty }
}

/// Seans sonunda ustanın danışanına yazdığı kısa mektup.
public struct LibraryLetter: Identifiable, Equatable, Sendable {
    public let id: Int
    public let conversationID: Int
    public let conversationTitle: String
    public let masterID: String
    public let content: String
    public let createdAt: String

    public init(
        id: Int, conversationID: Int, conversationTitle: String,
        masterID: String, content: String, createdAt: String
    ) {
        self.id = id
        self.conversationID = conversationID
        self.conversationTitle = conversationTitle
        self.masterID = masterID
        self.content = content
        self.createdAt = createdAt
    }
}

/// Usta değişiminde eski ustanın yenisine yazdığı devir mektubu.
public struct LibraryReferral: Identifiable, Equatable, Sendable {
    public let id: Int
    public let fromMasterID: String
    public let toMasterID: String
    public let content: String
    public let createdAt: String

    public init(
        id: Int, fromMasterID: String, toMasterID: String,
        content: String, createdAt: String
    ) {
        self.id = id
        self.fromMasterID = fromMasterID
        self.toMasterID = toMasterID
        self.content = content
        self.createdAt = createdAt
    }
}

public struct LibraryLetters: Equatable, Sendable {
    public let letters: [LibraryLetter]
    public let referrals: [LibraryReferral]

    public init(letters: [LibraryLetter], referrals: [LibraryReferral]) {
        self.letters = letters
        self.referrals = referrals
    }

    public var isEmpty: Bool { letters.isEmpty && referrals.isEmpty }
}

public struct LibraryDream: Identifiable, Equatable, Sendable {
    public let text: String
    public let conversationTitle: String
    public let masterID: String
    public let createdAt: String

    public var id: String { createdAt + text.prefix(24) }

    public init(
        text: String, conversationTitle: String,
        masterID: String, createdAt: String
    ) {
        self.text = text
        self.conversationTitle = conversationTitle
        self.masterID = masterID
        self.createdAt = createdAt
    }
}

public struct LibraryDreamJournal: Equatable, Sendable {
    public let dreams: [LibraryDream]
    /// Ustanın rüya motifleri üzerine yorumu; henüz istenmediyse boştur.
    public let analysis: String

    public init(dreams: [LibraryDream], analysis: String) {
        self.dreams = dreams
        self.analysis = analysis
    }
}

public struct LibrarySearchHit: Identifiable, Equatable, Sendable {
    public let messageID: Int?
    public let conversationID: Int
    public let conversationTitle: String
    public let snippet: String
    public let masterID: String
    public let createdAt: String
    /// Eşleşme bir mesajda değil, ustanın seans notunda bulunduysa.
    public let isNote: Bool

    public var id: String {
        "\(conversationID)-\(messageID ?? 0)-\(isNote)-\(createdAt)"
    }

    public init(
        messageID: Int?, conversationID: Int, conversationTitle: String,
        snippet: String, masterID: String, createdAt: String, isNote: Bool
    ) {
        self.messageID = messageID
        self.conversationID = conversationID
        self.conversationTitle = conversationTitle
        self.snippet = snippet
        self.masterID = masterID
        self.createdAt = createdAt
        self.isNote = isNote
    }
}

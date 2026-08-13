import Foundation

// Defter, mektup, rüya, arama ve profil uçlarının tel biçimleri.
// Bu yüzeyler web arayüzünde vardı ama native uygulamada eksikti.

struct ProfileWire: Decodable {
    let profile: String?
}

struct NoteWire: Decodable {
    let id: Int?
    let conv: Int?
    let mode: String?
    let content: String?
    let created: String?
    let title: String?

    var model: LibraryNote {
        LibraryNote(
            id: id ?? 0,
            conversationID: conv ?? 0,
            conversationTitle: title ?? "",
            content: content ?? "",
            createdAt: created ?? ""
        )
    }
}

struct FormulationWire: Decodable {
    let id: Int?
    let content: String?
    let created: String?
    let noteCount: Int?

    var model: LibraryFormulation {
        LibraryFormulation(
            id: id ?? 0,
            content: content ?? "",
            createdAt: created ?? "",
            noteCount: noteCount ?? 0
        )
    }
}

struct NotesResponseWire: Decodable {
    let notes: [NoteWire]?
    let formulations: [FormulationWire]?

    var model: LibraryNotebook {
        LibraryNotebook(
            notes: (notes ?? []).map(\.model),
            formulations: (formulations ?? []).map(\.model)
        )
    }
}

struct LetterWire: Decodable {
    let id: Int?
    let conv: Int?
    let therapist: String?
    let content: String?
    let created: String?
    let title: String?

    var model: LibraryLetter {
        LibraryLetter(
            id: id ?? 0,
            conversationID: conv ?? 0,
            conversationTitle: title ?? "",
            masterID: therapist ?? "",
            content: content ?? "",
            createdAt: created ?? ""
        )
    }
}

struct ReferralWire: Decodable {
    let id: Int?
    let fromT: String?
    let toT: String?
    let content: String?
    let created: String?

    var model: LibraryReferral {
        LibraryReferral(
            id: id ?? 0,
            fromMasterID: fromT ?? "",
            toMasterID: toT ?? "",
            content: content ?? "",
            createdAt: created ?? ""
        )
    }
}

struct LettersResponseWire: Decodable {
    let letters: [LetterWire]?
    let referrals: [ReferralWire]?

    var model: LibraryLetters {
        LibraryLetters(
            letters: (letters ?? []).map(\.model),
            referrals: (referrals ?? []).map(\.model)
        )
    }
}

struct DreamWire: Decodable {
    let content: String?
    let created: String?
    let title: String?
    let therapist: String?

    var model: LibraryDream {
        // Çekirdek rüya mesajlarını "🌙 [Rüya]" önekiyle saklar; kullanıcıya
        // gösterirken bu teknik işaret ayıklanır.
        let raw = (content ?? "").replacingOccurrences(
            of: "🌙 [Rüya]", with: "")
        return LibraryDream(
            text: raw.trimmingCharacters(in: .whitespacesAndNewlines),
            conversationTitle: title ?? "",
            masterID: therapist ?? "",
            createdAt: created ?? ""
        )
    }
}

struct DreamsResponseWire: Decodable {
    let dreams: [DreamWire]?
    let analysis: String?

    var model: LibraryDreamJournal {
        LibraryDreamJournal(
            dreams: (dreams ?? []).map(\.model),
            analysis: analysis ?? ""
        )
    }
}

struct SearchHitWire: Decodable {
    let messageId: Int?
    let conv: Int?
    let title: String?
    let snippet: String?
    let created: String?
    let kind: String?
    let therapist: String?
    let mode: String?

    var model: LibrarySearchHit {
        LibrarySearchHit(
            messageID: messageId,
            conversationID: conv ?? 0,
            conversationTitle: title ?? "",
            snippet: snippet ?? "",
            masterID: therapist ?? "",
            createdAt: created ?? "",
            isNote: (kind ?? "") == "not"
        )
    }
}

struct SearchResponseWire: Decodable {
    let results: [SearchHitWire]?

    var model: [LibrarySearchHit] { (results ?? []).map(\.model) }
}

import Foundation

// Defter yüzeylerinin uçları. Temel sohbet istemcisiyle aynı kimlik
// doğrulamalı loopback oturumunu kullanır.
public extension APIClient {

    /// Kullanıcının kalıcı "Hakkımda" metni. Her ustanın her görüşmede
    /// bildiği sabit bilgidir; sistem istemine eklenir.
    func profileText() async throws -> String {
        let response: ProfileWire = try await get("/api/profile")
        return response.profile ?? ""
    }

    func updateProfileText(_ text: String) async throws {
        // Sunucu 5.000 karakterde kırpıyor; burada da aynı sınırı uygularız
        // ki kullanıcı sessizce veri kaybetmesin.
        // Profil boş bırakılabilir; sunucu 5.000 karakterde kırptığı için
        // aynı sınırı burada uygulayıp sessiz veri kaybını önlüyoruz.
        let value = String(
            text.trimmingCharacters(in: .whitespacesAndNewlines).prefix(5_000))
        let _: OKResponse = try await post(
            "/api/profile", body: ["profile": .string(value)]
        )
    }

    /// Bir ustanın seans notları ve damıtılmış formülasyonları.
    func notebook(
        masterID: String,
        mode: String
    ) async throws -> LibraryNotebook {
        let master = try LibraryInput.masterID(masterID)
        let response: NotesResponseWire = try await get(
            "/api/notes",
            query: [
                URLQueryItem(name: "therapist", value: master),
                URLQueryItem(name: "mode", value: mode),
            ]
        )
        return response.model
    }

    /// Ustanın veda mektupları ve varsa sevk mektupları.
    func letters(masterID: String) async throws -> LibraryLetters {
        let master = try LibraryInput.masterID(masterID)
        let response: LettersResponseWire = try await get(
            "/api/letters",
            query: [URLQueryItem(name: "therapist", value: master)]
        )
        return response.model
    }

    /// Rüya defteri ve varsa motif yorumu.
    func dreamJournal(masterID: String) async throws -> LibraryDreamJournal {
        let master = try LibraryInput.masterID(masterID)
        let response: DreamsResponseWire = try await get(
            "/api/dreams",
            query: [URLQueryItem(name: "therapist", value: master)]
        )
        return response.model
    }

    /// Rüya motiflerini ustaya yorumlatır. Model çağrısı içerdiği için
    /// yavaştır; çağıran tarafta ilerleme göstergesi beklenir.
    func analyzeDreams(masterID: String) async throws -> String {
        let master = try LibraryInput.masterID(masterID)
        let response: DreamsAnalysisWire = try await post(
            "/api/dreams/analyze",
            body: ["therapist": .string(master)],
            timeout: 600
        )
        return response.answer ?? ""
    }

    /// Tüm görüşmelerde mesaj ve not araması.
    func search(_ term: String) async throws -> [LibrarySearchHit] {
        let query = term.trimmingCharacters(in: .whitespacesAndNewlines)
        // Sunucu iki karakterin altını boş sonuç sayıyor; ağı meşgul etmeyelim.
        guard query.count >= 2 else { return [] }
        let value = String(query.prefix(200))
        let response: SearchResponseWire = try await get(
            "/api/search", query: [URLQueryItem(name: "q", value: value)]
        )
        return response.model
    }
}

/// Defter uçlarının girdi doğrulaması.
///
/// `APIClient`'ın kendi yardımcıları `private extension` içinde olduğu için
/// burada ayrı ve dar kapsamlı bir doğrulayıcı tutuyoruz.
enum LibraryInput {
    static func masterID(_ value: String) throws -> String {
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, trimmed.count <= 64,
              trimmed.unicodeScalars.allSatisfy({ scalar in
                  (48...57).contains(scalar.value)
                      || (65...90).contains(scalar.value)
                      || (97...122).contains(scalar.value)
                      || scalar == "_" || scalar == "-"
              })
        else {
            throw DivanAPIError(
                message: "Usta kimliği geçersiz.",
                errorCode: "invalid_request")
        }
        return trimmed
    }
}

struct DreamsAnalysisWire: Decodable {
    let answer: String?
}

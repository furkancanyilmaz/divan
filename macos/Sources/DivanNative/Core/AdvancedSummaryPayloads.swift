import Foundation

// Bu dosya `AdvancedAPIPayloads.swift`'ten ayrıldı: 1214 satırlık
// tek dosya, alan sınırları zaten `// MARK` ile çizilmiş 53 tel
// tipini barındırıyordu. Tipler değişmedi, yalnızca yerleşimleri
// alanlarına göre ayrıldı.
// Seans özeti tel biçimleri.

// MARK: - Session summary

struct SessionSummaryWire: Decodable {
    let conv: Int?
    let draft: String?
    let approvedContent: String?
    let status: String?
    let created: String?
    let approvedAt: String?
    let updated: String?

    var model: SessionSummaryRecord {
        SessionSummaryRecord(
            conversationID: conv ?? 0,
            draft: draft ?? "",
            approvedContent: approvedContent ?? "",
            status: SessionSummaryStatus(rawValue: status ?? "pending")
                ?? .pending,
            approvedAt: approvedAt ?? "",
            updatedAt: updated ?? ""
        )
    }
}

struct SessionSummaryResponseWire: Decodable {
    let summary: SessionSummaryWire?

    var model: SessionSummaryRecord? {
        // Sunucu taslak yoksa boş sözlük döndürür; bu, "özet henüz
        // hazırlanmadı" demektir ve hata değildir.
        guard let summary, summary.conv != nil else { return nil }
        return summary.model
    }
}

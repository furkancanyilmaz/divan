import Foundation
import SwiftUI

@MainActor
public final class FreudImageryWorkspaceViewModel: ObservableObject {
    public static let realityConsentStatement =
        "Bir çağrışım yaşanmış bir olayın tarihsel kanıtı, kesin anısı veya bastırılmış bir anının deşifresi değildir."

    public let conversationID: Int

    @Published public private(set) var snapshot: FreudImageryWorkspace?
    @Published public private(set) var isBusy = false
    @Published public private(set) var operationDescription = ""
    @Published public var failure: StructuredWorkspaceFailure?
    @Published public var statusMessage = ""

    @Published public var orientationConfirmed = false
    @Published public var frameConfirmed = false
    @Published public var realityConfirmed = false
    @Published public var stopSignal = "Dur"
    @Published public var modelConsent = false
    @Published public private(set) var selectedCardID: String?
    @Published public var associationDraft = ""

    private struct PendingRequest: Sendable {
        let fingerprint: String
        let id: String
    }

    private let dataSource: any StructuredTherapyDataSource
    private var hasLoaded = false
    private var pendingRequests: [String: PendingRequest] = [:]

    public init(
        dataSource: any StructuredTherapyDataSource,
        conversationID: Int
    ) {
        self.dataSource = dataSource
        self.conversationID = conversationID
    }

    public var selectedCard: FreudImageryCard? {
        guard let selectedCardID else { return nil }
        return snapshot?.cards.first { $0.id == selectedCardID }
    }

    public var suggestedCardIDs: Set<String> {
        Set((snapshot?.suggestions ?? []).prefix(3).map(\.id))
    }

    public var normalizedStopSignal: String {
        stopSignal.split(whereSeparator: \.isWhitespace).joined(separator: " ")
    }

    public var canConsent: Bool {
        snapshot?.capabilities.consent == true
            && orientationConfirmed
            && frameConfirmed
            && realityConfirmed
            && (2...24).contains(normalizedStopSignal.count)
            && !isBusy
    }

    public var canSuggest: Bool {
        snapshot?.capabilities.suggest == true
            && snapshot?.session != nil
            && modelConsent
            && !isBusy
    }

    public var canSaveAssociation: Bool {
        let text = associationDraft.trimmingCharacters(in: .whitespacesAndNewlines)
        return snapshot?.capabilities.select == true
            && selectedCard != nil
            && !text.isEmpty
            && text.count <= 2_400
            && !isBusy
    }

    public var associationCharacterCount: Int { associationDraft.count }

    public func loadIfNeeded() async {
        guard !hasLoaded else { return }
        await reload()
    }

    public func reload() async {
        guard !isBusy else { return }
        isBusy = true
        operationDescription = "Görsel kart destesi yükleniyor…"
        failure = nil
        defer {
            isBusy = false
            operationDescription = ""
        }
        do {
            let value = try await dataSource.freudImagery(
                conversationID: conversationID
            )
            apply(value, preserveUnsavedDraft: false)
            hasLoaded = true
        } catch {
            failure = Self.failure("Görsel çalışma açılamadı", error)
        }
    }

    public func consent() async {
        guard canConsent else {
            failure = .init(
                title: "Açık onay gerekli",
                message: "Yönelimi, çalışma çerçevesini ve gerçeklik ayrımını ayrı ayrı doğrulayın; 2–24 karakterlik bir durma sözcüğü belirleyin."
            )
            return
        }
        let fingerprint = [
            "consent", String(orientationConfirmed), String(frameConfirmed),
            String(realityConfirmed), normalizedStopSignal,
        ].joined(separator: "|")
        let mutation = FreudImagerySelectionMutation.consent(
            conversationID: conversationID,
            requestID: requestID(
                operation: "consent",
                fingerprint: fingerprint,
                prefix: "native-freud-consent"
            ),
            orientationConfirmed: orientationConfirmed,
            frameConfirmed: frameConfirmed,
            realityConfirmed: realityConfirmed,
            stopSignal: normalizedStopSignal
        )
        await perform(
            "Çalışma çerçevesi kaydediliyor…",
            operation: "consent",
            fingerprint: fingerprint
        ) {
            let response = try await dataSource.mutateFreudImagerySelection(mutation)
            apply(response.imagery, preserveUnsavedDraft: false)
            orientationConfirmed = false
            frameConfirmed = false
            realityConfirmed = false
            statusMessage = "Çalışma çerçevesi kaydedildi. Kartlara hazır olduğunuz hızda bakabilirsiniz."
        }
    }

    public func chooseCard(_ card: FreudImageryCard) {
        guard snapshot?.capabilities.select == true,
              snapshot?.cards.contains(where: { $0.id == card.id }) == true else {
            return
        }
        if selectedCardID != card.id {
            selectedCardID = card.id
            associationDraft = snapshot?.selection?.stepData.cardID == card.id
                ? snapshot?.selection?.stepData.association ?? ""
                : ""
        }
        statusMessage = "\(card.title) seçildi. Çağrışımınız yalnız Kaydet düğmesine bastığınızda saklanır."
    }

    public func discardUnsavedDraft() {
        if let selection = snapshot?.selection {
            selectedCardID = selection.stepData.cardID
            associationDraft = selection.stepData.association
        } else {
            selectedCardID = nil
            associationDraft = ""
        }
        statusMessage = "Kaydedilmemiş değişiklikler bırakıldı."
    }

    public func saveAssociation() async {
        guard canSaveAssociation,
              let session = snapshot?.session,
              let cardID = selectedCardID else {
            failure = .init(
                title: "Kart ve çağrışım gerekli",
                message: "Bir kartı kendiniz seçin, ilk çağrışımınızı yazın ve ardından Kaydet’e basın."
            )
            return
        }
        let association = associationDraft.trimmingCharacters(
            in: .whitespacesAndNewlines
        )
        let fingerprint = [
            "select", String(session.revision), cardID, association,
        ].joined(separator: "|")
        let mutation = FreudImagerySelectionMutation.select(
            conversationID: conversationID,
            requestID: requestID(
                operation: "select",
                fingerprint: fingerprint,
                prefix: "native-freud-select"
            ),
            revision: session.revision,
            cardID: cardID,
            association: association
        )
        await perform(
            "Çağrışımınız kaydediliyor…",
            operation: "select",
            fingerprint: fingerprint
        ) {
            let response = try await dataSource.mutateFreudImagerySelection(mutation)
            apply(response.imagery, preserveUnsavedDraft: false)
            statusMessage = "Kendi çağrışımınız kaydedildi; karta bir anlam veya tanı eklenmedi."
        }
    }

    public func clearSelection() async {
        await redactSelection(action: "clear")
    }

    public func undoSelection() async {
        await redactSelection(action: "undo")
    }

    public func stop() async {
        guard let session = snapshot?.session,
              snapshot?.capabilities.stop == true else { return }
        let fingerprint = "stop|\(session.revision)"
        let mutation = FreudImagerySelectionMutation.stop(
            conversationID: conversationID,
            requestID: requestID(
                operation: "stop",
                fingerprint: fingerprint,
                prefix: "native-freud-stop"
            ),
            revision: session.revision
        )
        await perform(
            "Görsel çalışma durduruluyor…",
            operation: "stop",
            fingerprint: fingerprint
        ) {
            let response = try await dataSource.mutateFreudImagerySelection(mutation)
            apply(response.imagery, preserveUnsavedDraft: false)
            modelConsent = false
            statusMessage = "Görsel çalışma durduruldu ve kayıtlı çağrışım metni temizlendi."
        }
    }

    public func requestSuggestions() async {
        guard canSuggest, let session = snapshot?.session else {
            failure = .init(
                title: "Model gönderimi için açık onay gerekli",
                message: "Yalnız son kullanıcı mesajınızın kart kimliği önerisi için seçili modele gönderileceğini onaylayın."
            )
            return
        }
        let fingerprint = "suggest|\(session.revision)|model-consent"
        let mutation = FreudImagerySuggestionMutation(
            conversationID: conversationID,
            requestID: requestID(
                operation: "suggest",
                fingerprint: fingerprint,
                prefix: "native-freud-suggest"
            ),
            revision: session.revision,
            modelConsent: true
        )
        await perform(
            "En fazla üç kart önerisi alınıyor…",
            operation: "suggest",
            fingerprint: fingerprint
        ) {
            let response = try await dataSource.suggestFreudImagery(mutation)
            // A model result may only annotate the deck. Never replace the
            // user's local or durable selection with a suggestion.
            apply(response.imagery, preserveUnsavedDraft: true)
            modelConsent = false
            statusMessage = "Öneriler geldi; hiçbir kart seçilmedi. Seçim yalnız size ait."
        }
    }

    public func dismissFailure() {
        failure = nil
    }

    private func redactSelection(action: String) async {
        guard let session = snapshot?.session else { return }
        let allowed = action == "clear"
            ? snapshot?.capabilities.clear == true
            : snapshot?.capabilities.undo == true
        guard allowed else { return }
        let fingerprint = "\(action)|\(session.revision)"
        let id = requestID(
            operation: action,
            fingerprint: fingerprint,
            prefix: "native-freud-\(action)"
        )
        let mutation: FreudImagerySelectionMutation = action == "clear"
            ? .clear(
                conversationID: conversationID,
                requestID: id,
                revision: session.revision
            )
            : .undo(
                conversationID: conversationID,
                requestID: id,
                revision: session.revision
            )
        await perform(
            action == "clear" ? "Kayıt temizleniyor…" : "Kayıt geri alınıyor…",
            operation: action,
            fingerprint: fingerprint
        ) {
            let response = try await dataSource.mutateFreudImagerySelection(mutation)
            apply(response.imagery, preserveUnsavedDraft: false)
            statusMessage = action == "clear"
                ? "Kart ve çağrışım kaydı temizlendi."
                : "Son kart ve çağrışım kaydı geri alındı."
        }
    }

    private func perform(
        _ description: String,
        operation: String,
        fingerprint: String,
        action: () async throws -> Void
    ) async {
        guard !isBusy else { return }
        isBusy = true
        operationDescription = description
        failure = nil
        defer {
            isBusy = false
            operationDescription = ""
        }
        do {
            try await action()
            if pendingRequests[operation]?.fingerprint == fingerprint {
                pendingRequests[operation] = nil
            }
        } catch {
            failure = Self.failure("İşlem tamamlanamadı", error)
            if Self.isSafetyHoldError(error),
               let redacted = try? await dataSource.freudImagery(
                    conversationID: conversationID
               ) {
                apply(redacted, preserveUnsavedDraft: false)
                modelConsent = false
            }
        }
    }

    private static func isSafetyHoldError(_ error: Error) -> Bool {
        guard let api = error as? DivanAPIError else { return false }
        if api.errorCode == "safety_hold" { return true }
        let folded = api.localizedDescription.folding(
            options: [.diacriticInsensitive, .caseInsensitive],
            locale: Locale(identifier: "tr_TR")
        )
        return api.statusCode == 409 && folded.contains("guvenlik destegi")
    }

    private func requestID(
        operation: String,
        fingerprint: String,
        prefix: String
    ) -> String {
        if let pending = pendingRequests[operation],
           pending.fingerprint == fingerprint {
            return pending.id
        }
        let id = prefix + "-" + UUID().uuidString.lowercased()
        pendingRequests[operation] = PendingRequest(
            fingerprint: fingerprint,
            id: id
        )
        return id
    }

    private func apply(
        _ value: FreudImageryWorkspace,
        preserveUnsavedDraft: Bool
    ) {
        snapshot = value
        guard !preserveUnsavedDraft else { return }
        if let selection = value.selection {
            selectedCardID = selection.stepData.cardID
            associationDraft = selection.stepData.association
        } else {
            selectedCardID = nil
            associationDraft = ""
        }
    }

    private static func failure(
        _ title: String,
        _ error: Error
    ) -> StructuredWorkspaceFailure {
        let message = (error as? LocalizedError)?.errorDescription
            ?? error.localizedDescription
        return .init(
            title: title,
            message: message.isEmpty ? "Beklenmeyen bir sorun oluştu." : message
        )
    }
}

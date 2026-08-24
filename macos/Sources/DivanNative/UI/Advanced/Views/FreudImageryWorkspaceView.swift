import AppKit
import SwiftUI

public struct FreudImageryWorkspaceView: View {
    @StateObject private var model: FreudImageryWorkspaceViewModel
    private let dataSource: any StructuredTherapyDataSource
    @State private var stopConfirmationPresented = false

    public init(
        dataSource: any StructuredTherapyDataSource,
        conversationID: Int
    ) {
        self.dataSource = dataSource
        _model = StateObject(wrappedValue: FreudImageryWorkspaceViewModel(
            dataSource: dataSource,
            conversationID: conversationID
        ))
    }

    public init(
        model: FreudImageryWorkspaceViewModel,
        dataSource: any StructuredTherapyDataSource
    ) {
        self.dataSource = dataSource
        _model = StateObject(wrappedValue: model)
    }

    public var body: some View {
        ZStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    if let failure = model.failure {
                        StructuredWorkspaceFailureBanner(
                            failure: failure,
                            dismiss: model.dismissFailure
                        )
                    }
                    if let workspace = model.snapshot {
                        methodHeader(workspace)
                        if workspace.available {
                            if workspace.capabilities.consent {
                                consentPanel(workspace)
                            } else if workspace.session != nil {
                                activeWorkspace(workspace)
                            } else {
                                blockedPanel(reason: "technique_consent_required")
                            }
                        } else {
                            blockedPanel(reason: workspace.blockedReason)
                        }
                    } else if !model.isBusy {
                        StructuredWorkspaceCard {
                            Label("Görsel kart destesi alınamadı", systemImage: "photo.on.rectangle.angled")
                                .font(.headline)
                            Button("Yeniden dene") { Task { await model.reload() } }
                        }
                    }
                    if !model.statusMessage.isEmpty {
                        Label(model.statusMessage, systemImage: "checkmark.circle")
                            .font(.callout)
                            .foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                            .accessibilityIdentifier("freudImagery.status")
                    }
                }
                .padding(16)
                .frame(maxWidth: 1_080, alignment: .leading)
                .frame(maxWidth: .infinity, alignment: .top)
            }
            if model.isBusy {
                VStack(spacing: 9) {
                    ProgressView()
                    Text(model.operationDescription)
                        .font(.callout)
                }
                .padding(18)
                .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 12))
                .accessibilityElement(children: .combine)
                .accessibilityLabel(model.operationDescription)
                .accessibilityIdentifier("freudImagery.loading")
            }
        }
        .task { await model.loadIfNeeded() }
        .alert("Görsel çalışma durdurulsun mu?", isPresented: $stopConfirmationPresented) {
            Button("Vazgeç", role: .cancel) {}
            Button("Durdur ve çağrışımı temizle", role: .destructive) {
                Task { await model.stop() }
            }
        } message: {
            Text("Çalışma kapanır; kayıtlı kart ve çağrışım metni fiziksel olarak temizlenir.")
        }
        .accessibilityIdentifier("freudImagery.workspace")
    }

    private func methodHeader(_ workspace: FreudImageryWorkspace) -> some View {
        StructuredWorkspaceCard {
            HStack(alignment: .top, spacing: 12) {
                Image(systemName: "photo.on.rectangle.angled")
                    .font(.title2)
                    .foregroundStyle(DivanPalette.wine)
                    .accessibilityHidden(true)
                VStack(alignment: .leading, spacing: 5) {
                    Text(workspace.method.title)
                        .font(.title3.weight(.semibold))
                    Text(workspace.method.description)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                    Text("Kartlar yalnız görünen sahneyi betimler. Anlamı, çağrışımı ve seçim tamamen size aittir.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: 8)
                Button {
                    Task { await model.reload() }
                } label: {
                    Image(systemName: "arrow.clockwise")
                }
                .buttonStyle(.plain)
                .disabled(model.isBusy)
                .help("Görsel çalışma durumunu yenile")
                .accessibilityLabel("Görsel çalışma durumunu yenile")
            }
        }
    }

    private func consentPanel(_ workspace: FreudImageryWorkspace) -> some View {
        StructuredWorkspaceCard {
            Label("Çalışma çerçevesi", systemImage: "checkmark.shield")
                .font(.headline)
            Text("Bu bir projektif test veya Rorschach değildir. İstediğiniz an durabilir; kart seçmeden de çıkabilirsiniz.")
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            Toggle(
                "Şu anda bulunduğum yeri ve zamanı biliyorum.",
                isOn: $model.orientationConfirmed
            )
            Toggle(
                "Kartların yalnız görünen sahneyi sunduğunu; tanı veya gizli anlam vermediğini anlıyorum.",
                isOn: $model.frameConfirmed
            )
            Toggle(
                FreudImageryWorkspaceViewModel.realityConsentStatement,
                isOn: $model.realityConfirmed
            )
            VStack(alignment: .leading, spacing: 5) {
                Text("Durma sözcüğünüz")
                    .font(.caption.weight(.semibold))
                TextField("Örn. Dur", text: $model.stopSignal)
                    .textFieldStyle(.roundedBorder)
                    .accessibilityLabel("Görsel çalışma durma sözcüğü")
                Text("2–24 karakter. Bu sözcüğü söylediğinizde çalışma durur.")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
            HStack {
                Spacer()
                Button("Onayla ve kartları aç") {
                    Task { await model.consent() }
                }
                .buttonStyle(.borderedProminent)
                .disabled(!model.canConsent)
                .accessibilityIdentifier("freudImagery.consent")
            }
            .accessibilityElement(children: .contain)
            .accessibilityLabel("Görsel kart çalışma onayı")
        }
    }

    @ViewBuilder
    private func activeWorkspace(_ workspace: FreudImageryWorkspace) -> some View {
        activeControls(workspace)
        suggestionPanel(workspace)
        deckPanel(workspace)
        if model.selectedCard != nil {
            associationPanel(workspace)
        }
    }

    private func activeControls(_ workspace: FreudImageryWorkspace) -> some View {
        StructuredWorkspaceCard {
            ViewThatFits(in: .horizontal) {
                HStack(spacing: 12) {
                    activeSessionText(workspace)
                    Spacer(minLength: 8)
                    stopButton(workspace)
                }
                VStack(alignment: .leading, spacing: 10) {
                    activeSessionText(workspace)
                    stopButton(workspace)
                }
            }
        }
    }

    private func activeSessionText(_ workspace: FreudImageryWorkspace) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Text("Kart destesi açık")
                .font(.headline)
            Text("Durma sözcüğü: \(workspace.session?.stopSignal ?? "—")")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }

    private func stopButton(_ workspace: FreudImageryWorkspace) -> some View {
        Button("Çalışmayı durdur", role: .destructive) {
            stopConfirmationPresented = true
        }
        .disabled(!workspace.capabilities.stop || model.isBusy)
        .accessibilityIdentifier("freudImagery.stop")
    }

    private func suggestionPanel(_ workspace: FreudImageryWorkspace) -> some View {
        StructuredWorkspaceCard {
            Label("İsteğe bağlı kart önerisi", systemImage: "sparkles")
                .font(.headline)
            Text("Açık onay verirseniz yalnız son kullanıcı mesajınız, en fazla üç kart kimliği önermek için seçili modele gönderilir. Model hiçbir kartı seçemez ve karta anlam yükleyemez.")
                .font(.callout)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            Toggle(
                "Bu tek öneri isteği için son mesajımın seçili modele gönderilmesini onaylıyorum.",
                isOn: $model.modelConsent
            )
            .disabled(!workspace.capabilities.suggest || model.isBusy)
            HStack {
                Button("En fazla 3 kart öner") {
                    Task { await model.requestSuggestions() }
                }
                .disabled(!model.canSuggest)
                .accessibilityIdentifier("freudImagery.suggest")
                Spacer()
                Text("Öneri seçim değildir")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            if !workspace.suggestions.isEmpty {
                Divider()
                Text(workspace.suggestionQuestion)
                    .font(.callout.weight(.medium))
                    .fixedSize(horizontal: false, vertical: true)
                FlowingSuggestionLabels(cards: Array(workspace.suggestions.prefix(3)))
            }
        }
    }

    private func deckPanel(_ workspace: FreudImageryWorkspace) -> some View {
        StructuredWorkspaceCard {
            Text("24 kart")
                .font(.headline)
            Text("Bir kartı tıklamak yalnız düzenleme alanına getirir; çağrışımınız ayrıca Kaydet’e basmadan saklanmaz.")
                .font(.caption)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            LazyVGrid(
                columns: [GridItem(.adaptive(minimum: 210, maximum: 310), spacing: 12)],
                alignment: .leading,
                spacing: 12
            ) {
                ForEach(workspace.cards) { card in
                    FreudImageryCardButton(
                        card: card,
                        selected: model.selectedCardID == card.id,
                        suggested: model.suggestedCardIDs.contains(card.id),
                        dataSource: dataSource,
                        action: { model.chooseCard(card) }
                    )
                }
            }
        }
    }

    private func associationPanel(_ workspace: FreudImageryWorkspace) -> some View {
        StructuredWorkspaceCard {
            if let card = model.selectedCard {
                Text(card.title)
                    .font(.headline)
                Text("Bu kart sende ilk olarak ne çağrıştırıyor?")
                    .foregroundStyle(.secondary)
                TextEditor(text: $model.associationDraft)
                    .font(.body)
                    .frame(minHeight: 110)
                    .padding(5)
                    .background(
                        Color(nsColor: .textBackgroundColor),
                        in: RoundedRectangle(cornerRadius: 8)
                    )
                    .overlay {
                        RoundedRectangle(cornerRadius: 8)
                            .stroke(Color(nsColor: .separatorColor))
                    }
                    .accessibilityLabel("\(card.title) için kendi çağrışımınız")
                    .accessibilityIdentifier("freudImagery.association")
                HStack(alignment: .center, spacing: 10) {
                    Text("\(model.associationCharacterCount) / 2400")
                        .font(.caption.monospacedDigit())
                        .foregroundStyle(
                            model.associationCharacterCount > 2_400 ? .red : .secondary
                        )
                    Spacer()
                    Button("Kaydedilmemiş değişikliği bırak") {
                        model.discardUnsavedDraft()
                    }
                    .disabled(model.isBusy)
                    Button("Çağrışımı kaydet") {
                        Task { await model.saveAssociation() }
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(!model.canSaveAssociation)
                    .accessibilityIdentifier("freudImagery.save")
                }
                if workspace.selection != nil {
                    Divider()
                    ViewThatFits(in: .horizontal) {
                        HStack(spacing: 10) {
                            Text("Kayıtlı kart ve metin yalnız açık işleminizle temizlenir.")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                            Spacer(minLength: 8)
                            redactionButtons(workspace)
                        }
                        VStack(alignment: .leading, spacing: 10) {
                            Text("Kayıtlı kart ve metin yalnız açık işleminizle temizlenir.")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                            redactionButtons(workspace)
                        }
                    }
                }
            }
        }
    }

    private func redactionButtons(_ workspace: FreudImageryWorkspace) -> some View {
        HStack(spacing: 8) {
            Button("Geri al") { Task { await model.undoSelection() } }
                .disabled(!workspace.capabilities.undo || model.isBusy)
                .accessibilityIdentifier("freudImagery.undo")
            Button("Temizle", role: .destructive) {
                Task { await model.clearSelection() }
            }
            .disabled(!workspace.capabilities.clear || model.isBusy)
            .accessibilityIdentifier("freudImagery.clear")
        }
    }

    private func blockedPanel(reason: String) -> some View {
        StructuredWorkspaceCard {
            Label(blockedTitle(reason), systemImage: blockedIcon(reason))
                .font(.headline)
            Text(blockedMessage(reason))
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            Button("Durumu yeniden kontrol et") {
                Task { await model.reload() }
            }
            .disabled(model.isBusy)
        }
        .accessibilityIdentifier("freudImagery.blocked")
    }

    private func blockedTitle(_ reason: String) -> String {
        switch reason {
        case "safety_hold": "Güvenlik desteği öncelikli"
        case "session_stopped": "Görsel çalışma durduruldu"
        case "catalog_unavailable": "Kart destesi doğrulanamadı"
        default: "Görsel çalışma henüz hazır değil"
        }
    }

    private func blockedMessage(_ reason: String) -> String {
        switch reason {
        case "safety_hold":
            "Güvenlik desteği sürerken kartlar ve önceki seçim görünmez. Şimdiye dönme ve gerçek destek önceliklidir."
        case "free_association_required":
            "Önce Freud görüşmesinde Serbest Çağrışım yöntemini seçin. Bu panel başka terapistte veya başka yöntemle açılmaz."
        case "technique_consent_required":
            "Önce Serbest Çağrışım yöntemi için görüşme içindeki açık onayı tamamlayın."
        case "precheck_required":
            "Önce seansın başlangıç güvenlik kontrolünü tamamlayın."
        case "session_stopped":
            "Bu kart oturumu kapandı ve kayıtlı çağrışım temizlendi. Yeniden başlamak için Serbest Çağrışım yöntemini yeni bir çalışma olarak açın."
        case "catalog_unavailable":
            "Yerel 24 kartlık allowlist ve manifest bütünlüğü doğrulanamadı. Güncel Divan paketini yeniden kurun."
        default:
            "Bu alan yalnız Freud ile açık ana terapi görüşmesinde ve etkin Serbest Çağrışım yöntemi sırasında kullanılabilir."
        }
    }

    private func blockedIcon(_ reason: String) -> String {
        reason == "safety_hold" ? "cross.case.fill" : "lock"
    }
}

private struct FreudImageryCardButton: View {
    let card: FreudImageryCard
    let selected: Bool
    let suggested: Bool
    let dataSource: any StructuredTherapyDataSource
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            VStack(alignment: .leading, spacing: 8) {
                FreudImageryCardImage(card: card, dataSource: dataSource)
                    .frame(maxWidth: .infinity)
                    .aspectRatio(3 / 2, contentMode: .fit)
                    .clipShape(RoundedRectangle(cornerRadius: 9))
                HStack(alignment: .firstTextBaseline) {
                    Text(card.title)
                        .font(.callout.weight(.semibold))
                        .foregroundStyle(.primary)
                    Spacer(minLength: 5)
                    if suggested {
                        Text("Öneri")
                            .font(.caption2.weight(.semibold))
                            .foregroundStyle(DivanPalette.wine)
                    }
                }
                Text(card.description)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .padding(10)
            .frame(maxWidth: .infinity, alignment: .topLeading)
            .background(
                selected ? DivanPalette.wine.opacity(0.10) : Color.clear,
                in: RoundedRectangle(cornerRadius: 12)
            )
            .overlay {
                RoundedRectangle(cornerRadius: 12)
                    .stroke(
                        selected ? DivanPalette.wine : Color(nsColor: .separatorColor),
                        lineWidth: selected ? 2 : 1
                    )
            }
        }
        .buttonStyle(.plain)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(card.title). \(card.description)")
        .accessibilityValue(
            selected ? "Kullanıcı tarafından seçildi" :
                suggested ? "Model önerisi; seçili değil" : "Seçili değil"
        )
        .accessibilityHint("Kartı çağrışım düzenleme alanına getirir; otomatik kaydetmez")
        .accessibilityAddTraits(selected ? .isSelected : [])
        .accessibilityIdentifier("freudImagery.card.\(card.id)")
    }
}

private struct FreudImageryCardImage: View {
    let card: FreudImageryCard
    let dataSource: any StructuredTherapyDataSource
    @State private var image: NSImage?
    @State private var failed = false

    var body: some View {
        ZStack {
            Color(nsColor: .underPageBackgroundColor)
            if let image {
                Image(nsImage: image)
                    .resizable()
                    .scaledToFill()
                    .accessibilityLabel(card.alt)
            } else if failed {
                VStack(spacing: 5) {
                    Image(systemName: "photo.badge.exclamationmark")
                    Text("Görsel yüklenemedi")
                        .font(.caption2)
                }
                .foregroundStyle(.secondary)
                .accessibilityLabel("\(card.alt). Görsel yüklenemedi")
            } else {
                ProgressView()
                    .controlSize(.small)
                    .accessibilityLabel("\(card.alt) yükleniyor")
            }
        }
        .clipped()
        .task(id: card.sha256) {
            image = nil
            failed = false
            do {
                let data = try await dataSource.freudImageryCardData(card: card)
                guard !Task.isCancelled, let decoded = NSImage(data: data) else {
                    failed = !Task.isCancelled
                    return
                }
                image = decoded
            } catch {
                if !Task.isCancelled { failed = true }
            }
        }
    }
}

private struct FlowingSuggestionLabels: View {
    let cards: [FreudImageryCard]

    var body: some View {
        ViewThatFits(in: .horizontal) {
            HStack(spacing: 8) { labels }
            VStack(alignment: .leading, spacing: 7) { labels }
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Modelin kart önerileri; hiçbir kart seçili değil")
    }

    @ViewBuilder
    private var labels: some View {
        ForEach(cards.prefix(3)) { card in
            Label(card.title, systemImage: "sparkles")
                .font(.caption)
                .padding(.horizontal, 9)
                .padding(.vertical, 6)
                .background(DivanPalette.wine.opacity(0.08), in: Capsule())
        }
    }
}

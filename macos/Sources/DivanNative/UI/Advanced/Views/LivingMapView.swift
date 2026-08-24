import SwiftUI

struct LivingMapView: View {
    @ObservedObject var model: AdvancedWorkspaceViewModel
    let schemaAnalysisDataSource: (any StructuredTherapyDataSource)?
    @State private var expandedCards: Set<String> = []

    init(
        model: AdvancedWorkspaceViewModel,
        schemaAnalysisDataSource: (any StructuredTherapyDataSource)? = nil
    ) {
        self.model = model
        self.schemaAnalysisDataSource = schemaAnalysisDataSource
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                ViewThatFits(in: .horizontal) {
                    HStack(alignment: .top, spacing: 16) {
                        livingMapHeader
                        Spacer(minLength: 12)
                        livingMapRefreshButton
                    }
                    VStack(alignment: .leading, spacing: 10) {
                        livingMapHeader
                        livingMapRefreshButton
                    }
                }

                hypothesisBoundary
                if model.context.masterID == "young",
                   let conversationID = model.context.conversationID,
                   let schemaAnalysisDataSource {
                    LivingMapTurnAnalysisPanel(
                        dataSource: schemaAnalysisDataSource,
                        conversationID: conversationID
                    )
                }
                filterBar

                if model.filteredLivingMapCards.isEmpty {
                    emptyState
                } else {
                    LazyVStack(alignment: .leading, spacing: 12) {
                        ForEach(model.filteredLivingMapCards) { card in
                            livingMapCard(card)
                        }
                    }
                }
            }
            .padding(22)
            .frame(maxWidth: 920)
            .frame(maxWidth: .infinity)
        }
    }

    private var livingMapHeader: some View {
        AdvancedSectionHeader(
            title: "Yaşayan harita",
            detail: "Tamamlanmış kullanıcı–usta mesaj çiftlerinde beliren işaretleri, mesaj dayanaklarıyla inceleyin. Her kart değişebilir bir çalışma hipotezidir; tanı değildir.",
            systemImage: "point.3.connected.trianglepath.dotted"
        )
    }

    private var livingMapRefreshButton: some View {
        Button {
            Task { await model.refreshLivingMap() }
        } label: {
            Label("Haritayı yenile", systemImage: "arrow.clockwise")
        }
        .disabled(model.isPerformingAction)
    }

    private var hypothesisBoundary: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: "checkmark.seal")
                .foregroundStyle(DivanPalette.wine)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 8) {
                    Text("Son söz sizde")
                        .font(.callout.weight(.semibold))
                    AISimulationBadge()
                }
                Text("Kartın bütünü için “uyuyor”, “kısmen”, “bağlama göre” veya “bu dayanak uygun değil” diyebilirsiniz. Karar, çalışma hipotezinin sonraki kullanımını değiştirir; kaynak konuşmayı veya geçmiş olayı silmez.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(DivanPalette.parchment.opacity(0.42), in: RoundedRectangle(cornerRadius: 10))
        .overlay {
            RoundedRectangle(cornerRadius: 10)
                .stroke(DivanPalette.gold.opacity(0.45))
        }
        .accessibilityElement(children: .combine)
    }

    private var filterBar: some View {
        HStack {
            Picker("Harita alanı", selection: $model.livingMapDomain) {
                Text("Tüm alanlar").tag(nil as WorkspaceLivingMapDomain?)
                ForEach(WorkspaceLivingMapDomain.allCases) { domain in
                    Text(domain.title).tag(Optional(domain))
                }
            }
            .pickerStyle(.menu)
            .frame(maxWidth: 260, alignment: .leading)
            Spacer()
            Text("\(model.filteredLivingMapCards.count) hipotez")
                .font(.callout.monospacedDigit())
                .foregroundStyle(.secondary)
                .accessibilityLabel("\(model.filteredLivingMapCards.count) çalışma hipotezi")
        }
    }

    private var emptyState: some View {
        VStack(spacing: 10) {
            Image(systemName: "map")
                .font(.system(size: 34, weight: .light))
                .foregroundStyle(DivanPalette.gold)
                .accessibilityHidden(true)
            Text(model.livingMapCards.isEmpty ? "Henüz harita kaydı yok" : "Bu alanda kayıt yok")
                .font(.title3.weight(.semibold))
            Text(
                model.livingMapCards.isEmpty
                    ? "Harita oluşturulduğunda her çıkarım, onu desteklediği düşünülen sohbet parçalarıyla birlikte burada görünür."
                    : "Başka bir alan seçebilir veya tüm alanları gösterebilirsiniz."
            )
            .foregroundStyle(.secondary)
            .multilineTextAlignment(.center)
            .frame(maxWidth: 500)
            if model.livingMapCards.isEmpty {
                Button("Haritayı kontrol et") {
                    Task { await model.refreshLivingMap() }
                }
                .buttonStyle(.borderedProminent)
                .tint(DivanPalette.wine)
                .disabled(model.isPerformingAction)
            }
        }
        .padding(.vertical, 46)
        .frame(maxWidth: .infinity)
    }

    private func livingMapCard(_ card: WorkspaceLivingMapCard) -> some View {
        DisclosureGroup(isExpanded: expansionBinding(for: card.id)) {
            VStack(alignment: .leading, spacing: 12) {
                Divider()
                Text("Dayanakları inceleyin")
                    .font(.headline)
                if card.evidence.isEmpty {
                    Label("Bu hipotez için gösterilebilir bir dayanak yok.", systemImage: "questionmark.circle")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                }
                ForEach(card.evidence) { evidence in
                    evidenceCard(evidence)
                }
                reviewPanel(card)
            }
            .padding(.top, 8)
        } label: {
            HStack(alignment: .top, spacing: 12) {
                Image(systemName: card.domain.systemImage)
                    .font(.title3)
                    .foregroundStyle(DivanPalette.wine)
                    .frame(width: 28)
                    .accessibilityHidden(true)
                VStack(alignment: .leading, spacing: 5) {
                    HStack(spacing: 8) {
                        Text(card.domain.title)
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(DivanPalette.wine)
                        Text(card.confidence.title)
                            .font(.caption2.weight(.semibold))
                            .foregroundStyle(.secondary)
                            .padding(.horizontal, 7)
                            .padding(.vertical, 3)
                            .background(.quaternary, in: Capsule())
                    }
                    Text(card.title)
                        .font(.headline)
                    Text(card.hypothesis)
                        .font(.callout)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                    HStack(spacing: 12) {
                        Label("\(card.evidence.count) dayanak", systemImage: "text.quote")
                        Text("Güncelleme \(card.updatedAt.formatted(date: .abbreviated, time: .shortened))")
                    }
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                }
            }
            .padding(.trailing, 8)
            .accessibilityElement(children: .combine)
            .accessibilityLabel("\(card.domain.title), \(card.title). \(card.hypothesis)")
            .accessibilityValue("\(card.confidence.title), \(card.evidence.count) dayanak")
            .accessibilityHint("Dayanakları açmak veya kapatmak için basın")
        }
        .advancedCard()
    }

    private func evidenceCard(_ evidence: WorkspaceLivingMapEvidence) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .firstTextBaseline) {
                Text(evidence.sourceTitle)
                    .font(.callout.weight(.semibold))
                Spacer()
                if let reviewStatus = evidence.reviewStatus, !reviewStatus.isEmpty {
                    Text(reviewStatus)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            Text("“\(evidence.excerpt)”")
                .font(.body)
                .textSelection(.enabled)
                .fixedSize(horizontal: false, vertical: true)
                .privacySensitive()
            HStack(spacing: 10) {
                Text(evidence.observedAt.formatted(date: .abbreviated, time: .shortened))
                if let conversationID = evidence.conversationID {
                    Text("Konuşma \(conversationID)")
                }
            }
            .font(.caption2)
            .foregroundStyle(.secondary)

        }
        .padding(12)
        .background(.background, in: RoundedRectangle(cornerRadius: 10))
        .overlay {
            RoundedRectangle(cornerRadius: 10)
                .stroke(Color(nsColor: .separatorColor))
        }
    }

    private func reviewPanel(_ card: WorkspaceLivingMapCard) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Divider()
            Text(card.reviewPrompt ?? "Bu hipotez ve gösterilen dayanaklar size ne kadar uyuyor?")
                .font(.callout.weight(.semibold))
            if let reviewStatus = card.reviewStatus, !reviewStatus.isEmpty {
                Label("Son değerlendirme: \(reviewStatus)", systemImage: "checkmark.seal")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            TextField(
                "İsteğe bağlı bağlam veya düzeltme notu",
                text: reviewNoteBinding(card.id),
                axis: .vertical
            )
            .lineLimit(1...4)
            .accessibilityLabel("\(card.title) için isteğe bağlı inceleme notu")

            LazyVGrid(columns: [GridItem(.adaptive(minimum: 170), spacing: 8)], alignment: .leading, spacing: 8) {
                ForEach(card.allowedReviewActions) { action in
                    Button {
                        Task { await model.reviewLivingMap(cardID: card.id, action: action) }
                    } label: {
                        Label(action.title, systemImage: reviewSymbol(action))
                    }
                    .buttonStyle(.bordered)
                    .disabled(model.isPerformingAction)
                }
            }
            Text("Karar kart düzeyinde kaydedilir. Kaynak konuşma ve dayanak metni silinmez.")
                .font(.caption2)
                .foregroundStyle(.secondary)
        }
        .padding(.top, 4)
    }

    private func expansionBinding(for id: String) -> Binding<Bool> {
        Binding(
            get: { expandedCards.contains(id) },
            set: { isExpanded in
                if isExpanded {
                    expandedCards.insert(id)
                } else {
                    expandedCards.remove(id)
                }
            }
        )
    }

    private func reviewNoteBinding(_ id: String) -> Binding<String> {
        Binding(
            get: { model.livingMapReviewNotes[id, default: ""] },
            set: { model.livingMapReviewNotes[id] = $0 }
        )
    }

    private func reviewSymbol(_ action: WorkspaceLivingMapReviewAction) -> String {
        switch action {
        case .confirm: "checkmark.circle"
        case .partial: "circle.lefthalf.filled"
        case .context: "arrow.triangle.branch"
        case .rejectEvidence: "xmark.circle"
        }
    }
}

private struct LivingMapTurnAnalysisPanel: View {
    @StateObject private var schemaModel: SchemaPathViewModel

    init(
        dataSource: any StructuredTherapyDataSource,
        conversationID: Int
    ) {
        _schemaModel = StateObject(wrappedValue: SchemaPathViewModel(
            dataSource: dataSource,
            conversationID: conversationID
        ))
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .firstTextBaseline) {
                Label("Mesaj bazında harita incelemesi", systemImage: "text.bubble")
                    .font(.headline)
                Spacer()
                if schemaModel.isBusy { ProgressView().controlSize(.small) }
            }
            Text("Kerem ile her tamamlanmış kullanıcı–Kerem mesaj çifti ayrı bir turdur. Yarım, başarısız, özel veya güvenlik kapsamındaki turlar haritaya işlenmez.")
                .font(.caption)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            Text("Her tamamlanmış mesaj çifti ayrı bir model çağrısıdır; bulut sağlayıcınız ücretlendirebilir.")
                .font(.caption)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)

            if schemaModel.snapshot == nil {
                ProgressView("Mesaj çifti kapsamı yükleniyor…")
                    .controlSize(.small)
            } else if schemaModel.schemaMode?.enabled != true {
                Text("Gelecekteki mesaj çiftlerinin otomatik incelenmesi kapalı. Kerem Genç konuşmasındaki Şema terapisi modu ayarından açabilirsiniz; geçmiş kapsamı yine ayrıca onaylanır.")
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            } else if let analysis = schemaModel.turnAnalysis {
                ProgressView(
                    value: Double(analysis.analyzedTurns),
                    total: Double(max(1, analysis.eligibleTurns))
                )
                Text("\(analysis.analyzedTurns) / \(analysis.eligibleTurns) tamamlanmış tur incelendi · \(analysis.remainingTurns) kaldı")
                    .font(.callout.monospacedDigit())
                if let provider = analysis.provider {
                    Text("\(provider.label) · \(provider.model) · \(provider.local ? "yerel" : "bulut")")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                if analysis.processing {
                    Label(
                        analysis.job?.stage ?? "İnceleme kaldığı yerden sürüyor…",
                        systemImage: "arrow.triangle.2.circlepath"
                    )
                    .font(.caption)
                    .foregroundStyle(.secondary)
                } else if analysis.remainingTurns > 0 {
                    Toggle(
                        "Bu geçmiş mesaj çifti sayısını ve sağlayıcıyı gördüm; tek tek incelemeyi onaylıyorum",
                        isOn: $schemaModel.historicalScanConfirmed
                    )
                    .fixedSize(horizontal: false, vertical: true)
                    ViewThatFits(in: .horizontal) {
                        HStack { scanActions(analysis) }
                        VStack(alignment: .leading) { scanActions(analysis) }
                    }
                } else {
                    Label("Uygun tamamlanmış mesaj çiftleri güncel", systemImage: "checkmark.circle")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                }
            }

            if let failure = schemaModel.failure {
                Text(failure.message)
                    .font(.caption)
                    .foregroundStyle(.red)
                    .fixedSize(horizontal: false, vertical: true)
            } else if !schemaModel.statusMessage.isEmpty {
                Text(schemaModel.statusMessage)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(DivanPalette.parchment.opacity(0.34), in: RoundedRectangle(cornerRadius: 12))
        .overlay {
            RoundedRectangle(cornerRadius: 12)
                .stroke(DivanPalette.gold.opacity(0.42))
        }
        .task { await schemaModel.loadIfNeeded() }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("livingMap.turnAnalysis")
    }

    @ViewBuilder
    private func scanActions(_ analysis: SchemaTurnAnalysisState) -> some View {
        Button(analysis.failedTurns > 0 ? "Kaldığı yerden sürdür" : "Geçmiş incelemeyi başlat") {
            Task { await schemaModel.scanHistoricalTurns() }
        }
        .buttonStyle(.borderedProminent)
        .tint(DivanPalette.wine)
        .disabled(!schemaModel.historicalScanConfirmed || schemaModel.isBusy)
        if analysis.failedTurns > 0, analysis.job?.id != nil {
            Button("Başarısız turu yeniden dene") {
                Task { await schemaModel.retryHistoricalScan() }
            }
            .buttonStyle(.bordered)
            .disabled(schemaModel.isBusy)
        }
    }
}

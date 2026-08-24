import SwiftUI

struct WiFiSyncView: View {
    @ObservedObject var model: AdvancedWorkspaceViewModel
    @State private var cancelConfirmationPresented = false
    @State private var role: WorkspaceSyncRole = .host

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                ViewThatFits(in: .horizontal) {
                    HStack(alignment: .top, spacing: 16) {
                        syncHeader
                        Spacer(minLength: 12)
                        syncRefreshButton
                    }
                    VStack(alignment: .leading, spacing: 10) {
                        syncHeader
                        syncRefreshButton
                    }
                }

                localSyncBoundary
                statusCard(model.syncStatus)
                processExplanation
            }
            .padding(22)
            .frame(maxWidth: 840)
            .frame(maxWidth: .infinity)
        }
        .confirmationDialog(
            "Eşitleme bağlantısı durdurulsun mu?",
            isPresented: $cancelConfirmationPresented
        ) {
            Button("Bağlantıyı durdur", role: .destructive) {
                Task { await model.cancelSync() }
            }
            Button("Devam et", role: .cancel) {}
        } message: {
            Text("Tamamlanan kayıtlar silinmez; açık davet veya sürmekte olan bağlantı durdurulur.")
        }
    }

    private var syncHeader: some View {
        AdvancedSectionHeader(
            title: "Aynı Wi-Fi ile eşitleme",
            detail: "Mac ve telefon aynı yerel ağdayken kısa süreli QR kod veya eşleştirme koduyla veri alanlarını birleştirin.",
            systemImage: "qrcode.viewfinder"
        )
    }

    private var syncRefreshButton: some View {
        Button {
            Task { await model.refreshSyncStatus() }
        } label: {
            Label("Durumu yenile", systemImage: "arrow.clockwise")
        }
        .disabled(model.isPerformingAction)
    }

    private var localSyncBoundary: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: "lock.shield.fill")
                .foregroundStyle(DivanPalette.wine)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 4) {
                Text("Yerel ağ, açık birleştirme onayı")
                    .font(.callout.weight(.semibold))
                Text("Kod kısa sürelidir ama eşitleme gerçek verileri birleştirir. Başka cihazdaki koda katılmak, ayrıca bir cihaz-onay ekranı göstermeden aktarımı başlatır; bu nedenle Katıl düğmesinden önce açık onay istenir. Çakışmalar kaynak kaydı sessizce silmeden listelenir.")
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

    @ViewBuilder
    private func statusCard(_ status: WorkspaceWiFiSyncStatus) -> some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack(alignment: .top) {
                Label(status.phase.title, systemImage: phaseSymbol(status.phase))
                    .font(.title3.weight(.semibold))
                    .foregroundStyle(phaseColor(status.phase))
                Spacer()
                Text(status.updatedAt.formatted(date: .omitted, time: .shortened))
                    .font(.caption.monospacedDigit())
                    .foregroundStyle(.secondary)
                    .accessibilityLabel("Son durum, \(status.updatedAt.formatted(date: .omitted, time: .shortened))")
            }
            Text(status.message)
                .font(.callout)
                .foregroundStyle(.secondary)
                .textSelection(.enabled)

            switch status.phase {
            case .idle:
                idleControls
            case .preparing:
                preparingState
            case .waitingForScan:
                waitingForScan(status)
            case .transferring:
                transferState(status)
            case .awaitingClinicalConfirmation:
                Label(
                    "Olağan kayıtlar korunarak eşitleme güvenli biçimde durdu.",
                    systemImage: "pause.circle"
                )
                .font(.callout)
                .foregroundStyle(.secondary)
            case .awaitingClinicalSafety:
                Label(
                    "Klinik çalışma aktarımı güvenlik beklemesi nedeniyle atlandı.",
                    systemImage: "shield.lefthalf.filled"
                )
                .font(.callout)
                .foregroundStyle(.secondary)
            case .completed:
                completedState(status)
            case .failed, .cancelled:
                restartActions(status)
            }

            if status.clinicalSafetyPause {
                clinicalSafetyState(status)
            } else if status.clinicalConfirmationRequired
                        || status.pendingClinicalConfirmationCount > 0 {
                clinicalConfirmationState(status)
            }

            if status.secretsExcluded {
                Label("API anahtarları eşitleme kapsamı dışındadır.", systemImage: "key.slash")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .advancedCard()
        .accessibilityElement(children: .contain)
        .accessibilityAddTraits(status.phase.isInProgress ? .updatesFrequently : [])
    }

    private func clinicalSafetyState(
        _ status: WorkspaceWiFiSyncStatus
    ) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Label(
                "Şema kayıtları güvenlik beklemesinde",
                systemImage: "shield.lefthalf.filled"
            )
            .font(.headline)
            .foregroundStyle(DivanPalette.wine)
            Text(
                status.clinicalSafetyMessage
                    ?? "Güvenlik beklemesi sürerken Şema çalışma kayıtları alınmadı."
            )
            .font(.callout)
            .fixedSize(horizontal: false, vertical: true)
            Label(
                "Güvenlik beklemesi kapandıktan sonra yeni bir QR oluşturup yeniden eşitleyin.",
                systemImage: "qrcode.viewfinder"
            )
            .font(.caption)
            .foregroundStyle(.secondary)
            Button("Bekleme kapandıysa yeni QR oluştur") {
                Task { await model.createSyncOffer() }
            }
            .buttonStyle(.bordered)
            .disabled(model.isPerformingAction)
            .accessibilityIdentifier("syncSafetyCreateFreshQR")
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            DivanPalette.parchment.opacity(0.55),
            in: RoundedRectangle(cornerRadius: 11)
        )
        .overlay {
            RoundedRectangle(cornerRadius: 11)
                .stroke(DivanPalette.gold.opacity(0.6))
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("syncClinicalSafetyPause")
    }

    private func clinicalConfirmationState(
        _ status: WorkspaceWiFiSyncStatus
    ) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Label(
                "Şema çalışmalarında bu cihazın kararı gerekli",
                systemImage: "hand.raised.fill"
            )
            .font(.headline)
            .foregroundStyle(DivanPalette.wine)
            Text(
                status.clinicalConfirmationMessage
                    ?? "Eşitleme klinik çalışma kapsamı için açık cihaz onayı bekliyor."
            )
            .font(.callout)
            .fixedSize(horizontal: false, vertical: true)

            if status.pendingClinicalConfirmations.isEmpty {
                Label(
                    status.clinicalConfirmationDevice == .computer
                        ? "Onayı bilgisayar tarafında verin; sonra yeni bir QR oluşturun."
                        : "Gerekli cihazda kararı verin; sonra yeni bir QR oluşturun.",
                    systemImage: "iphone.and.arrow.forward"
                )
                .font(.caption)
                .foregroundStyle(.secondary)
                Button("Onay verildiyse yeni QR oluştur") {
                    Task { await model.createSyncOffer() }
                }
                .buttonStyle(.bordered)
                .disabled(model.isPerformingAction)
                .accessibilityIdentifier("syncClinicalCreateFreshQR")
            } else {
                ForEach(status.pendingClinicalConfirmations) { item in
                    VStack(alignment: .leading, spacing: 8) {
                        Text(item.title)
                            .font(.callout.weight(.semibold))
                            .privacySensitive()
                        Text(
                            "Şema ve Yaşayan Harita kayıtlarını Mac ile Android arasında eşitlemek ayrı bir tercihtir; model sağlayıcısı onayı değişmez."
                        )
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                        ViewThatFits(in: .horizontal) {
                            HStack(spacing: 8) {
                                clinicalConfirmationButtons(item)
                            }
                            VStack(alignment: .leading, spacing: 8) {
                                clinicalConfirmationButtons(item)
                            }
                        }
                    }
                    .padding(10)
                    .background(
                        .background,
                        in: RoundedRectangle(cornerRadius: 9)
                    )
                }
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            DivanPalette.parchment.opacity(0.55),
            in: RoundedRectangle(cornerRadius: 11)
        )
        .overlay {
            RoundedRectangle(cornerRadius: 11)
                .stroke(DivanPalette.gold.opacity(0.6))
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("syncClinicalConfirmation")
    }

    @ViewBuilder
    private func clinicalConfirmationButtons(
        _ item: WorkspaceSyncClinicalConfirmation
    ) -> some View {
        Button("Bu cihazda onayla") {
            Task {
                await model.resolveSyncClinicalConfirmation(
                    conversationID: item.conversationID,
                    enabled: true
                )
            }
        }
        .buttonStyle(.borderedProminent)
        .tint(DivanPalette.wine)
        .disabled(model.isPerformingAction)
        .accessibilityIdentifier(
            "syncClinicalConfirm.\(item.conversationID)"
        )

        Button("Kapalı tut", role: .destructive) {
            Task {
                await model.resolveSyncClinicalConfirmation(
                    conversationID: item.conversationID,
                    enabled: false
                )
            }
        }
        .buttonStyle(.bordered)
        .disabled(model.isPerformingAction)
        .accessibilityIdentifier(
            "syncClinicalKeepOff.\(item.conversationID)"
        )
    }

    private var idleControls: some View {
        VStack(alignment: .leading, spacing: 14) {
            ViewThatFits(in: .horizontal) {
                Picker("Bu Mac ne yapacak?", selection: $role) {
                    ForEach(WorkspaceSyncRole.allCases) { choice in
                        Text(choice.title).tag(choice)
                    }
                }
                .pickerStyle(.segmented)
                Picker("Bu Mac ne yapacak?", selection: $role) {
                    ForEach(WorkspaceSyncRole.allCases) { choice in
                        Text(choice.title).tag(choice)
                    }
                }
                .pickerStyle(.menu)
            }

            if role == .host {
                VStack(alignment: .leading, spacing: 9) {
                    Text("Telefonda okutulacak kısa süreli bir QR ve kod üretir.")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                    ViewThatFits(in: .horizontal) {
                        HStack {
                            hostRequirement
                            Spacer()
                            createOfferButton
                        }
                        VStack(alignment: .leading, spacing: 9) {
                            hostRequirement
                            createOfferButton
                        }
                    }
                }
            } else {
                joinControls
            }
        }
    }

    private var hostRequirement: some View {
        Label("Telefon ve Mac aynı Wi-Fi ağında olmalı.", systemImage: "wifi")
            .font(.callout)
    }

    private var createOfferButton: some View {
        Button {
            Task { await model.createSyncOffer() }
        } label: {
            Label("QR ve kod oluştur", systemImage: "qrcode")
        }
        .buttonStyle(.borderedProminent)
        .tint(DivanPalette.wine)
        .disabled(model.isPerformingAction)
    }

    private var joinControls: some View {
        VStack(alignment: .leading, spacing: 10) {
            TextField("Diğer cihazdaki eşleştirme kodu", text: $model.syncPairingCode)
                .font(.system(.body, design: .monospaced))
                .accessibilityLabel("Eşleştirme kodu")
            TextField("Bu cihazın görünen adı", text: $model.syncDeviceName)
                .accessibilityLabel("Bu Mac’in eşitlemede görünecek adı")
            Toggle(isOn: $model.syncJoinConfirmed) {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Katılınca verilerin hemen birleştirileceğini onaylıyorum")
                        .font(.callout.weight(.semibold))
                    Text("Kodun güvendiğim ve aynı Wi-Fi ağındaki kendi cihazıma ait olduğunu kontrol ettim.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            .toggleStyle(.checkbox)
            HStack {
                Spacer()
                Button {
                    Task { await model.joinSync() }
                } label: {
                    Label("Koda katıl ve eşitle", systemImage: "arrow.triangle.2.circlepath")
                }
                .buttonStyle(.borderedProminent)
                .tint(DivanPalette.wine)
                .disabled(
                    model.isPerformingAction ||
                    !model.syncJoinConfirmed ||
                    model.syncPairingCode.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ||
                    model.syncDeviceName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                )
            }
        }
    }

    private var preparingState: some View {
        HStack(spacing: 9) {
            ProgressView().controlSize(.small)
            Text("Yerel bağlantı hazırlanıyor…")
                .font(.callout)
            Spacer()
            cancelButton
        }
    }

    private func waitingForScan(_ status: WorkspaceWiFiSyncStatus) -> some View {
        VStack(spacing: 15) {
            if let matrix = status.qrMatrix {
                AdvancedQRMatrixView(matrix: matrix)
                    .frame(width: 230, height: 230)
                    .padding(12)
                    .background(.white, in: RoundedRectangle(cornerRadius: 12))
                    .overlay {
                        RoundedRectangle(cornerRadius: 12)
                            .stroke(Color.black.opacity(0.18))
                    }
                    .accessibilityLabel("Telefondaki Divan eşitleme ekranıyla taranacak kısa süreli QR kod")
                    .accessibilityHint("QR kodu yalnız güvendiğiniz telefonla tarayın")
                    .privacySensitive()
            } else {
                Label("QR matrisi henüz hazır değil.", systemImage: "exclamationmark.circle")
                    .foregroundStyle(.orange)
            }

            if let pairingCode = status.pairingCode {
                VStack(spacing: 4) {
                    Text("Eşleştirme kodu")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Text(pairingCode)
                        .font(.system(.title2, design: .monospaced, weight: .bold))
                        .textSelection(.disabled)
                        .privacySensitive()
                }
            }
            Text("Telefonda Divan’ın Eşitleme ekranını açıp QR kodu okutun veya eşleştirme kodunu yazın.")
                .font(.callout.weight(.medium))
                .multilineTextAlignment(.center)

            if let expiresAt = status.expiresAt {
                TimelineView(.periodic(from: .now, by: 1)) { context in
                    Text(expiryText(expiresAt: expiresAt, now: context.date))
                        .font(.caption.monospacedDigit())
                        .foregroundStyle(.secondary)
                        .accessibilityAddTraits(.updatesFrequently)
                }
            }
            if let address = status.localAddress {
                Text("Yerel adres: \(address)")
                    .font(.caption.monospaced())
                    .foregroundStyle(.secondary)
                    .textSelection(.enabled)
                    .privacySensitive()
            }
            // Açık bir davet varken kullanıcı bu ekranda kilitleniyordu:
            // rol seçicisi yalnız `.idle` durumunda çizildiği için
            // "diğer cihazdaki koda katıl" yoluna hiç ulaşılamıyordu.
            // Buradan daveti kapatıp katılma akışına geçilebilir.
            HStack(spacing: 10) {
                cancelButton
                Button("Bunun yerine bir koda katıl") {
                    role = .join
                    Task { await model.cancelSync() }
                }
                .buttonStyle(.link)
                .accessibilityIdentifier("syncSwitchToJoin")
                Spacer()
            }
        }
        .frame(maxWidth: .infinity)
    }

    private func transferState(_ status: WorkspaceWiFiSyncStatus) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            if let progress = status.progress {
                ProgressView(value: max(0, min(progress, 1))) {
                    Text("\(status.peerName ?? "Diğer cihaz") ile eşitleniyor")
                } currentValueLabel: {
                    Text("%\(Int(max(0, min(progress, 1)) * 100))")
                        .monospacedDigit()
                }
                .accessibilityLabel("Eşitleme ilerlemesi")
                .accessibilityValue("Yüzde \(Int(max(0, min(progress, 1)) * 100))")
            } else {
                ProgressView()
                    .accessibilityLabel("Eşitleme sürüyor")
            }
            Text("\(status.recordsTransferred) kayıt aktarıldı")
                .font(.caption.monospacedDigit())
                .foregroundStyle(.secondary)
            HStack {
                Spacer()
                cancelButton
            }
        }
    }

    private func completedState(_ status: WorkspaceWiFiSyncStatus) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Label(
                "\(status.recordsTransferred) kayıt işlendi",
                systemImage: "checkmark.circle.fill"
            )
            .foregroundStyle(.green)
            if status.conflicts.isEmpty {
                Text("Çözülmeyi bekleyen çakışma yok.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            } else {
                Text("Çözülmeyi bekleyen çakışmalar")
                    .font(.headline)
                ForEach(status.conflicts) { conflict in
                    conflictCard(conflict)
                }
            }
            Button("Yeni eşitleme başlat") {
                Task { await model.createSyncOffer() }
            }
            .disabled(model.isPerformingAction)
        }
    }

    private func conflictCard(_ conflict: WorkspaceSyncConflict) -> some View {
        VStack(alignment: .leading, spacing: 7) {
            Text(conflict.title).font(.callout.weight(.semibold))
            Text(conflict.summary).font(.callout)
            Text(conflict.reason)
                .font(.caption)
                .foregroundStyle(.secondary)
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 150), spacing: 8)], alignment: .leading) {
                ForEach(WorkspaceSyncConflictResolution.allCases) { resolution in
                    Button(resolution.title) {
                        Task {
                            await model.resolveSyncConflict(
                                conflictID: conflict.id,
                                resolution: resolution
                            )
                        }
                    }
                    .disabled(model.isPerformingAction)
                }
            }
        }
        .padding(11)
        .background(.background, in: RoundedRectangle(cornerRadius: 9))
        .overlay {
            RoundedRectangle(cornerRadius: 9)
                .stroke(Color(nsColor: .separatorColor))
        }
    }

    private func restartActions(_ status: WorkspaceWiFiSyncStatus) -> some View {
        HStack {
            if status.phase == .failed {
                Label("Mevcut kayıtlar korunur.", systemImage: "externaldrive.badge.checkmark")
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }
            Spacer()
            Button("Başlangıca dön") {
                Task { await model.refreshSyncStatus() }
            }
            .buttonStyle(.borderedProminent)
            .tint(DivanPalette.wine)
            .disabled(model.isPerformingAction)
        }
    }

    private var cancelButton: some View {
        Button("Durdur", role: .destructive) {
            cancelConfirmationPresented = true
        }
        .disabled(model.isPerformingAction)
    }

    private var processExplanation: some View {
        GroupBox("Eşitleme nasıl ilerler?") {
            VStack(alignment: .leading, spacing: 10) {
                syncStep(number: 1, text: "Cihazlardan biri kısa süreli QR ve eşleştirme kodu üretir.")
                syncStep(number: 2, text: "Diğer cihaz QR’ı okutur veya kodu yazar; Katıl onayı aktarımı ve birleştirmeyi başlatır.")
                syncStep(number: 3, text: "Sonuçta aktarılan kayıtlar ve çakışmalar gösterilir. API anahtarları aktarılmaz.")
                syncStep(number: 4, text: "Her çakışmada hangi cihazdaki sürümün tutulacağını siz seçersiniz.")
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private func syncStep(number: Int, text: String) -> some View {
        HStack(alignment: .top, spacing: 10) {
            Text("\(number)")
                .font(.caption.weight(.bold))
                .foregroundStyle(.white)
                .frame(width: 22, height: 22)
                .background(DivanPalette.wine, in: Circle())
                .accessibilityHidden(true)
            Text(text).font(.callout)
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(number). adım. \(text)")
    }

    private func expiryText(expiresAt: Date, now: Date) -> String {
        let seconds = max(0, Int(expiresAt.timeIntervalSince(now)))
        if seconds == 0 { return "Kodun süresi doldu; yeni kod oluşturun." }
        return "Kod \(seconds / 60):\(String(format: "%02d", seconds % 60)) içinde sona erer"
    }

    private func phaseSymbol(_ phase: WorkspaceWiFiSyncPhase) -> String {
        switch phase {
        case .idle: "wifi"
        case .preparing: "lock.rotation"
        case .waitingForScan: "qrcode"
        case .transferring: "arrow.triangle.2.circlepath"
        case .awaitingClinicalConfirmation: "hand.raised.fill"
        case .awaitingClinicalSafety: "shield.lefthalf.filled"
        case .completed: "checkmark.circle.fill"
        case .failed: "exclamationmark.triangle.fill"
        case .cancelled: "xmark.circle"
        }
    }

    private func phaseColor(_ phase: WorkspaceWiFiSyncPhase) -> Color {
        switch phase {
        case .completed: .green
        case .awaitingClinicalConfirmation, .awaitingClinicalSafety: .orange
        case .failed: .red
        case .cancelled: .secondary
        default: DivanPalette.wine
        }
    }
}

private enum WorkspaceSyncRole: String, CaseIterable, Identifiable {
    case host
    case join

    var id: Self { self }
    var title: String { self == .host ? "Bu Mac kod üretsin" : "Bu Mac bir koda katılsın" }
}

private struct AdvancedQRMatrixView: View {
    let matrix: WorkspaceQRMatrix

    var body: some View {
        Canvas { context, size in
            let dimension = max(1, matrix.size)
            let module = min(size.width, size.height) / CGFloat(dimension)
            for (rowIndex, row) in matrix.rows.prefix(dimension).enumerated() {
                for (columnIndex, value) in row.prefix(dimension).enumerated() where value == "1" {
                    let rect = CGRect(
                        x: CGFloat(columnIndex) * module,
                        y: CGFloat(rowIndex) * module,
                        width: module.rounded(.up),
                        height: module.rounded(.up)
                    )
                    context.fill(Path(rect), with: .color(.black))
                }
            }
        }
        .background(.white)
    }
}

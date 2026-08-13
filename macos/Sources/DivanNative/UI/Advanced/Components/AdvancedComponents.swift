import SwiftUI

struct AdvancedSafetyBanner: View {
    let compact: Bool

    init(compact: Bool = false) {
        self.compact = compact
    }

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: "hand.raised.fill")
                .foregroundStyle(DivanPalette.wine)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 3) {
                HStack(spacing: 7) {
                    Text("Sınırı siz belirlersiniz")
                        .font(.callout.weight(.semibold))
                    AISimulationBadge()
                }
                Text(compact ? compactText : fullText)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(11)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(DivanPalette.parchment.opacity(0.42), in: RoundedRectangle(cornerRadius: 10))
        .overlay {
            RoundedRectangle(cornerRadius: 10)
                .stroke(DivanPalette.gold.opacity(0.45))
        }
        .accessibilityElement(children: .combine)
    }

    private var compactText: String {
        "İstediğiniz anda duraklatabilir veya bitirebilirsiniz. Hiçbir anının doğruluğu varsayılmaz."
    }

    private var fullText: String {
        "Bu AI destekli öz çalışma bir terapi veya kriz hizmeti değildir. Bir anıyı zorlamanız gerekmez; imge ve çağrışımlar tarihsel kanıt sayılmaz. Yoğunluk taşınamaz gelirse çalışmayı durdurun, bulunduğunuz ortama yönelin ve gerçek bir insandan destek alın. Acil tehlikede bulunduğunuz yerdeki acil yardım hattını arayın."
    }
}

struct AdvancedFailureBanner: View {
    let failure: AdvancedWorkspaceFailure
    let retry: () -> Void
    let dismiss: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .top, spacing: 8) {
                Image(systemName: "exclamationmark.triangle.fill")
                    .foregroundStyle(.orange)
                    .accessibilityHidden(true)
                Text(failure.title).font(.headline)
                Spacer(minLength: 4)
                Button(action: dismiss) {
                    Image(systemName: "xmark")
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Uyarıyı kapat")
            }
            ScrollView {
                VStack(alignment: .leading, spacing: 8) {
                    Text(failure.message)
                        .font(.callout)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                        .textSelection(.enabled)
                    if failure.retryAction != nil {
                        Button("Yeniden dene", action: retry)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .frame(maxHeight: 92)
        }
        .padding(12)
        .frame(maxHeight: 150, alignment: .top)
        .background(.regularMaterial)
        .overlay(alignment: .bottom) { Divider() }
        .accessibilityElement(children: .contain)
    }
}

struct AdvancedOperationStatus: View {
    let description: String

    var body: some View {
        if !description.isEmpty {
            HStack(spacing: 8) {
                ProgressView().controlSize(.small)
                Text(description)
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }
            .padding(.horizontal, 11)
            .padding(.vertical, 7)
            .background(.regularMaterial, in: Capsule())
            .accessibilityElement(children: .combine)
            .accessibilityLabel(description)
            .accessibilityAddTraits(.updatesFrequently)
        }
    }
}

struct AdvancedPhaseBadge: View {
    let phase: WorkspaceWorkPhase

    var body: some View {
        Label(title, systemImage: systemImage)
            .font(.caption.weight(.semibold))
            .foregroundStyle(color)
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .background(color.opacity(0.12), in: Capsule())
            .accessibilityLabel("Çalışma durumu: \(title)")
    }

    private var title: String {
        switch phase {
        case .notStarted: "Başlamadı"
        case .active: "Devam ediyor"
        case .paused: "Duraklatıldı"
        case .completed: "Tamamlandı"
        }
    }

    private var systemImage: String {
        switch phase {
        case .notStarted: "circle"
        case .active: "play.circle.fill"
        case .paused: "pause.circle.fill"
        case .completed: "checkmark.circle.fill"
        }
    }

    private var color: Color {
        switch phase {
        case .notStarted: .secondary
        case .active: DivanPalette.wine
        case .paused: .orange
        case .completed: .green
        }
    }
}

struct AdvancedIntensityControl: View {
    let title: String
    @Binding var value: Int
    var maximum = 10
    var disabled = false

    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            HStack {
                Text(title).font(.callout.weight(.medium))
                Spacer()
                Text("\(value) / \(maximum)")
                    .monospacedDigit()
                    .foregroundStyle(.secondary)
                    .accessibilityHidden(true)
            }
            Slider(
                value: Binding(
                    get: { Double(value) },
                    set: { value = Int($0.rounded()) }
                ),
                in: 0...Double(max(1, maximum)),
                step: 1
            )
            .disabled(disabled)
            .accessibilityLabel(title)
            .accessibilityValue("\(maximum) üzerinden \(value)")
            .accessibilityHint("Yoğunluğu azaltmak için sola, artırmak için sağa ayarlayın")
        }
    }
}

struct AdvancedSafetyHoldBanner: View {
    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: "exclamationmark.shield.fill")
                .foregroundStyle(.orange)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 3) {
                Text("Güvenlik bekletmesi açık")
                    .font(.callout.weight(.semibold))
                Text("Yeni deneyimsel adım başlatılmaz. Duraklatma, şimdiye dönme ve durdurma seçenekleri açık kalır.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(11)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.orange.opacity(0.1), in: RoundedRectangle(cornerRadius: 10))
        .overlay { RoundedRectangle(cornerRadius: 10).stroke(.orange.opacity(0.45)) }
        .accessibilityElement(children: .combine)
    }
}

struct AdvancedSectionHeader: View {
    let title: String
    let detail: String
    let systemImage: String
    var showsDetail = true

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: systemImage)
                .font(.title2)
                .foregroundStyle(DivanPalette.wine)
                .frame(width: 30)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 3) {
                Text(title).font(.title2.weight(.semibold))
                if showsDetail {
                    Text(detail)
                        .font(.callout)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(title). \(detail)")
        .accessibilityAddTraits(.isHeader)
    }
}

struct AdvancedUnavailableState: View {
    let title: String
    let message: String
    let nextStep: String
    let accessibilityIdentifier: String
    /// Çıkışsız bir boş durum kullanıcıyı ekranda kilitliyordu; çağıran
    /// verirse görünür bir dönüş yolu sunulur.
    var exitAction: (() -> Void)?
    var exitTitle: String = "Son konuşmalara dön"

    var body: some View {
        ScrollView {
            VStack(spacing: 12) {
                Image(systemName: "lock.shield")
                    .font(.system(size: 36, weight: .light))
                    .foregroundStyle(DivanPalette.gold)
                    .accessibilityHidden(true)
                Text(title).font(.title3.weight(.semibold))
                Text(message)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
                    .frame(maxWidth: 440)
                VStack(alignment: .leading, spacing: 5) {
                    Label("Sonraki adım", systemImage: "arrow.right.circle.fill")
                        .font(.callout.weight(.semibold))
                        .foregroundStyle(DivanPalette.wine)
                    Text(nextStep)
                        .font(.callout)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .padding(12)
                .frame(maxWidth: 520, alignment: .leading)
                .background(.quaternary, in: RoundedRectangle(cornerRadius: 10))
                if let exitAction {
                    Button(exitTitle) { exitAction() }
                        .buttonStyle(.borderedProminent)
                        .accessibilityIdentifier("divan.advanced.unavailable.exit")
                }
                AdvancedSafetyBanner(compact: true)
                    .frame(maxWidth: 520)
            }
            .padding(20)
            .frame(maxWidth: .infinity)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier(accessibilityIdentifier)
    }
}

extension View {
    func advancedCard() -> some View {
        self
            .padding(14)
            .background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 12))
            .overlay {
                RoundedRectangle(cornerRadius: 12)
                    .stroke(Color(nsColor: .separatorColor))
            }
    }
}

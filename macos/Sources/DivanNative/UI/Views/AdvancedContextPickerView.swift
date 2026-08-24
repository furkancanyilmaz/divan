import SwiftUI

/// Keeps conversation selection in the native middle column while the full
/// advanced workspace uses the wide detail column.
public struct AdvancedContextPickerView: View {
    @ObservedObject private var model: DivanViewModel
    private let onSelect: () -> Void

    public init(model: DivanViewModel, onSelect: @escaping () -> Void = {}) {
        self.model = model
        self.onSelect = onSelect
    }

    public var body: some View {
        VStack(spacing: 0) {
            header
            Divider()
            if model.destination == .sync {
                syncExplanation
            } else if model.activeTherapyConversations.isEmpty {
                DivanEmptyState(
                    systemImage: "heart.text.square",
                    title: "Açık terapi seansı yok",
                    message: "Bu çalışmayı kullanmak için Ustalar’dan bir terapistle yeni terapi seansı başlatın.",
                    actionTitle: "Ustalara git",
                    action: { model.selectDestination(.masters) }
                )
            } else {
                List(model.activeTherapyConversations) { conversation in
                    Button {
                        model.selectAdvancedConversation(id: conversation.id)
                        onSelect()
                    } label: {
                        HStack(alignment: .top, spacing: 11) {
                            DivanPersonaPortrait(
                                master: model.master(id: conversation.masterID),
                                model: model,
                                size: 40
                            )
                            VStack(alignment: .leading, spacing: 5) {
                                Text(model.master(id: conversation.masterID)?.name ?? "Terapist")
                                    .font(.title3.weight(.semibold))
                                Text(conversation.title)
                                    .font(.subheadline)
                                    .lineLimit(1)
                                Text(conversation.updatedAt, format: .dateTime.day().month(.abbreviated).hour().minute())
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                        }
                    }
                    .buttonStyle(.plain)
                    .padding(.vertical, 7)
                    .accessibilityElement(children: .combine)
                    .listRowBackground(
                        model.advancedConversationID == conversation.id
                            ? DivanPalette.parchment.opacity(0.58)
                            : Color.clear
                    )
                }
                .listStyle(.inset)
            }
        }
    }

    private var header: some View {
        HStack(alignment: .top, spacing: 9) {
            Text(explanation)
                .font(.callout)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 4)
            if model.destination != .sync {
                Text("\(model.activeTherapyConversations.count)")
                    .font(.caption.monospacedDigit())
                    .foregroundStyle(.secondary)
                    .padding(.horizontal, 7)
                    .padding(.vertical, 4)
                    .background(.quaternary, in: Capsule())
                    .accessibilityLabel(
                        "\(model.activeTherapyConversations.count) açık terapi konuşması"
                    )
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
    }

    private var syncExplanation: some View {
        VStack(alignment: .leading, spacing: 14) {
            Label("Aynı Wi-Fi gerekir", systemImage: "wifi")
                .font(.headline)
            Text("Bir cihaz eşitlemeyi başlatır, diğeri QR kodunu okur. Her iki taraf da onaylamadan veri aktarılmaz.")
                .foregroundStyle(.secondary)
            Label("Dış sunucu kullanılmaz", systemImage: "lock.shield")
                .font(.callout.weight(.medium))
            Text("Eşitleme sırasında iki cihazı da açık ve aynı ağda tutun.")
                .font(.callout)
                .foregroundStyle(.secondary)
            Spacer()
        }
        .padding(20)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    }

    private var explanation: String {
        switch model.destination {
        case .works:
            "Görsel çağrışım, sandalye, şema yolu, ritim veya yeniden ebeveynlik çalışmasının bağlanacağı açık seansı seçin."
        case .livingMap:
            "Haritada yeni kanıt üretmek veya ilgili seansa dönmek için açık seansı seçin."
        case .sync:
            "Telefon ve bilgisayar arasında güvenli yerel eşitleme."
        default:
            ""
        }
    }
}

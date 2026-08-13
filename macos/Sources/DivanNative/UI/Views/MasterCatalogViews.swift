import SwiftUI

public struct MasterCatalogView: View {
    @ObservedObject private var model: DivanViewModel
    private let onSelect: () -> Void

    public init(model: DivanViewModel, onSelect: @escaping () -> Void = {}) {
        self.model = model
        self.onSelect = onSelect
    }

    public var body: some View {
        VStack(spacing: 0) {
            catalogHeader
            Divider()
            if model.visibleMasters.isEmpty {
                DivanEmptyState(
                    systemImage: "person.crop.circle.badge.questionmark",
                    title: "Eşleşen usta yok",
                    message: "Arama sözcüğünü değiştirin veya kataloğu yenileyin."
                )
            } else {
                List(model.visibleMasters) { master in
                    Button {
                        model.selectCatalogMaster(master)
                        onSelect()
                    } label: {
                        MasterCatalogRow(master: master, model: model)
                    }
                    .buttonStyle(.plain)
                    .listRowBackground(
                        model.selectedCatalogMaster?.id == master.id
                            ? DivanPalette.parchment.opacity(0.58)
                            : Color.clear
                    )
                }
                .listStyle(.inset)
            }
        }
        .navigationTitle("Ustalar")
        .searchable(
            text: $model.catalogSearch,
            placement: .toolbar,
            prompt: "İsim, ekol veya yaklaşım"
        )
        .toolbar {
            ToolbarItem {
                Button {
                    Task { await model.refreshCurrentDestination() }
                } label: {
                    Label("Kataloğu yenile", systemImage: "arrow.clockwise")
                }
                .help("Kataloğu yenile")
            }
        }
    }

    private var catalogHeader: some View {
        VStack(alignment: .leading, spacing: 9) {
            Picker("Usta türü", selection: catalogKind) {
                ForEach(DivanCatalogKind.allCases) { kind in
                    Label(kind.title, systemImage: kind.systemImage).tag(kind)
                }
            }
            .pickerStyle(.segmented)
            .accessibilityHint("Terapistler ve felsefeciler arasında geçiş yapar")

            HStack {
                Text(model.masterCatalogKind == .therapist
                     ? "Terapi veya ders için bir ekol ve usta seçin."
                     : "Felsefi diyalog ve ders için bir düşünür seçin.")
                    .font(.callout)
                    .foregroundStyle(.secondary)
                Spacer()
                Text("\(model.visibleMasters.count) usta")
                    .font(.caption.monospacedDigit())
                    .foregroundStyle(.secondary)
            }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 12)
    }

    private var catalogKind: Binding<DivanCatalogKind> {
        Binding(
            get: { model.masterCatalogKind },
            set: { model.selectMasterCatalogKind($0) }
        )
    }

}

private struct MasterCatalogRow: View {
    let master: DivanMaster
    @ObservedObject var model: DivanViewModel

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            DivanPersonaPortrait(master: master, model: model, size: 52)
            VStack(alignment: .leading, spacing: 4) {
                Text(master.name)
                    .font(.system(.headline, design: .serif).weight(.bold))
                    .fixedSize(horizontal: false, vertical: true)
                Text(master.school)
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                if !master.subtitle.isEmpty {
                    Text(master.subtitle)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            Spacer(minLength: 0)
        }
        .padding(.vertical, 5)
        .contentShape(Rectangle())
        .accessibilityLabel(
            [master.name, master.school, master.subtitle, "AI canlandırması"]
                .filter { !$0.isEmpty }
                .joined(separator: ", ")
        )
        .accessibilityHint("Ustanın ayrıntılarını gösterir")
    }
}

public struct MasterCatalogDetailView: View {
    @ObservedObject private var model: DivanViewModel

    public init(model: DivanViewModel) {
        self.model = model
    }

    public var body: some View {
        if let master = model.selectedCatalogMaster {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    HStack(alignment: .top, spacing: 18) {
                        DivanPersonaPortrait(master: master, model: model, size: 112)
                        VStack(alignment: .leading, spacing: 7) {
                            Text(master.name)
                                .font(.system(.largeTitle, design: .serif).weight(.bold))
                                .textSelection(.enabled)
                            Text(master.school)
                                .font(.title3.weight(.semibold))
                                .foregroundStyle(DivanPalette.wine)
                            AISimulationBadge()
                        }
                    }

                    if !master.subtitle.isEmpty {
                        Text(master.subtitle)
                            .font(.title3)
                            .foregroundStyle(.secondary)
                            .textSelection(.enabled)
                    }

                    Divider()

                    VStack(alignment: .leading, spacing: 9) {
                        Label(
                            master.kind == .therapist
                                ? "Terapi ekolü ve güncel yöntem bilgisiyle canlandırılır."
                                : "Fikirleri, eserleri ve güncel tartışmalar üzerinden konuşur.",
                            systemImage: master.kind == .therapist
                                ? "heart.text.square" : "book.closed"
                        )
                        Label(
                            master.isLiving
                                ? "Bu canlandırma kişinin kendisi veya kurum sözcüsü değildir."
                                : "Tarihsel kişiliğin AI canlandırmasıdır.",
                            systemImage: "sparkles"
                        )
                    }
                    .font(.callout)
                    .foregroundStyle(.secondary)

                    HStack(spacing: 10) {
                        ForEach(
                            DivanSessionMode.allCases.filter(master.supportedModes.contains)
                        ) { mode in
                            Label(mode.title, systemImage: mode.systemImage)
                                .font(.caption.weight(.semibold))
                                .padding(.horizontal, 9)
                                .padding(.vertical, 5)
                                .background(.quaternary, in: Capsule())
                        }
                    }

                    Button {
                        model.prepareNewSession(master: master)
                    } label: {
                        Label("Yeni görüşme başlat", systemImage: "plus.bubble.fill")
                            .frame(maxWidth: 260)
                    }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.large)
                    .tint(DivanPalette.wine)
                    .keyboardShortcut(.defaultAction)
                }
                .padding(28)
                .frame(maxWidth: 760, alignment: .leading)
                .frame(maxWidth: .infinity, alignment: .center)
            }
            .navigationTitle(master.name)
        } else {
            DivanEmptyState(
                systemImage: "person.crop.circle.badge.questionmark",
                title: "Bir usta seçin",
                message: "Terapist veya felsefecinin yaklaşımı ve görüşme seçenekleri burada görünür."
            )
        }
    }
}

public struct NewSessionSheet: View {
    @ObservedObject private var model: DivanViewModel
    @Environment(\.dismiss) private var dismiss
    @State private var kind: DivanCatalogKind = .therapist
    @State private var search = ""

    public init(model: DivanViewModel) {
        self.model = model
    }

    public var body: some View {
        VStack(spacing: 0) {
            ViewThatFits(in: .horizontal) {
                HStack(alignment: .firstTextBaseline) {
                    newSessionTitle
                    Spacer()
                    newSessionCancelButton
                }
                VStack(alignment: .leading, spacing: 9) {
                    newSessionTitle
                    newSessionCancelButton
                }
            }
            .padding(18)
            Divider()

            ViewThatFits(in: .horizontal) {
                HStack(spacing: 12) {
                    newSessionKindPicker
                    newSessionSearchField
                }
                VStack(alignment: .leading, spacing: 9) {
                    newSessionKindPicker
                    newSessionSearchField
                }
            }
            .padding(14)

            List(filteredMasters, selection: masterSelection) { master in
                HStack(spacing: 11) {
                    DivanPersonaPortrait(master: master, model: model, size: 42)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(master.name).font(.headline)
                        Text(master.school)
                            .font(.callout.weight(.medium))
                            .foregroundStyle(.secondary)
                        Text(master.subtitle)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                    if model.newSessionMaster?.id == master.id {
                        Image(systemName: "checkmark.circle.fill")
                            .foregroundStyle(DivanPalette.wine)
                            .accessibilityLabel("Seçili")
                    }
                }
                .tag(master.id)
                .padding(.vertical, 4)
                .accessibilityElement(children: .combine)
            }

            Divider()
            ViewThatFits(in: .horizontal) {
                HStack(spacing: 12) {
                    newSessionMasterSummary
                    Spacer()
                    newSessionModePicker
                        .frame(width: 170)
                    newSessionStartButton
                }
                VStack(alignment: .leading, spacing: 10) {
                    newSessionMasterSummary
                    newSessionModePicker
                    HStack {
                        Spacer()
                        newSessionStartButton
                    }
                }
            }
            .padding(16)
        }
        .frame(idealWidth: 700, idealHeight: 620)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .onAppear {
            kind = model.newSessionMaster?.kind ?? .therapist
            keepSelectionVisible()
        }
        .onChange(of: kind) { _ in keepSelectionVisible() }
        .onChange(of: search) { _ in keepSelectionVisible() }
    }

    private var newSessionTitle: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text("Yeni görüşme")
                .font(.title2.weight(.semibold))
            Text("Usta ve görüşme türünü siz seçersiniz.")
                .foregroundStyle(.secondary)
        }
    }

    private var newSessionCancelButton: some View {
        Button("Vazgeç") {
            model.isNewSessionPresented = false
            dismiss()
        }
        .keyboardShortcut(.cancelAction)
    }

    private var newSessionKindPicker: some View {
        Picker("Usta türü", selection: $kind) {
            ForEach(DivanCatalogKind.allCases) { value in
                Text(value.title).tag(value)
            }
        }
        .pickerStyle(.segmented)
    }

    private var newSessionSearchField: some View {
        TextField("İsim veya ekol ara", text: $search)
            .textFieldStyle(.roundedBorder)
            .accessibilityLabel("Yeni görüşme için usta ara")
    }

    @ViewBuilder
    private var newSessionMasterSummary: some View {
        if let master = model.newSessionMaster {
            HStack(spacing: 10) {
                DivanPersonaPortrait(master: master, model: model, size: 38)
                VStack(alignment: .leading, spacing: 1) {
                    Text(master.name).font(.headline)
                    AISimulationBadge()
                }
            }
        } else {
            Text("Bir usta seçin").foregroundStyle(.secondary)
        }
    }

    private var newSessionModePicker: some View {
        Picker("Görüşme türü", selection: $model.newSessionMode) {
            ForEach(availableModes) { mode in
                Label(mode.title, systemImage: mode.systemImage).tag(mode)
            }
        }
    }

    private var newSessionStartButton: some View {
        Button {
            Task { await model.createNewSession() }
        } label: {
            if model.isCreatingSession {
                ProgressView().controlSize(.small)
            } else {
                Text("Başlat")
            }
        }
        .buttonStyle(.borderedProminent)
        .tint(DivanPalette.wine)
        .keyboardShortcut(.defaultAction)
        .disabled(model.newSessionMaster == nil || model.isCreatingSession)
    }

    private var filteredMasters: [DivanMaster] {
        let source = kind == .therapist ? model.therapists : model.philosophers
        let query = normalized(search)
        guard !query.isEmpty else { return source }
        return source.filter {
            normalized([$0.name, $0.school, $0.subtitle].joined(separator: " "))
                .contains(query)
        }
    }

    private func normalized(_ value: String) -> String {
        value.trimmingCharacters(in: .whitespacesAndNewlines)
            .folding(
                options: [.caseInsensitive, .diacriticInsensitive, .widthInsensitive],
                locale: Locale(identifier: "tr_TR")
            )
            .localizedLowercase
    }

    private var masterSelection: Binding<String?> {
        Binding(
            get: { model.newSessionMaster?.id },
            set: { id in
                guard let id,
                      let master = (model.therapists + model.philosophers)
                        .first(where: { $0.id == id }) else { return }
                model.newSessionMaster = master
                if !master.supportedModes.contains(model.newSessionMode) {
                    model.newSessionMode = master.supportedModes.first ?? .lesson
                }
            }
        )
    }

    private var availableModes: [DivanSessionMode] {
        guard let master = model.newSessionMaster else { return [] }
        return DivanSessionMode.allCases.filter(master.supportedModes.contains)
    }

    private func keepSelectionVisible() {
        guard !filteredMasters.contains(where: {
            $0.id == model.newSessionMaster?.id
        }) else { return }
        model.newSessionMaster = filteredMasters.first
        if let master = model.newSessionMaster,
           !master.supportedModes.contains(model.newSessionMode) {
            model.newSessionMode = master.supportedModes.first ?? .lesson
        }
    }
}

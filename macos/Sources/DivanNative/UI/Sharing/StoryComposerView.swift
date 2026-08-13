import AppKit
import SwiftUI
import UniformTypeIdentifiers

public enum DivanStoryTheme: String, CaseIterable, Identifiable {
    case parchment
    case wine
    case midnight
    case ivory

    public var id: Self { self }

    public var title: String {
        switch self {
        case .parchment: "Parşömen"
        case .wine: "Divan"
        case .midnight: "Gece"
        case .ivory: "Sade"
        }
    }

    fileprivate var background: LinearGradient {
        switch self {
        case .parchment:
            LinearGradient(
                colors: [
                    Color(red: 0.97, green: 0.93, blue: 0.84),
                    Color(red: 0.88, green: 0.79, blue: 0.65),
                ],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )
        case .wine:
            LinearGradient(
                colors: [DivanPalette.wineDeep, DivanPalette.wine],
                startPoint: .top,
                endPoint: .bottomTrailing
            )
        case .midnight:
            LinearGradient(
                colors: [Color(red: 0.05, green: 0.07, blue: 0.12),
                         Color(red: 0.14, green: 0.12, blue: 0.20)],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )
        case .ivory:
            LinearGradient(
                colors: [Color.white, Color(red: 0.93, green: 0.92, blue: 0.89)],
                startPoint: .top,
                endPoint: .bottom
            )
        }
    }

    fileprivate var primary: Color {
        switch self {
        case .wine, .midnight: .white
        case .parchment, .ivory: DivanPalette.ink
        }
    }

    fileprivate var secondary: Color { primary.opacity(0.70) }
    fileprivate var assistantBubble: Color {
        switch self {
        case .wine, .midnight: Color.white.opacity(0.13)
        case .parchment, .ivory: Color.white.opacity(0.72)
        }
    }
    fileprivate var userBubble: Color {
        switch self {
        case .wine, .midnight: DivanPalette.gold.opacity(0.33)
        case .parchment, .ivory: DivanPalette.wine.opacity(0.12)
        }
    }
}

private enum StoryComposerPanel: String, CaseIterable, Identifiable {
    case preview
    case settings

    var id: Self { self }
    var title: String { self == .preview ? "Önizleme" : "Ayarlar" }
    var systemImage: String { self == .preview ? "rectangle.portrait" : "slider.horizontal.3" }
}

public struct StoryComposerView: View {
    public let master: DivanMaster
    public let portraitData: Data?
    public let messages: [DivanMessage]

    @Environment(\.dismiss) private var dismiss
    @State private var theme: DivanStoryTheme = .parchment
    @State private var fontScale = 1.0
    @State private var showTimes = true
    @State private var showUserLabel = false
    @State private var exportError: String?
    @State private var sharingPicker: NSSharingServicePicker?
    @State private var compactPanel: StoryComposerPanel = .preview

    public init(
        master: DivanMaster,
        portraitData: Data?,
        messages: [DivanMessage]
    ) {
        self.master = master
        self.portraitData = portraitData
        self.messages = Array(messages.prefix(8))
    }

    public var body: some View {
        GeometryReader { geometry in
            if geometry.size.width < 760 {
                compactLayout
            } else {
                HStack(spacing: 0) {
                    previewPane
                    Divider()
                    controlsPane
                }
            }
        }
        .frame(minWidth: 420, idealWidth: 900, minHeight: 320, idealHeight: 720)
        .alert("Hikâye oluşturulamadı", isPresented: Binding(
            get: { exportError != nil },
            set: { if !$0 { exportError = nil } }
        )) {
            Button("Tamam", role: .cancel) { exportError = nil }
        } message: {
            Text(exportError ?? "Bilinmeyen hata")
        }
    }

    private var compactLayout: some View {
        VStack(spacing: 0) {
            Picker("Hikâye düzenleme görünümü", selection: $compactPanel) {
                ForEach(StoryComposerPanel.allCases) { panel in
                    Label(panel.title, systemImage: panel.systemImage).tag(panel)
                }
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .padding(10)
            .background(.bar)
            Divider()
            if compactPanel == .preview {
                previewPane
            } else {
                controlsPane
            }
        }
    }

    private var previewPane: some View {
        ScrollView([.horizontal, .vertical]) {
            storyCanvas
                .scaleEffect(0.56, anchor: .top)
                .frame(width: 302, height: 538, alignment: .top)
                .shadow(color: .black.opacity(0.22), radius: 18, y: 8)
                .padding(28)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color(nsColor: .windowBackgroundColor))
    }

    private var controlsPane: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                HStack(alignment: .top) {
                    VStack(alignment: .leading, spacing: 3) {
                        Text("Hikâye oluştur")
                            .font(.title2.weight(.semibold))
                        Text("1080 × 1920 · Divan teması")
                            .font(.callout)
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                    Button("Kapat") { dismiss() }
                        .keyboardShortcut(.cancelAction)
                }

                GroupBox("Görünüm") {
                    VStack(alignment: .leading, spacing: 14) {
                        ViewThatFits(in: .horizontal) {
                            Picker("Tema", selection: $theme) {
                                ForEach(DivanStoryTheme.allCases) { value in
                                    Text(value.title).tag(value)
                                }
                            }
                            .pickerStyle(.segmented)
                            Picker("Tema", selection: $theme) {
                                ForEach(DivanStoryTheme.allCases) { value in
                                    Text(value.title).tag(value)
                                }
                            }
                            .pickerStyle(.menu)
                        }

                        HStack {
                            Text("Yazı boyutu")
                            Slider(value: $fontScale, in: 0.82...1.22, step: 0.05)
                            Text("%\(Int(fontScale * 100))")
                                .frame(width: 48, alignment: .trailing)
                                .monospacedDigit()
                        }

                        Toggle("Mesaj saatlerini göster", isOn: $showTimes)
                        Toggle("Kendi mesajlarımda ‘Sen’ yazsın", isOn: $showUserLabel)
                    }
                    .padding(.top, 6)
                }

                GroupBox("Gizlilik") {
                    VStack(alignment: .leading, spacing: 7) {
                        Label("Yalnız seçtiğiniz mesajlar kullanılır.", systemImage: "checkmark.shield")
                        Label("PNG yerelde oluşturulur; modele gönderilmez.", systemImage: "internaldrive")
                        Label("Paylaşmadan önce hassas ayrıntıları okuyun.", systemImage: "eye")
                    }
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                }

                Text("\(messages.count) mesaj seçildi")
                    .font(.callout.monospacedDigit())
                    .foregroundStyle(.secondary)

                HStack {
                    Button {
                        exportPNG()
                    } label: {
                        Label("PNG kaydet", systemImage: "square.and.arrow.down")
                    }
                    Spacer()
                    Button {
                        sharePNG()
                    } label: {
                        Label("Paylaş", systemImage: "square.and.arrow.up")
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(DivanPalette.wine)
                    .keyboardShortcut(.defaultAction)
                }
            }
            .padding(24)
            .frame(maxWidth: 520)
            .frame(maxWidth: .infinity, alignment: .center)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private var storyCanvas: some View {
        DivanStoryCanvas(
            master: master,
            portraitData: portraitData,
            messages: messages,
            theme: theme,
            fontScale: fontScale,
            showTimes: showTimes,
            showUserLabel: showUserLabel
        )
        .frame(width: 540, height: 960)
    }

    @MainActor
    private func renderedPNG() throws -> Data {
        let renderer = ImageRenderer(content: storyCanvas)
        renderer.scale = 2
        guard let image = renderer.nsImage,
              let tiff = image.tiffRepresentation,
              let bitmap = NSBitmapImageRep(data: tiff),
              let data = bitmap.representation(using: .png, properties: [:]) else {
            throw StoryExportError.renderFailed
        }
        return data
    }

    private func exportPNG() {
        do {
            let data = try renderedPNG()
            let panel = NSSavePanel()
            panel.allowedContentTypes = [.png]
            panel.nameFieldStringValue = "Divan-Hikaye.png"
            panel.canCreateDirectories = true
            guard panel.runModal() == .OK, let url = panel.url else { return }
            try data.write(to: url, options: .atomic)
        } catch {
            exportError = error.localizedDescription
        }
    }

    private func sharePNG() {
        do {
            let data = try renderedPNG()
            let url = FileManager.default.temporaryDirectory
                .appendingPathComponent("Divan-Hikaye-\(UUID().uuidString).png")
            try data.write(to: url, options: .atomic)
            guard let view = NSApp.keyWindow?.contentView else {
                throw StoryExportError.noWindow
            }
            let picker = NSSharingServicePicker(items: [url])
            sharingPicker = picker
            picker.show(relativeTo: view.bounds, of: view, preferredEdge: .minY)
        } catch {
            exportError = error.localizedDescription
        }
    }
}

private struct DivanStoryCanvas: View {
    let master: DivanMaster
    let portraitData: Data?
    let messages: [DivanMessage]
    let theme: DivanStoryTheme
    let fontScale: Double
    let showTimes: Bool
    let showUserLabel: Bool

    var body: some View {
        ZStack {
            theme.background
            Circle()
                .fill(DivanPalette.gold.opacity(0.10))
                .frame(width: 430, height: 430)
                .offset(x: 250, y: -390)
            Circle()
                .stroke(DivanPalette.gold.opacity(0.18), lineWidth: 2)
                .frame(width: 520, height: 520)
                .offset(x: -270, y: 420)

            VStack(alignment: .leading, spacing: 19) {
                HStack(spacing: 14) {
                    portrait
                    VStack(alignment: .leading, spacing: 3) {
                        Text(master.name)
                            .font(.system(size: 24, weight: .bold, design: .serif))
                            .foregroundStyle(theme.primary)
                        Text(master.school)
                            .font(.system(size: 13, weight: .semibold))
                            .foregroundStyle(theme.secondary)
                    }
                    Spacer()
                    Text("divan")
                        .font(.system(size: 18, weight: .bold, design: .serif))
                        .foregroundStyle(theme.primary.opacity(0.90))
                }

                Rectangle()
                    .fill(DivanPalette.gold.opacity(0.70))
                    .frame(height: 1)

                VStack(spacing: 11) {
                    ForEach(messages) { message in
                        storyMessage(message)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .top)

                Spacer(minLength: 4)

                HStack {
                    Label("AI canlandırması", systemImage: "sparkles")
                    Spacer()
                    Text("Yalnız seçilen konuşma kesitidir")
                }
                .font(.system(size: 10, weight: .medium))
                .foregroundStyle(theme.secondary)
            }
            .padding(.horizontal, 34)
            .padding(.vertical, 38)
        }
        .clipShape(RoundedRectangle(cornerRadius: 2))
    }

    private var portrait: some View {
        Group {
            if let portraitData, let image = NSImage(data: portraitData) {
                Image(nsImage: image).resizable().scaledToFill()
            } else {
                Text(master.name.split(separator: " ").prefix(3)
                    .compactMap(\.first).map(String.init).joined())
                    .font(.system(size: 18, weight: .bold, design: .serif))
                    .foregroundStyle(DivanPalette.wine)
            }
        }
        .frame(width: 58, height: 58)
        .background(Color.white.opacity(0.80))
        .clipShape(Circle())
        .overlay(Circle().stroke(DivanPalette.gold, lineWidth: 2))
    }

    private func storyMessage(_ message: DivanMessage) -> some View {
        HStack {
            if message.role == .user { Spacer(minLength: 54) }
            VStack(alignment: .leading, spacing: 5) {
                if showUserLabel && message.role == .user {
                    Text("Sen")
                        .font(.system(size: 10, weight: .bold))
                        .foregroundStyle(theme.secondary)
                }
                Text(message.content)
                    .font(.system(
                        size: 15 * fontScale,
                        weight: .regular,
                        design: .rounded
                    ))
                    .foregroundStyle(theme.primary)
                    .lineLimit(messages.count > 5 ? 4 : 6)
                    .multilineTextAlignment(.leading)
                if showTimes {
                    Text(message.createdAt, format: .dateTime.hour().minute())
                        .font(.system(size: 9, weight: .medium))
                        .foregroundStyle(theme.secondary)
                        .frame(maxWidth: .infinity, alignment: .trailing)
                }
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 10)
            .background(
                message.role == .user ? theme.userBubble : theme.assistantBubble,
                in: RoundedRectangle(cornerRadius: 15)
            )
            .overlay {
                RoundedRectangle(cornerRadius: 15)
                    .stroke(theme.primary.opacity(0.08), lineWidth: 1)
            }
            if message.role != .user { Spacer(minLength: 54) }
        }
    }
}

private enum StoryExportError: LocalizedError {
    case renderFailed
    case noWindow

    var errorDescription: String? {
        switch self {
        case .renderFailed: "PNG önizlemesi oluşturulamadı."
        case .noWindow: "Paylaşım menüsü için açık pencere bulunamadı."
        }
    }
}

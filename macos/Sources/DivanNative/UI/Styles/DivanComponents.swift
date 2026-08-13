import AppKit
import SwiftUI

public enum DivanPalette {
    public static let wine = adaptive(
        name: "DivanWine",
        light: NSColor(srgbRed: 0.34, green: 0.12, blue: 0.17, alpha: 1),
        dark: NSColor(srgbRed: 0.96, green: 0.70, blue: 0.75, alpha: 1)
    )
    public static let wineDeep = adaptive(
        name: "DivanWineDeep",
        light: NSColor(srgbRed: 0.19, green: 0.07, blue: 0.10, alpha: 1),
        dark: NSColor(srgbRed: 0.93, green: 0.72, blue: 0.76, alpha: 1)
    )
    public static let gold = adaptive(
        name: "DivanGold",
        light: NSColor(srgbRed: 0.70, green: 0.53, blue: 0.29, alpha: 1),
        dark: NSColor(srgbRed: 0.84, green: 0.68, blue: 0.43, alpha: 1)
    )
    public static let parchment = adaptive(
        name: "DivanParchment",
        light: NSColor(srgbRed: 0.96, green: 0.92, blue: 0.83, alpha: 1),
        dark: NSColor(srgbRed: 0.24, green: 0.19, blue: 0.16, alpha: 1)
    )
    public static let ink = adaptive(
        name: "DivanInk",
        light: NSColor(srgbRed: 0.18, green: 0.14, blue: 0.10, alpha: 1),
        dark: NSColor(srgbRed: 0.93, green: 0.90, blue: 0.86, alpha: 1)
    )

    private static func adaptive(
        name: String,
        light: NSColor,
        dark: NSColor
    ) -> Color {
        Color(nsColor: NSColor(name: NSColor.Name(name)) { appearance in
            appearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua
                ? dark : light
        })
    }
}

extension DynamicTypeSize {
    /// Scale used by AppKit-backed controls that do not inherit SwiftUI's
    /// Dynamic Type environment automatically.
    var divanFontScale: CGFloat {
        switch self {
        case .xSmall: 0.82
        case .small: 0.90
        case .medium: 0.95
        case .large: 1.00
        case .xLarge: 1.15
        case .xxLarge: 1.30
        case .xxxLarge: 1.42
        case .accessibility1: 1.52
        case .accessibility2: 1.64
        case .accessibility3: 1.78
        case .accessibility4: 1.92
        case .accessibility5: 2.08
        @unknown default: 1.00
        }
    }

    var divanIsAccessibilitySize: Bool {
        switch self {
        case .accessibility1, .accessibility2, .accessibility3,
             .accessibility4, .accessibility5:
            true
        default:
            false
        }
    }
}

public struct DivanPersonaPortrait: View {
    public let master: DivanMaster?
    @ObservedObject private var model: DivanViewModel
    public var size: CGFloat = 52

    public init(
        master: DivanMaster?,
        model: DivanViewModel,
        size: CGFloat = 52
    ) {
        self.master = master
        self.model = model
        self.size = size
    }

    public var body: some View {
        Group {
            if let data = model.portraitData(for: master),
               let image = NSImage(data: data) {
                Image(nsImage: image).resizable().scaledToFill()
            } else {
                fallback
            }
        }
        .frame(width: size, height: size)
        .background(.quaternary)
        .clipShape(Circle())
        .overlay(Circle().stroke(DivanPalette.gold.opacity(0.75), lineWidth: 1.5))
        .accessibilityHidden(true)
        .task(id: master?.id) {
            await model.loadPortrait(for: master)
        }
    }

    private var fallback: some View {
        Text(initials)
            .font(.system(size: max(11, size * 0.25), weight: .semibold, design: .serif))
            .foregroundStyle(DivanPalette.wine)
    }

    private var initials: String {
        let words = master?.name.split(separator: " ") ?? []
        return words.prefix(3).compactMap(\.first).map(String.init).joined()
    }
}

public struct AISimulationBadge: View {
    public init() {}

    public var body: some View {
        Label("AI canlandırması", systemImage: "sparkles")
            .font(.caption2.weight(.semibold))
            .foregroundStyle(DivanPalette.wine)
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .background(DivanPalette.parchment.opacity(0.85), in: Capsule())
            .overlay(Capsule().stroke(DivanPalette.gold.opacity(0.55)))
            .accessibilityLabel("Yapay zekâ canlandırması")
    }
}

public struct NativePreviewScopeBadge: View {
    public init() {}

    public var body: some View {
        Label("Bu Mac’te özel veri alanı", systemImage: "internaldrive")
            .font(.caption)
            .foregroundStyle(.secondary)
            .accessibilityHint("Mevcut Divan verilerini değiştirmez")
    }
}

public struct DivanNoticeBanner: View {
    public let notice: DivanNotice
    public let retry: () -> Void
    public let dismiss: () -> Void

    public init(
        notice: DivanNotice,
        retry: @escaping () -> Void,
        dismiss: @escaping () -> Void
    ) {
        self.notice = notice
        self.retry = retry
        self.dismiss = dismiss
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .top, spacing: 8) {
                Image(systemName: "exclamationmark.triangle.fill")
                    .foregroundStyle(.orange)
                    .accessibilityHidden(true)
                Text(notice.title).font(.headline)
                Spacer(minLength: 4)
                Button(action: dismiss) {
                    Image(systemName: "xmark")
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Uyarıyı kapat")
            }
            Text(notice.message)
                .font(.callout)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
                .textSelection(.enabled)
            if notice.retry != nil {
                Button("Yeniden dene", action: retry)
            }
        }
        .padding(12)
        .background(.regularMaterial)
        .overlay(alignment: .bottom) { Divider() }
        .accessibilityElement(children: .contain)
    }
}

public struct DivanEmptyState: View {
    public let systemImage: String
    public let title: String
    public let message: String
    public var actionTitle: String?
    public var action: (() -> Void)?

    public init(
        systemImage: String,
        title: String,
        message: String,
        actionTitle: String? = nil,
        action: (() -> Void)? = nil
    ) {
        self.systemImage = systemImage
        self.title = title
        self.message = message
        self.actionTitle = actionTitle
        self.action = action
    }

    public var body: some View {
        VStack(spacing: 12) {
            Image(systemName: systemImage)
                .font(.system(size: 38, weight: .light))
                .foregroundStyle(DivanPalette.gold)
                .accessibilityHidden(true)
            Text(title).font(.title3.weight(.semibold))
            Text(message)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .frame(maxWidth: 420)
            if let actionTitle, let action {
                Button(actionTitle, action: action)
                    .buttonStyle(.borderedProminent)
                    .tint(DivanPalette.wine)
            }
        }
        .padding(28)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

import SwiftUI

/// The title bar is the single identity surface while a root Divan window is
/// visible. Standalone previews keep their local headers through the default
/// `false` value.
private struct DivanWindowToolbarIdentityKey: EnvironmentKey {
    static let defaultValue = false
}

extension EnvironmentValues {
    var divanWindowToolbarProvidesIdentity: Bool {
        get { self[DivanWindowToolbarIdentityKey.self] }
        set { self[DivanWindowToolbarIdentityKey.self] = newValue }
    }
}

enum DivanWindowToolbarContext: Equatable {
    case master(DivanMaster)
    case destination(title: String, systemImage: String)

    @MainActor
    static func resolve(model: DivanViewModel) -> Self {
        switch model.destination {
        case .recent, .archived:
            if let conversation = model.selectedConversation,
               let master = model.master(id: conversation.masterID) {
                return .master(master)
            }
        case .masters:
            if let selectedID = model.selectedCatalogMasterID,
               let master = model.master(id: selectedID) {
                return .master(master)
            }
        case .works, .livingMap:
            if let conversation = model.advancedConversation,
               let master = model.master(id: conversation.masterID) {
                return .master(master)
            }
        case .notebook, .letters, .dreams:
            // Defter yüzeyleri bir ustaya aittir; başlıkta o usta görünsün.
            if let selectedID = model.selectedCatalogMasterID,
               let master = model.master(id: selectedID) {
                return .master(master)
            }
        case .sync, .settings, .profile:
            break
        }
        return .destination(
            title: model.destination.title,
            systemImage: model.destination.systemImage
        )
    }
}

struct DivanToolbarBrand: View {
    var body: some View {
        Image(systemName: "sofa.fill")
            .font(.system(size: 15, weight: .semibold))
            .foregroundStyle(DivanPalette.wine)
            .frame(width: 24, height: 24)
            .contentShape(Rectangle())
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Divan logosu")
        .accessibilityIdentifier("divan.toolbar.brand")
    }
}

struct DivanToolbarContextView: View {
    let context: DivanWindowToolbarContext
    @ObservedObject var model: DivanViewModel
    let compact: Bool

    var body: some View {
        Group {
            switch context {
            case let .master(master):
                masterContext(master)
            case let .destination(title, systemImage):
                destinationContext(title: title, systemImage: systemImage)
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(contextAccessibilityLabel)
        .accessibilityIdentifier("divan.toolbar.context")
    }

    private var contextAccessibilityLabel: String {
        switch context {
        case let .master(master):
            return [master.name, master.school, "AI canlandırması"]
                .filter { !$0.isEmpty }
                .joined(separator: ", ")
        case let .destination(title, _):
            return title
        }
    }

    private func masterContext(_ master: DivanMaster) -> some View {
        HStack(spacing: compact ? 7 : 9) {
            DivanPersonaPortrait(
                master: master,
                model: model,
                size: compact ? 28 : 32
            )
            .accessibilityIdentifier("divan.toolbar.portrait")

            VStack(alignment: .leading, spacing: 0) {
                Text(master.name)
                    .font(.headline)
                    .lineLimit(1)
                    .truncationMode(.tail)
                Text(master.school)
                    .font(compact ? .caption2 : .caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                    .truncationMode(.tail)
            }

            aiBadge
        }
    }

    private var aiBadge: some View {
        Label {
            if !compact { Text("AI canlandırması") }
        } icon: {
            Image(systemName: "sparkles")
        }
        .font(.caption2.weight(.medium))
        .foregroundStyle(.secondary)
        .padding(.horizontal, compact ? 5 : 7)
        .padding(.vertical, 3)
        .background(.quaternary, in: Capsule())
        .accessibilityLabel("AI canlandırması")
    }

    private func destinationContext(
        title: String,
        systemImage: String
    ) -> some View {
        Label(title, systemImage: systemImage)
            .font(.headline)
            .foregroundStyle(.secondary)
            .lineLimit(1)
            .accessibilityLabel(title)
    }
}

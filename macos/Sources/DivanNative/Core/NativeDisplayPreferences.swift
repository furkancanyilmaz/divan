import Foundation

/// Native-only text presets. These values are intentionally independent from
/// provider settings and never cross the local HTTP API boundary.
public enum DivanTextSizePreference: String, CaseIterable, Identifiable,
    Codable, Sendable {
    case small
    case standard
    case large
    case extraLarge = "extra_large"

    public var id: Self { self }

    public var title: String {
        switch self {
        case .small: "Küçük"
        case .standard: "Standart"
        case .large: "Büyük"
        case .extraLarge: "Çok büyük"
        }
    }

    /// A platform-neutral value for preview labels and non-SwiftUI consumers.
    /// SwiftUI maps the same preset to DynamicTypeSize at the root view.
    public var scale: Double {
        switch self {
        case .small: 0.90
        case .standard: 1.00
        case .large: 1.15
        case .extraLarge: 1.30
        }
    }
}

public enum DivanAppearancePreference: String, CaseIterable, Identifiable,
    Codable, Sendable {
    case system
    case light
    case dark

    public var id: Self { self }

    public var title: String {
        switch self {
        case .system: "Sistem"
        case .light: "Açık"
        case .dark: "Koyu"
        }
    }
}

public struct DivanDisplayPreferences: Codable, Equatable, Sendable {
    public var textSize: DivanTextSizePreference
    public var appearance: DivanAppearancePreference
    /// Pencere diğer uygulamaların üstünde kalsın mı? FaceTime'ın görüntü
    /// penceresi gibi: sohbet görünür kalırken başka bir işle uğraşılabilir.
    public var keepsWindowOnTop: Bool

    public init(
        textSize: DivanTextSizePreference = .standard,
        appearance: DivanAppearancePreference = .system,
        keepsWindowOnTop: Bool = false
    ) {
        self.textSize = textSize
        self.appearance = appearance
        self.keepsWindowOnTop = keepsWindowOnTop
    }

    public static let `default` = DivanDisplayPreferences()
}

/// Synchronous by design: UserDefaults is local, tiny, and must be available
/// before the first SwiftUI frame chooses its color scheme and text size.
@MainActor
public protocol DivanDisplayPreferencesStore: AnyObject {
    func load() -> DivanDisplayPreferences
    func save(_ preferences: DivanDisplayPreferences)
}

@MainActor
public final class UserDefaultsDivanDisplayPreferencesStore:
    DivanDisplayPreferencesStore {
    public static let textSizeKey = "divan.native.display.text-size.v1"
    public static let appearanceKey = "divan.native.display.appearance.v1"
    public static let onTopKey = "divan.native.display.on-top.v1"

    private let defaults: UserDefaults

    public init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
    }

    public func load() -> DivanDisplayPreferences {
        let textSize = defaults.string(forKey: Self.textSizeKey)
            .flatMap(DivanTextSizePreference.init(rawValue:)) ?? .standard
        let appearance = defaults.string(forKey: Self.appearanceKey)
            .flatMap(DivanAppearancePreference.init(rawValue:)) ?? .system
        return DivanDisplayPreferences(
            textSize: textSize,
            appearance: appearance,
            keepsWindowOnTop: defaults.bool(forKey: Self.onTopKey)
        )
    }

    public func save(_ preferences: DivanDisplayPreferences) {
        defaults.set(preferences.textSize.rawValue, forKey: Self.textSizeKey)
        defaults.set(preferences.appearance.rawValue, forKey: Self.appearanceKey)
        defaults.set(preferences.keepsWindowOnTop, forKey: Self.onTopKey)
    }
}

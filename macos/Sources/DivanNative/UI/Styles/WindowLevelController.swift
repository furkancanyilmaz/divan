import AppKit
import SwiftUI

/// Pencereyi diğer uygulamaların üstünde tutar (FaceTime'ın görüntü
/// penceresi gibi).
///
/// SwiftUI'nin `WindowGroup`'u pencere seviyesini doğrudan açmaz; bu yüzden
/// görünümün bağlı olduğu `NSWindow`'a erişip `level` değerini değiştiriyoruz.
///
/// `.floating` seçildi, `.screenSaver` gibi daha yüksek seviyeler değil:
/// kullanıcı hâlâ menü çubuğunu, bildirimleri ve sistem uyarılarını
/// görebilmeli. Yalnız sıradan uygulama pencerelerinin üstüne çıkarız.
struct WindowLevelModifier: ViewModifier {
    let keepsOnTop: Bool

    func body(content: Content) -> some View {
        content.background(WindowLevelBridge(keepsOnTop: keepsOnTop))
    }
}

private struct WindowLevelBridge: NSViewRepresentable {
    let keepsOnTop: Bool

    func makeNSView(context: Context) -> NSView {
        let view = NSView(frame: .zero)
        // Pencere ilk karede henüz bağlı olmayabilir; bir sonraki döngüde
        // yeniden dener.
        DispatchQueue.main.async { apply(from: view) }
        return view
    }

    func updateNSView(_ nsView: NSView, context: Context) {
        DispatchQueue.main.async { apply(from: nsView) }
    }

    private func apply(from view: NSView) {
        guard let window = view.window else { return }
        let desired: NSWindow.Level = keepsOnTop ? .floating : .normal
        guard window.level != desired else { return }
        window.level = desired
        // Üstte kalan pencere, kullanıcı başka bir Space'e geçtiğinde de
        // görünür kalsın; FaceTime bunu böyle yapar.
        if keepsOnTop {
            window.collectionBehavior.insert(.canJoinAllSpaces)
        } else {
            window.collectionBehavior.remove(.canJoinAllSpaces)
        }
    }
}

extension View {
    /// Pencereyi üstte tutma tercihini uygular.
    func divanKeepsWindowOnTop(_ keepsOnTop: Bool) -> some View {
        modifier(WindowLevelModifier(keepsOnTop: keepsOnTop))
    }
}

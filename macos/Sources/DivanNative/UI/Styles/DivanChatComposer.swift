import AppKit
import SwiftUI

enum DivanComposerReturnAction: Equatable {
    case send
    case newline
    case ignore
}

enum DivanComposerReturnBehavior {
    static func action(text: String, shiftPressed: Bool) -> DivanComposerReturnAction {
        if shiftPressed { return .newline }
        return text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            ? .ignore : .send
    }
}

/// AppKit-backed composer so Return and Shift-Return behave consistently on
/// macOS. SwiftUI's multiline TextField changes Return semantics between OS
/// releases, which made the primary send action unreliable.
public struct DivanChatComposer: NSViewRepresentable {
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @Binding private var text: String
    @Binding private var isFocused: Bool
    private let isEnabled: Bool
    private let canSend: Bool
    private let onHeightChange: @MainActor (CGFloat) -> Void
    private let onSend: @MainActor () -> Void

    public init(
        text: Binding<String>,
        isEnabled: Bool,
        canSend: Bool? = nil,
        isFocused: Binding<Bool> = .constant(false),
        onHeightChange: @escaping @MainActor (CGFloat) -> Void = { _ in },
        onSend: @escaping @MainActor () -> Void
    ) {
        _text = text
        _isFocused = isFocused
        self.isEnabled = isEnabled
        self.canSend = canSend ?? isEnabled
        self.onHeightChange = onHeightChange
        self.onSend = onSend
    }

    public func makeCoordinator() -> Coordinator {
        Coordinator(
            text: $text,
            isFocused: $isFocused,
            canSend: canSend,
            onHeightChange: onHeightChange,
            onSend: onSend
        )
    }

    public func makeNSView(context: Context) -> NSScrollView {
        let scroll = ComposerMeasuringScrollView()
        scroll.drawsBackground = false
        scroll.borderType = .noBorder
        scroll.hasVerticalScroller = true
        scroll.autohidesScrollers = true

        let editor = NSTextView()
        editor.delegate = context.coordinator
        editor.drawsBackground = false
        editor.isRichText = false
        editor.importsGraphics = false
        editor.allowsUndo = true
        editor.isAutomaticQuoteSubstitutionEnabled = true
        editor.isAutomaticDashSubstitutionEnabled = true
        editor.isAutomaticSpellingCorrectionEnabled = true
        editor.font = composerFont
        editor.textColor = .labelColor
        editor.textContainerInset = composerInsets
        editor.typingAttributes = composerTypingAttributes
        editor.textContainer?.lineFragmentPadding = 0
        editor.textContainer?.widthTracksTextView = true
        editor.isVerticallyResizable = true
        editor.isHorizontallyResizable = false
        editor.autoresizingMask = [.width]
        editor.setAccessibilityIdentifier("divan.chat.composerEditor")
        editor.setAccessibilityLabel("Mesaj")
        editor.setAccessibilityHelp("Göndermek için Return, yeni satır için Shift Return")
        scroll.documentView = editor
        context.coordinator.editor = editor
        scroll.onLayout = { [weak coordinator = context.coordinator] in
            coordinator?.reportHeightDeferred()
        }
        context.coordinator.reportHeightDeferred()
        return scroll
    }

    public func updateNSView(_ scroll: NSScrollView, context: Context) {
        guard let editor = scroll.documentView as? NSTextView else { return }
        context.coordinator.canSend = canSend
        context.coordinator.onHeightChange = onHeightChange
        if editor.string != text {
            let selection = editor.selectedRange()
            editor.string = text
            editor.setSelectedRange(NSRange(
                location: min(selection.location, (text as NSString).length),
                length: 0
            ))
        }
        editor.isEditable = isEnabled
        // A response in progress disables Send, not drafting or copying.
        editor.isSelectable = true
        editor.font = composerFont
        editor.textContainerInset = composerInsets
        var attributes = composerTypingAttributes
        attributes[.foregroundColor] = isEnabled
            ? NSColor.labelColor : NSColor.disabledControlTextColor
        editor.typingAttributes = attributes
        // Var olan metin de aynı kaydırmayı almalı; aksi hâlde yazdıkça
        // eski karakterler yukarıda kalırdı.
        if editor.string.isEmpty == false {
            let range = NSRange(location: 0, length: (editor.string as NSString).length)
            editor.textStorage?.addAttributes(attributes, range: range)
        }
        editor.textColor = isEnabled ? .labelColor : .disabledControlTextColor
        editor.insertionPointColor = isEnabled ? .controlAccentColor : .disabledControlTextColor
        scroll.alphaValue = isEnabled ? 1 : 0.78
        context.coordinator.reportHeightDeferred()
    }

    private var composerFont: NSFont {
        let base = NSFont.preferredFont(forTextStyle: .body)
        return NSFont.systemFont(
            ofSize: max(11, base.pointSize * dynamicTypeSize.divanFontScale),
            weight: .regular
        )
    }

    /// Kapsül kenarıyla metin arasındaki iç boşluk.
    ///
    /// Yatayda 14pt: yuvarlak kapsülün kavisi yüzünden 9pt görsel olarak
    /// metni kenara yapıştırıyordu. Dikeyde simetrik ölçülür; metnin optik
    /// merkezin altına inmesi `composerBaselineDrop` ile ayrı sağlanır.
    static let composerHorizontalInset: CGFloat = 14

    private var composerInsets: NSSize {
        NSSize(
            width: Self.composerHorizontalInset,
            height: max(9, 10 * dynamicTypeSize.divanFontScale)
        )
    }

    /// Metni kutunun optik merkezinin altına indiren taban çizgisi kaydırması.
    ///
    /// `NSTextView` tek bir dikey `textContainerInset` aldığı için metin
    /// kutuda tam ortalanır; WhatsApp'ta yazı gözle görülür biçimde merkezin
    /// altında durur. `.baselineOffset` negatif verildiğinde metin aşağı
    /// iner ve satır yüksekliğini şişirmez — `paragraphSpacingBefore` ilk
    /// satırda güvenilir çalışmıyordu.
    private var composerBaselineDrop: CGFloat {
        max(1, 1.5 * dynamicTypeSize.divanFontScale)
    }

    /// Yer tutucu metnin editörle birebir hizalanabilmesi için ölçüler.
    /// SwiftUI tarafı bunları okur; iki metin farklı yazı tipi veya farklı
    /// sol boşluk kullanırsa imleç yazının içine giriyormuş gibi görünür.
    static func placeholderFont(for size: DynamicTypeSize) -> Font {
        let base = NSFont.preferredFont(forTextStyle: .body).pointSize
        return .system(size: max(11, base * size.divanFontScale))
    }

    /// Yer tutucunun da gerçek metinle aynı kadar aşağı inmesi gerekir;
    /// aksi hâlde yazmaya başlayınca metin bir tık zıplıyormuş gibi olur.
    static func placeholderBaselineDrop(for size: DynamicTypeSize) -> CGFloat {
        max(1, 1.5 * size.divanFontScale)
    }

    private var composerTypingAttributes: [NSAttributedString.Key: Any] {
        [
            .font: composerFont,
            .foregroundColor: NSColor.labelColor,
            .baselineOffset: -composerBaselineDrop,
        ]
    }

    public final class Coordinator: NSObject, NSTextViewDelegate {
        @Binding private var text: String
        @Binding private var isFocused: Bool
        private let onSend: @MainActor () -> Void
        fileprivate var canSend: Bool
        fileprivate var onHeightChange: @MainActor (CGFloat) -> Void
        fileprivate weak var editor: NSTextView?
        private var heightReportScheduled = false
        private var lastReportedHeight: CGFloat = 0

        init(
            text: Binding<String>,
            isFocused: Binding<Bool>,
            canSend: Bool,
            onHeightChange: @escaping @MainActor (CGFloat) -> Void,
            onSend: @escaping @MainActor () -> Void
        ) {
            _text = text
            _isFocused = isFocused
            self.canSend = canSend
            self.onHeightChange = onHeightChange
            self.onSend = onSend
        }

        public func textDidBeginEditing(_ notification: Notification) {
            isFocused = true
        }

        public func textDidEndEditing(_ notification: Notification) {
            isFocused = false
        }

        public func textDidChange(_ notification: Notification) {
            guard let editor = notification.object as? NSTextView else { return }
            text = editor.string
            reportHeightDeferred()
        }

        public func textView(
            _ textView: NSTextView,
            doCommandBy commandSelector: Selector
        ) -> Bool {
            guard commandSelector == #selector(NSResponder.insertNewline(_:))
                    || commandSelector == #selector(
                        NSResponder.insertNewlineIgnoringFieldEditor(_:)
                    ) else { return false }

            let action = DivanComposerReturnBehavior.action(
                text: textView.string,
                shiftPressed: NSApp.currentEvent?.modifierFlags.contains(.shift) == true
            )
            if action == .newline {
                textView.insertText("\n", replacementRange: textView.selectedRange())
                return true
            }
            if action == .send, canSend {
                Task { @MainActor in onSend() }
            }
            return true
        }

        fileprivate func reportHeightDeferred() {
            guard !heightReportScheduled else { return }
            heightReportScheduled = true
            DispatchQueue.main.async { [weak self] in
                guard let self else { return }
                self.heightReportScheduled = false
                self.reportHeight()
            }
        }

        private func reportHeight() {
            guard let editor,
                  let layoutManager = editor.layoutManager,
                  let textContainer = editor.textContainer else { return }
            layoutManager.ensureLayout(for: textContainer)
            let lineHeight = layoutManager.defaultLineHeight(for: editor.font
                ?? NSFont.preferredFont(forTextStyle: .body))
            let contentHeight = max(
                lineHeight,
                layoutManager.usedRect(for: textContainer).height
            )
            // Kaydırma kutuyu büyütmemeli: büyütülürse eklenen pay altta
            // birikiyor ve metin optik olarak merkezin ÜSTÜNDE kalıyordu —
            // istenenin tam tersi. Simetrik ölçüp kaydırmayı yalnız metne
            // uyguluyoruz; tek satırlık kutuda kırpılma olmuyor çünkü
            // dikey iç boşluk (>=9pt) kaydırmadan (<=2pt) fazla.
            let insets = editor.textContainerInset.height * 2
            let wanted = min(
                ceil(lineHeight * 5 + insets),
                max(ceil(lineHeight + insets), ceil(contentHeight + insets))
            )
            guard abs(wanted - lastReportedHeight) > 0.5 else { return }
            lastReportedHeight = wanted
            Task { @MainActor [onHeightChange] in
                onHeightChange(wanted)
            }
        }
    }
}

private final class ComposerMeasuringScrollView: NSScrollView {
    var onLayout: (() -> Void)?

    override func layout() {
        super.layout()
        onLayout?()
    }
}

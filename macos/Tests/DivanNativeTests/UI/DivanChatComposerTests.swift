import AppKit
import SwiftUI
import XCTest
@testable import DivanNative

@MainActor
final class DivanChatComposerTests: XCTestCase {
    func testReturnSendsNonemptyMessage() {
        XCTAssertEqual(
            DivanComposerReturnBehavior.action(
                text: "Merhaba",
                shiftPressed: false
            ),
            .send
        )
    }

    func testShiftReturnCreatesNewline() {
        XCTAssertEqual(
            DivanComposerReturnBehavior.action(
                text: "Bir satır",
                shiftPressed: true
            ),
            .newline
        )
    }

    func testReturnDoesNotSendWhitespace() {
        XCTAssertEqual(
            DivanComposerReturnBehavior.action(
                text: "  \n ",
                shiftPressed: false
            ),
            .ignore
        )
    }

    func testComposerCanBecomeFirstResponderAfterRepeatedFocusCycles() throws {
        var value = "İkinci odak döngüsü"
        let binding = Binding<String>(
            get: { value },
            set: { value = $0 }
        )
        let hosting = NSHostingView(rootView: DivanChatComposer(
            text: binding,
            isEnabled: true,
            onSend: {}
        ))
        hosting.frame = NSRect(x: 0, y: 0, width: 420, height: 80)
        let window = NSWindow(
            contentRect: hosting.frame,
            styleMask: [.borderless],
            backing: .buffered,
            defer: false
        )
        window.contentView = hosting
        hosting.layoutSubtreeIfNeeded()

        let editor = try XCTUnwrap(firstTextView(in: hosting))
        XCTAssertTrue(window.makeFirstResponder(editor))
        XCTAssertTrue(window.firstResponder === editor)
        XCTAssertTrue(window.makeFirstResponder(nil))
        XCTAssertTrue(window.makeFirstResponder(editor))
        XCTAssertTrue(window.firstResponder === editor)
        XCTAssertEqual(editor.string, value)
        window.contentView = nil
    }

    func testComposerMeasuresWrappedTextAndUpdatesFontForTextPreset() async throws {
        var value = String(repeating: "Uzun bir cümle gerçek satır genişliğine göre ölçülür. ", count: 8)
        var measuredHeights: [CGFloat] = []
        let binding = Binding<String>(
            get: { value },
            set: { value = $0 }
        )
        let standard = NSHostingView(rootView:
            DivanChatComposer(
                text: binding,
                isEnabled: true,
                onHeightChange: { measuredHeights.append($0) },
                onSend: {}
            )
            .environment(\.dynamicTypeSize, .large)
        )
        standard.frame = NSRect(x: 0, y: 0, width: 240, height: 180)
        standard.layoutSubtreeIfNeeded()
        for _ in 0..<4 {
            await Task.yield()
            standard.layoutSubtreeIfNeeded()
        }

        let standardEditor = try XCTUnwrap(firstTextView(in: standard))
        let standardPointSize = try XCTUnwrap(standardEditor.font).pointSize
        XCTAssertGreaterThan(
            measuredHeights.last ?? 0,
            40,
            "Dar editörde gerçek LayoutManager ölçümü birden fazla satırı bildirmeli."
        )

        let large = NSHostingView(rootView:
            DivanChatComposer(
                text: binding,
                isEnabled: true,
                onSend: {}
            )
            .environment(\.dynamicTypeSize, .xxLarge)
        )
        large.frame = NSRect(x: 0, y: 0, width: 240, height: 180)
        large.layoutSubtreeIfNeeded()
        await Task.yield()
        large.layoutSubtreeIfNeeded()
        let largeEditor = try XCTUnwrap(firstTextView(in: large))
        XCTAssertGreaterThan(
            try XCTUnwrap(largeEditor.font).pointSize,
            standardPointSize,
            "Yerel AppKit editörü yazı boyutu tercihini canlı yansıtmalı."
        )
    }

    func testComposerStaysEditableWhileSendIsTemporarilyUnavailable() throws {
        var value = "Yanıt sürerken taslağımı yazabilirim"
        let binding = Binding<String>(get: { value }, set: { value = $0 })
        let hosting = NSHostingView(rootView: DivanChatComposer(
            text: binding,
            isEnabled: true,
            canSend: false,
            onSend: { XCTFail("Gönder devre dışıyken Return yeni istek açmamalı") }
        ))
        hosting.frame = NSRect(x: 0, y: 0, width: 420, height: 80)
        hosting.layoutSubtreeIfNeeded()

        let editor = try XCTUnwrap(firstTextView(in: hosting))
        XCTAssertTrue(editor.isEditable)
        XCTAssertTrue(editor.isSelectable)
        XCTAssertEqual(editor.accessibilityIdentifier(), "divan.chat.composerEditor")

        var focused = false
        let coordinator = DivanChatComposer.Coordinator(
            text: binding,
            isFocused: Binding(get: { focused }, set: { focused = $0 }),
            canSend: false,
            onHeightChange: { _ in },
            onSend: { XCTFail("Gönder devre dışıyken Return yeni istek açmamalı") }
        )
        editor.string = value
        XCTAssertTrue(coordinator.textView(
            editor,
            doCommandBy: #selector(NSResponder.insertNewline(_:))
        ))
    }

    private func firstTextView(in root: NSView) -> NSTextView? {
        if let editor = root as? NSTextView { return editor }
        if let scroll = root as? NSScrollView,
           let editor = scroll.documentView as? NSTextView {
            return editor
        }
        for child in root.subviews {
            if let editor = firstTextView(in: child) { return editor }
        }
        return nil
    }
}

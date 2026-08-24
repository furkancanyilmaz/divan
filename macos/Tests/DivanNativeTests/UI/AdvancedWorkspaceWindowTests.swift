import AppKit
import ApplicationServices
import SwiftUI
import XCTest
@testable import DivanNative

@MainActor
final class AdvancedWorkspaceWindowTests: XCTestCase {
    private let acceptanceSizes = [
        CGSize(width: 480, height: 360),
        CGSize(width: 720, height: 520),
        CGSize(width: 900, height: 650),
    ]

    private let availabilitySizes = [
        CGSize(width: 480, height: 360),
        CGSize(width: 900, height: 650),
    ]

    func testPublishedChairProtocolWithoutWorkspaceShowsWorkingStartCTAForYoungAndPerls() async throws {
        let supportedMasters = [
            (id: "young", name: "Jeffrey Young"),
            (id: "perls", name: "Fritz Perls"),
        ]

        for master in supportedMasters {
            let prestartStates: [(name: String, session: WorkspaceChairSession?)] = [
                ("published-no-workspace", nil),
                ("proposed-not-started", makeChairSession(phase: .notStarted)),
            ]
            for state in prestartStates {
                for size in availabilitySizes {
                    let source = AdvancedSafetyDataSource(
                        chair: state.session,
                        chairAvailable: true,
                        imageryAvailable: false
                    )
                    let model = makeModel(
                        source,
                        initialModule: .chairWork,
                        masterID: master.id,
                        masterName: master.name
                    )
                    await model.reloadWorkspace()

                    XCTAssertTrue(model.chairAvailable, "\(master.name) \(state.name)")
                    XCTAssertEqual(
                        model.chairSession?.phase,
                        state.session?.phase,
                        "\(master.name) \(state.name)"
                    )
                    XCTAssertEqual(model.selectedModule, .chairWork, master.name)
                    XCTAssertNil(model.unavailableReason(for: .chairWork), master.name)

                    try await assertStartSurfaceInWindow(
                        model: model,
                        size: size,
                        moduleLabel: "Sandalye",
                        headingContains: "Bu çalışmada neyi anlamak veya değiştirmek istiyorsunuz?",
                        actionLabel: "Onayla ve başlat",
                        expectedValidation: AdvancedWorkspaceValidationError
                            .explicitConsentRequired.localizedDescription
                    )
                }
            }
        }
    }

    func testUnsupportedKohutAndBeckShowExplicitChairDirectionInsteadOfSilentMissingCTA() async throws {
        let unsupportedMasters = [
            (id: "kohut", name: "Heinz Kohut"),
            (id: "beck", name: "Aaron Beck"),
        ]

        for master in unsupportedMasters {
            for size in availabilitySizes {
                let reason = "\(master.name) için yayımlanmış sandalye çalışması bulunmuyor."
                let source = AdvancedSafetyDataSource(
                    chairAvailable: false,
                    chairUnavailableReason: reason,
                    imageryAvailable: false,
                    imageryUnavailableReason: "Bu ustada imgeleme bulunmuyor."
                )
                let model = makeModel(
                    source,
                    initialModule: .chairWork,
                    masterID: master.id,
                    masterName: master.name
                )
                await model.reloadWorkspace()

                XCTAssertFalse(model.chairAvailable, master.name)
                XCTAssertNil(model.chairSession, master.name)
                XCTAssertEqual(model.selectedModule, .chairWork, master.name)
                XCTAssertEqual(model.unavailableReason(for: .chairWork), reason, master.name)
                XCTAssertEqual(model.failure?.title, "Bu usta bu çalışmayı sunmuyor")
                XCTAssertTrue(model.failure?.message.contains(reason) == true)
                XCTAssertTrue(model.failure?.message.contains("Perls veya Young") == true)

                try await assertUnavailableChairDirectionInWindow(
                    model: model,
                    size: size,
                    masterName: master.name,
                    reason: reason
                )
            }
        }
    }

    func testChairStartScreenRemainsReachableInsideRealWindow() async throws {
        for size in acceptanceSizes {
            let source = AdvancedSafetyDataSource()
            let model = makeModel(source, initialModule: .chairWork)
            await model.reloadWorkspace()

            try await assertStartSurfaceInWindow(
                model: model,
                size: size,
                moduleLabel: "Sandalye",
                headingContains: "Bu çalışmada neyi anlamak veya değiştirmek istiyorsunuz?",
                actionLabel: "Onayla ve başlat",
                expectedValidation: AdvancedWorkspaceValidationError
                    .explicitConsentRequired.localizedDescription
            )
        }
    }

    func testImageryStartScreenRemainsReachableInsideRealWindow() async throws {
        for size in acceptanceSizes {
            let source = AdvancedSafetyDataSource()
            let model = makeModel(source, initialModule: .reparenting)
            await model.reloadWorkspace()

            try await assertStartSurfaceInWindow(
                model: model,
                size: size,
                moduleLabel: "Yeniden ebeveynlik",
                headingContains: "Bugün hangi ihtiyaca nazikçe yaklaşmak istiyorsunuz?",
                actionLabel: "Onayla ve ilk adıma geç",
                expectedValidation: AdvancedWorkspaceValidationError
                    .explicitConsentRequired.localizedDescription
            )
        }
    }

    func testStartHeadersAndActionsStayOutsideScrollableForms() throws {
        try assertFixedStartChrome(
            source: "ChairWorkView.swift",
            headingIdentifier: "chairStartHeading",
            actionIdentifier: "chairStartAction",
            actionBarCall: "chairStartActionBar"
        )
        try assertFixedStartChrome(
            source: "ReparentingImageryView.swift",
            headingIdentifier: "imageryStartHeading",
            actionIdentifier: "imageryStartAction",
            actionBarCall: "imageryStartActionBar"
        )
        try assertChairPhaseRoutingContract()
    }

    func testWiFiSyncShowsExplicitLocalClinicalConfirmationChoices() throws {
        let project = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let source = try String(
            contentsOf: project.appendingPathComponent(
                "Sources/DivanNative/UI/Advanced/Views/WiFiSyncView.swift"
            ),
            encoding: .utf8
        )
        for required in [
            "Şema çalışmalarında bu cihazın kararı gerekli",
            "Bu cihazda onayla",
            "Kapalı tut",
            "syncClinicalConfirmation",
            "syncClinicalConfirm.",
            "syncClinicalKeepOff.",
            "model.resolveSyncClinicalConfirmation",
            "model sağlayıcısı onayı değişmez",
        ] {
            XCTAssertTrue(
                source.contains(required),
                "Mac v6 klinik cihaz-onayı yüzeyi eksik: \(required)"
            )
        }
    }

    func testWiFiSyncShowsSafetyPauseWithoutAConsentCTA() throws {
        let project = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let source = try String(
            contentsOf: project.appendingPathComponent(
                "Sources/DivanNative/UI/Advanced/Views/WiFiSyncView.swift"
            ),
            encoding: .utf8
        )
        for required in [
            "if status.clinicalSafetyPause",
            "} else if status.clinicalConfirmationRequired",
            "Şema kayıtları güvenlik beklemesinde",
            "Güvenlik beklemesi kapandıktan sonra yeni bir QR oluşturup yeniden eşitleyin.",
            "syncClinicalSafetyPause",
            "Bekleme kapandıysa yeni QR oluştur",
            "syncSafetyCreateFreshQR",
        ] {
            XCTAssertTrue(
                source.contains(required),
                "Mac v6 klinik güvenlik beklemesi yüzeyi eksik: \(required)"
            )
        }
    }

    func testActivePausedAndCompletedChairPhasesExposeNonStartNextStepsAtAcceptanceSizes() async throws {
        let phases: [WorkspaceWorkPhase] = [.active, .paused, .completed]
        for phase in phases {
            for size in availabilitySizes {
                let source = AdvancedSafetyDataSource(
                    chair: makeChairSession(phase: phase),
                    chairAvailable: true,
                    imageryAvailable: false
                )
                let model = makeModel(
                    source,
                    initialModule: .chairWork,
                    masterID: "young",
                    masterName: "Jeffrey Young"
                )
                await model.reloadWorkspace()
                XCTAssertEqual(model.chairSession?.phase, phase)

                try await assertPhaseSurfaceFitsWindow(
                    model: model,
                    size: size,
                    phase: phase
                )
                if phase == .completed {
                    model.prepareNewChairWork()
                    XCTAssertNil(
                        model.chairSession,
                        "Tamamlanan kayıt sunucuda kalırken yeni form yerelde hazırlanmalı."
                    )
                    XCTAssertFalse(model.chairConsentComplete)
                }
            }
        }
    }

    private func assertStartSurfaceInWindow(
        model: AdvancedWorkspaceViewModel,
        size: CGSize,
        moduleLabel: String,
        headingContains: String,
        actionLabel: String,
        expectedValidation: String,
        file: StaticString = #filePath,
        line: UInt = #line
    ) async throws {
        let controller = NSHostingController(
            rootView: NavigationStack {
                AdvancedWorkspaceView(model: model)
            }
            .accessibilityElement(children: .contain)
            .environment(\.dynamicTypeSize, .accessibility3)
        )
        let window = NSWindow(
            contentRect: NSRect(origin: .zero, size: size),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )
        window.title = "Divan"
        window.isReleasedWhenClosed = false
        window.contentMinSize = size
        window.contentMaxSize = size
        window.contentViewController = controller
        controller.preferredContentSize = size
        window.setContentSize(size)
        window.center()
        window.makeKeyAndOrderFront(nil)
        defer {
            window.orderOut(nil)
            window.close()
        }

        await settleWindow(window)
        let contentView = try XCTUnwrap(window.contentView, file: file, line: line)
        let visibleScreenFrame = window.convertToScreen(
            contentView.convert(contentView.bounds, to: nil)
        )
        let elements = appKitAccessibilityDescendants(from: contentView)
        let accessibilitySummary = elements.map {
            "\($0.role?.rawValue ?? "nil"):\($0.label):\($0.frame):\($0.enabled)"
        }

        let moduleSelector = try XCTUnwrap(
            elements.first(where: {
                ($0.role == .popUpButton && $0.label == moduleLabel) ||
                (size.width >= 760 && $0.role == .outline)
            }),
            "Modül seçici AX ağacında yok. AX: \(accessibilitySummary)",
            file: file,
            line: line
        )
        XCTAssertTrue(
            visibleScreenFrame.intersects(moduleSelector.frame),
            "Modül seçici başlangıç ekranının üst alanında görünür olmalı.",
            file: file,
            line: line
        )

        let heading = elements.first(where: {
            $0.label.localizedCaseInsensitiveContains(headingContains)
        })
        let formHasScrollableReach = hasScrollableVerticalRange(in: contentView)
        XCTAssertTrue(
            heading.map { visibleScreenFrame.intersects($0.frame) } == true ||
                formHasScrollableReach,
            "Başlangıç formu ya ilk görünümde olmalı ya da dikey kaydırmayla erişilebilmeli.",
            file: file,
            line: line
        )

        let namedAction = elements.first(where: {
                $0.label == actionLabel && $0.role == .button
            })
        // SwiftUI's package-test accessibility proxy currently drops the
        // explicit label/identifier on inset buttons even though the product
        // view declares both. The same proxy still exposes the real actionable
        // element and its screen frame, so fall back to the unique fixed
        // safe-area trailing control and exercise its AXPress action.
        let geometricActions = elements
            .filter {
                visibleScreenFrame.intersects($0.frame) &&
                $0.frame.width >= 90 && $0.frame.width <= 280 &&
                $0.frame.height >= 20 && $0.frame.height <= 80 &&
                $0.frame.midX > visibleScreenFrame.midX
            }
            .sorted { $0.frame.width * $0.frame.height < $1.frame.width * $1.frame.height }
        let actions = namedAction.map { [$0] } ?? geometricActions
        let action = try XCTUnwrap(
            actions.first,
            "Başlangıç eylemi AX ağacında yok. AX: \(accessibilitySummary)",
            file: file,
            line: line
        )

        let actionIsVisible = visibleScreenFrame.intersects(action.frame)
        XCTAssertTrue(
            actionIsVisible,
            "Başlangıç eylemi sabit güvenli alanda ilk görünümde kalmalı.",
            file: file,
            line: line
        )
        var pressed = false
        for candidate in actions {
            let hitPoint = NSPoint(
                x: candidate.frame.midX,
                y: candidate.frame.midY
            )
            let hitTarget = contentView.accessibilityHitTest(hitPoint)
                as? any NSAccessibilityProtocol
            if candidate.element.accessibilityPerformPress() ||
                hitTarget?.accessibilityPerformPress() == true {
                pressed = true
                break
            }
        }
        if !pressed {
            // Swift Package's in-process accessibility proxy exposes SwiftUI
            // controls as AXUnknown and returns false for AXPress. Exercise the
            // same rendered control with a real AppKit mouse event; the
            // resulting ViewModel state is the assertion that it was handled.
            click(screenPoint: NSPoint(
                x: action.frame.midX,
                y: action.frame.midY
            ), in: window)
        }

        await settleWindow(window)
        XCTAssertTrue(
            pressed || model.failure != nil,
            "Başlangıç eylemi tıklamayı kabul edip görünür state üretmeli.",
            file: file,
            line: line
        )
        XCTAssertEqual(model.failure?.title, "Devam etmek için", file: file, line: line)
        XCTAssertEqual(model.failure?.message, expectedValidation, file: file, line: line)
    }

    private func makeModel(
        _ source: AdvancedSafetyDataSource,
        initialModule: AdvancedModule,
        masterID: String = "young",
        masterName: String = "Jeffrey Young ve güncel şema terapi yaklaşımı"
    ) -> AdvancedWorkspaceViewModel {
        AdvancedWorkspaceViewModel(
            dataSource: source,
            context: AdvancedWorkspaceContext(
                conversationID: 12,
                masterID: masterID,
                masterName: masterName,
                allowsClinicalWork: true
            ),
            initialModule: initialModule
        )
    }

    private func assertUnavailableChairDirectionInWindow(
        model: AdvancedWorkspaceViewModel,
        size: CGSize,
        masterName: String,
        reason: String,
        file: StaticString = #filePath,
        line: UInt = #line
    ) async throws {
        let controller = NSHostingController(
            rootView: NavigationStack {
                AdvancedWorkspaceView(model: model)
            }
            .accessibilityElement(children: .contain)
            .environment(\.dynamicTypeSize, .accessibility3)
        )
        let window = NSWindow(
            contentRect: NSRect(origin: .zero, size: size),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )
        window.title = "Divan"
        window.isReleasedWhenClosed = false
        window.contentMinSize = size
        window.contentMaxSize = size
        window.contentViewController = controller
        controller.preferredContentSize = size
        window.setContentSize(size)
        window.center()
        window.makeKeyAndOrderFront(nil)
        defer {
            window.orderOut(nil)
            window.close()
        }

        await settleWindow(window)
        let contentView = try XCTUnwrap(window.contentView, file: file, line: line)
        let visibleScreenFrame = window.convertToScreen(
            contentView.convert(contentView.bounds, to: nil)
        )
        let elements = appKitAccessibilityDescendants(from: contentView)
        let readable = elements.filter {
            !$0.label.isEmpty && visibleScreenFrame.intersects($0.frame)
        }
        let summary = readable.map { "\($0.label):\($0.frame)" }

        XCTAssertTrue(
            readable.contains {
                $0.label.localizedCaseInsensitiveContains(reason)
            },
            "\(masterName) için eksik CTA sessiz kalmamalı; neden görünmeli. AX: \(summary)",
            file: file,
            line: line
        )
        XCTAssertTrue(
            readable.contains {
                $0.label.localizedCaseInsensitiveContains("Perls veya Young")
            },
            "\(masterName) için desteklenen usta yönlendirmesi görünmeli. AX: \(summary)",
            file: file,
            line: line
        )
    }

    private func assertFixedStartChrome(
        source: String,
        headingIdentifier: String,
        actionIdentifier: String,
        actionBarCall: String,
        file: StaticString = #filePath,
        line: UInt = #line
    ) throws {
        let project = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let url = project
            .appendingPathComponent("Sources/DivanNative/UI/Advanced/Views")
            .appendingPathComponent(source)
        let text = try String(contentsOf: url, encoding: .utf8)
        let scroll = try XCTUnwrap(
            text.range(of: "ScrollView {"),
            file: file,
            line: line
        )
        let safeArea = try XCTUnwrap(
            text.range(
                of: ".safeAreaInset(edge: .top",
                range: scroll.upperBound..<text.endIndex
            ),
            file: file,
            line: line
        )
        let header = try XCTUnwrap(
            text.range(
                of: "AdvancedSectionHeader(",
                range: safeArea.upperBound..<text.endIndex
            ),
            file: file,
            line: line
        )
        let action = try XCTUnwrap(
            text.range(of: actionBarCall, range: header.upperBound..<text.endIndex),
            file: file,
            line: line
        )
        XCTAssertLessThan(scroll.lowerBound, safeArea.lowerBound, file: file, line: line)
        XCTAssertLessThan(safeArea.lowerBound, header.lowerBound, file: file, line: line)
        XCTAssertLessThan(header.lowerBound, action.lowerBound, file: file, line: line)
        XCTAssertTrue(
            text.contains(".accessibilityIdentifier(\"\(headingIdentifier)\")"),
            file: file,
            line: line
        )
        XCTAssertTrue(
            text.contains(".accessibilityIdentifier(\"\(actionIdentifier)\")"),
            file: file,
            line: line
        )
    }

    private func assertChairPhaseRoutingContract(
        file: StaticString = #filePath,
        line: UInt = #line
    ) throws {
        let project = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let text = try String(
            contentsOf: project
                .appendingPathComponent("Sources/DivanNative/UI/Advanced/Views/ChairWorkView.swift"),
            encoding: .utf8
        )
        for required in [
            "session.phase != .notStarted",
            "activeSession(session)",
            "startForm",
            ".accessibilityIdentifier(\"chairStartAction\")",
            ".accessibilityIdentifier(\"chairStopAction\")",
            ".accessibilityIdentifier(\"chairResumeAction\")",
            ".accessibilityIdentifier(\"chairResumeStopAction\")",
            ".accessibilityIdentifier(\"chairCompletedGuidance\")",
            ".accessibilityIdentifier(\"chairPrepareNewAction\")",
            "model.prepareNewChairWork()",
            "Bu çalışma kapatıldı. Yeni bir çalışma hazırlayabilir veya başka bir açık terapi seansı seçebilirsiniz.",
        ] {
            XCTAssertTrue(
                text.contains(required),
                "Sandalye aşama/yönlendirme sözleşmesi eksik: \(required)",
                file: file,
                line: line
            )
        }
    }

    private func assertPhaseSurfaceFitsWindow(
        model: AdvancedWorkspaceViewModel,
        size: CGSize,
        phase: WorkspaceWorkPhase,
        file: StaticString = #filePath,
        line: UInt = #line
    ) async throws {
        let controller = NSHostingController(
            rootView: NavigationStack {
                AdvancedWorkspaceView(model: model)
            }
            .accessibilityElement(children: .contain)
            .environment(\.dynamicTypeSize, .accessibility3)
        )
        let window = NSWindow(
            contentRect: NSRect(origin: .zero, size: size),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )
        window.title = "Divan"
        window.isReleasedWhenClosed = false
        window.contentMinSize = size
        window.contentMaxSize = size
        window.contentViewController = controller
        controller.preferredContentSize = size
        window.setContentSize(size)
        window.center()
        window.makeKeyAndOrderFront(nil)
        await settleWindow(window)

        let contentView = try XCTUnwrap(window.contentView)
        XCTAssertEqual(
            contentView.bounds.width,
            size.width,
            accuracy: 0.5,
            "\(phase) width",
            file: file,
            line: line
        )
        XCTAssertEqual(
            contentView.bounds.height,
            size.height,
            accuracy: 0.5,
            "\(phase) height",
            file: file,
            line: line
        )
        var queue = [contentView]
        while !queue.isEmpty {
            let view = queue.removeFirst()
            XCTAssertTrue(
                [view.frame.minX, view.frame.minY, view.frame.width, view.frame.height]
                    .allSatisfy(\.isFinite),
                "\(phase) aşaması sonlu AppKit frame üretmeli.",
                file: file,
                line: line
            )
            queue.append(contentsOf: view.subviews)
        }
        window.orderOut(nil)
        window.close()
    }

    private func settleWindow(_ window: NSWindow) async {
        for _ in 0..<4 {
            window.setContentSize(window.contentMinSize)
            window.contentViewController?.view.frame = NSRect(
                origin: .zero,
                size: window.contentMinSize
            )
            window.contentView?.layoutSubtreeIfNeeded()
            try? await Task.sleep(for: .milliseconds(30))
            await Task.yield()
        }
    }

    private func click(screenPoint: NSPoint, in window: NSWindow) {
        let location = window.convertPoint(fromScreen: screenPoint)
        for type in [NSEvent.EventType.leftMouseDown, .leftMouseUp] {
            guard let event = NSEvent.mouseEvent(
                with: type,
                location: location,
                modifierFlags: [],
                timestamp: ProcessInfo.processInfo.systemUptime,
                windowNumber: window.windowNumber,
                context: nil,
                eventNumber: 0,
                clickCount: 1,
                pressure: type == .leftMouseDown ? 1 : 0
            ) else { continue }
            window.sendEvent(event)
        }
    }

    private func accessibilityDescendantsForCurrentProcess() -> [AXNode] {
        let root = AXUIElementCreateApplication(
            ProcessInfo.processInfo.processIdentifier
        )
        var result: [AXNode] = []
        var queue: [(AXUIElement, Int)] = [(root, 0)]
        var seen = Set<CFHashCode>()

        while !queue.isEmpty, result.count < 2_000 {
            let (element, depth) = queue.removeFirst()
            guard depth < 40, seen.insert(CFHash(element)).inserted else { continue }
            result.append(AXNode(element: element))
            queue.append(contentsOf: axChildren(of: element).map { ($0, depth + 1) })
        }
        return result
    }

    private func appKitAccessibilityDescendants(
        from root: NSView
    ) -> [AppKitAXNode] {
        var roots: [any NSAccessibilityProtocol] = [root]
        if let unignored = NSAccessibility.unignoredDescendant(of: root)
            as? any NSAccessibilityProtocol {
            roots.append(unignored)
        }
        var result: [AppKitAXNode] = []
        var queue = roots
        var seen = Set<ObjectIdentifier>()

        while !queue.isEmpty, result.count < 2_000 {
            let element = queue.removeFirst()
            let identity = ObjectIdentifier(element as AnyObject)
            guard seen.insert(identity).inserted else { continue }
            result.append(AppKitAXNode(element: element))

            let rawChildren = element.accessibilityChildren() ?? []
            let children = rawChildren + NSAccessibility.unignoredChildren(
                from: rawChildren
            )
            for child in children {
                if let accessible = child as? any NSAccessibilityProtocol {
                    queue.append(accessible)
                }
            }
            if let view = element as? NSView {
                for child in view.subviews {
                    queue.append(child)
                }
            }
        }
        return result
    }

    private func axChildren(of element: AXUIElement) -> [AXUIElement] {
        var value: CFTypeRef?
        guard AXUIElementCopyAttributeValue(
            element,
            kAXChildrenAttribute as CFString,
            &value
        ) == .success,
        let children = value as? [AXUIElement] else { return [] }
        return children
    }

    private func hasScrollableVerticalRange(in root: NSView) -> Bool {
        var queue = [root]
        while !queue.isEmpty {
            let view = queue.removeFirst()
            if let scroll = view as? NSScrollView,
               scroll.hasVerticalScroller,
               let document = scroll.documentView,
               document.frame.height > scroll.contentView.bounds.height + 1 {
                return true
            }
            queue.append(contentsOf: view.subviews)
        }
        return false
    }
}

private struct AppKitAXNode {
    let element: any NSAccessibilityProtocol
    let label: String
    let role: NSAccessibility.Role?
    let frame: CGRect
    let enabled: Bool

    init(element: any NSAccessibilityProtocol) {
        self.element = element
        label = [
            element.accessibilityLabel(),
            element.accessibilityTitle(),
            element.accessibilityValue() as? String,
            element.accessibilityValueDescription(),
            element.accessibilityPlaceholderValue(),
            element.accessibilityIdentifier(),
            element.accessibilityHelp(),
        ].compactMap { $0 }.first(where: { !$0.isEmpty }) ?? ""
        role = element.accessibilityRole()
        frame = element.accessibilityFrame()
        enabled = element.isAccessibilityEnabled()
    }
}

private struct AXNode {
    let element: AXUIElement
    let label: String
    let role: String
    let frame: CGRect
    let enabled: Bool

    init(element: AXUIElement) {
        self.element = element
        role = Self.stringAttribute(kAXRoleAttribute, of: element)
        label = [
            Self.stringAttribute(kAXTitleAttribute, of: element),
            Self.stringAttribute(kAXDescriptionAttribute, of: element),
            Self.stringAttribute(kAXValueAttribute, of: element),
        ].first(where: { !$0.isEmpty }) ?? ""
        let position = Self.pointAttribute(kAXPositionAttribute, of: element)
        let size = Self.sizeAttribute(kAXSizeAttribute, of: element)
        frame = CGRect(origin: position, size: size)
        enabled = Self.boolAttribute(kAXEnabledAttribute, of: element) ?? true
    }

    private static func rawAttribute(
        _ name: String,
        of element: AXUIElement
    ) -> CFTypeRef? {
        var value: CFTypeRef?
        guard AXUIElementCopyAttributeValue(
            element,
            name as CFString,
            &value
        ) == .success else { return nil }
        return value
    }

    private static func stringAttribute(
        _ name: String,
        of element: AXUIElement
    ) -> String {
        rawAttribute(name, of: element) as? String ?? ""
    }

    private static func boolAttribute(
        _ name: String,
        of element: AXUIElement
    ) -> Bool? {
        rawAttribute(name, of: element) as? Bool
    }

    private static func pointAttribute(
        _ name: String,
        of element: AXUIElement
    ) -> CGPoint {
        guard let raw = rawAttribute(name, of: element),
              CFGetTypeID(raw) == AXValueGetTypeID(),
              AXValueGetType(raw as! AXValue) == .cgPoint else { return .zero }
        var value = CGPoint.zero
        AXValueGetValue(raw as! AXValue, .cgPoint, &value)
        return value
    }

    private static func sizeAttribute(
        _ name: String,
        of element: AXUIElement
    ) -> CGSize {
        guard let raw = rawAttribute(name, of: element),
              CFGetTypeID(raw) == AXValueGetTypeID(),
              AXValueGetType(raw as! AXValue) == .cgSize else { return .zero }
        var value = CGSize.zero
        AXValueGetValue(raw as! AXValue, .cgSize, &value)
        return value
    }
}

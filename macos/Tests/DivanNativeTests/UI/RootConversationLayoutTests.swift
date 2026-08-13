import AppKit
import SwiftUI
import XCTest
@testable import DivanNative

@MainActor
final class RootConversationLayoutTests: XCTestCase {
    func testRootHasTwoColumnContractAndCollapsesAtMinimumWidth() async throws {
        let sizes = [
            CGSize(width: 480, height: 360),
            CGSize(width: 720, height: 520),
            CGSize(width: 900, height: 650),
        ]

        for size in sizes {
            let source = RootConversationDataSource()
            let model = DivanViewModel(dataSource: source)
            await model.bootstrap()
            let conversation = try XCTUnwrap(model.activeConversations.first {
                $0.id == RootConversationDataSource.openTherapyID
            })
            await model.openConversation(conversation)
            model.columnVisibility = .automatic

            let window = makeWindow(
                rootView: DivanRootView(
                    model: model,
                    advancedDataSource: AdvancedSafetyDataSource()
                )
                .environment(\.dynamicTypeSize, .accessibility2),
                size: size
            )
            defer { close(window) }
            await settle(window)

            let content = try XCTUnwrap(window.contentView)
            let splitViews = viewDescendants(from: content)
                .compactMap { $0 as? NSSplitView }
            XCTAssertTrue(splitViews.isEmpty, "Kök düzen gizli bir üçüncü kolon üretmemeli.")

            let scrollFrames = viewDescendants(from: content)
                .compactMap { $0 as? NSScrollView }
                .map { $0.convert($0.bounds, to: content) }
                .filter { $0.width > 80 && $0.height > 80 }
            if size.width >= 680 {
                let sidebarTrailing = desktopSidebarWidth(for: size.width)
                XCTAssertTrue(
                    scrollFrames.contains { $0.midX < sidebarTrailing },
                    "Masaüstünde sol konuşma listesi görünmeli: \(size)"
                )
                XCTAssertTrue(
                    scrollFrames.contains { $0.midX > sidebarTrailing + 1 },
                    "Masaüstünde sağ ayrıntı yüzeyi görünmeli: \(size)"
                )
            } else if size.width == 480 {
                XCTAssertTrue(
                    scrollFrames.contains { $0.width >= content.bounds.width * 0.75 },
                    "480×360 boyutunda sohbet tek geniş ayrıntı kolonuna çökmeli."
                )
            }

            XCTAssertEqual(content.bounds.width, size.width, accuracy: 0.5)
            XCTAssertEqual(content.bounds.height, size.height, accuracy: 0.5)
            XCTAssertTrue(viewDescendants(from: content).allSatisfy {
                [$0.frame.minX, $0.frame.minY, $0.frame.width, $0.frame.height]
                    .allSatisfy(\.isFinite)
            })
        }

        let rootSource = try productSource("DivanRootView.swift")
        XCTAssertTrue(rootSource.contains("private func desktopRoot(size: CGSize)"))
        XCTAssertTrue(rootSource.contains("return HStack(spacing: 0)"))
        XCTAssertTrue(rootSource.contains(".accessibilityIdentifier(\"divan.desktopTwoColumnLayout\")"))
        XCTAssertTrue(rootSource.contains(".accessibilityIdentifier(\"divan.detailColumn\")"))
        XCTAssertFalse(rootSource.contains("NavigationSplitView("))
    }

    func testRecentConversationRowLoadsPortraitAndExposesLatestSummaryAndTime() async throws {
        let source = RootConversationDataSource()
        let model = DivanViewModel(dataSource: source)
        await model.bootstrap()
        let conversation = try XCTUnwrap(model.activeConversations.first {
            $0.id == RootConversationDataSource.openTherapyID
        })
        await model.openConversation(conversation)
        model.destination = .recent
        model.columnVisibility = .all

        let window = makeWindow(
            rootView: DivanRootView(
                model: model,
                advancedDataSource: AdvancedSafetyDataSource()
            ),
            size: CGSize(width: 900, height: 650)
        )
        defer { close(window) }
        await settle(window, cycles: 8)

        let master = try XCTUnwrap(model.master(id: conversation.masterID))
        XCTAssertNotNil(
            model.portraitData(for: master),
            "Konuşma listesi görünür olduğunda kişi portresi yüklenmeli."
        )

        // SwiftUI's package-hosted AppKit accessibility proxy does not expose
        // `.accessibilityElement(children: .combine)` labels consistently.
        // Keep the runtime portrait assertion above, then pin the complete row
        // contract at its source boundary so a future visual simplification
        // cannot silently remove the latest-message or time affordances.
        let sourceText = try productSource("ConversationViews.swift")
        let rowSource = try XCTUnwrap(
            sourceText.slice(
                after: "private struct ConversationRow: View",
                before: "public struct NativeChatView: View"
            )
        )
        for required in [
            // Portrenin varlığı sözleşmedir; piksel boyutu tasarım ayarıdır
            // ve serbest bırakılır.
            "DivanPersonaPortrait(master: master, model: model, size:",
            "Text(master?.name ?? \"Bilinmeyen usta\")",
            "Text(conversation.updatedAt, format:",
            "Text(conversation.preview.isEmpty ? \"Henüz mesaj yok\" : conversation.preview)",
            ".accessibilityLabel(accessibilitySummary)",
            "conversation.preview",
        ] {
            XCTAssertTrue(
                rowSource.contains(required),
                "Konuşma satırının kişi/portre/son mesaj/zaman sözleşmesi eksik: \(required)"
            )
        }
    }

    func testWorkPrimaryListContainsOnlyOpenTherapyConversations() async throws {
        let source = RootConversationDataSource()
        let model = DivanViewModel(dataSource: source)
        await model.bootstrap()

        XCTAssertEqual(
            model.activeTherapyConversations.map(\.id),
            [RootConversationDataSource.openTherapyID]
        )
        model.selectDestination(.works)
        XCTAssertEqual(
            model.advancedConversationID,
            RootConversationDataSource.openTherapyID
        )

        let window = makeWindow(
            rootView: DivanRootView(
                model: model,
                advancedDataSource: AdvancedSafetyDataSource()
            ),
            size: CGSize(width: 900, height: 650)
        )
        defer { close(window) }
        await settle(window)

        XCTAssertEqual(model.advancedConversation?.id, RootConversationDataSource.openTherapyID)

        let sourceText = try productSource("AdvancedContextPickerView.swift")
        XCTAssertTrue(sourceText.contains("List(model.activeTherapyConversations"))
        XCTAssertTrue(sourceText.contains("DivanPersonaPortrait("))
        XCTAssertTrue(sourceText.contains("Text(model.master(id: conversation.masterID)?.name"))
        XCTAssertTrue(sourceText.contains("Text(conversation.title)"))
        XCTAssertTrue(sourceText.contains("Text(conversation.updatedAt, format:"))
    }

    func testRootWorksKeepsSupportedStartCTAsInsideVisibleDetail() async throws {
        try assertRootAdvancedStartSurfaceContract()
        let modules: [AdvancedModule] = [.chairWork, .reparenting]
        for module in modules {
          for size in [
              CGSize(width: 900, height: 650),
              CGSize(width: 1_512, height: 895),
          ] {
            let source = RootConversationDataSource()
            let model = DivanViewModel(dataSource: source)
            await model.bootstrap()
            model.selectDestination(.works)
            model.advancedInitialModule = module
            model.columnVisibility = .all
            XCTAssertEqual(
                model.advancedConversationID,
                RootConversationDataSource.openTherapyID
            )

            let advancedSource = AdvancedSafetyDataSource(
                chairAvailable: module == .chairWork,
                imageryAvailable: module == .reparenting
            )
            let window = makeWindow(
                rootView: DivanRootView(
                    model: model,
                    advancedDataSource: advancedSource
                )
                .environment(\.dynamicTypeSize, .accessibility2),
                size: size
            )
            defer { close(window) }
            await settle(window, cycles: 8)

            let content = try XCTUnwrap(window.contentView)
            XCTAssertEqual(content.bounds.width, size.width, accuracy: 0.5)
            XCTAssertEqual(content.bounds.height, size.height, accuracy: 0.5)
            XCTAssertTrue(viewDescendants(from: content).allSatisfy {
                [$0.frame.minX, $0.frame.minY, $0.frame.width, $0.frame.height]
                    .allSatisfy(\.isFinite)
            })
            XCTAssertNotNil(
                content.hitTest(NSPoint(x: size.width - 24, y: 24)),
                "\(module.shortTitle) ayrıntı yüzeyi pencerenin alt eylem bölgesini kapsamalı."
            )
          }
        }
    }

    func testMainAdvancedSurfacesAcceptNormalAndFullscreenWindowMatrix() async throws {
        let cases: [(size: CGSize, appearance: DivanAppearancePreference)] = [
            (CGSize(width: 900, height: 650), .light),
            (CGSize(width: 1_280, height: 780), .dark),
            (CGSize(width: 1_512, height: 895), .light),
            (CGSize(width: 1_872, height: 1_080), .dark),
        ]

        for acceptance in cases {
            let size = acceptance.size
            let appearance = acceptance.appearance
            for module in AdvancedModule.allCases {
                    let source = RootConversationDataSource()
                    let model = DivanViewModel(dataSource: source)
                    await model.bootstrap()
                    model.textSizePreference = .large
                    model.appearancePreference = appearance
                    model.columnVisibility = .all
                    switch module {
                    case .chairWork, .reparenting:
                        model.selectDestination(.works)
                        model.advancedInitialModule = module
                    case .livingMap:
                        model.selectDestination(.livingMap)
                    case .wifiSync:
                        model.selectDestination(.sync)
                    }

                    let advancedSource = AdvancedSafetyDataSource(
                        chair: fourChairActiveSession(),
                        imagery: makeImagerySession(phase: .active, intensity: 4, limit: 7),
                        chairAvailable: true,
                        imageryAvailable: true
                    )
                    let window = makeWindow(
                        rootView: DivanRootView(
                            model: model,
                            advancedDataSource: advancedSource
                        )
                        .environment(\.dynamicTypeSize, .xLarge),
                        size: size
                    )
                    await settle(window, cycles: 4)

                    let scenario = "\(module.shortTitle), \(appearance.title), " +
                        "\(Int(size.width))×\(Int(size.height))"
                    let content = try XCTUnwrap(window.contentView)
                    let detail = content
                    let sidebarTrailing = desktopSidebarWidth(for: size.width)
                    let detailFrame = CGRect(
                        x: sidebarTrailing + 1,
                        y: 0,
                        width: size.width - sidebarTrailing - 1,
                        height: size.height
                    )
                    XCTAssertGreaterThan(detailFrame.width, 300, scenario)
                    XCTAssertGreaterThan(detailFrame.height, 300, scenario)
                    assertFiniteFrames(in: content, scenario: scenario)

                    if module == .chairWork {
                        assertActiveChairControls(
                            in: detail,
                            content: content,
                            detailFrame: detailFrame,
                            sidebarTrailingEdge: sidebarTrailing,
                            scenario: scenario
                        )
                    } else {
                        assertScrollableAdvancedSurface(
                            in: detail,
                            content: content,
                            detailFrame: detailFrame,
                            scenario: scenario
                        )
                    }
                    close(window)
            }
        }
    }

    func testWindowToolbarKeepsOneDivanAndSelectedPersonIdentityAcrossMatrix()
        async throws {
        let cases: [(size: CGSize, appearance: DivanAppearancePreference)] = [
            (CGSize(width: 480, height: 360), .dark),
            (CGSize(width: 900, height: 650), .light),
            (CGSize(width: 1_280, height: 780), .dark),
            (CGSize(width: 1_512, height: 895), .light),
            (CGSize(width: 1_872, height: 1_080), .dark),
        ]

        for acceptance in cases {
            let source = RootConversationDataSource()
            let model = DivanViewModel(dataSource: source)
            await model.bootstrap()
            let conversation = try XCTUnwrap(model.activeConversations.first {
                $0.id == RootConversationDataSource.openTherapyID
            })
            await model.openConversation(conversation)
            model.textSizePreference = .large
            model.appearancePreference = acceptance.appearance
            model.columnVisibility = .all

            let window = makeWindow(
                rootView: DivanRootView(
                    model: model,
                    advancedDataSource: AdvancedSafetyDataSource()
                )
                .environment(\.dynamicTypeSize, .xLarge),
                size: acceptance.size
            )
            await settle(window, cycles: 6)

            let scenario = "toolbar, \(acceptance.appearance.title), " +
                "\(Int(acceptance.size.width))×\(Int(acceptance.size.height))"
            XCTAssertEqual(window.title, "Divan", "Native pencere adı kaybolmamalı: \(scenario)")
            let toolbar = try XCTUnwrap(
                window.toolbar,
                "Native pencere araç çubuğu eksik: \(scenario)"
            )
            XCTAssertFalse(toolbar.items.isEmpty, "Araç çubuğu boş olamaz: \(scenario)")
            let itemIDs = toolbar.items.map(\.itemIdentifier.rawValue)
            for expected in [
                "divan.toolbar.sidebarToggle",
                "divan.toolbar.brand",
                "divan.toolbar.context",
                "divan.toolbar.newConversation",
                "divan.toolbar.navigationMenu",
            ] {
                XCTAssertEqual(
                    itemIDs.filter { $0 == expected }.count,
                    1,
                    "Native toolbar öğesi tekil olmalı: \(expected), \(scenario), ids=\(itemIDs)"
                )
            }
            let brandItem = try XCTUnwrap(toolbar.items.first {
                $0.itemIdentifier.rawValue == "divan.toolbar.brand"
            })
            XCTAssertNotNil(brandItem.view, "Toolbar Divan görünümü kurulmalı: \(scenario)")
            let contextItem = try XCTUnwrap(toolbar.items.first {
                $0.itemIdentifier.rawValue == "divan.toolbar.context"
            })
            XCTAssertNotNil(contextItem.view, "Toolbar kişi görünümü kurulmalı: \(scenario)")
            switch DivanWindowToolbarContext.resolve(model: model) {
            case let .master(master):
                XCTAssertEqual(master.name, "Jeffrey Young", scenario)
                XCTAssertFalse(master.school.isEmpty, "Kişinin ekolü boş olamaz: \(scenario)")
                XCTAssertNotNil(
                    model.portraitData(for: master),
                    "Seçili kişinin toolbar portresi yüklenmeli: \(scenario)"
                )
            case let .destination(title, _):
                XCTFail("Seçili sohbet kişi yerine \(title) gösteriyor: \(scenario)")
            }
            let hierarchy = try XCTUnwrap(windowHierarchyRoot(window))
            XCTAssertTrue(
                viewDescendants(from: hierarchy).allSatisfy {
                    $0.accessibilityIdentifier() != "divan.primaryHeader"
                },
                "Eski ikinci Divan başlığı render edilmemeli: \(scenario)"
            )
            close(window)
        }

        let rootSource = try productSource("DivanRootView.swift")
        XCTAssertTrue(rootSource.contains(".environment(\\.divanWindowToolbarProvidesIdentity, true)"))
        XCTAssertFalse(rootSource.contains("private var primaryHeader"))
        let toolbarSource = try productSource("DivanWindowToolbar.swift")
        for identifier in [
            "divan.toolbar.brand",
            "divan.toolbar.context",
            "divan.toolbar.portrait",
        ] {
            XCTAssertEqual(
                toolbarSource.components(separatedBy: "\"\(identifier)\"").count - 1,
                1,
                "Toolbar kimliği kaynakta tam bir kez tanımlanmalı: \(identifier)"
            )
        }
        for required in ["Image(systemName: \"sofa.fill\")", "Text(master.name)", "DivanPersonaPortrait("] {
            XCTAssertTrue(toolbarSource.contains(required), "Toolbar görünür kimliği eksik: \(required)")
        }
        let conversationSource = try productSource("ConversationViews.swift")
        let nativeChatSource = try XCTUnwrap(
            conversationSource.slice(
                after: "public struct NativeChatView: View",
                before: "private struct ScrollFollowObserver"
            )
        )
        XCTAssertTrue(nativeChatSource.contains("if !windowToolbarProvidesIdentity"))
    }

    func testActiveFourChairWorkspaceNeverDrawsUnderConversationColumn() async throws {
        for size in [
            CGSize(width: 1_512, height: 895),
            CGSize(width: 1_872, height: 1_080),
        ] {
            let source = RootConversationDataSource()
            let model = DivanViewModel(dataSource: source)
            await model.bootstrap()
            model.selectDestination(.works)
            model.advancedInitialModule = .chairWork
            model.columnVisibility = .all

            let advancedSource = AdvancedSafetyDataSource(
                chair: fourChairActiveSession(),
                chairAvailable: true,
                imageryAvailable: false
            )
            let window = makeWindow(
                rootView: DivanRootView(
                    model: model,
                    advancedDataSource: advancedSource
                ),
                size: size
            )
            defer { close(window) }
            await settle(window, cycles: 10)

            let content = try XCTUnwrap(window.contentView)
            XCTAssertTrue(
                viewDescendants(from: content).compactMap { $0 as? NSSplitView }.isEmpty,
                "WhatsApp kök düzeni NSSplitView kullanmamalı."
            )
            let sidebarTrailing = desktopSidebarWidth(for: size.width)
            let detailFrame = CGRect(
                x: sidebarTrailing + 1,
                y: 0,
                width: size.width - sidebarTrailing - 1,
                height: size.height
            )
            XCTAssertLessThan(
                detailFrame.width,
                size.width - 100,
                "Test gerçekten görünür sol konuşma kolonu ile çalışmalı."
            )

            let detailViews = viewDescendants(from: content).filter {
                $0.convert($0.bounds, to: content).intersects(detailFrame)
            }
            let horizontalSelectors = detailViews.compactMap { $0 as? NSScrollView }
                .filter {
                    $0.hasHorizontalScroller
                }
            let participantFields = detailViews.compactMap { $0 as? NSTextField }
                .filter {
                    ($0.placeholderString ?? "")
                        .localizedCaseInsensitiveContains("sandalyenin adı")
                }
            let turnEditors = detailViews.compactMap { $0 as? NSTextView }
                .filter {
                    $0.isEditable && $0.frame.height >= 40
                }
            XCTAssertFalse(horizontalSelectors.isEmpty, "Dört sandalye yatay kaydırılabilmeli.")
            XCTAssertFalse(participantFields.isEmpty, "Yeni sandalye alanı görünür olmalı.")
            XCTAssertFalse(turnEditors.isEmpty, "Seçili sandalye söz alanı görünür olmalı.")

            let boundedViews: [NSView] = horizontalSelectors.map { $0 as NSView } +
                participantFields.map { $0 as NSView } +
                turnEditors.map { $0 as NSView }
            for view in boundedViews {
                let frame = view.convert(view.bounds, to: content)
                XCTAssertGreaterThanOrEqual(
                    frame.minX,
                    detailFrame.minX - 1,
                    "Aktif sandalye kontrolü sol konuşma listesinin altına taşmamalı: \(type(of: view)) \(frame)"
                )
                XCTAssertLessThanOrEqual(
                    frame.maxX,
                    detailFrame.maxX + 1,
                    "Aktif sandalye kontrolü ayrıntı sütununun sağından taşmamalı: \(type(of: view)) \(frame)"
                )
            }
        }

        let chairSource = try advancedProductSource("Views/ChairWorkView.swift")
        XCTAssertFalse(chairSource.contains("HSplitView"))
        for required in [
            "geometry.size.width < 1_040",
            "let guidanceWidth = min(",
            "HStack(spacing: 0)",
            ".accessibilityIdentifier(\"chairWideWorkspace\")",
            ".accessibilityIdentifier(\"chairSelector\")",
            ".accessibilityIdentifier(\"chairComposer\")",
        ] {
            XCTAssertTrue(chairSource.contains(required), "Aktif sandalye düzeni eksik: \(required)")
        }
    }

    private func makeWindow<Content: View>(
        rootView: Content,
        size: CGSize
    ) -> NSWindow {
        let controller = NSHostingController(rootView: rootView)
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
        return window
    }

    private func desktopSidebarWidth(for width: CGFloat) -> CGFloat {
        min(400, max(300, width * 0.30))
    }

    private func windowHierarchyRoot(_ window: NSWindow) -> NSView? {
        guard var root = window.contentView else { return nil }
        while let parent = root.superview { root = parent }
        return root
    }


    private func assertActiveChairControls(
        in detail: NSView,
        content: NSView,
        detailFrame: CGRect,
        sidebarTrailingEdge: CGFloat,
        scenario: String,
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        let descendants = viewDescendants(from: detail)
        let editors = descendants.compactMap { $0 as? NSTextView }
            .filter { $0.isEditable && $0.frame.width > 80 && $0.frame.height > 30 }
        XCTAssertFalse(
            editors.isEmpty,
            "Seçili sandalyenin söz alanı görünür olmalı: \(scenario)",
            file: file,
            line: line
        )
        guard let editor = editors.max(by: {
            $0.frame.width * $0.frame.height < $1.frame.width * $1.frame.height
        }) else { return }

        let editorFrame = editor.convert(editor.bounds, to: content)
        XCTAssertGreaterThanOrEqual(
            editorFrame.minX,
            max(detailFrame.minX, sidebarTrailingEdge) - 1,
            "Sandalye girişi sol sohbet kolonu altına girmemeli: \(scenario)",
            file: file,
            line: line
        )
        XCTAssertLessThanOrEqual(
            editorFrame.maxX,
            detailFrame.maxX + 1,
            "Sandalye girişi ayrıntı alanının sağından taşmamalı: \(scenario)",
            file: file,
            line: line
        )
        XCTAssertGreaterThanOrEqual(
            editorFrame.minY,
            detailFrame.minY - 1,
            "Sandalye girişi alt sınırın altında kalmamalı: \(scenario)",
            file: file,
            line: line
        )
        XCTAssertLessThanOrEqual(
            editorFrame.maxY,
            detailFrame.maxY + 1,
            "Sandalye girişi üst sınırın dışında kalmamalı: \(scenario)",
            file: file,
            line: line
        )
        let visibleIntersection = editorFrame.intersection(content.bounds)
        let ancestorSummary = viewAncestorSummary(
            from: editor,
            through: content,
            convertedTo: content
        )
        XCTAssertGreaterThanOrEqual(
            visibleIntersection.height,
            editorFrame.height - 2,
            "Sandalye girişinin tamamı pencere viewport'unda kalmalı: \(scenario), " +
            "content=\(content.bounds), editor=\(editorFrame), ancestors=\(ancestorSummary)",
            file: file,
            line: line
        )
        let editorMidpoint = NSPoint(x: editorFrame.midX, y: editorFrame.midY)
        let contentHit = content.hitTest(editorMidpoint)
        let editorLocalPoint = editor.convert(editorMidpoint, from: content)
        let editorLocalHit = editor.hitTest(editorLocalPoint)
        XCTAssertNotNil(
            contentHit,
            "Sandalye girişi görünür alanda tıklanabilir olmalı: \(scenario). " +
            "content=\(content.bounds), detail=\(detailFrame), editor=\(editorFrame), " +
            "editorVisible=\(editor.visibleRect), localPoint=\(editorLocalPoint), " +
            "localHit=\(String(describing: editorLocalHit)), hidden=\(editor.isHidden), " +
            "alpha=\(editor.alphaValue)",
            file: file,
            line: line
        )
        XCTAssertTrue(
            content.window?.makeFirstResponder(editor) == true,
            "Sandalye girişi klavye odağını alabilmeli: \(scenario)",
            file: file,
            line: line
        )

        let horizontalSelector = descendants.compactMap { $0 as? NSScrollView }
            .contains {
                let frame = $0.convert($0.bounds, to: content)
                return frame.intersects(detailFrame) &&
                    $0.hasHorizontalScroller
            }
        XCTAssertTrue(
            horizontalSelector,
            "Çoklu sandalye seçicisi ayrıntı içinde yatay kaydırılabilmeli: \(scenario)",
            file: file,
            line: line
        )
    }

    private func viewAncestorSummary(
        from view: NSView,
        through root: NSView,
        convertedTo coordinateView: NSView
    ) -> String {
        var parts: [String] = []
        var current: NSView? = view
        while let node = current, parts.count < 18 {
            let frame = node.convert(node.bounds, to: coordinateView)
            parts.append("\(type(of: node)) frame=\(frame) fit=\(node.fittingSize)")
            if node === root { break }
            current = node.superview
        }
        return parts.joined(separator: " <- ")
    }

    private func assertScrollableAdvancedSurface(
        in detail: NSView,
        content: NSView,
        detailFrame: CGRect,
        scenario: String,
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        let scrollSurfaces = viewDescendants(from: detail)
            .compactMap { $0 as? NSScrollView }
            .filter {
                let frame = $0.convert($0.bounds, to: content)
                return frame.width > 120 && frame.height > 120 &&
                    frame.intersection(detailFrame).width >= frame.width - 2 &&
                    frame.intersection(detailFrame).height >= frame.height - 2
            }
        XCTAssertFalse(
            scrollSurfaces.isEmpty,
            "İleri çalışma yüzeyi görünür ayrıntı içinde kaydırılabilir kalmalı: \(scenario)",
            file: file,
            line: line
        )
    }

    private func assertFiniteFrames(
        in root: NSView,
        scenario: String,
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        for view in viewDescendants(from: root) {
            XCTAssertTrue(
                [view.frame.minX, view.frame.minY, view.frame.width, view.frame.height]
                    .allSatisfy(\.isFinite),
                "Sonlu olmayan görünüm çerçevesi: \(scenario), \(type(of: view)), \(view.frame)",
                file: file,
                line: line
            )
        }
    }

    private func settle(_ window: NSWindow, cycles: Int = 4) async {
        for _ in 0..<cycles {
            window.setContentSize(window.contentMinSize)
            window.contentViewController?.view.frame = NSRect(
                origin: .zero,
                size: window.contentMinSize
            )
            window.contentView?.layoutSubtreeIfNeeded()
            try? await Task.sleep(for: .milliseconds(35))
            await Task.yield()
        }
    }

    private func close(_ window: NSWindow) {
        window.orderOut(nil)
        window.close()
    }

    private func viewDescendants(from root: NSView) -> [NSView] {
        var result: [NSView] = []
        var queue = [root]
        while !queue.isEmpty {
            let view = queue.removeFirst()
            result.append(view)
            queue.append(contentsOf: view.subviews)
        }
        return result
    }

    private func fourChairActiveSession() -> WorkspaceChairSession {
        let titles = [
            "Kırılgan Çocuk",
            "Eleştirel Ebeveyn",
            "Başa çıkma modu",
            "Sağlıklı Yetişkin",
        ]
        let participants = titles.enumerated().map { index, title in
            WorkspaceChairIdentity(
                id: "chair-\(index + 1)",
                title: title,
                prompt: "\(title) şimdi ne söylemek istiyor?",
                sortOrder: index
            )
        }
        return WorkspaceChairSession(
            id: "root-four-chair-active",
            title: "Şema Modu Sandalyeleri",
            frame: "Her parçanın sözü kullanıcıya aittir.",
            goalText: "Tetikleyiciden Sağlıklı Yetişkine uzanan döngüyü ayırt etmek",
            stopSignal: "DUR",
            participants: participants,
            minimumParticipants: 2,
            maximumParticipants: 6,
            allowsAddingParticipants: true,
            orientationConfirmed: true,
            frameConfirmed: true,
            activeChairID: participants[0].id,
            phase: .active,
            intensity: 4,
            intensityLimit: 7,
            updatedAt: Date()
        )
    }

    private func assertRootAdvancedStartSurfaceContract() throws {
        let packageRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let files: [(path: String, required: [String])] = [
            (
                "Sources/DivanNative/UI/Advanced/AdvancedWorkspaceView.swift",
                [
                    "GeometryReader { geometry in",
                    "let safeInsets = geometry.safeAreaInsets",
                    "let contentHeight = max(",
                    "height: contentHeight",
                    ".clipped()",
                ]
            ),
            (
                "Sources/DivanNative/UI/Advanced/Views/ChairWorkView.swift",
                [
                    "chairStartSurface",
                    "chairStartAction",
                    "chairStartActionBar",
                    ".safeAreaInset(edge: .top",
                ]
            ),
            (
                "Sources/DivanNative/UI/Advanced/Views/ReparentingImageryView.swift",
                [
                    "imageryStartSurface",
                    "imageryStartAction",
                    "imageryStartActionBar",
                    ".safeAreaInset(edge: .top",
                ]
            ),
        ]
        for contract in files {
            let text = try String(
                contentsOf: packageRoot.appendingPathComponent(contract.path),
                encoding: .utf8
            )
            for required in contract.required {
                XCTAssertTrue(
                    text.contains(required),
                    "Root başlangıç yüzeyi sözleşmesi eksik: \(contract.path) → \(required)"
                )
            }
        }
    }

    private func productSource(_ filename: String) throws -> String {
        let packageRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent() // UI
            .deletingLastPathComponent() // DivanNativeTests
            .deletingLastPathComponent() // Tests
            .deletingLastPathComponent() // package root
        return try String(
            contentsOf: packageRoot
                .appendingPathComponent("Sources/DivanNative/UI/Views")
                .appendingPathComponent(filename),
            encoding: .utf8
        )
    }

    private func advancedProductSource(_ relativePath: String) throws -> String {
        let packageRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        return try String(
            contentsOf: packageRoot
                .appendingPathComponent("Sources/DivanNative/UI/Advanced")
                .appendingPathComponent(relativePath),
            encoding: .utf8
        )
    }
}

private extension String {
    func slice(after start: String, before end: String) -> Substring? {
        guard let startRange = range(of: start),
              let endRange = range(of: end, range: startRange.upperBound..<endIndex) else {
            return nil
        }
        return self[startRange.upperBound..<endRange.lowerBound]
    }
}

private actor RootConversationDataSource: DivanUIDataSource {
    static let openTherapyID = 1201
    static let lessonID = 1202
    static let endedTherapyID = 1203

    private let therapist = DivanMaster(
        id: "young-root-test",
        kind: .therapist,
        name: "Jeffrey Young",
        school: "Şema Terapi",
        subtitle: "Şemalar, modlar ve deneyimsel çalışmalar",
        portraitURL: URL(string: "http://127.0.0.1:54321/assets/portraits/young.png"),
        supportedModes: [.therapy, .lesson]
    )
    private let philosopher = DivanMaster(
        id: "confucius-root-test",
        kind: .philosopher,
        name: "Konfüçyüs",
        school: "Erdem etiği",
        subtitle: "İlişkiler, ritüel ve toplumsal uyum",
        supportedModes: [.lesson]
    )
    private let now = Date(timeIntervalSince1970: 1_786_449_600)

    private var conversations: [DivanConversation] {
        [
            DivanConversation(
                id: Self.openTherapyID,
                masterID: therapist.id,
                title: "Açık terapi bağlamı",
                preview: "Son mesaj: sınırımı daha erken fark ettim.",
                updatedAt: now,
                isArchived: false,
                mode: .therapy
            ),
            DivanConversation(
                id: Self.lessonID,
                masterID: philosopher.id,
                title: "Konfüçyüs ile ders",
                preview: "Ritüel ile erdem arasındaki ilişkiyi konuştuk.",
                updatedAt: now.addingTimeInterval(-60),
                isArchived: false,
                mode: .lesson
            ),
            DivanConversation(
                id: Self.endedTherapyID,
                masterID: therapist.id,
                title: "Bitmiş terapi bağlamı",
                preview: "Bu seans tamamlandı.",
                updatedAt: now.addingTimeInterval(-120),
                isArchived: false,
                isEnded: true,
                mode: .therapy
            ),
        ]
    }

    private var settings: DivanSettingsSummary {
        DivanSettingsSummary(
            provider: .lmStudio,
            providerName: "LM Studio",
            modelName: "yerel-model",
            baseURL: "http://127.0.0.1:1234/v1",
            connectionDetail: "Yerel sağlayıcı",
            state: .ready,
            apiKeyStored: false,
            localOnly: true
        )
    }

    func bootstrap() async throws -> DivanUISnapshot {
        DivanUISnapshot(
            therapists: [therapist],
            philosophers: [philosopher],
            activeConversations: conversations,
            archivedConversations: [],
            settings: settings
        )
    }

    func masters(kind: DivanCatalogKind) async throws -> [DivanMaster] {
        kind == .therapist ? [therapist] : [philosopher]
    }

    func conversations(archived: Bool) async throws -> [DivanConversation] {
        archived ? [] : conversations
    }

    func conversation(
        id: Int,
        limit: Int,
        beforeID: Int?
    ) async throws -> DivanConversationPage {
        let conversation = conversations.first { $0.id == id } ?? conversations[0]
        let master = conversation.masterID == therapist.id ? therapist : philosopher
        let message = DivanMessage(
            id: "root-message-\(id)",
            serverID: id,
            role: .assistant,
            content: conversation.preview,
            createdAt: conversation.updatedAt
        )
        return DivanConversationPage(
            conversation: conversation,
            master: master,
            messages: [message],
            messageCount: 1,
            loadedMessageCount: 1,
            hasMoreMessages: false,
            oldestMessageID: id
        )
    }

    func createConversation(
        masterID: String,
        mode: DivanSessionMode
    ) async throws -> DivanNewConversation {
        DivanNewConversation(conversation: conversations[0], greeting: "Merhaba")
    }

    func setArchived(_ archived: Bool, conversationID: Int) async throws {}
    func setPinned(_ pinned: Bool, conversationID: Int) async throws {}
    func profileText() async throws -> String { "" }
    func updateProfileText(_ text: String) async throws {}
    func notebook(masterID: String, mode: DivanSessionMode) async throws -> LibraryNotebook {
        LibraryNotebook(notes: [], formulations: [])
    }
    func letters(masterID: String) async throws -> LibraryLetters {
        LibraryLetters(letters: [], referrals: [])
    }
    func dreamJournal(masterID: String) async throws -> LibraryDreamJournal {
        LibraryDreamJournal(dreams: [], analysis: "")
    }
    func analyzeDreams(masterID: String) async throws -> String { "" }
    func search(_ term: String) async throws -> [LibrarySearchHit] { [] }
    func sessionSummary(conversationID: Int) async throws -> DivanSessionSummary? { nil }
    func updateSessionSummary(
        conversationID: Int,
        action: DivanSummaryAction,
        content: String?
    ) async throws -> DivanSessionSummary? { nil }
    func deleteConversation(id: Int) async throws {}
    func endConversation(id: Int) async throws {}

    func sendMessage(
        conversationID: Int,
        text: String
    ) async -> AsyncThrowingStream<DivanChatUpdate, Error> {
        AsyncThrowingStream { $0.finish() }
    }

    func chatStatus(requestID: String) async throws -> DivanPendingChat {
        DivanPendingChat(
            requestID: requestID,
            status: "completed",
            content: "Tamamlandı",
            retryable: false,
            isPending: false,
            waitingForProvider: false
        )
    }

    func portraitData(url: URL) async throws -> Data {
        Data(base64Encoded:
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        ) ?? Data()
    }

    func settingsSummary() async throws -> DivanSettingsSummary { settings }
    func saveSettings(_ input: DivanSettingsInput) async throws -> DivanSettingsSummary { settings }
    func clearAPIKey(provider: DivanProviderID) async throws -> DivanSettingsSummary { settings }
}

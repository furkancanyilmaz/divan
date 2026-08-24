import SwiftUI

public struct DivanRootView: View {
    @ObservedObject private var model: DivanViewModel
    @Environment(\.dynamicTypeSize) private var inheritedDynamicTypeSize
    private let advancedDataSource: any AdvancedWorkspaceDataSource
    private let structuredDataSource: (any StructuredTherapyDataSource)?
    @State private var compactDetailVisible = false
    @State private var guestConfirm: GuestModeConfirmation?

    private enum GuestModeConfirmation: String, Identifiable {
        case enter
        case exit
        var id: String { rawValue }
    }

    public init(
        model: DivanViewModel,
        advancedDataSource: any AdvancedWorkspaceDataSource,
        structuredDataSource: (any StructuredTherapyDataSource)? = nil
    ) {
        self.model = model
        self.advancedDataSource = advancedDataSource
        self.structuredDataSource = structuredDataSource
    }

    public var body: some View {
        GeometryReader { proxy in
            Group {
                if proxy.size.width < 680 {
                    compactRoot
                } else {
                    desktopRoot(size: proxy.size)
                }
            }
            .frame(
                width: max(0, proxy.size.width),
                height: max(0, proxy.size.height),
                alignment: .topLeading
            )
            .clipped()
            .toolbar { windowToolbar(width: proxy.size.width) }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .safeAreaInset(edge: .top, spacing: 0) {
            if let notice = model.notice {
                DivanNoticeBanner(
                    notice: notice,
                    retry: { Task { await model.retryNotice() } },
                    dismiss: model.dismissNotice
                )
            }
        }
        .sheet(isPresented: $model.isNewSessionPresented) {
            NewSessionSheet(model: model)
        }
        .alert(item: $guestConfirm) { confirmation in
            switch confirmation {
            case .enter:
                return Alert(
                    title: Text("Misafir moduna geçilsin mi?"),
                    message: Text("Misafir modunda görüşmeleriniz gizlenir; yeni görüşmeler ayrı tutulur. Moddan çıkınca misafir görüşmeleri silinir."),
                    primaryButton: .cancel(Text("Vazgeç")),
                    secondaryButton: .default(Text("Misafir moduna geç")) {
                        Task { await model.setGuestMode(active: true) }
                    }
                )
            case .exit:
                return Alert(
                    title: Text("Misafir modundan çıkılsın mı?"),
                    message: Text("Bu modda açılan tüm misafir görüşmeleri silinecek. Kendi görüşmeleriniz silinmez."),
                    primaryButton: .cancel(Text("Vazgeç")),
                    secondaryButton: .destructive(
                        Text("Çık ve misafir görüşmelerini sil")
                    ) {
                        Task { await model.setGuestMode(active: false) }
                    }
                )
            }
        }
        .onChange(of: model.destination) { destination in
            compactDetailVisible = destination == .settings || destination == .sync
        }
        .environment(\.divanWindowToolbarProvidesIdentity, true)
        .dynamicTypeSize(rootDynamicTypeSize)
        .preferredColorScheme(rootColorScheme)
        .divanKeepsWindowOnTop(model.keepsWindowOnTop)
        .task { await model.bootstrap() }
    }

    private var rootDynamicTypeSize: DynamicTypeSize {
        if inheritedDynamicTypeSize.divanIsAccessibilitySize {
            return inheritedDynamicTypeSize
        }
        switch model.textSizePreference {
        case .small: return .small
        case .standard: return .large
        case .large: return .xLarge
        case .extraLarge: return .xxLarge
        }
    }

    private var rootColorScheme: ColorScheme? {
        switch model.appearancePreference {
        case .system: nil
        case .light: .light
        case .dark: .dark
        }
    }

    /// A deliberately finite, WhatsApp-style two-column layout.
    ///
    /// `NavigationSplitView` lets an intrinsically tall clinical workspace
    /// enlarge its AppKit split host beyond the visible window. That can move
    /// the chair-work composer below the viewport. Giving both columns the
    /// exact window proposal keeps the conversation list and work surface
    /// stable at normal and full-screen sizes.
    private func desktopRoot(size: CGSize) -> some View {
        let showsSidebar = model.columnVisibility != .detailOnly
        let sidebarWidth = showsSidebar ? desktopSidebarWidth(for: size.width) : 0
        let dividerWidth: CGFloat = showsSidebar ? 1 : 0
        let detailWidth = max(0, size.width - sidebarWidth - dividerWidth)

        return HStack(spacing: 0) {
            if showsSidebar {
                primaryColumn
                    .frame(width: sidebarWidth, height: size.height)
                    .clipped()

                Divider()
                    .frame(width: dividerWidth, height: size.height)
            }

            detailColumn(compactChat: false)
                .frame(width: detailWidth, height: size.height)
                .clipped()
                .accessibilityIdentifier("divan.detailColumn")
        }
        .frame(width: size.width, height: size.height, alignment: .topLeading)
        .clipped()
        .accessibilityIdentifier("divan.desktopTwoColumnLayout")
    }

    private func desktopSidebarWidth(for width: CGFloat) -> CGFloat {
        min(400, max(300, width * 0.30))
    }

    @ViewBuilder
    private var compactRoot: some View {
        if compactShouldShowDetail {
            if [.recent, .archived].contains(model.destination) {
                detailColumn(compactChat: true)
            } else {
                detailColumn(compactChat: false)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        } else {
            primaryColumn
        }
    }

    private var compactShouldShowDetail: Bool {
        if [.recent, .archived].contains(model.destination) {
            return model.selectedConversation != nil
        }
        return compactDetailVisible
    }

    private func closeCompactDetail() {
        if model.destination == .settings || model.destination == .sync {
            model.selectDestination(.recent)
        }
        compactDetailVisible = false
    }

    private var primaryColumn: some View {
        VStack(spacing: 0) {
            if model.guestModeActive {
                guestModeBanner
            }
            browserColumn
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .background(.bar)
        .accessibilityIdentifier("divan.primaryColumn")
    }

    private var guestModeBanner: some View {
        HStack(spacing: 9) {
            Image(systemName: "person.crop.circle.badge.checkmark")
                .foregroundStyle(DivanPalette.wine)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 1) {
                Text("Misafir modunda")
                    .font(.callout.weight(.semibold))
                Text("Görüşmeleriniz gizli; çıkınca misafir görüşmeleri silinir.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 6)
            Button("Çık") {
                guestConfirm = .exit
            }
            .buttonStyle(.bordered)
            .controlSize(.small)
            .disabled(model.isTogglingGuestMode)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 9)
        .background(DivanPalette.wine.opacity(0.10))
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("divan.guestModeBanner")
    }

    @ToolbarContentBuilder
    private func windowToolbar(width: CGFloat) -> some ToolbarContent {
        ToolbarItem(
            id: "divan.toolbar.back",
            placement: .navigation
        ) {
            Button {
                goBackToConversations()
            } label: {
                Image(systemName: "chevron.left")
            }
            .disabled(!canGoBackToConversations)
            .opacity(canGoBackToConversations ? 1 : 0)
            .keyboardShortcut("[", modifiers: [.command])
            .help("Son konuşmalara dön")
            .accessibilityLabel("Son konuşmalara dön")
            .accessibilityIdentifier("divan.toolbar.back")
        }

        ToolbarItem(
            id: "divan.toolbar.sidebarToggle",
            placement: .navigation
        ) {
            Button {
                toggleSidebar(width: width)
            } label: {
                Image(systemName: compactShouldShowDetail && width < 680
                      ? "chevron.left" : "sidebar.left")
            }
            .disabled(width < 680 && !compactShouldShowDetail)
            .help(width < 680 ? "Listeye dön" : "Kenar çubuğunu göster veya gizle")
            .accessibilityLabel(width < 680 ? "Listeye dön" : "Kenar çubuğunu göster veya gizle")
            .accessibilityIdentifier("divan.toolbar.sidebarToggle")
        }

        ToolbarItem(id: "divan.toolbar.brand", placement: .navigation) {
            DivanToolbarBrand()
        }

        ToolbarItem(id: "divan.toolbar.context", placement: .principal) {
            DivanToolbarContextView(
                context: .resolve(model: model),
                model: model,
                compact: width < 720
            )
            .frame(maxWidth: toolbarContextWidth(for: width))
        }

        ToolbarItem(
            id: "divan.toolbar.newConversation",
            placement: .primaryAction
        ) {
            Button {
                model.prepareNewSession()
            } label: {
                Image(systemName: "square.and.pencil")
            }
            .keyboardShortcut("n", modifiers: [.command])
            .help("Yeni görüşme")
            .accessibilityLabel("Yeni görüşme")
            .accessibilityIdentifier("divan.toolbar.newConversation")
        }

        // Pencereyi üstte tutma: sohbet açık kalsın, kullanıcı başka bir işle
        // uğraşabilsin. FaceTime'ın görüntü penceresiyle aynı fikir.
        ToolbarItem(
            id: "divan.toolbar.pinWindow",
            placement: .primaryAction
        ) {
            Button {
                model.keepsWindowOnTop.toggle()
            } label: {
                Image(systemName: model.keepsWindowOnTop
                      ? "pin.fill" : "pin")
            }
            .keyboardShortcut("t", modifiers: [.command, .shift])
            .help(model.keepsWindowOnTop
                  ? "Pencereyi üstte tutmayı bırak"
                  : "Pencereyi hep üstte tut")
            .accessibilityLabel("Pencereyi hep üstte tut")
            .accessibilityValue(model.keepsWindowOnTop ? "Açık" : "Kapalı")
            .accessibilityIdentifier("divan.toolbar.pinWindow")
        }

        // Ayarlar her ekrandan tek tıkla erişilebilir olmalı: sağlayıcı ya da
        // API anahtarı sorunu çıktığında kullanıcı menü içinde aramamalı.
        ToolbarItem(
            id: "divan.toolbar.settings",
            placement: .primaryAction
        ) {
            Button {
                if model.destination == .settings {
                    goBackToConversations()
                } else {
                    model.selectDestination(.settings)
                }
            } label: {
                Image(systemName: model.destination == .settings
                      ? "gearshape.fill" : "gearshape")
            }
            .keyboardShortcut(",", modifiers: [.command])
            .help(model.destination == .settings
                  ? "Ayarlardan çık" : "Ayarlar")
            .accessibilityLabel("Ayarlar")
            .accessibilityIdentifier("divan.toolbar.settings")
        }

        ToolbarItem(
            id: "divan.toolbar.navigationMenu",
            placement: .primaryAction
        ) {
            navigationMenu
        }
    }

    private func toolbarContextWidth(for width: CGFloat) -> CGFloat {
        if width < 560 { return 170 }
        if width < 900 { return 260 }
        return 420
    }

    /// Konuşma listesi dışındaki her yerden geri dönülebilir. Sohbet açıkken
    /// de geri, sohbeti kapatıp listeye döner: kullanıcı tek düğmeyle her
    /// zaman başladığı yere ulaşır.
    private var canGoBackToConversations: Bool {
        if model.destination != .recent { return true }
        return model.selectedConversation != nil || compactDetailVisible
    }

    private func goBackToConversations() {
        if model.destination != .recent {
            model.selectDestination(.recent)
        } else if model.selectedConversation != nil {
            model.closeConversation()
        }
        compactDetailVisible = false
        if model.columnVisibility == .detailOnly {
            model.columnVisibility = .all
        }
    }

    private func toggleSidebar(width: CGFloat) {
        if width < 680 {
            if [.recent, .archived].contains(model.destination),
               model.selectedConversation != nil {
                model.closeConversation()
            } else if compactDetailVisible {
                closeCompactDetail()
            }
            return
        }
        model.columnVisibility = model.columnVisibility == .detailOnly
            ? .all : .detailOnly
    }

    private var navigationMenu: some View {
        Menu {
            Section("Konuşmalar") {
                destinationButton(.recent)
                destinationButton(.archived)
            }
            Section("Keşfet") {
                destinationButton(.masters)
                destinationButton(.works)
                destinationButton(.livingMap)
            }
            Section("Defter") {
                if !model.guestModeActive {
                    destinationButton(.notebook)
                    destinationButton(.letters)
                    destinationButton(.dreams)
                }
            }
            Section("Divan") {
                if !model.guestModeActive {
                    destinationButton(.profile)
                }
                destinationButton(.sync)
                destinationButton(.settings)
            }
            Section("Misafir") {
                Button {
                    guestConfirm = model.guestModeActive ? .exit : .enter
                } label: {
                    Label(
                        model.guestModeActive
                            ? "Misafir modundan çık"
                            : "Misafir moduna geç",
                        systemImage: model.guestModeActive
                            ? "person.crop.circle.badge.xmark"
                            : "person.crop.circle.badge.plus"
                    )
                }
                .disabled(model.isTogglingGuestMode)
            }
        } label: {
            Image(systemName: "square.grid.2x2")
                .frame(width: 30, height: 30)
        }
        .menuStyle(.borderlessButton)
        .menuIndicator(.hidden)
        .fixedSize()
        .help("Divan bölümleri")
        .accessibilityLabel("Divan bölümleri")
        .accessibilityIdentifier("divan.toolbar.navigationMenu")
    }

    private func destinationButton(
        _ destination: DivanSidebarDestination
    ) -> some View {
        Button {
            model.selectDestination(destination)
        } label: {
            Label {
                HStack {
                    Text(destination.title)
                    if model.destination == destination {
                        Image(systemName: "checkmark")
                    }
                }
            } icon: {
                Image(systemName: destination.systemImage)
            }
        }
    }

    @ViewBuilder
    private var browserColumn: some View {
        if model.isBootstrapping && model.allMasters.isEmpty {
            VStack(spacing: 12) {
                ProgressView()
                Text("Divan hazırlanıyor…")
                    .foregroundStyle(.secondary)
                NativePreviewScopeBadge()
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .accessibilityElement(children: .combine)
            .accessibilityLabel("Divan hazırlanıyor")
        } else {
            switch model.destination {
            case .recent, .archived, .notebook, .letters, .dreams, .profile:
                // Defter yüzeyleri sağ kolonu kullanır; sol kolonda konuşma
                // listesi kalır, böylece kullanıcı bağlamını kaybetmez.
                ConversationLibraryView(model: model)
            case .masters:
                MasterCatalogView(
                    model: model,
                    onSelect: { compactDetailVisible = true }
                )
            case .works, .livingMap, .sync:
                AdvancedContextPickerView(
                    model: model,
                    onSelect: { compactDetailVisible = true }
                )
            case .settings:
                DivanEmptyState(
                    systemImage: "gearshape.fill",
                    title: "Bu Mac’in ayarları",
                    message: "Sağlayıcı, model ve güvenli API anahtarı ayarları sağdaki alanda açıktır."
                )
            }
        }
    }

    @ViewBuilder
    private func detailColumn(compactChat: Bool) -> some View {
        if [.recent, .archived].contains(model.destination),
           model.selectedConversation != nil {
            NativeChatView(
                model: model,
                onBack: compactChat ? { model.closeConversation() } : nil
            )
        } else if model.destination == .masters {
            MasterCatalogDetailView(model: model)
        } else if model.destination == .works,
                  model.advancedConversation != nil {
            advancedWorkspace(initialModule: model.advancedInitialModule)
        } else if model.destination == .livingMap,
                  model.advancedConversation != nil {
            advancedWorkspace(initialModule: .livingMap)
        } else if model.destination == .sync {
            advancedWorkspace(initialModule: .wifiSync)
        } else if model.destination == .settings {
            ProviderSettingsView(model: model)
        } else if model.destination == .notebook {
            NotebookView(model: model)
        } else if model.destination == .letters {
            LettersView(model: model)
        } else if model.destination == .dreams {
            DreamJournalView(model: model)
        } else if model.destination == .profile {
            ProfileView(model: model)
        } else {
            detailPlaceholder
        }
    }

    private func advancedWorkspace(initialModule: AdvancedModule) -> some View {
        let conversation = model.advancedConversation
        let master = conversation.flatMap { model.master(id: $0.masterID) }
        let clinicalContext = conversation != nil && master?.kind == .therapist
        return AdvancedWorkspaceView(
            dataSource: advancedDataSource,
            structuredDataSource: structuredDataSource,
            context: AdvancedWorkspaceContext(
                conversationID: conversation?.id,
                masterID: master?.id,
                masterName: master?.name,
                allowsClinicalWork: initialModule != .wifiSync && clinicalContext
            ),
            initialModule: initialModule,
            onExit: { goBackToConversations() }
        )
        .id("\(model.destination.rawValue)-\(initialModule.rawValue)-\(conversation?.id ?? 0)")
    }

    private var detailPlaceholder: some View {
        Group {
            switch model.destination {
            case .recent, .archived:
                DivanEmptyState(
                    systemImage: "bubble.left",
                    title: "Bir konuşma seçin",
                    message: "Mesajlar, saatleri ve görüşme işlemleri burada görünür."
                )
            case .masters:
                DivanEmptyState(
                    systemImage: "person.crop.circle.badge.plus",
                    title: "Ustanızı seçin",
                    message: "Her kayıtta ad, ekol ve AI canlandırması sınırı açıkça görünür."
                )
            case .works:
                DivanEmptyState(
                    systemImage: "chair.lounge",
                    title: "Seans çalışmaları",
                    message: "Sandalye ve yeniden ebeveynlik çalışmaları burada açılır."
                )
            case .livingMap:
                DivanEmptyState(
                    systemImage: "map",
                    title: "Yaşayan harita",
                    message: "Onayladığınız örüntüler ve yeni kanıtlar burada görünür."
                )
            case .sync:
                DivanEmptyState(
                    systemImage: "arrow.triangle.2.circlepath",
                    title: "Cihaz eşitleme",
                    message: "Aynı Wi-Fi üzerindeki cihazlar açık onayla eşitlenir."
                )
            case .settings:
                DivanEmptyState(
                    systemImage: "lock.shield",
                    title: "Anahtarlar geri gösterilmez",
                    message: "Sağlayıcı anahtarları yalnız güvenli ayar isteğiyle yazılır."
                )
            case .notebook, .letters, .dreams, .profile:
                EmptyView()
            }
        }
        .background(Color(nsColor: .textBackgroundColor))
    }
}

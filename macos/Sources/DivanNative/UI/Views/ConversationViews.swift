import AppKit
import SwiftUI

public struct ConversationLibraryView: View {
    @ObservedObject private var model: DivanViewModel
    @State private var actionConversation: DivanConversation?
    @State private var showArchiveConfirmation = false
    @State private var showDeleteConfirmation = false

    public init(model: DivanViewModel) {
        self.model = model
    }

    public var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 9) {
                // Yazarken yerel liste filtrelenir; Return'e basınca sunucu
                // tarafında mesaj ve not içeriğinde tam metin araması yapılır.
                TextField(
                    "Başlık, mesaj veya usta ara",
                    text: $model.conversationSearch
                )
                    .textFieldStyle(.roundedBorder)
                    .accessibilityLabel("Konuşmalarda ara")
                    .onSubmit {
                        Task { await model.runSearch(model.conversationSearch) }
                    }
                if model.isSearching {
                    ProgressView().controlSize(.small)
                }
                Text("\(conversationGroups.count)")
                    .font(.caption.monospacedDigit())
                    .foregroundStyle(.secondary)
                    .padding(.horizontal, 7)
                    .padding(.vertical, 4)
                    .background(.quaternary, in: Capsule())
                    .accessibilityLabel("\(conversationGroups.count) konuşulan kişi")
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 10)
            if !model.searchHits.isEmpty {
                HStack(spacing: 6) {
                    Text("\(model.searchHits.count) sonuç")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Spacer()
                    Button("Temizle") { model.searchHits = [] }
                        .buttonStyle(.link)
                        .font(.caption)
                }
                .padding(.horizontal, 12)
                .padding(.bottom, 6)
            }
            Divider()
            if !model.searchHits.isEmpty {
                LibrarySearchResultsView(model: model)
            } else {

            if model.visibleConversations.isEmpty {
                DivanEmptyState(
                    systemImage: model.destination == .archived
                        ? "archivebox" : "bubble.left.and.bubble.right",
                    title: model.destination == .archived
                        ? "Arşiv boş" : "Henüz konuşma yok",
                    message: model.destination == .archived
                        ? "Arşivlediğiniz görüşmeler burada, silinmeden saklanır."
                        : "Bir terapist veya felsefeci seçerek başlayabilirsiniz.",
                    actionTitle: model.destination == .recent ? "Yeni görüşme" : nil,
                    action: model.destination == .recent
                        ? { model.prepareNewSession() } : nil
                )
            } else {
                List(conversationGroups) { group in
                    ZStack(alignment: .trailing) {
                        Button {
                            Task { await model.openConversation(group.latest) }
                        } label: {
                            ConversationRow(
                                conversation: group.latest,
                                master: model.master(id: group.masterID),
                                model: model,
                                selected: group.conversations.contains {
                                    $0.id == model.selectedConversation?.id
                                },
                                sessionCount: group.conversations.count
                            )
                            .padding(.trailing, 34)
                        }
                        .buttonStyle(.plain)
                        .accessibilityHint("En son konuşmayı açar")

                        conversationMenu(for: group.latest, group: group)
                    }
                    .listRowBackground(
                        group.conversations.contains {
                            $0.id == model.selectedConversation?.id
                        } ? DivanPalette.parchment.opacity(0.58) : Color.clear
                    )
                    .contextMenu { rowActions(for: group.latest) }
                }
                .listStyle(.inset)
            }
            }
        }
        .toolbar {
            ToolbarItem {
                Button {
                    Task { await model.refreshCurrentDestination() }
                } label: {
                    Label("Konuşmaları yenile", systemImage: "arrow.clockwise")
                }
                .help("Konuşmaları yenile")
            }
        }
        .confirmationDialog(
            actionConversation?.isArchived == true
                ? "Konuşma arşivden çıkarılsın mı?"
                : "Konuşma arşivlensin mi?",
            isPresented: $showArchiveConfirmation
        ) {
            if let conversation = actionConversation {
                Button(conversation.isArchived ? "Arşivden çıkar" : "Arşivle") {
                    Task {
                        await model.setConversationArchived(
                            conversation,
                            archived: !conversation.isArchived
                        )
                    }
                }
            }
            Button("Vazgeç", role: .cancel) {}
        } message: {
            Text("Mesajlar silinmez; konuşma diğer listeye taşınır.")
        }
        .confirmationDialog(
            "Bu konuşma kalıcı olarak silinsin mi?",
            isPresented: $showDeleteConfirmation
        ) {
            if let conversation = actionConversation {
                Button("Kalıcı olarak sil", role: .destructive) {
                    Task { await model.deleteConversation(conversation) }
                }
            }
            Button("Vazgeç", role: .cancel) {}
        } message: {
            Text("Bu işlem geri alınamaz.")
        }
    }

    private var conversationGroups: [ConversationMasterGroup] {
        Dictionary(grouping: model.visibleConversations, by: \.masterID)
            .map { masterID, conversations in
                ConversationMasterGroup(
                    masterID: masterID,
                    conversations: conversations.sorted {
                        if $0.updatedAt == $1.updatedAt { return $0.id > $1.id }
                        return $0.updatedAt > $1.updatedAt
                    }
                )
            }
            .sorted {
                if $0.latest.updatedAt == $1.latest.updatedAt {
                    return $0.latest.id > $1.latest.id
                }
                return $0.latest.updatedAt > $1.latest.updatedAt
            }
    }

    private func conversationMenu(
        for conversation: DivanConversation,
        group: ConversationMasterGroup
    ) -> some View {
        Menu {
            if group.conversations.count > 1 {
                Section("\(group.conversations.count) görüşme") {
                    ForEach(group.conversations) { item in
                        Button {
                            Task { await model.openConversation(item) }
                        } label: {
                            Text(item.title)
                        }
                    }
                }
                Divider()
            }
            rowActions(for: conversation)
        } label: {
            Image(systemName: "ellipsis")
                .frame(width: 28, height: 28)
                .contentShape(Rectangle())
        }
        .menuStyle(.borderlessButton)
        .menuIndicator(.hidden)
        .help("Konuşma seçenekleri")
        .accessibilityLabel(
            group.conversations.count > 1
                ? "\(conversation.title), \(group.conversations.count) görüşme ve seçenekler"
                : "\(conversation.title) seçenekleri"
        )
    }

    @ViewBuilder
    private func rowActions(for conversation: DivanConversation) -> some View {
        Button {
            Task { await model.openConversation(conversation) }
        } label: {
            Label("Konuşmayı aç", systemImage: "bubble.left")
        }
        if !conversation.isArchived {
            Button {
                Task {
                    await model.setConversationPinned(
                        conversation, pinned: !conversation.isPinned)
                }
            } label: {
                Label(
                    conversation.isPinned ? "Raptiyeyi kaldır" : "Raptiyele",
                    systemImage: conversation.isPinned ? "pin.slash" : "pin"
                )
            }
        }
        Button {
            actionConversation = conversation
            showArchiveConfirmation = true
        } label: {
            Label(
                conversation.isArchived ? "Arşivden çıkar" : "Arşivle",
                systemImage: conversation.isArchived
                    ? "tray.and.arrow.up" : "archivebox"
            )
        }
        Divider()
        Button(role: .destructive) {
            actionConversation = conversation
            showDeleteConfirmation = true
        } label: {
            Label("Sil", systemImage: "trash")
        }
    }
}

private struct ConversationMasterGroup: Identifiable {
    let masterID: String
    let conversations: [DivanConversation]

    var id: String { masterID }
    var latest: DivanConversation { conversations[0] }
}

private struct ConversationRow: View {
    let conversation: DivanConversation
    let master: DivanMaster?
    @ObservedObject var model: DivanViewModel
    let selected: Bool
    let sessionCount: Int

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            DivanPersonaPortrait(master: master, model: model, size: 44)
            // Usta adı satırın kimliğidir: önizlemeden belirgin biçimde
            // büyük ve koyu olmalı. Ad bloğu ile önizleme arasındaki boşluk
            // da ayrıca açılır, aksi hâlde iki metin yapışık görünüyordu.
            VStack(alignment: .leading, spacing: 6) {
                HStack(alignment: .firstTextBaseline) {
                    Text(master?.name ?? "Bilinmeyen usta")
                        .font(.title3.weight(.semibold))
                        .lineLimit(1)
                    if conversation.isPinned {
                        Image(systemName: "pin.fill")
                            .font(.caption)
                            .foregroundStyle(DivanPalette.gold)
                            .accessibilityLabel("Raptiyeli")
                    }
                    Spacer(minLength: 8)
                    Text(conversation.updatedAt, format: .dateTime
                        .day().month(.abbreviated).hour().minute())
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .monospacedDigit()
                }
                HStack(spacing: 6) {
                    Text(conversation.title)
                        .font(.subheadline.weight(.medium))
                        .lineLimit(1)
                    if conversation.isEnded {
                        Text("Bitti")
                            .font(.caption2.weight(.semibold))
                            .padding(.horizontal, 6)
                            .padding(.vertical, 2)
                            .background(.quaternary, in: Capsule())
                    }
                }
                Text(conversation.preview.isEmpty ? "Henüz mesaj yok" : conversation.preview)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.top, 1)
            }
        }
        .padding(.vertical, 9)
        .contentShape(Rectangle())
        .accessibilityElement(children: .combine)
        .accessibilityLabel(accessibilitySummary)
        .accessibilityAddTraits(selected ? .isSelected : [])
    }

    private var accessibilitySummary: String {
        let date = conversation.updatedAt.formatted(date: .abbreviated, time: .shortened)
        return [
            master?.name ?? "Bilinmeyen usta",
            conversation.title,
            conversation.isEnded ? "Bitmiş görüşme" : "Açık görüşme",
            sessionCount > 1 ? "\(sessionCount) görüşme" : "",
            date,
            conversation.preview
        ].filter { !$0.isEmpty }.joined(separator: ", ")
    }
}

public struct NativeChatView: View {
    @ObservedObject private var model: DivanViewModel
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @Environment(\.divanWindowToolbarProvidesIdentity)
    private var windowToolbarProvidesIdentity
    private let onBack: (() -> Void)?
    @State private var showArchiveConfirmation = false
    @State private var showDeleteConfirmation = false
    @State private var showEndConfirmation = false
    @State private var isSelectingStoryMessages = false
    @State private var selectedStoryMessageIDs = Set<String>()
    @State private var showStoryComposer = false
    @State private var followsLatestMessage = true
    @State private var composerFocused = false
    @State private var composerMeasuredHeight: CGFloat = 40
    @FocusState private var sendButtonFocused: Bool
    @FocusState private var composerMenuFocused: Bool

    public init(model: DivanViewModel, onBack: (() -> Void)? = nil) {
        self.model = model
        self.onBack = onBack
    }

    public var body: some View {
        VStack(spacing: 0) {
            if !windowToolbarProvidesIdentity {
                personaHeader
                Divider()
            }
            if model.isLoadingConversation {
                VStack(spacing: 10) {
                    ProgressView()
                    Text("Konuşma yükleniyor…").foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .accessibilityElement(children: .combine)
                .accessibilityLabel("Konuşma yükleniyor")
            } else {
                messageList
                Divider()
                composer
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color(nsColor: .textBackgroundColor))
        .toolbar { chatToolbar }
        .sheet(isPresented: $showStoryComposer) {
            if let master = model.selectedMaster {
                StoryComposerView(
                    master: master,
                    portraitData: model.portraitData(for: master),
                    messages: selectedStoryMessages
                )
            }
        }
        .onChange(of: model.selectedConversation?.id) { _ in
            isSelectingStoryMessages = false
            selectedStoryMessageIDs.removeAll()
            followsLatestMessage = true
        }
        .confirmationDialog(
            model.selectedConversation?.isArchived == true
                ? "Konuşma arşivden çıkarılsın mı?"
                : "Konuşma arşivlensin mi?",
            isPresented: $showArchiveConfirmation
        ) {
            Button(model.selectedConversation?.isArchived == true
                   ? "Arşivden çıkar" : "Arşivle") {
                Task {
                    await model.setSelectedConversationArchived(
                        model.selectedConversation?.isArchived != true
                    )
                }
            }
            Button("Vazgeç", role: .cancel) {}
        } message: {
            Text("Mesajlar silinmez; konuşma diğer listeye taşınır.")
        }
        .confirmationDialog(
            "Bu konuşma kalıcı olarak silinsin mi?",
            isPresented: $showDeleteConfirmation
        ) {
            Button("Kalıcı olarak sil", role: .destructive) {
                Task { await model.deleteSelectedConversation() }
            }
            Button("Vazgeç", role: .cancel) {}
        } message: {
            Text("Bu işlem geri alınamaz.")
        }
        .confirmationDialog(
            model.selectedConversation?.mode == .therapy
                ? "Bugünkü seans bitirilsin mi?"
                : "Bu görüşme bitirilsin mi?",
            isPresented: $showEndConfirmation
        ) {
            Button(model.selectedConversation?.mode == .therapy
                   ? "Seansı bitir" : "Görüşmeyi bitir") {
                Task { await model.endSelectedConversation() }
            }
            Button("Devam et", role: .cancel) {}
        } message: {
            Text("Kapanış mesajı hazırlanır ve bu görüşme salt okunur olur.")
        }
    }

    private var personaHeader: some View {
        HStack(alignment: .top, spacing: 12) {
            if let onBack {
                Button(action: onBack) {
                    Image(systemName: "chevron.left")
                        .frame(width: 30, height: 30)
                }
                .buttonStyle(.plain)
                .help("Konuşmalara dön")
                .accessibilityLabel("Konuşmalara dön")
            }
            DivanPersonaPortrait(
                master: model.selectedMaster,
                model: model,
                size: 50
            )
            VStack(alignment: .leading, spacing: 4) {
                ViewThatFits(in: .horizontal) {
                    HStack(spacing: 8) {
                        Text(model.selectedMaster?.name ?? "Usta")
                            .font(.title3.weight(.bold))
                        AISimulationBadge()
                    }
                    VStack(alignment: .leading, spacing: 4) {
                        Text(model.selectedMaster?.name ?? "Usta")
                            .font(.headline.weight(.bold))
                            .fixedSize(horizontal: false, vertical: true)
                        AISimulationBadge()
                    }
                }
                Text(model.selectedMaster?.school ?? "")
                    .font(.callout.weight(.medium))
                    .foregroundStyle(.secondary)
                if model.selectedMaster?.isLiving == true {
                    Text("Bu, kişinin kendisi veya kurum sözcüsü değildir.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                if !model.chatStatusText.isEmpty {
                    HStack(spacing: 6) {
                        if model.isSending { ProgressView().controlSize(.small) }
                        Text(model.chatStatusText)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    .accessibilityElement(children: .combine)
                    .accessibilityLabel(model.chatStatusText)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 11)
        .background(.bar)
    }

    private var messageList: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(spacing: 8) {
                    historyControl
                    if isSelectingStoryMessages {
                        storySelectionBanner
                    }
                    ForEach(model.messages) { message in
                        NativeMessageBubble(
                            message: message,
                            masterName: model.selectedMaster?.name ?? "Usta",
                            portrait: bubblePortrait,
                            outgoingDelivery: outgoingDeliveryState(for: message),
                            selectionEnabled: isSelectingStoryMessages,
                            selected: selectedStoryMessageIDs.contains(message.id),
                            selectable: isStoryEligible(message),
                            toggleSelection: {
                                toggleStoryMessage(message)
                            },
                            beginSelection: {
                                beginStorySelection(with: message)
                            }
                        )
                        .id(message.id)
                        .accessibilityIdentifier("divan.chat.message.\(message.id)")
                    }
                }
                .padding(.horizontal, 18)
                .padding(.vertical, 16)
                .frame(maxWidth: 860)
                .frame(maxWidth: .infinity)
                .background {
                    ScrollFollowObserver { nearBottom in
                        if followsLatestMessage != nearBottom {
                            followsLatestMessage = nearBottom
                        }
                    }
                }
            }
            .onAppear { scrollToLatest(proxy, animated: false) }
            .onChange(of: model.scrollToLatestRequest) { _ in
                // Token akışı sırasında üst üste yüzlerce animasyon kuyruğa girmesin.
                // Metin yine anında aşağı doğru izlenir; yalnız tamamlanan geçişler animasyonludur.
                guard followsLatestMessage else { return }
                scrollToLatest(proxy, animated: !model.isSending)
            }
            .onChange(of: model.isSending) { isSending in
                guard isSending else { return }
                followsLatestMessage = true
                scrollToLatest(proxy, animated: false)
            }
            .onChange(of: model.historyAnchorRequest) { anchor in
                guard let anchor else { return }
                proxy.scrollTo(anchor, anchor: .top)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .layoutPriority(1)
        .accessibilityIdentifier("divan.chat.messageList")
    }

    private var storySelectionBanner: some View {
        ViewThatFits(in: .horizontal) {
            HStack(spacing: 10) {
                storySelectionLabel
                Spacer()
                storySelectionButtons
            }
            VStack(alignment: .leading, spacing: 9) {
                storySelectionLabel
                HStack {
                    Spacer()
                    storySelectionButtons
                }
            }
        }
        .padding(10)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 12))
        .accessibilityElement(children: .contain)
    }

    private var storySelectionLabel: some View {
        HStack(spacing: 8) {
            Image(systemName: "checkmark.circle")
                .foregroundStyle(DivanPalette.wine)
            Text(selectedStoryMessageIDs.isEmpty
                 ? "Hikâyeye eklemek için mesajları seçin."
                 : "\(selectedStoryMessageIDs.count) mesaj seçildi")
                .font(.callout.weight(.medium))
        }
    }

    private var storySelectionButtons: some View {
        Group {
            Button("Vazgeç") {
                isSelectingStoryMessages = false
                selectedStoryMessageIDs.removeAll()
            }
            Button("Hikâye oluştur") {
                showStoryComposer = true
            }
            .buttonStyle(.borderedProminent)
            .tint(DivanPalette.wine)
            .disabled(selectedStoryMessageIDs.isEmpty)
        }
    }

    @ViewBuilder
    private var historyControl: some View {
        if model.hasMoreMessages || model.isLoadingOlderMessages {
            Button {
                Task { await model.loadOlderMessages() }
            } label: {
                HStack(spacing: 7) {
                    if model.isLoadingOlderMessages {
                        ProgressView().controlSize(.small)
                        Text("Eski mesajlar yükleniyor…")
                    } else {
                        Image(systemName: "arrow.up.circle")
                        Text("Daha eski mesajları yükle")
                    }
                }
            }
            .buttonStyle(.bordered)
            .disabled(model.isLoadingOlderMessages)
            .accessibilityHint("Önceki 80 mesajı yükler ve bulunduğunuz yeri korur")
        } else if model.messageCount > 0 {
            Text("Görüşmenin başlangıcı · \(model.messageCount) mesaj")
                .font(.caption)
                .foregroundStyle(.secondary)
                .accessibilityLabel("Görüşmenin başlangıcına ulaşıldı. Toplam \(model.messageCount) mesaj")
        }
    }

    /// Seans sonrası özet: çekirdek taslağı arka planda yazar, kullanıcı
    /// onaylamadan kalıcı hafızaya geçmez. Onay/ret kararı kullanıcınındır.
    @ViewBuilder
    private var sessionSummaryCard: some View {
        if let summary = model.sessionSummary, summary.hasContent {
            VStack(alignment: .leading, spacing: 9) {
                HStack(spacing: 7) {
                    Image(systemName: "text.append")
                        .foregroundStyle(DivanPalette.gold)
                        .accessibilityHidden(true)
                    Text("Seans özeti")
                        .font(.headline)
                    if summary.isApproved {
                        Text("onaylandı")
                            .font(.caption2.weight(.semibold))
                            .padding(.horizontal, 6)
                            .padding(.vertical, 2)
                            .background(.quaternary, in: Capsule())
                    }
                    Spacer()
                }
                Text(summary.displayText)
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                    .textSelection(.enabled)
                if !summary.isApproved {
                    HStack(spacing: 9) {
                        Button("Onayla") {
                            Task { await model.resolveSessionSummary(.approve) }
                        }
                        .buttonStyle(.borderedProminent)
                        Button("Reddet") {
                            Task { await model.resolveSessionSummary(.reject) }
                        }
                        .buttonStyle(.bordered)
                        if model.isSummaryBusy {
                            ProgressView().controlSize(.small)
                        }
                        Spacer()
                    }
                    Text("Onaylamadan kalıcı hafızaya geçmez.")
                        .font(.caption)
                        .foregroundStyle(.tertiary)
                }
            }
            .padding(14)
            .frame(maxWidth: .infinity, alignment: .leading)
            .accessibilityIdentifier("divan.chat.sessionSummary")
            Divider()
        }
    }

    @ViewBuilder
    private var composer: some View {
        if let conversation = model.selectedConversation,
           conversation.isEnded || conversation.isArchived {
            VStack(spacing: 0) {
                if conversation.isEnded { sessionSummaryCard }
                HStack(spacing: 9) {
                    Image(systemName: conversation.isEnded ? "checkmark.seal" : "archivebox")
                        .accessibilityHidden(true)
                    Text(conversation.isEnded
                         ? (conversation.mode == .therapy
                            ? "Bu seans tamamlandı. Mesajlar salt okunur."
                            : "Bu görüşme tamamlandı. Mesajlar salt okunur.")
                         : "Bu konuşma arşivde. Yazmak için önce arşivden çıkarın.")
                        .foregroundStyle(.secondary)
                    Spacer()
                }
                .padding(14)
            }
            .background(.bar)
        } else {
            VStack(spacing: 7) {
                if model.canReloadAfterFailedResponse {
                    ViewThatFits(in: .horizontal) {
                        HStack {
                            failedResponseLabel
                            Spacer()
                            reloadConversationButton
                        }
                        VStack(alignment: .leading, spacing: 7) {
                            failedResponseLabel
                            reloadConversationButton
                        }
                    }
                    .font(.callout)
                }
                HStack(alignment: .bottom, spacing: 8) {
                    composerMenu
                    ZStack(alignment: .leading) {
                        if model.composerText.isEmpty {
                            // Yer tutucu, editörün yazı tipini ve sol iç
                            // boşluğunu birebir kullanmalı; farklı olursa
                            // imleç yazının içine girmiş gibi görünüyordu.
                            Text("Mesajınızı yazın")
                                .font(DivanChatComposer.placeholderFont(
                                    for: dynamicTypeSize))
                                .foregroundStyle(.tertiary)
                                .padding(.leading,
                                         DivanChatComposer.composerHorizontalInset)
                                .offset(y: DivanChatComposer
                                    .placeholderBaselineDrop(for: dynamicTypeSize))
                                .allowsHitTesting(false)
                                .accessibilityHidden(true)
                        }
                        DivanChatComposer(
                            text: $model.composerText,
                            isEnabled: !model.isLoadingConversation,
                            canSend: model.canSend,
                            isFocused: $composerFocused,
                            onHeightChange: { composerMeasuredHeight = $0 },
                            onSend: {
                                guard model.canSend else { return }
                                Task { await model.sendComposerMessage() }
                            }
                        )
                        .frame(height: composerHeight)
                    }
                    .background(.background, in: Capsule())
                    .overlay {
                        Capsule()
                            .stroke(
                                composerFocused
                                    ? DivanPalette.wine.opacity(0.72)
                                    : Color(nsColor: .separatorColor).opacity(0.72),
                                lineWidth: composerFocused ? 1.5 : 1
                            )
                    }
                    .shadow(
                        color: composerFocused
                            ? DivanPalette.wine.opacity(0.10) : .clear,
                        radius: 4,
                        y: 1
                    )
                    .animation(
                        reduceMotion ? nil : .easeOut(duration: 0.14),
                        value: composerFocused
                    )
                    Button {
                        Task { await model.sendComposerMessage() }
                    } label: {
                        Image(systemName: "arrow.up")
                            .font(.system(size: 14, weight: .bold))
                            .frame(width: composerControlSize, height: composerControlSize)
                            .background(
                                model.canSend
                                    ? DivanPalette.wine
                                    : Color.secondary.opacity(0.16),
                                in: Circle()
                            )
                            .foregroundStyle(model.canSend ? .white : .secondary)
                            .overlay {
                                Circle().stroke(
                                    sendButtonFocused
                                        ? Color.accentColor : Color.clear,
                                    lineWidth: 2
                                )
                            }
                            .shadow(
                                color: model.canSend
                                    ? DivanPalette.wine.opacity(0.16) : .clear,
                                radius: 3,
                                y: 1
                            )
                    }
                    .buttonStyle(.plain)
                    .frame(width: composerControlSize, height: composerControlSize)
                    .focused($sendButtonFocused)
                    .disabled(!model.canSend)
                    .accessibilityLabel("Mesajı gönder")
                    .accessibilityIdentifier("divan.chat.send")
                    .help(model.canSend ? "Mesajı gönder" : "Göndermek için bir mesaj yazın")
                }
            }
            .frame(maxWidth: 860)
            .padding(.horizontal, 12)
            .padding(.vertical, 9)
            .frame(maxWidth: .infinity)
            .background(.bar)
            .accessibilityIdentifier("divan.chat.composer")
        }
    }

    private var failedResponseLabel: some View {
        Label(DivanStrings.responseIncomplete, systemImage: "exclamationmark.circle")
            .foregroundStyle(.secondary)
    }

    private var reloadConversationButton: some View {
        Button("Konuşmayı yenile") {
            Task { await model.reloadConversationAfterFailedResponse() }
        }
        .help("Sunucudaki son mesaj durumunu yeniden yükler; aynı mesajı tekrar göndermez")
    }

    private var composerMenu: some View {
        Menu {
            if model.selectedConversation?.mode == .therapy {
                // Ustanın bu protokolü sunup sunmadığı ancak çalışma ekranı
                // yüklendiğinde sunucudan öğrenilir; etiketler bu belirsizliği
                // gizlemez ve ekranın kendi çıkışı vardır.
                Button {
                    model.openAdvancedModule(.chairWork)
                } label: {
                    Label("Sandalye çalışması…", systemImage: "chair.lounge")
                }
                Button {
                    model.openAdvancedModule(.reparenting)
                } label: {
                    Label("Yeniden ebeveynlik…", systemImage: "heart.circle")
                }
                Button {
                    model.openAdvancedModule(.livingMap)
                } label: {
                    Label("Yaşayan harita", systemImage: "map")
                }
                Divider()
            }
            Button {
                beginStorySelection()
            } label: {
                Label("Hikâye oluştur", systemImage: "rectangle.portrait.on.rectangle.portrait")
            }
            if model.selectedConversation?.isEnded == false {
                Divider()
                Button {
                    showEndConfirmation = true
                } label: {
                    Label(
                        model.selectedConversation?.mode == .therapy
                            ? "Seansı bitir" : "Görüşmeyi bitir",
                        systemImage: "checkmark.seal"
                    )
                }
            }
        } label: {
            Image(systemName: "plus")
                .font(.system(size: 15, weight: .semibold))
                .frame(width: composerControlSize, height: composerControlSize)
                .background(Color(nsColor: .controlBackgroundColor), in: Circle())
                .overlay {
                    Circle()
                        .stroke(
                            composerMenuFocused
                                ? Color.accentColor
                                : Color(nsColor: .separatorColor).opacity(0.72),
                            lineWidth: composerMenuFocused ? 2 : 1
                        )
                }
                .contentShape(Circle())
        }
        .menuStyle(.borderlessButton)
        .menuIndicator(.hidden)
        .fixedSize()
        .frame(width: composerControlSize, height: composerControlSize)
        .focused($composerMenuFocused)
        .help("Ek seçenekler")
        .accessibilityLabel("Ek seçenekler")
        .accessibilityIdentifier("divan.chat.composerMenu")
    }

    private var composerHeight: CGFloat {
        max(composerControlSize, composerMeasuredHeight)
    }

    private var composerControlSize: CGFloat {
        max(40, min(54, 40 * dynamicTypeSize.divanFontScale))
    }

    @ToolbarContentBuilder
    private var chatToolbar: some ToolbarContent {
        ToolbarItem {
            Menu {
                Button {
                    beginStorySelection()
                } label: {
                    Label("Mesajlardan hikâye oluştur", systemImage: "rectangle.portrait.on.rectangle.portrait")
                }
                if model.selectedConversation?.mode == .therapy {
                    Button {
                        model.openAdvancedModule(.chairWork)
                    } label: {
                        Label("Seans çalışmaları", systemImage: "chair.lounge")
                    }
                    Button {
                        model.openAdvancedModule(.livingMap)
                    } label: {
                        Label("Yaşayan harita", systemImage: "map")
                    }
                }
                Divider()
                if model.selectedConversation?.isEnded == false,
                   model.selectedConversation?.isArchived == false {
                    Button {
                        showEndConfirmation = true
                    } label: {
                        Label(
                            model.selectedConversation?.mode == .therapy
                                ? "Seansı bitir" : "Görüşmeyi bitir",
                            systemImage: "checkmark.seal"
                        )
                    }
                    .disabled(model.isEndingConversation)
                }
                Button {
                    showArchiveConfirmation = true
                } label: {
                    Label(
                        model.selectedConversation?.isArchived == true
                            ? "Arşivden çıkar" : "Arşivle",
                        systemImage: model.selectedConversation?.isArchived == true
                            ? "tray.and.arrow.up" : "archivebox"
                    )
                }
                .disabled(model.isMutatingConversation)
                Button(role: .destructive) {
                    showDeleteConfirmation = true
                } label: {
                    Label("Konuşmayı sil", systemImage: "trash")
                }
                .disabled(model.isMutatingConversation)
            } label: {
                Image(systemName: "ellipsis")
                    .frame(width: 28, height: 28)
            }
            .menuStyle(.borderlessButton)
            .menuIndicator(.hidden)
            .help("Konuşma menüsü")
            .accessibilityLabel("Konuşma menüsü")
        }
    }

    private var selectedStoryMessages: [DivanMessage] {
        model.messages.filter { selectedStoryMessageIDs.contains($0.id) }
    }

    private func isStoryEligible(_ message: DivanMessage) -> Bool {
        message.role != .system && !message.content
            .trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && !message.isPending && message.failedDescription == nil
    }

    /// Seçili ustanın portresi, balon arka planı için bir kez çözülür.
    private var bubblePortrait: NSImage? {
        guard let data = model.portraitData(for: model.selectedMaster) else {
            return nil
        }
        return NSImage(data: data)
    }

    private func outgoingDeliveryState(
        for message: DivanMessage
    ) -> NativeOutgoingDeliveryState? {
        guard message.role == .user else { return nil }
        if message.serverID != nil { return .accepted }
        guard let index = model.messages.firstIndex(where: { $0.id == message.id }),
              index + 1 < model.messages.endIndex,
              let response = model.messages[(index + 1)...]
                .first(where: { $0.role == .assistant }) else {
            return .sending
        }
        if response.failedDescription != nil,
           response.content.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return .unconfirmed
        }
        if !response.content.isEmpty || !response.isPending {
            return .accepted
        }
        return .sending
    }

    private func beginStorySelection(with message: DivanMessage? = nil) {
        isSelectingStoryMessages = true
        if let message, isStoryEligible(message) {
            selectedStoryMessageIDs.insert(message.id)
        }
    }

    private func toggleStoryMessage(_ message: DivanMessage) {
        guard isStoryEligible(message) else { return }
        if selectedStoryMessageIDs.contains(message.id) {
            selectedStoryMessageIDs.remove(message.id)
        } else if selectedStoryMessageIDs.count < 8 {
            selectedStoryMessageIDs.insert(message.id)
        }
    }

    private func scrollToLatest(_ proxy: ScrollViewProxy, animated: Bool) {
        guard let id = model.messages.last?.id else { return }
        if animated {
            withAnimation(.easeOut(duration: 0.18)) {
                proxy.scrollTo(id, anchor: .bottom)
            }
        } else {
            proxy.scrollTo(id, anchor: .bottom)
        }
    }
}

/// AppKit's scroll view remains the source of truth for whether the reader is
/// following the live edge. This prevents incoming deltas from pulling the
/// viewport away while an older message is being read.
private struct ScrollFollowObserver: NSViewRepresentable {
    let onChange: @MainActor (Bool) -> Void

    func makeNSView(context: Context) -> ObserverView {
        ObserverView(onChange: onChange)
    }

    func updateNSView(_ view: ObserverView, context: Context) {
        view.onChange = onChange
        view.attachWhenReady()
    }

    final class ObserverView: NSView {
        var onChange: @MainActor (Bool) -> Void
        private weak var observedScrollView: NSScrollView?
        private var boundsObserver: NSObjectProtocol?

        init(onChange: @escaping @MainActor (Bool) -> Void) {
            self.onChange = onChange
            super.init(frame: .zero)
        }

        @available(*, unavailable)
        required init?(coder: NSCoder) { nil }

        override func viewDidMoveToWindow() {
            super.viewDidMoveToWindow()
            attachWhenReady()
        }

        func attachWhenReady() {
            DispatchQueue.main.async { [weak self] in self?.attach() }
        }

        private func attach() {
            var ancestor = superview
            var scrollView: NSScrollView?
            while let view = ancestor {
                if let candidate = view as? NSScrollView {
                    scrollView = candidate
                    break
                }
                ancestor = view.superview
            }
            guard let scrollView else { return }
            if observedScrollView !== scrollView {
                if let boundsObserver {
                    NotificationCenter.default.removeObserver(boundsObserver)
                }
                observedScrollView = scrollView
                scrollView.contentView.postsBoundsChangedNotifications = true
                boundsObserver = NotificationCenter.default.addObserver(
                    forName: NSView.boundsDidChangeNotification,
                    object: scrollView.contentView,
                    queue: .main
                ) { [weak self] _ in
                    self?.reportPosition()
                }
            }
            reportPosition()
        }

        private func reportPosition() {
            guard let scrollView = observedScrollView,
                  let documentView = scrollView.documentView else { return }
            let distance = documentView.bounds.maxY - documentView.visibleRect.maxY
            let nearBottom = distance <= 96
            Task { @MainActor [weak self] in self?.onChange(nearBottom) }
        }

        deinit {
            if let boundsObserver {
                NotificationCenter.default.removeObserver(boundsObserver)
            }
        }
    }
}

private enum NativeOutgoingDeliveryState {
    case sending
    case accepted
    case unconfirmed

    var accessibilityText: String {
        switch self {
        case .sending: "Gönderiliyor"
        case .accepted: "Divan tarafından alındı"
        case .unconfirmed: "Gönderim doğrulanamadı"
        }
    }
}

private struct NativeMessageBubble: View {
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    let message: DivanMessage
    let masterName: String
    /// Usta balonunun arkasında beliren portre. Yalnız dekoratiftir; metnin
    /// okunabilirliğini bozmamak için çok düşük opaklıkta ve yumuşatılmış
    /// kenarlarla çizilir.
    var portrait: NSImage?
    let outgoingDelivery: NativeOutgoingDeliveryState?
    let selectionEnabled: Bool
    let selected: Bool
    let selectable: Bool
    let toggleSelection: () -> Void
    let beginSelection: () -> Void

    var body: some View {
        HStack(alignment: .bottom, spacing: 8) {
            if message.role == .user { Spacer(minLength: 44) }
            VStack(alignment: message.role == .user ? .trailing : .leading, spacing: 4) {
                if message.isPending && message.content.isEmpty && message.failedDescription == nil {
                    HStack(alignment: .lastTextBaseline, spacing: 7) {
                        ProgressView().controlSize(.small)
                        Text("yazıyor")
                        timestampText
                    }
                    .font(.system(size: messageFontSize))
                    .foregroundStyle(.secondary)
                } else {
                    contentWithMetadata
                        .font(.system(size: messageFontSize))
                        .textSelection(.enabled)
                }
                if let failure = message.failedDescription {
                    Label(failure, systemImage: "exclamationmark.circle")
                        .font(.caption)
                        .foregroundStyle(.red)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .background {
                RoundedRectangle(cornerRadius: 16)
                    .fill(
                        message.role == .user
                            ? DivanPalette.parchment.opacity(0.92)
                            : Color(nsColor: .controlBackgroundColor)
                    )
                    .overlay {
                        // Ustanın yüzü balonun içinden hafifçe belirir:
                        // konuşanın kim olduğunu metni gölgelemeden hatırlatır.
                        if message.role != .user, let portrait {
                            Image(nsImage: portrait)
                                .resizable()
                                .scaledToFill()
                                .opacity(0.10)
                                .blendMode(.luminosity)
                                .clipShape(RoundedRectangle(cornerRadius: 16))
                                .allowsHitTesting(false)
                                .accessibilityHidden(true)
                        }
                    }
                    .clipShape(RoundedRectangle(cornerRadius: 16))
            }
            .overlay {
                RoundedRectangle(cornerRadius: 16)
                    .stroke(
                        selected ? DivanPalette.wine : Color.clear,
                        lineWidth: selected ? 2 : 0
                    )
            }
            .frame(maxWidth: 680, alignment: message.role == .user ? .trailing : .leading)
            .overlay(alignment: .topTrailing) {
                if selectionEnabled && selectable {
                    Image(systemName: selected ? "checkmark.circle.fill" : "circle")
                        .font(.title3)
                        .foregroundStyle(selected ? DivanPalette.wine : .secondary)
                        .padding(7)
                        .accessibilityHidden(true)
                }
            }
            if message.role != .user { Spacer(minLength: 44) }
        }
        .frame(maxWidth: .infinity)
        .contentShape(Rectangle())
        .onTapGesture {
            if selectionEnabled && selectable { toggleSelection() }
        }
        .onLongPressGesture(minimumDuration: 0.45) {
            if selectable && !selectionEnabled { beginSelection() }
        }
        .contextMenu {
            if selectable {
                Button {
                    if selectionEnabled { toggleSelection() }
                    else { beginSelection() }
                } label: {
                    Label(
                        selected ? "Hikâyeden çıkar" : "Hikâyeye ekle",
                        systemImage: selected ? "minus.circle" : "plus.circle"
                    )
                }
            }
            Button {
                NSPasteboard.general.clearContents()
                NSPasteboard.general.setString(message.content, forType: .string)
            } label: {
                Label("Kopyala", systemImage: "doc.on.doc")
            }
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel(accessibilityText)
        .accessibilityAddTraits(selected ? .isSelected : [])
    }

    private var accessibilityText: String {
        let speaker = message.role == .user ? "Siz" : masterName
        let time = message.createdAt.formatted(date: .omitted, time: .shortened)
        let state: String
        if message.failedDescription != nil {
            state = DivanStrings.responseIncomplete
        } else if message.isPending {
            state = "Gönderiliyor"
        } else if let outgoingDelivery {
            state = outgoingDelivery.accessibilityText
        } else {
            state = ""
        }
        return [speaker, message.content, time, state]
            .filter { !$0.isEmpty }.joined(separator: ", ")
    }

    /// An invisible caption-width tail reserves only the final-line space.
    /// The visible metadata is then anchored to that line's bottom-trailing
    /// edge. This is the compact WhatsApp pattern without a separate row.
    /// Ayarlardaki yazı boyutu tercihi mesaj balonlarına da uygulanır.
    /// Composer ile aynı `divanFontScale` çarpanı kullanılır; aksi hâlde
    /// yazdığınız metinle okuduğunuz metin farklı boyutta görünüyordu.
    private var messageFontSize: CGFloat {
        let base = NSFont.preferredFont(forTextStyle: .body).pointSize
        return max(11, base * dynamicTypeSize.divanFontScale)
    }

    private var contentWithMetadata: some View {
        ZStack(alignment: .bottomTrailing) {
            (renderedContent + Text("  ") + metadataReservation)
                .fixedSize(horizontal: false, vertical: true)
            metadataText
                .fixedSize()
        }
    }

    private var metadataReservation: Text {
        let count = message.role == .user || message.isPending ||
            message.failedDescription != nil ? 16 : 12
        return Text(String(repeating: "\u{00A0}", count: count))
            .font(.caption2)
            .foregroundColor(.clear)
    }

    private var metadataText: Text {
        var value = timestampText
        if message.failedDescription != nil {
            value = value + Text(" ") + Text(Image(systemName: "exclamationmark.circle.fill"))
                .foregroundColor(.red)
        } else if let outgoingDelivery {
            value = value + Text(" ") + deliverySymbol(outgoingDelivery)
        } else if message.isPending {
            value = value + Text(" ") + Text(Image(systemName: "clock"))
        }
        return value
    }

    private func deliverySymbol(_ state: NativeOutgoingDeliveryState) -> Text {
        switch state {
        case .sending:
            return Text(Image(systemName: "clock"))
                .foregroundColor(.secondary)
        case .accepted:
            // A single check is deliberately only “Divan accepted it”; there
            // is no simulated read receipt for a historical persona.
            return Text(Image(systemName: "checkmark"))
                .foregroundColor(DivanPalette.wine)
        case .unconfirmed:
            return Text(Image(systemName: "exclamationmark.circle.fill"))
                .foregroundColor(.red)
        }
    }

    private var timestampText: Text {
        Text(message.createdAt, format: .dateTime.hour().minute())
            .font(.caption2.monospacedDigit())
            .foregroundColor(
                message.role == .user
                    ? DivanPalette.ink.opacity(0.72)
                    : Color.secondary
            )
    }

    private var renderedContent: Text {
        guard var attributed = try? AttributedString(
            markdown: message.content,
            options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace)
        ) else {
            return Text(message.content)
        }
        // Model text may contain links. Native preview renders their labels but
        // deliberately removes navigation until a URL allow-list exists.
        let linkedRanges = attributed.runs.compactMap { run in
            run.link == nil ? nil : run.range
        }
        linkedRanges.forEach { attributed[$0].link = nil }
        return Text(attributed)
            .foregroundColor(message.role == .user ? DivanPalette.ink : nil)
    }
}

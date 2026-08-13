import SwiftUI

struct ChairWorkView: View {
    @ObservedObject var model: AdvancedWorkspaceViewModel
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @FocusState private var turnEditorFocused: Bool
    @State private var closureSheetPresented = false
    @State private var compactPane: ChairCompactPane = .dialogue
    @State private var measuredComposerHeight: CGFloat = 0

    var body: some View {
        Group {
            if let session = model.chairSession,
               session.phase != .notStarted {
                activeSession(session)
            } else {
                startForm
            }
        }
        .sheet(isPresented: $closureSheetPresented) {
            ChairClosureSheet(model: model)
        }
    }

    private var startForm: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                        if model.chairSession?.phase == .notStarted {
                            Label(
                                "Önerilmiş çalışma hazır. Başlangıç bilgilerini gözden geçirip onayları yeniden verin.",
                                systemImage: "clock.badge.checkmark"
                            )
                            .font(.callout.weight(.semibold))
                            .foregroundStyle(DivanPalette.wine)
                            .fixedSize(horizontal: false, vertical: true)
                            .accessibilityIdentifier("chairProposedGuidance")
                        }
                        Text(model.chairConfiguration.frame)
                            .font(.callout)
                            .foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                        AdvancedSafetyBanner()

                GroupBox("Çalışmanın çerçevesi") {
                    VStack(alignment: .leading, spacing: 14) {
                        TextField(
                            "Bu çalışmada neyi anlamak veya değiştirmek istiyorsunuz?",
                            text: $model.chairGoalText,
                            axis: .vertical
                        )
                        .lineLimit(2...4)
                        .accessibilityHint("Örneğin, bir yanım yaklaşmak isterken diğer yanım kaçıyor")

                        TextField("Durma işaretiniz", text: $model.chairStopSignal)
                            .accessibilityHint("Bu sözü yazdığınız anda çalışma ilerlemeden duraklatılmalıdır")

                        VStack(alignment: .leading, spacing: 9) {
                            Text("Konuşacak sandalyeler")
                                .font(.callout.weight(.medium))
                            ForEach(model.chairParticipantTitles.indices, id: \.self) { index in
                                HStack {
                                    TextField(
                                        "\(index + 1). sandalye",
                                        text: participantTitleBinding(index)
                                    )
                                    .accessibilityLabel("\(index + 1). sandalyenin adı")
                                    if model.chairParticipantTitles.count > model.chairConfiguration.minimumParticipants {
                                        Button(role: .destructive) {
                                            model.chairParticipantTitles.remove(at: index)
                                        } label: {
                                            Image(systemName: "minus.circle")
                                        }
                                        .buttonStyle(.plain)
                                        .accessibilityLabel("\(index + 1). sandalyeyi kaldır")
                                    }
                                }
                            }
                            if model.chairConfiguration.allowsAddingParticipants,
                               model.chairParticipantTitles.count < model.chairConfiguration.maximumParticipants {
                                Button {
                                    model.chairParticipantTitles.append(
                                        "Parça \(model.chairParticipantTitles.count + 1)"
                                    )
                                } label: {
                                    Label("Başka bir sandalye ekle", systemImage: "plus.circle")
                                }
                            }
                            Text("Bu yöntem \(model.chairConfiguration.minimumParticipants)–\(model.chairConfiguration.maximumParticipants) sandalye destekler.")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }

                        AdvancedIntensityControl(
                            title: "Başlangıç yoğunluğu",
                            value: $model.chairIntensity,
                            maximum: model.clinicalIntensityLimit
                        )
                    }
                    .padding(.top, 6)
                }

                GroupBox("Başlangıç onayları") {
                    VStack(alignment: .leading, spacing: 12) {
                        Toggle(isOn: $model.chairOrientationConfirmed) {
                            VStack(alignment: .leading, spacing: 2) {
                                Text("Yönelimim açık")
                                    .font(.callout.weight(.semibold))
                                Text("Şu an nerede olduğumu ve bu çalışmayı ekranda yaptığımı biliyorum.")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                        }
                        Toggle(isOn: $model.chairFrameConfirmed) {
                            VStack(alignment: .leading, spacing: 2) {
                                Text("Çerçeveyi kabul ediyorum")
                                    .font(.callout.weight(.semibold))
                                Text("Sözleri ben yazacağım; durma işaretimi kullanabilir, duraklatabilir veya bitirebilirim.")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                        }
                    }
                    .toggleStyle(.checkbox)
                    .frame(maxWidth: .infinity, alignment: .leading)
                }

            }
            .padding(22)
            .frame(maxWidth: 760)
            .frame(maxWidth: .infinity)
        }
        .safeAreaInset(edge: .top, spacing: 0) {
            VStack(spacing: 0) {
                AdvancedSectionHeader(
                    title: model.chairConfiguration.title,
                    detail: model.chairConfiguration.frame,
                    systemImage: "chair.lounge",
                    showsDetail: false
                )
                .accessibilityIdentifier("chairStartHeading")
                .padding(.horizontal, 16)
                .padding(.vertical, 10)
                .background(.bar)
                Divider()
                chairStartActionBar
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .accessibilityIdentifier("chairStartSurface")
    }

    private var chairStartActionBar: some View {
        VStack(alignment: .leading, spacing: 8) {
            chairStartIssueLabel
            chairStartButton
                .frame(maxWidth: .infinity, alignment: .trailing)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 10)
        .background(.bar)
        .overlay(alignment: .top) { Divider() }
    }

    @ViewBuilder
    private var chairStartIssueLabel: some View {
        if let issue = chairStartIssue {
            Label(issue, systemImage: "info.circle")
                .font(.callout)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
                .accessibilityLabel("Başlangıç için eksik: \(issue)")
        } else {
            Label("Başlamaya hazır", systemImage: "checkmark.circle")
                .font(.callout)
                .foregroundStyle(.secondary)
        }
    }

    private var chairStartButton: some View {
        Button("Onayla ve başlat") {
            Task { await model.startChairWork() }
        }
        .buttonStyle(.borderedProminent)
        .controlSize(.large)
        .tint(DivanPalette.wine)
        .disabled(model.isPerformingAction || model.clinicalSafetyHold)
        .accessibilityLabel("Onayla ve başlat")
        .accessibilityIdentifier("chairStartAction")
    }

    private func activeSession(_ session: WorkspaceChairSession) -> some View {
        GeometryReader { geometry in
            let compactHeight = geometry.size.height < 560
            VStack(spacing: 0) {
                sessionHeader(session, compactHeight: compactHeight)
                Divider()
                if session.phase == .completed {
                    completedSessionGuidance(session)
                } else if geometry.size.width < 1_040 {
                    compactSession(session, compactHeight: compactHeight)
                } else {
                    let guidanceWidth = min(
                        380,
                        max(280, geometry.size.width * 0.28)
                    )
                    HStack(spacing: 0) {
                        dialogueColumn(session, compactHeight: compactHeight)
                            .frame(
                                minWidth: 0,
                                maxWidth: .infinity,
                                maxHeight: .infinity
                            )
                            .clipped()
                            .accessibilityIdentifier("chairDialoguePane")
                        Divider()
                        guidanceColumn(session)
                            .frame(width: guidanceWidth)
                            .frame(maxHeight: .infinity)
                            .clipped()
                            .accessibilityIdentifier("chairGuidancePane")
                    }
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .clipped()
                    .accessibilityElement(children: .contain)
                    .accessibilityIdentifier("chairWideWorkspace")
                }
            }
            .frame(
                width: max(0, geometry.size.width),
                height: max(0, geometry.size.height),
                alignment: .topLeading
            )
            .clipped()
        }
        .frame(
            minWidth: 0,
            maxWidth: .infinity,
            minHeight: 0,
            maxHeight: .infinity
        )
        .clipped()
    }

    private func completedSessionGuidance(
        _ session: WorkspaceChairSession
    ) -> some View {
        ScrollView {
            VStack(spacing: 14) {
                Image(systemName: "checkmark.seal.fill")
                    .font(.system(size: 34, weight: .light))
                    .foregroundStyle(.green)
                    .accessibilityHidden(true)
                Text("Bu çalışma kapatıldı")
                    .font(.title3.weight(.semibold))
                Text(
                    "Bu çalışma kapatıldı. Yeni bir çalışma hazırlayabilir veya başka bir açık terapi seansı seçebilirsiniz."
                )
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
                Button {
                    model.prepareNewChairWork()
                } label: {
                    Label("Yeni sandalye çalışması hazırla", systemImage: "plus.circle")
                }
                .buttonStyle(.borderedProminent)
                .tint(DivanPalette.wine)
                .disabled(model.isPerformingAction || model.clinicalSafetyHold)
                .accessibilityIdentifier("chairPrepareNewAction")
                AdvancedSafetyBanner(compact: true)
                    .frame(maxWidth: 520)
            }
            .padding(22)
            .frame(maxWidth: 620)
            .frame(maxWidth: .infinity)
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("chairCompletedGuidance")
    }

    private func compactSession(
        _ session: WorkspaceChairSession,
        compactHeight: Bool
    ) -> some View {
        VStack(spacing: 0) {
            Picker("Çalışma görünümü", selection: $compactPane) {
                ForEach(ChairCompactPane.allCases) { pane in
                    Label(pane.title, systemImage: pane.systemImage).tag(pane)
                }
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .background(.bar)

            if compactPane == .dialogue {
                dialogueColumn(session, compactHeight: compactHeight)
            } else {
                guidanceColumn(session)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .clipped()
    }

    private func sessionHeader(
        _ session: WorkspaceChairSession,
        compactHeight: Bool
    ) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            ViewThatFits(in: .horizontal) {
                HStack(alignment: .top, spacing: 12) {
                    chairSessionIdentity(session, compact: compactHeight)
                    Spacer()
                    AdvancedPhaseBadge(phase: session.phase)
                }
                VStack(alignment: .leading, spacing: 8) {
                    chairSessionIdentity(session, compact: compactHeight)
                    AdvancedPhaseBadge(phase: session.phase)
                }
            }
            if session.phase != .completed {
                if compactHeight {
                    compactSessionActions(session)
                } else {
                    ViewThatFits(in: .horizontal) {
                        HStack(spacing: 10) {
                            sessionActionButtons(session)
                        }
                        VStack(alignment: .leading, spacing: 8) {
                            sessionActionButtons(session)
                        }
                    }
                }
            }
            if compactHeight {
                Label(
                    "Sınırı siz belirlersiniz; istediğiniz anda çalışmayı kapatabilirsiniz.",
                    systemImage: "hand.raised"
                )
                .font(.caption)
                .foregroundStyle(.secondary)
            } else {
                AdvancedSafetyBanner(compact: true)
            }
        }
        .padding(compactHeight ? 10 : 16)
        .background(.bar)
    }

    private func chairSessionIdentity(
        _ session: WorkspaceChairSession,
        compact: Bool
    ) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(session.title).font(.title3.weight(.semibold))
            if !compact {
                Text(session.goalText)
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            }
            Label("Durma işareti: \(session.stopSignal)", systemImage: "hand.raised.fill")
                .font(.caption.weight(.semibold))
                .foregroundStyle(DivanPalette.wine)
            if !compact, !session.stages.isEmpty {
                Text("Aşama \(session.currentStageIndex + 1) / \(session.stages.count): \(chairStageLabel(session))")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
    }

    @ViewBuilder
    private func sessionActionButtons(_ session: WorkspaceChairSession) -> some View {
        if session.phase == .active {
            Button {
                prepareChairGrounding()
            } label: {
                Label("Şimdiye dön", systemImage: "hand.raised.fill")
            }
            .disabled(model.isPerformingAction)
            .help("Açık şimdiye dönme formunu açar ve çalışmayı duraklatır")
            .accessibilityLabel("Şimdiye dönme formunu aç ve sandalye çalışmasını duraklat")
        }
        Button {
            closureSheetPresented = true
        } label: {
            Label("Kapanış adımları", systemImage: "list.number")
        }
        .disabled(model.isPerformingAction || model.clinicalSafetyHold)

        chairStopButton
    }

    private func compactSessionActions(_ session: WorkspaceChairSession) -> some View {
        HStack(spacing: 10) {
            Menu {
                if session.phase == .active {
                    Button("Şimdiye dön") { prepareChairGrounding() }
                        .disabled(model.isPerformingAction)
                }
                Button("Kapanış adımları") { closureSheetPresented = true }
                    .disabled(model.isPerformingAction || model.clinicalSafetyHold)
            } label: {
                Label("Çalışma adımları", systemImage: "ellipsis.circle")
            }
            Spacer(minLength: 8)
            chairStopButton
        }
    }

    private var chairStopButton: some View {
        Button(role: .destructive) {
            Task { await model.stopChairWork() }
        } label: {
            Label("Çalışmayı kapat", systemImage: "stop.fill")
        }
        .disabled(model.isChairStopInFlight)
        .help("Onay beklemeden ilerlemeyi keser; kapanış adımlarını tamamlanmış saymaz")
        .accessibilityHint(DivanStrings.alwaysAvailableActionHint)
        .accessibilityIdentifier("chairStopAction")
    }

    private func dialogueColumn(
        _ session: WorkspaceChairSession,
        compactHeight: Bool
    ) -> some View {
        VStack(spacing: 0) {
            chairSelector(session, compactHeight: compactHeight)
                .padding(.horizontal, compactHeight ? 10 : 14)
                .padding(.vertical, compactHeight ? 8 : 14)
                .fixedSize(horizontal: false, vertical: true)
                .layoutPriority(2)
            Divider()

            chairTranscript(session, compactHeight: compactHeight)
                .frame(minWidth: 0, maxWidth: .infinity, minHeight: 0, maxHeight: .infinity)
                .layoutPriority(1)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .clipped()
        .overlay(alignment: .bottom) {
            if session.phase == .active {
                VStack(spacing: 0) {
                    Divider()
                    chairComposer(session, compactHeight: compactHeight)
                }
                .frame(maxWidth: .infinity)
                .background(.bar)
                .accessibilityIdentifier("chairComposerDock")
                .background {
                    GeometryReader { composerGeometry in
                        Color.clear.preference(
                            key: ChairComposerHeightPreferenceKey.self,
                            value: composerGeometry.size.height
                        )
                    }
                }
            }
        }
        .onPreferenceChange(ChairComposerHeightPreferenceKey.self) { height in
            guard height.isFinite, height >= 0 else { return }
            measuredComposerHeight = height
        }
    }

    private func chairTranscript(
        _ session: WorkspaceChairSession,
        compactHeight: Bool
    ) -> some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: compactHeight ? 8 : 12) {
                    if session.turns.isEmpty {
                        VStack(spacing: 8) {
                            Image(systemName: "text.bubble")
                                .font(.title)
                                .foregroundStyle(.secondary)
                                .accessibilityHidden(true)
                            Text("İlk sandalyenin sözünü bekliyor")
                                .font(.headline)
                            Text("Seçili parçanın ağzından, mümkünse “Ben…” diye başlayan kısa bir cümle yazın.")
                                .font(.callout)
                                .foregroundStyle(.secondary)
                                .multilineTextAlignment(.center)
                        }
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, compactHeight ? 16 : 40)
                    }
                    ForEach(session.turns) { turn in
                        ChairTurnBubble(
                            turn: turn,
                            alignmentLeading: participantOrder(
                                chairID: turn.chairID,
                                in: session
                            ).isMultiple(of: 2)
                        )
                        .id(turn.id)
                    }
                    if session.phase == .paused {
                        chairResumeControls(session)
                            .id("chair-resume-controls")
                    }
                    if session.phase == .active, measuredComposerHeight > 0 {
                        Color.clear
                            .frame(height: measuredComposerHeight)
                            .accessibilityHidden(true)
                            .id("chair-composer-clearance")
                    }
                }
                .padding(compactHeight ? 10 : 16)
            }
            .onChange(of: session.turns.count) { _ in
                guard let lastID = session.turns.last?.id else { return }
                if reduceMotion {
                    proxy.scrollTo(lastID, anchor: .bottom)
                } else {
                    withAnimation(.easeOut(duration: 0.2)) {
                        proxy.scrollTo(lastID, anchor: .bottom)
                    }
                }
            }
            .onAppear {
                guard session.phase == .paused else { return }
                Task { @MainActor in
                    await Task.yield()
                    proxy.scrollTo("chair-resume-controls", anchor: .bottom)
                }
            }
            .onChange(of: session.phase) { phase in
                guard phase == .paused else { return }
                proxy.scrollTo("chair-resume-controls", anchor: .bottom)
            }
        }
        .accessibilityIdentifier("chairDialogueTranscript")
    }

    private func chairResumeControls(_ session: WorkspaceChairSession) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Label("Çalışma şimdiye dönme adımında duraklatıldı", systemImage: "pause.circle")
                .font(.callout.weight(.semibold))

            Text("Sürdürme önceki onayları devralmaz. Odayı ve beden temasını yeniden fark edip güncel yoğunluğunuzu belirtin.")
                .font(.caption)
                .foregroundStyle(.secondary)

            AdvancedIntensityControl(
                title: "Şu anki yoğunluk",
                value: $model.chairIntensity,
                maximum: session.intensityLimit,
                disabled: model.isPerformingAction
            )

            Toggle(
                "Bulunduğum odayı, bugünü ve ekran başında olduğumu yeniden fark ettim",
                isOn: $model.chairResumeOrientationConfirmed
            )
            Toggle(
                "Ayaklarımın veya bedenimin desteklendiği yüzeyle temasını yeniden fark ettim",
                isOn: $model.chairResumeGroundingConfirmed
            )
            .toggleStyle(.checkbox)

            if WorkspaceSafety.intensityBlocksResume(
                intensity: model.chairIntensity,
                limit: session.intensityLimit
            ) {
                Label(
                    "Bu yoğunlukta çalışmaya dönülmez. Şimdiye dönme adımında kalın veya çalışmayı kapatın.",
                    systemImage: "exclamationmark.shield"
                )
                .font(.callout)
                .foregroundStyle(.orange)
            }

            ViewThatFits(in: .horizontal) {
                HStack {
                    chairResumeStopButton
                    Spacer()
                    chairResumeButton(session)
                }
                VStack(alignment: .leading, spacing: 9) {
                    chairResumeButton(session)
                    chairResumeStopButton
                }
            }
        }
        .toggleStyle(.checkbox)
        .padding(14)
        .background(.bar)
    }

    private var chairResumeStopButton: some View {
        Button(role: .destructive) {
            Task { await model.stopChairWork() }
        } label: {
            Label("Çalışmayı kapat", systemImage: "stop.fill")
        }
        .disabled(model.isChairStopInFlight)
        .accessibilityHint(DivanStrings.alwaysAvailableActionHint)
        .accessibilityIdentifier("chairResumeStopAction")
    }

    private func chairResumeButton(_ session: WorkspaceChairSession) -> some View {
        Button {
            Task { await model.resumeChairWork() }
        } label: {
            Label("Bu noktadan sürdür", systemImage: "play.fill")
        }
        .buttonStyle(.borderedProminent)
        .tint(DivanPalette.wine)
        .disabled(
            model.isPerformingAction ||
            model.isChairStopInFlight ||
            model.clinicalSafetyHold ||
            !model.chairResumeOrientationConfirmed ||
            !model.chairResumeGroundingConfirmed ||
            WorkspaceSafety.intensityBlocksResume(
                intensity: model.chairIntensity,
                limit: session.intensityLimit)
        )
        .accessibilityIdentifier("chairResumeAction")
    }

    private func prepareChairGrounding() {
        model.chairClosureAction = .ground
        model.chairClosureCheckpointConfirmed = false
        model.chairClosureOrientationConfirmed = false
        model.chairClosureNote = ""
        closureSheetPresented = true
    }

    private func chairSelector(
        _ session: WorkspaceChairSession,
        compactHeight: Bool
    ) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            ScrollView(.horizontal, showsIndicators: true) {
                LazyHStack(spacing: 10) {
                    ForEach(session.participants) { chair in
                        ChairChoiceButton(
                            chair: chair,
                            isSelected: session.activeChairID == chair.id,
                            sideLabel: "\(chair.sortOrder + 1). sandalye"
                        ) {
                            Task { await model.selectChair(chair) }
                        }
                        .frame(width: 220)
                    }
                }
                .padding(.vertical, 1)
            }
            .frame(height: chairSelectorHeight(compactHeight: compactHeight))
            .frame(maxWidth: .infinity, alignment: .leading)
            .clipped()
            if session.allowsAddingParticipants,
               session.participants.count < session.maximumParticipants,
               session.phase == .active {
                ViewThatFits(in: .horizontal) {
                    HStack(spacing: 8) {
                        chairParticipantField
                        chairParticipantAddButton
                    }
                    VStack(alignment: .leading, spacing: 8) {
                        chairParticipantField
                        chairParticipantAddButton
                            .frame(maxWidth: .infinity, alignment: .trailing)
                    }
                }
                .frame(maxWidth: .infinity)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .clipped()
        .disabled(session.phase != .active || model.isPerformingAction || model.clinicalSafetyHold)
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Konuşacak sandalyeyi seçin")
        .accessibilityIdentifier("chairSelector")
    }

    private func chairSelectorHeight(compactHeight: Bool) -> CGFloat {
        if dynamicTypeSize.divanIsAccessibilitySize { return compactHeight ? 110 : 132 }
        switch dynamicTypeSize {
        case .xxLarge, .xxxLarge:
            return compactHeight ? 96 : 112
        default:
            return compactHeight ? 84 : 98
        }
    }

    private var chairParticipantField: some View {
        TextField("Yeni sandalyenin adı", text: $model.chairNewParticipantTitle)
            .textFieldStyle(.roundedBorder)
            .accessibilityLabel("Yeni sandalyenin adı")
            .accessibilityIdentifier("chairAddParticipantField")
            .frame(minWidth: 0, maxWidth: .infinity)
    }

    private var chairParticipantAddButton: some View {
        Button {
            Task { await model.addChairParticipant() }
        } label: {
            Label("Ekle", systemImage: "plus")
        }
        .disabled(
            model.chairNewParticipantTitle.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ||
            model.isPerformingAction
        )
    }

    private func chairComposer(
        _ session: WorkspaceChairSession,
        compactHeight: Bool
    ) -> some View {
        let activeTitle = session.activeChair?.title ?? "Seçili sandalye"
        return VStack(alignment: .leading, spacing: 9) {
            HStack {
                Text("\(activeTitle) olarak konuşun")
                    .font(.callout.weight(.semibold))
                Spacer()
                Text("Cümleler size aittir")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            ZStack(alignment: .topLeading) {
                Color(nsColor: .textBackgroundColor)
                if model.chairTurnDraft.isEmpty {
                    Text("Bu sandalyenin sözünü yazın…")
                        .font(.body)
                        .foregroundStyle(.tertiary)
                        .padding(.horizontal, 10)
                        .padding(.vertical, 9)
                        .allowsHitTesting(false)
                        .accessibilityHidden(true)
                }
                TextEditor(text: $model.chairTurnDraft)
                    .font(.body)
                    .scrollContentBackground(.hidden)
                    .padding(4)
                    .focused($turnEditorFocused)
                    .accessibilityLabel("\(activeTitle) için sözünüz")
                    .accessibilityHint("Göndermek için Komut ve Return tuşlarına basın")
            }
            .frame(minHeight: compactHeight ? 46 : 62, maxHeight: compactHeight ? 58 : 96)
            .clipShape(RoundedRectangle(cornerRadius: 10))
            .overlay {
                RoundedRectangle(cornerRadius: 10)
                    .stroke(
                        turnEditorFocused
                            ? DivanPalette.wine.opacity(0.82)
                            : Color(nsColor: .separatorColor),
                        lineWidth: turnEditorFocused ? 1.5 : 1
                    )
            }
            .accessibilityIdentifier("chairTurnEditorSurface")

            ViewThatFits(in: .horizontal) {
                HStack(alignment: .bottom, spacing: 12) {
                    chairIntensityControl(session)
                    Spacer(minLength: 8)
                    chairSubmitButton
                }
                VStack(alignment: .leading, spacing: 10) {
                    chairIntensityControl(session)
                    chairSubmitButton
                        .frame(maxWidth: .infinity, alignment: .trailing)
                }
            }
        }
        .padding(.horizontal, compactHeight ? 10 : 14)
        .padding(.vertical, compactHeight ? 8 : 12)
        .background(.bar)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("chairComposer")
    }

    private func chairIntensityControl(_ session: WorkspaceChairSession) -> some View {
        AdvancedIntensityControl(
            title: "Şu anki yoğunluk",
            value: $model.chairIntensity,
            maximum: session.intensityLimit,
            disabled: model.isPerformingAction
        )
        .frame(maxWidth: 260)
    }

    private var chairSubmitButton: some View {
        Button {
            Task { await model.submitChairTurn() }
        } label: {
            Label("Bu sandalyeden söyle", systemImage: "arrow.up.circle.fill")
        }
        .buttonStyle(.borderedProminent)
        .tint(DivanPalette.wine)
        .keyboardShortcut(.return, modifiers: [.command])
        .disabled(
            model.isPerformingAction ||
            model.clinicalSafetyHold ||
            model.chairTurnDraft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        )
        .accessibilityIdentifier("chairSubmitTurnAction")
    }

    private var chairStartIssue: String? {
        if model.clinicalSafetyHold {
            return "Güvenlik bekletmesi sürerken yeni çalışma başlatılmaz; seansa dönün veya şimdiye dönme desteğini kullanın."
        }
        if model.isPerformingAction {
            return model.operationDescription.isEmpty
                ? "Süren işlem tamamlandığında yeniden deneyin."
                : model.operationDescription
        }
        if !model.chairConsentComplete {
            return "İki başlangıç onayını ayrı ayrı işaretleyin."
        }
        if model.chairGoalText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return "Çalışmanın amacını kısa bir cümleyle yazın."
        }
        if model.chairStopSignal.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return "Kişisel bir durma işareti yazın."
        }
        if model.chairParticipantTitles.contains(where: {
            $0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        }) {
            return "Her sandalyeye ayırt edilebilir bir ad verin."
        }
        return nil
    }

    private func guidanceColumn(_ session: WorkspaceChairSession) -> some View {
        VStack(spacing: 0) {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Terapist gözlemi").font(.headline)
                    Text("AI canlandırmasının yönergesi")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                AISimulationBadge()
            }
            .padding(14)
            Divider()

            ScrollView {
                LazyVStack(alignment: .leading, spacing: 12) {
                    if session.guidance.isEmpty {
                        Text("Bir veya daha fazla sandalyeyi konuşturduktan sonra kısa bir gözlem isteyebilirsiniz.")
                            .font(.callout)
                            .foregroundStyle(.secondary)
                            .padding(.vertical, 18)
                    }
                    ForEach(session.guidance) { guidance in
                        VStack(alignment: .leading, spacing: 8) {
                            Text(guidance.observation)
                                .font(.callout)
                                .textSelection(.enabled)
                            Divider()
                            Label(guidance.nextStep, systemImage: "arrow.right.circle")
                                .font(.callout.weight(.medium))
                                .foregroundStyle(DivanPalette.wine)
                                .textSelection(.enabled)
                            if !guidance.checkIn.isEmpty {
                                Label(guidance.checkIn, systemImage: "questionmark.bubble")
                                    .font(.callout)
                                    .foregroundStyle(.secondary)
                                    .textSelection(.enabled)
                            }
                            Text(guidance.createdAt.formatted(date: .omitted, time: .shortened))
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                        }
                        .advancedCard()
                        .accessibilityElement(children: .combine)
                    }
                }
                .padding(14)
            }

            Divider()
            Button {
                Task { await model.requestChairGuidance() }
            } label: {
                Label("Gözlem ve yönerge iste", systemImage: "sparkles")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.bordered)
            .disabled(
                session.phase != .active ||
                session.turns.isEmpty ||
                model.clinicalSafetyHold ||
                model.isPerformingAction
            )
            .padding(12)
        }
        .background(Color(nsColor: .windowBackgroundColor))
    }

    private func participantTitleBinding(_ index: Int) -> Binding<String> {
        Binding(
            get: {
                guard model.chairParticipantTitles.indices.contains(index) else { return "" }
                return model.chairParticipantTitles[index]
            },
            set: { newValue in
                guard model.chairParticipantTitles.indices.contains(index) else { return }
                model.chairParticipantTitles[index] = newValue
            }
        )
    }

    private func participantOrder(chairID: String, in session: WorkspaceChairSession) -> Int {
        session.participants.first(where: { $0.id == chairID })?.sortOrder ?? 0
    }

    private func chairStageLabel(_ session: WorkspaceChairSession) -> String {
        session.stages.first(where: { $0.id == session.currentStageID })?.label ?? "Çalışma"
    }
}

private struct ChairClosureSheet: View {
    @ObservedObject var model: AdvancedWorkspaceViewModel
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(spacing: 0) {
            ViewThatFits(in: .horizontal) {
                HStack(alignment: .top) {
                    closureTitle
                    Spacer()
                    closureDismissButton
                }
                VStack(alignment: .leading, spacing: 9) {
                    closureTitle
                    closureDismissButton
                }
            }
            .padding(18)
            Divider()

            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    AdvancedSafetyBanner(compact: true)
                    closureStepPicker
                    selectedStepForm
                }
                .padding(20)
                .frame(maxWidth: 680)
                .frame(maxWidth: .infinity)
            }

            Divider()
            ViewThatFits(in: .horizontal) {
                HStack {
                    closureStopButton
                    closureCancelButton
                    Spacer()
                    closureSubmitButton
                }
                VStack(alignment: .leading, spacing: 9) {
                    closureSubmitButton
                        .frame(maxWidth: .infinity, alignment: .leading)
                    HStack {
                        closureStopButton
                        closureCancelButton
                    }
                }
            }
            .padding(16)
            .background(.bar)
        }
        .frame(idealWidth: 620, idealHeight: 560)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private var closureTitle: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text("Kapanış adımları")
                .font(.title2.weight(.semibold))
            Text("Her adımı siz seçer ve ayrı ayrı onaylarsınız.")
                .foregroundStyle(.secondary)
        }
    }

    private var closureDismissButton: some View {
        Button("Kapat") { dismiss() }
            .keyboardShortcut(.cancelAction)
    }

    private var closureStopButton: some View {
        Button("Çalışmayı kapat", role: .destructive) {
            Task {
                await model.stopChairWork()
                if model.failure == nil { dismiss() }
            }
        }
        .disabled(model.isChairStopInFlight)
        .accessibilityHint(DivanStrings.alwaysAvailableActionHint)
    }

    private var closureCancelButton: some View {
        Button("Vazgeç") { dismiss() }
    }

    private var closureSubmitButton: some View {
        Button {
            Task {
                await model.advanceChairClosure()
                if model.failure == nil,
                   model.chairSession?.phase == .completed {
                    dismiss()
                }
            }
        } label: {
            Label(
                "\(model.chairClosureAction.title) adımını uygula",
                systemImage: model.chairClosureAction.systemImage
            )
        }
        .buttonStyle(.borderedProminent)
        .tint(DivanPalette.wine)
        .disabled(!canSubmit || model.isPerformingAction)
    }

    private var closureStepPicker: some View {
        VStack(alignment: .leading, spacing: 9) {
            Text("Adımı seçin")
                .font(.headline)
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 140), spacing: 10)], spacing: 10) {
                ForEach(WorkspaceChairClosureAction.allCases) { action in
                    Button {
                        model.chairClosureAction = action
                        model.chairClosureCheckpointConfirmed = false
                        model.chairClosureOrientationConfirmed = false
                        model.chairClosureNote = ""
                    } label: {
                        VStack(spacing: 6) {
                            Image(systemName: stepSymbol(action))
                                .font(.title3)
                                .accessibilityHidden(true)
                            Text(action.title)
                                .font(.callout.weight(.semibold))
                            Text(stepStatus(action))
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                        }
                        .frame(maxWidth: .infinity, minHeight: 74)
                        .padding(8)
                        .background(
                            model.chairClosureAction == action
                                ? DivanPalette.parchment.opacity(0.5)
                                : Color(nsColor: .controlBackgroundColor),
                            in: RoundedRectangle(cornerRadius: 10)
                        )
                        .overlay {
                            RoundedRectangle(cornerRadius: 10)
                                .stroke(
                                    model.chairClosureAction == action
                                        ? DivanPalette.wine
                                        : Color(nsColor: .separatorColor),
                                    lineWidth: model.chairClosureAction == action ? 2 : 1
                                )
                        }
                    }
                    .buttonStyle(.plain)
                    .disabled(!stepIsSelectable(action))
                    .accessibilityLabel(action.title)
                    .accessibilityValue(stepStatus(action))
                    .accessibilityHint(action.instruction)
                }
            }
        }
    }

    private var selectedStepForm: some View {
        VStack(alignment: .leading, spacing: 14) {
            Label(
                model.chairClosureAction.title,
                systemImage: model.chairClosureAction.systemImage
            )
            .font(.title3.weight(.semibold))
            Text(model.chairClosureAction.instruction)
                .foregroundStyle(.secondary)

            AdvancedIntensityControl(
                title: "Şu anki yoğunluk",
                value: $model.chairIntensity,
                maximum: model.chairSession?.intensityLimit ?? model.clinicalIntensityLimit,
                disabled: model.isPerformingAction
            )

            if [.ground, .complete].contains(model.chairClosureAction) {
                Toggle(
                    model.chairClosureAction == .ground
                        ? "Bulunduğum odayı, zemini ve ekran başında olduğumu yeniden fark ettim"
                        : "Tamamlamadan önce bulunduğum odayı ve ekran başında olduğumu yeniden fark ettim",
                    isOn: $model.chairClosureOrientationConfirmed
                )
                .toggleStyle(.checkbox)
            }

            if model.chairClosureAction == .reflect {
                TextField(
                    "Bu çalışmadan kalan en önemli şeyi kendi sözlerinizle yazın",
                    text: $model.chairClosureNote,
                    axis: .vertical
                )
                .lineLimit(3...6)
                .accessibilityLabel("Kapanış yansıtmanız")
            }

            if model.chairClosureAction == .complete {
                VStack(alignment: .leading, spacing: 6) {
                    closureRequirement(.ground)
                    closureRequirement(.reflect)
                }
                .padding(10)
                .background(.quaternary, in: RoundedRectangle(cornerRadius: 9))
            }

            Toggle(isOn: $model.chairClosureCheckpointConfirmed) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(checkpointTitle)
                        .font(.callout.weight(.semibold))
                    Text("Bu eylem yalnız seçili adımı ilerletir; sonraki aşamaları otomatik tamamlamaz.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            .toggleStyle(.checkbox)
        }
        .advancedCard()
    }

    private func closureRequirement(_ action: WorkspaceChairClosureAction) -> some View {
        let done = model.chairSession?.completedClosureActions.contains(action) == true
        return Label(
            "\(action.title): \(done ? "tamamlandı" : "henüz tamamlanmadı")",
            systemImage: done ? "checkmark.circle.fill" : "circle"
        )
        .foregroundStyle(done ? .green : .secondary)
    }

    private var checkpointTitle: String {
        switch model.chairClosureAction {
        case .ground: "Şimdiye dönme adımını kendi seçimimle kaydediyorum"
        case .reflect: "Bu yansıtma kendi sözlerimi taşıyor"
        case .complete: "Topraklanma ve yansıtma sonrası çalışmayı tamamlamak istiyorum"
        }
    }

    private var canSubmit: Bool {
        guard model.chairClosureCheckpointConfirmed,
              stepIsSelectable(model.chairClosureAction) else { return false }
        switch model.chairClosureAction {
        case .ground:
            return model.chairClosureOrientationConfirmed
        case .reflect:
            return !model.chairClosureNote.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        case .complete:
            guard let completed = model.chairSession?.completedClosureActions else { return false }
            return model.chairClosureOrientationConfirmed &&
                completed.isSuperset(of: [.ground, .reflect])
        }
    }

    private func stepIsSelectable(_ action: WorkspaceChairClosureAction) -> Bool {
        guard let session = model.chairSession,
              session.phase != .completed,
              !session.completedClosureActions.contains(action) else { return false }
        if model.clinicalSafetyHold { return action == .ground }
        return session.availableClosureActions.contains(action)
    }

    private func stepStatus(_ action: WorkspaceChairClosureAction) -> String {
        if model.chairSession?.completedClosureActions.contains(action) == true {
            return "Tamamlandı"
        }
        if !stepIsSelectable(action) { return "Henüz kullanılamıyor" }
        return model.chairClosureAction == action ? "Seçili" : "Hazır"
    }

    private func stepSymbol(_ action: WorkspaceChairClosureAction) -> String {
        if model.chairSession?.completedClosureActions.contains(action) == true {
            return "checkmark.circle.fill"
        }
        return action.systemImage
    }
}

private enum ChairCompactPane: String, CaseIterable, Identifiable {
    case dialogue
    case guidance

    var id: String { rawValue }
    var title: String { self == .dialogue ? "Sandalyeler" : "Terapist gözlemi" }
    var systemImage: String { self == .dialogue ? "text.bubble" : "sparkles" }
}

private struct ChairComposerHeightPreferenceKey: PreferenceKey {
    static var defaultValue: CGFloat = 0

    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) {
        value = max(value, nextValue())
    }
}

private struct ChairChoiceButton: View {
    let chair: WorkspaceChairIdentity
    let isSelected: Bool
    let sideLabel: String
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(alignment: .top, spacing: 10) {
                Image(systemName: isSelected ? "checkmark.circle.fill" : "circle")
                    .foregroundStyle(isSelected ? DivanPalette.wine : .secondary)
                    .accessibilityHidden(true)
                VStack(alignment: .leading, spacing: 3) {
                    Text(sideLabel)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Text(chair.title)
                        .font(.headline)
                        .fixedSize(horizontal: false, vertical: true)
                    if isSelected {
                        Text("Şu an konuşan")
                            .font(.caption2.weight(.semibold))
                            .foregroundStyle(DivanPalette.wine)
                    }
                }
                Spacer(minLength: 4)
                Image(systemName: "chair.lounge")
                    .foregroundStyle(.secondary)
                    .accessibilityHidden(true)
            }
            .padding(12)
            .frame(maxWidth: .infinity, minHeight: 76, alignment: .leading)
            .background(
                isSelected ? DivanPalette.parchment.opacity(0.5) : Color(nsColor: .controlBackgroundColor),
                in: RoundedRectangle(cornerRadius: 11)
            )
            .overlay {
                RoundedRectangle(cornerRadius: 11)
                    .stroke(isSelected ? DivanPalette.wine : Color(nsColor: .separatorColor), lineWidth: isSelected ? 2 : 1)
            }
        }
        .buttonStyle(.plain)
        .accessibilityLabel("\(sideLabel), \(chair.title)")
        .accessibilityValue(isSelected ? "Seçili, şu an konuşan" : "Seçili değil")
        .accessibilityHint("Bu parçanın sandalyesine geçmek için basın")
    }
}

private struct ChairTurnBubble: View {
    let turn: WorkspaceChairTurn
    let alignmentLeading: Bool

    var body: some View {
        HStack {
            if !alignmentLeading { Spacer(minLength: 60) }
            VStack(alignment: .leading, spacing: 5) {
                Text(turn.chairTitle)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(DivanPalette.wine)
                Text(turn.content)
                    .textSelection(.enabled)
                Text(turn.createdAt.formatted(date: .omitted, time: .shortened))
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
            .padding(.horizontal, 13)
            .padding(.vertical, 10)
            .background(
                alignmentLeading ? DivanPalette.parchment.opacity(0.48) : Color(nsColor: .controlBackgroundColor),
                in: RoundedRectangle(cornerRadius: 13)
            )
            .overlay {
                RoundedRectangle(cornerRadius: 13)
                    .stroke(Color(nsColor: .separatorColor))
            }
            .frame(maxWidth: 540, alignment: .leading)
            .accessibilityElement(children: .combine)
            if alignmentLeading { Spacer(minLength: 60) }
        }
        .frame(maxWidth: .infinity)
    }
}

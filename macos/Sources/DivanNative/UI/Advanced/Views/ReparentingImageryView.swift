import SwiftUI

struct ReparentingImageryView: View {
    @ObservedObject var model: AdvancedWorkspaceViewModel
    @State private var groundSheetPresented = false
    @State private var finishSheetPresented = false
    @FocusState private var noteFocused: Bool

    var body: some View {
        Group {
            if let session = model.imagerySession {
                sessionView(session)
            } else {
                startForm
            }
        }
        .sheet(isPresented: $groundSheetPresented) {
            ImageryGroundingSheet(model: model)
        }
        .sheet(isPresented: $finishSheetPresented) {
            ImageryFinishSheet(model: model)
        }
    }

    private var startForm: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                        Text("Amaç geçmişi yeniden kurmak değil; bugün ihtiyaç duyan parçaya güvenli bir mesafeden destekleyici bir yetişkin yanıtı denemektir.")
                            .font(.callout)
                            .foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                        AdvancedSafetyBanner()

                GroupBox("Başlamadan önce") {
                    VStack(alignment: .leading, spacing: 13) {
                        Label(
                            "Gözlerinizi kapatmanız gerekmez; odada sabit bir noktaya bakabilirsiniz.",
                            systemImage: "eye"
                        )
                        Label(
                            "Ayrıntılı veya kesin bir anı bulmanız gerekmez.",
                            systemImage: "photo.on.rectangle.angled"
                        )
                        Label(
                            "Yoğunluk yükselirse mesafeyi artırmak, şimdiye dönmek veya bitirmek güvenli bir seçimdir.",
                            systemImage: "arrow.uturn.backward.circle"
                        )
                    }
                    .font(.callout)
                    .frame(maxWidth: .infinity, alignment: .leading)
                }

                GroupBox("Niyet ve yoğunluk") {
                    VStack(alignment: .leading, spacing: 14) {
                        TextField(
                            "Bugün hangi ihtiyaca nazikçe yaklaşmak istiyorsunuz?",
                            text: $model.imageryIntention,
                            axis: .vertical
                        )
                        .lineLimit(2...4)
                        .accessibilityHint("Bir anıyı kanıtlamak yerine bugünkü ihtiyacınızı tarif edin")

                        AdvancedIntensityControl(
                            title: "Şu anki yoğunluk",
                            value: $model.imageryIntensity,
                            maximum: model.imageryStartIntensityMaximum
                        )

                        TextField("Durma işaretiniz", text: $model.imageryStopSignal)
                            .accessibilityHint("Bu sözü yazdığınız anda imgeleme ilerlemeden durmalıdır")
                        TextField(
                            "Sahne sınırınız",
                            text: $model.imagerySceneBoundary,
                            axis: .vertical
                        )
                        .lineLimit(2...4)
                        .accessibilityHint("Örneğin, sahneyi uzaktan ve odanın farkında kalarak izleyeceğim")
                    }
                    .padding(.top, 6)
                }

                GroupBox(
                    model.imageryRequiresPrecheck
                        ? "Başlangıç ve güvenlik onayları"
                        : "Üç ayrı başlangıç onayı"
                ) {
                    VStack(alignment: .leading, spacing: 12) {
                        consentToggle(
                            "Yönelimim açık",
                            detail: "Şu an nerede olduğumu ve bu çalışmayı ekranda yaptığımı biliyorum.",
                            binding: $model.imageryOrientationConfirmed
                        )
                        consentToggle(
                            "Çerçeveyi kabul ediyorum",
                            detail: "Durma işaretimi kullanabilir, sahne sınırımı değiştirebilir ve istediğim anda çıkabilirim.",
                            binding: $model.imageryFrameConfirmed
                        )
                        consentToggle(
                            "Gerçeklik ayrımı açık",
                            detail: "İmge ve çağrışımların tarihsel bir olayın kanıtı olmadığını biliyorum.",
                            binding: $model.imageryRealityConfirmed
                        )
                        if model.imageryRequiresPrecheck {
                            Divider()
                            consentToggle(
                                "Uyku ve aşırı etkinleşme açısından netim",
                                detail: "Bugün belirgin uykusuzluk, taşkınlık veya gerçeklik ayrımını zorlaştıran bir etkinleşme yaşamıyorum.",
                                binding: $model.imagerySleepActivationClear
                            )
                            VStack(alignment: .leading, spacing: 7) {
                                Text("Gerekirse ulaşabileceğiniz destek var mı?")
                                    .font(.callout.weight(.semibold))
                                Picker(
                                    "Destek erişimi",
                                    selection: $model.imagerySupportAvailable
                                ) {
                                    Text("Var").tag(Optional(true))
                                    Text("Şu an yok").tag(Optional(false))
                                }
                                .labelsHidden()
                                .pickerStyle(.segmented)
                                .accessibilityIdentifier("imagerySupportAvailability")
                            }
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }

            }
            .padding(22)
            .frame(maxWidth: 780)
            .frame(maxWidth: .infinity)
        }
        .safeAreaInset(edge: .top, spacing: 0) {
            VStack(spacing: 0) {
                AdvancedSectionHeader(
                    title: "Güvenli imgeleme ve sınırlı yeniden ebeveynlik",
                    detail: "Amaç geçmişi yeniden kurmak değil; bugün ihtiyaç duyan parçaya güvenli bir mesafeden destekleyici bir yetişkin yanıtı denemektir.",
                    systemImage: "figure.and.child.holdinghands",
                    showsDetail: false
                )
                .accessibilityIdentifier("imageryStartHeading")
                .padding(.horizontal, 16)
                .padding(.vertical, 10)
                .background(.bar)
                Divider()
                imageryStartActionBar
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .accessibilityIdentifier("imageryStartSurface")
    }

    private var imageryStartActionBar: some View {
        VStack(alignment: .leading, spacing: 8) {
            imageryStartIssueLabel
            imageryStartButton
                .frame(maxWidth: .infinity, alignment: .trailing)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 10)
        .background(.bar)
        .overlay(alignment: .top) { Divider() }
    }

    @ViewBuilder
    private var imageryStartIssueLabel: some View {
        if let issue = imageryStartIssue {
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

    private var imageryStartButton: some View {
        Button("Onayla ve ilk adıma geç") {
            Task { await model.startImagery() }
        }
        .buttonStyle(.borderedProminent)
        .controlSize(.large)
        .tint(DivanPalette.wine)
        .disabled(model.isPerformingAction || model.clinicalSafetyHold)
        .accessibilityLabel("Onayla ve ilk adıma geç")
        .accessibilityIdentifier("imageryStartAction")
    }

    private func sessionView(_ session: WorkspaceImagerySession) -> some View {
        GeometryReader { geometry in
            VStack(spacing: 0) {
                sessionHeader(session, compactHeight: geometry.size.height < 470)
                Divider()
                ScrollView {
                    VStack(alignment: .leading, spacing: 18) {
                        stageProgress(session)
                        if session.phase == .completed {
                            completedState(session)
                        } else if session.phase == .paused {
                            pausedState(session)
                        } else {
                            checkpointCard(session)
                        }
                        if !session.entries.isEmpty {
                            previousEntries(session)
                        }
                    }
                    .padding(geometry.size.width < 560 ? 12 : 22)
                    .frame(maxWidth: 820)
                    .frame(maxWidth: .infinity)
                }
            }
        }
    }

    private func sessionHeader(
        _ session: WorkspaceImagerySession,
        compactHeight: Bool
    ) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            ViewThatFits(in: .horizontal) {
                HStack(alignment: .top) {
                    imagerySessionIdentity(session, compact: compactHeight)
                    Spacer()
                    AdvancedPhaseBadge(phase: session.phase)
                }
                VStack(alignment: .leading, spacing: 8) {
                    imagerySessionIdentity(session, compact: compactHeight)
                    AdvancedPhaseBadge(phase: session.phase)
                }
            }
            if session.phase != .completed {
                if compactHeight {
                    compactImagerySessionActions(session)
                } else {
                    ViewThatFits(in: .horizontal) {
                        HStack(spacing: 10) {
                            imagerySessionActions(session)
                        }
                        VStack(alignment: .leading, spacing: 8) {
                            imagerySessionActions(session)
                        }
                    }
                }
            }
            if compactHeight {
                Label(
                    "Sınırı siz belirlersiniz; istediğiniz anda imgelemeyi kapatabilirsiniz.",
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

    private func imagerySessionIdentity(
        _ session: WorkspaceImagerySession,
        compact: Bool
    ) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text("İmgeleme çalışması")
                .font(.title3.weight(.semibold))
            if !compact {
                Text("\(session.currentStageIndex + 1). adım: \(currentStageLabel(session))")
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }
            Label("Durma işareti: \(session.stopSignal)", systemImage: "hand.raised.fill")
                .font(.caption.weight(.semibold))
                .foregroundStyle(DivanPalette.wine)
        }
    }

    @ViewBuilder
    private func imagerySessionActions(_ session: WorkspaceImagerySession) -> some View {
        Button {
            model.imageryGroundOrientationConfirmed = false
            groundSheetPresented = true
        } label: {
            Label("Şimdiye dön", systemImage: "scope")
        }
        .disabled(model.isPerformingAction)
        Button {
            model.imageryFinishGroundingConfirmed = false
            model.imageryFinishOrientationConfirmed = false
            model.imageryFinishRealityConfirmed = false
            finishSheetPresented = true
        } label: {
            Label("Güvenli bitir", systemImage: "checkmark.seal")
        }
        .disabled(model.isPerformingAction || model.clinicalSafetyHold)
        imageryStopButton(session)
    }

    private func compactImagerySessionActions(
        _ session: WorkspaceImagerySession
    ) -> some View {
        HStack(spacing: 10) {
            Menu {
                Button("Şimdiye dön") {
                    model.imageryGroundOrientationConfirmed = false
                    groundSheetPresented = true
                }
                .disabled(model.isPerformingAction)
                Button("Güvenli bitir") {
                    model.imageryFinishGroundingConfirmed = false
                    model.imageryFinishOrientationConfirmed = false
                    model.imageryFinishRealityConfirmed = false
                    finishSheetPresented = true
                }
                .disabled(model.isPerformingAction || model.clinicalSafetyHold)
            } label: {
                Label("Çalışma adımları", systemImage: "ellipsis.circle")
            }
            Spacer(minLength: 8)
            imageryStopButton(session)
        }
    }

    private func imageryStopButton(
        _ session: WorkspaceImagerySession
    ) -> some View {
        Button(role: .destructive) {
            Task { await model.stopImagery() }
        } label: {
            Label(
                session.phase == .active
                    ? "Durma işaretini uygula · kapat"
                    : "İmgelemeyi kapat",
                systemImage: "stop.fill"
            )
        }
        .disabled(model.isImageryStopInFlight)
        .help("Onay beklemeden ilerlemeyi keser; güvenli tamamlamayı yapılmış saymaz")
        .accessibilityLabel(
            session.phase == .active
                ? "Durma işareti \(session.stopSignal). İmgelemeyi kapat"
                : "İmgelemeyi kapat"
        )
        .accessibilityHint("Terminal eylemdir; başka bir işlem sürerken ve güvenlik bekletmesinde de kullanılabilir")
    }

    private func stageProgress(_ session: WorkspaceImagerySession) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Adımlar")
                .font(.headline)
            ScrollView(.horizontal) {
                HStack(spacing: 5) {
                    ForEach(Array(session.stages.enumerated()), id: \.element.id) { index, stage in
                        VStack(spacing: 5) {
                            Image(systemName: stageSymbol(index: index, currentIndex: session.currentStageIndex))
                                .foregroundStyle(stageColor(index: index, currentIndex: session.currentStageIndex))
                                .accessibilityHidden(true)
                            Text(stage.label)
                                .font(.caption2)
                                .lineLimit(2)
                                .multilineTextAlignment(.center)
                                .foregroundStyle(
                                    index == session.currentStageIndex ? .primary : .secondary
                                )
                        }
                        .frame(width: 112)
                        .frame(minHeight: 48)
                        .accessibilityElement(children: .combine)
                        .accessibilityLabel(stageAccessibilityLabel(index: index, label: stage.label))
                        .accessibilityValue(stageAccessibilityValue(index: index, currentIndex: session.currentStageIndex))
                    }
                }
            }
        }
        .advancedCard()
    }

    private func checkpointCard(_ session: WorkspaceImagerySession) -> some View {
        VStack(alignment: .leading, spacing: 16) {
            VStack(alignment: .leading, spacing: 6) {
                Label("Seçim noktası", systemImage: "signpost.right")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(DivanPalette.wine)
                Text(session.checkpoint.title)
                    .font(.title3.weight(.semibold))
                Text(session.checkpoint.prompt)
                    .font(.body)
                    .fixedSize(horizontal: false, vertical: true)
                    .textSelection(.enabled)
                Label(session.checkpoint.safetyNote, systemImage: "lifepreserver")
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .padding(.top, 3)
            }
            .accessibilityElement(children: .combine)

            AdvancedIntensityControl(
                title: "Şu anki yoğunluk",
                value: $model.imageryIntensity,
                maximum: session.intensityLimit,
                disabled: model.isPerformingAction
            )

            VStack(alignment: .leading, spacing: 7) {
                Text("Bu noktada neye ihtiyacınız var?")
                    .font(.callout.weight(.semibold))
                Picker("Sonraki seçim", selection: $model.imageryChoiceID) {
                    ForEach(session.checkpoint.choices) { choice in
                        Text(choice.title).tag(choice.id)
                    }
                }
                .pickerStyle(.radioGroup)
                .labelsHidden()
                .accessibilityLabel("Sonraki seçim")
            }

            TextField(
                "İsterseniz şu anda fark ettiğiniz ihtiyacı yazın",
                text: $model.imageryNote,
                axis: .vertical
            )
            .lineLimit(2...5)
            .focused($noteFocused)
            .accessibilityLabel("Bu adıma ilişkin isteğe bağlı notunuz")

            Toggle(isOn: $model.imageryCheckpointConfirmed) {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Bu adımı bilinçli olarak seçiyorum")
                        .font(.callout.weight(.semibold))
                    Text("Bu onay yalnız bu seçim noktası içindir; sonraki adımda yeniden sorulur.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            .toggleStyle(.checkbox)

            VStack(alignment: .leading, spacing: 10) {
                Text("Bu adım için yeniden doğrulayın")
                    .font(.callout.weight(.semibold))
                Toggle(
                    "Şu anda bulunduğum odayı ve ekran başında olduğumu fark ediyorum",
                    isOn: $model.imageryCheckpointOrientationConfirmed
                )
                Toggle(
                    "İmge ve çağrışımların tarihsel kanıt olmadığını biliyorum",
                    isOn: $model.imageryCheckpointRealityConfirmed
                )
            }
            .toggleStyle(.checkbox)
            .padding(10)
            .background(.quaternary, in: RoundedRectangle(cornerRadius: 9))

            ViewThatFits(in: .horizontal) {
                HStack {
                    checkpointGroundButton
                    Spacer()
                    checkpointSubmitButton(session)
                }
                VStack(alignment: .leading, spacing: 9) {
                    checkpointSubmitButton(session)
                    checkpointGroundButton
                }
            }
        }
        .advancedCard()
    }

    private var checkpointGroundButton: some View {
        Button("Şimdiye dön") {
            model.imageryGroundOrientationConfirmed = false
            groundSheetPresented = true
        }
        .disabled(model.isPerformingAction)
        .help("İlerlemek yerine çevreye ve bedene yönel")
    }

    private func checkpointSubmitButton(_ session: WorkspaceImagerySession) -> some View {
        Button {
            Task { await model.submitImageryCheckpoint() }
        } label: {
            Label(model.selectedImageryChoice?.title ?? "Seçimi uygula", systemImage: "arrow.right.circle.fill")
        }
        .buttonStyle(.borderedProminent)
        .tint(DivanPalette.wine)
        .disabled(
            model.isPerformingAction ||
            model.clinicalSafetyHold ||
            !model.imageryCheckpointOrientationConfirmed ||
            !model.imageryCheckpointRealityConfirmed ||
            !model.imageryCheckpointConfirmed
        )
    }

    private func pausedState(_ session: WorkspaceImagerySession) -> some View {
        VStack(alignment: .leading, spacing: 13) {
            Image(systemName: "pause.circle")
                .font(.system(size: 34, weight: .light))
                .foregroundStyle(.orange)
                .accessibilityHidden(true)
            Text("Çalışma duraklatıldı")
                .font(.title3.weight(.semibold))
            Text("Hazır olduğunuzda aynı seçim noktasına dönebilir ya da çalışmayı bitirebilirsiniz.")
                .foregroundStyle(.secondary)

            AdvancedIntensityControl(
                title: "Şu anki yoğunluk",
                value: $model.imageryIntensity,
                maximum: session.intensityLimit,
                disabled: model.isPerformingAction
            )

            Toggle(
                "Bulunduğum odayı ve ekran başında olduğumu yeniden fark ettim",
                isOn: $model.imageryResumeOrientationConfirmed
            )
            .toggleStyle(.checkbox)

            if WorkspaceSafety.intensityBlocksResume(
                intensity: model.imageryIntensity,
                limit: session.intensityLimit
            ) {
                Label(
                    "Yoğunluk 8 veya üzerindeyken imgelemeye dönülmez. Şimdiye dönün veya çalışmayı durdurun.",
                    systemImage: "exclamationmark.shield"
                )
                .font(.callout)
                .foregroundStyle(.orange)
            }

            ViewThatFits(in: .horizontal) {
                HStack {
                    pausedGroundButton
                    pausedStopButton
                    Spacer()
                    pausedResumeButton(session)
                }
                VStack(alignment: .leading, spacing: 9) {
                    pausedResumeButton(session)
                    HStack {
                        pausedGroundButton
                        pausedStopButton
                    }
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .advancedCard()
    }

    private var pausedGroundButton: some View {
        Button("Şimdiye dön") {
            model.imageryGroundOrientationConfirmed = false
            groundSheetPresented = true
        }
    }

    private var pausedStopButton: some View {
        Button("İmgelemeyi kapat", role: .destructive) {
            Task { await model.stopImagery() }
        }
        .disabled(model.isImageryStopInFlight)
        .accessibilityHint(DivanStrings.alwaysAvailableActionHint)
    }

    private func pausedResumeButton(_ session: WorkspaceImagerySession) -> some View {
        Button("Aynı adımdan sürdür") {
            Task { await model.resumeImagery() }
        }
        .buttonStyle(.borderedProminent)
        .tint(DivanPalette.wine)
        .disabled(
            model.isPerformingAction ||
            model.clinicalSafetyHold ||
            !model.imageryResumeOrientationConfirmed ||
            WorkspaceSafety.intensityBlocksResume(
                intensity: model.imageryIntensity,
                limit: session.intensityLimit)
        )
    }

    private func completedState(_ session: WorkspaceImagerySession) -> some View {
        VStack(alignment: .leading, spacing: 9) {
            Label("Çalışma kapatıldı", systemImage: "checkmark.circle.fill")
                .font(.title3.weight(.semibold))
                .foregroundStyle(.green)
            Text("Kayıt salt okunur. Birkaç dakika su içmek, çevrenizi fark etmek ve yoğunluk sürüyorsa gerçek bir destek kişisine ulaşmak iyi gelebilir.")
                .foregroundStyle(.secondary)
            Text("Son yoğunluk: 10 üzerinden \(session.intensity)")
                .font(.callout.monospacedDigit())
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .advancedCard()
        .accessibilityElement(children: .combine)
    }

    private func previousEntries(_ session: WorkspaceImagerySession) -> some View {
        DisclosureGroup("Bu çalışmadaki notlar (\(session.entries.count))") {
            LazyVStack(alignment: .leading, spacing: 9) {
                ForEach(session.entries) { entry in
                    VStack(alignment: .leading, spacing: 4) {
                        Text(entry.stageLabel)
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(DivanPalette.wine)
                        Text(entry.content)
                            .textSelection(.enabled)
                        Text(entry.createdAt.formatted(date: .omitted, time: .shortened))
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                    }
                    .padding(.vertical, 6)
                }
            }
            .padding(.top, 8)
        }
        .advancedCard()
    }

    private func stageSymbol(index: Int, currentIndex: Int) -> String {
        if index < currentIndex { return "checkmark.circle.fill" }
        if index == currentIndex { return "circle.inset.filled" }
        return "circle"
    }

    private func stageColor(index: Int, currentIndex: Int) -> Color {
        index <= currentIndex ? DivanPalette.wine : .secondary
    }

    private func stageAccessibilityValue(index: Int, currentIndex: Int) -> String {
        if index < currentIndex { return "Tamamlandı" }
        if index == currentIndex { return "Şimdiki adım" }
        return "Henüz başlamadı"
    }

    private func stageAccessibilityLabel(index: Int, label: String) -> String {
        "\(index + 1). adım, \(label)"
    }

    private func currentStageLabel(_ session: WorkspaceImagerySession) -> String {
        session.stages.first(where: { $0.id == session.currentStageID })?.label ?? session.checkpoint.title
    }

    private var imageryStartIssue: String? {
        if model.clinicalSafetyHold {
            return "Güvenlik bekletmesi sürerken yeni çalışma başlatılmaz; seansa dönün veya şimdiye dönme desteğini kullanın."
        }
        if model.isPerformingAction {
            return model.operationDescription.isEmpty
                ? "Süren işlem tamamlandığında yeniden deneyin."
                : model.operationDescription
        }
        if !model.imageryConsentComplete {
            return model.imageryRequiresPrecheck
                ? "Başlangıç onaylarını ve yaşantısal güvenlik kontrolünü ayrı ayrı tamamlayın."
                : "Üç başlangıç onayını ayrı ayrı işaretleyin."
        }
        if model.imageryIntention.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return "Yaklaşmak istediğiniz ihtiyacı kısa bir cümleyle yazın."
        }
        if model.imageryStopSignal.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return "Kişisel bir durma işareti yazın."
        }
        if model.imagerySceneBoundary.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return "Sahnenin güvenli sınırını yazın."
        }
        return nil
    }

    private func consentToggle(
        _ title: String,
        detail: String,
        binding: Binding<Bool>
    ) -> some View {
        Toggle(isOn: binding) {
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(.callout.weight(.semibold))
                Text(detail)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .toggleStyle(.checkbox)
    }
}

private struct ImageryGroundingSheet: View {
    @ObservedObject var model: AdvancedWorkspaceViewModel
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(spacing: 0) {
            ViewThatFits(in: .horizontal) {
                HStack {
                    groundingTitle
                    Spacer()
                    groundingDismissButton
                }
                VStack(alignment: .leading, spacing: 9) {
                    groundingTitle
                    groundingDismissButton
                }
            }
            .padding(18)
            Divider()

            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    GroupBox("Kısa yönelim") {
                        VStack(alignment: .leading, spacing: 9) {
                            Label("Ayaklarınızın zemine temasını fark edin.", systemImage: "figure.stand")
                            Label("Odada gördüğünüz üç nesneyi sessizce adlandırın.", systemImage: "eye")
                            Label("Bugünün tarihini ve bulunduğunuz yeri hatırlayın.", systemImage: "calendar")
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }

                    AdvancedIntensityControl(
                        title: "Şu anki yoğunluk",
                        value: $model.imageryIntensity,
                        maximum: model.imagerySession?.intensityLimit ?? model.clinicalIntensityLimit,
                        disabled: model.isPerformingAction
                    )

                    Toggle(
                        "Bulunduğum odayı, zemini ve ekran başında olduğumu yeniden fark ettim",
                        isOn: $model.imageryGroundOrientationConfirmed
                    )
                    .toggleStyle(.checkbox)

                    Text("Bu onay yalnız şimdiye dönme eylemi içindir; sonraki bir adıma otomatik izin vermez.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                .padding(20)
            }
            Divider()
            ViewThatFits(in: .horizontal) {
                HStack {
                    groundingStopButton
                    groundingCancelButton
                    Spacer()
                    groundingSubmitButton
                }
                VStack(alignment: .leading, spacing: 9) {
                    groundingSubmitButton
                    HStack {
                        groundingStopButton
                        groundingCancelButton
                    }
                }
            }
            .padding(16)
            .background(.bar)
        }
        .frame(idealWidth: 560, idealHeight: 480)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .onDisappear { model.imageryGroundOrientationConfirmed = false }
    }

    private var groundingTitle: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text("Şimdiye dön")
                .font(.title2.weight(.semibold))
            Text("İmgeyi ilerletmeden bulunduğunuz ortama yeniden yönelin.")
                .foregroundStyle(.secondary)
        }
    }

    private var groundingDismissButton: some View {
        Button("Kapat") { dismiss() }
            .keyboardShortcut(.cancelAction)
    }

    private var groundingStopButton: some View {
        Button("İmgelemeyi kapat", role: .destructive) {
            Task {
                await model.stopImagery()
                if model.failure == nil { dismiss() }
            }
        }
        .disabled(model.isImageryStopInFlight)
        .accessibilityHint(DivanStrings.alwaysAvailableActionHint)
    }

    private var groundingCancelButton: some View {
        Button("Vazgeç") { dismiss() }
    }

    private var groundingSubmitButton: some View {
        Button {
            Task {
                await model.groundImagery()
                if model.failure == nil { dismiss() }
            }
        } label: {
            Label("Onayla ve şimdiye dön", systemImage: "scope")
        }
        .buttonStyle(.borderedProminent)
        .tint(DivanPalette.wine)
        .disabled(
            model.isPerformingAction ||
            !model.imageryGroundOrientationConfirmed
        )
    }
}

private struct ImageryFinishSheet: View {
    @ObservedObject var model: AdvancedWorkspaceViewModel
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(spacing: 0) {
            ViewThatFits(in: .horizontal) {
                HStack {
                    finishTitle
                    Spacer()
                    finishDismissButton
                }
                VStack(alignment: .leading, spacing: 9) {
                    finishTitle
                    finishDismissButton
                }
            }
            .padding(18)
            Divider()

            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    AdvancedIntensityControl(
                        title: "Tamamlama anındaki yoğunluk",
                        value: $model.imageryIntensity,
                        maximum: model.imagerySession?.intensityLimit ?? model.clinicalIntensityLimit,
                        disabled: model.isPerformingAction
                    )

                    VStack(alignment: .leading, spacing: 12) {
                        finishToggle(
                            "Topraklanma yaptım",
                            detail: "Ayaklarımı, zemini ve odadaki nesneleri yeniden fark ettim.",
                            binding: $model.imageryFinishGroundingConfirmed
                        )
                        finishToggle(
                            "Yönelimim açık",
                            detail: "Bugünü, bulunduğum yeri ve ekran başında olduğumu biliyorum.",
                            binding: $model.imageryFinishOrientationConfirmed
                        )
                        finishToggle(
                            "Gerçeklik ayrımı açık",
                            detail: "İmge ve çağrışımların tarihsel kanıt olmadığını biliyorum.",
                            binding: $model.imageryFinishRealityConfirmed
                        )
                    }
                    .padding(12)
                    .background(.quaternary, in: RoundedRectangle(cornerRadius: 10))

                    if model.imageryIntensityBlocksResume {
                        Label(
                            "Yoğunluk 8 veya üzerindeyken güvenli tamamlama yapılmaz. Şimdiye dönün veya tamamlanmış saymadan durdurun.",
                            systemImage: "exclamationmark.shield"
                        )
                        .font(.callout)
                        .foregroundStyle(.orange)
                    }

                    Text("Bu onayları vermek istemiyorsanız çıkışınız engellenmez; çalışma tamamlanmış sayılmadan “İmgelemeyi kapat” ile kapanabilir.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                .padding(20)
            }

            Divider()
            ViewThatFits(in: .horizontal) {
                HStack {
                    finishStopButton
                    Spacer()
                    finishSubmitButton
                }
                VStack(alignment: .leading, spacing: 9) {
                    finishSubmitButton
                    finishStopButton
                }
            }
            .padding(16)
            .background(.bar)
        }
        .frame(idealWidth: 600, idealHeight: 520)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .onDisappear {
            model.imageryFinishGroundingConfirmed = false
            model.imageryFinishOrientationConfirmed = false
            model.imageryFinishRealityConfirmed = false
        }
    }

    private var finishTitle: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text("İmgelemeyi güvenli tamamla")
                .font(.title2.weight(.semibold))
            Text("Üç onay birbirinin yerine geçmez ve her biri sizin tarafınızdan verilmelidir.")
                .foregroundStyle(.secondary)
        }
    }

    private var finishDismissButton: some View {
        Button("Kapat") { dismiss() }
            .keyboardShortcut(.cancelAction)
    }

    private var finishStopButton: some View {
        Button("İmgelemeyi kapat", role: .destructive) {
            Task {
                await model.stopImagery()
                if model.failure == nil { dismiss() }
            }
        }
        .disabled(model.isImageryStopInFlight)
        .accessibilityHint(DivanStrings.alwaysAvailableActionHint)
    }

    private var finishSubmitButton: some View {
        Button {
            Task {
                await model.finishImagery()
                if model.failure == nil { dismiss() }
            }
        } label: {
            Label("Üç onayla tamamla", systemImage: "checkmark.seal.fill")
        }
        .buttonStyle(.borderedProminent)
        .tint(DivanPalette.wine)
        .disabled(
            !finishConfirmationsComplete ||
            model.imageryIntensityBlocksResume ||
            model.isPerformingAction
        )
    }

    private var finishConfirmationsComplete: Bool {
        model.imageryFinishGroundingConfirmed &&
            model.imageryFinishOrientationConfirmed &&
            model.imageryFinishRealityConfirmed
    }

    private func finishToggle(
        _ title: String,
        detail: String,
        binding: Binding<Bool>
    ) -> some View {
        Toggle(isOn: binding) {
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(.callout.weight(.semibold))
                Text(detail)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .toggleStyle(.checkbox)
    }
}

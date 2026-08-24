import SwiftUI

public struct StructuredTherapyWorkspaceView: View {
    private let dataSource: any StructuredTherapyDataSource
    private let conversationID: Int
    private let module: AdvancedModule

    public init(
        dataSource: any StructuredTherapyDataSource,
        conversationID: Int,
        module: AdvancedModule
    ) {
        self.dataSource = dataSource
        self.conversationID = conversationID
        self.module = module
    }

    public var body: some View {
        switch module {
        case .adhdSupport:
            ADHDWorkspaceView(dataSource: dataSource, conversationID: conversationID)
        case .schemaPath:
            EmptyView()
        case .freudImagery:
            FreudImageryWorkspaceView(dataSource: dataSource, conversationID: conversationID)
        default:
            EmptyView()
        }
    }
}

struct StructuredWorkspaceCard<Content: View>: View {
    let content: Content

    init(@ViewBuilder content: () -> Content) {
        self.content = content()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) { content }
            .padding(14)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(
                Color(nsColor: .controlBackgroundColor),
                in: RoundedRectangle(cornerRadius: 13, style: .continuous)
            )
            .overlay {
                RoundedRectangle(cornerRadius: 13, style: .continuous)
                    .stroke(Color(nsColor: .separatorColor).opacity(0.65))
            }
    }
}

struct StructuredWorkspaceFailureBanner: View {
    let failure: StructuredWorkspaceFailure
    let dismiss: () -> Void

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: "exclamationmark.circle.fill")
                .foregroundStyle(.orange)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 2) {
                Text(failure.title).font(.callout.weight(.semibold))
                Text(failure.message)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 8)
            Button("Kapat", action: dismiss)
                .buttonStyle(.plain)
        }
        .padding(12)
        .background(Color.orange.opacity(0.10))
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("structured.failure")
    }
}

public struct ADHDWorkspaceView: View {
    private enum Tab: String, CaseIterable, Identifiable {
        case today, routines, notebook, tus
        var id: Self { self }
        var title: String {
            switch self {
            case .today: "Bugün"
            case .routines: "Ritimler"
            case .notebook: "Defter"
            case .tus: "TUS Çalışma"
            }
        }
    }

    @StateObject private var model: ADHDWorkspaceViewModel
    @State private var selectedTab: Tab = .today
    @State private var habitFormExpanded = false
    @State private var journalFormExpanded = true
    @State private var journalToDelete: ADHDJournalEntry?

    public init(
        dataSource: any StructuredTherapyDataSource,
        conversationID: Int
    ) {
        _model = StateObject(wrappedValue: ADHDWorkspaceViewModel(
            dataSource: dataSource,
            conversationID: conversationID
        ))
    }

    public init(model: ADHDWorkspaceViewModel) {
        _model = StateObject(wrappedValue: model)
    }

    public var body: some View {
        GeometryReader { geometry in
            VStack(spacing: 0) {
                header
                Divider()
                if let failure = model.failure {
                    StructuredWorkspaceFailureBanner(
                        failure: failure,
                        dismiss: model.dismissFailure
                    )
                }
                if !model.safetyMessage.isEmpty {
                    safetyBanner
                }
                ScrollView {
                    VStack(alignment: .leading, spacing: 14) {
                        if let notice = model.snapshot?.notices.notDiagnostic {
                            Label(notice, systemImage: "info.circle")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                        switch selectedTab {
                        case .today: todayView
                        case .routines: routinesView
                        case .notebook: notebookView
                        case .tus: tusView
                        }
                    }
                    .frame(maxWidth: 900, alignment: .leading)
                    .padding(16)
                    .frame(maxWidth: .infinity, alignment: .top)
                }
                .scrollIndicators(.automatic)
                statusBar
            }
            .frame(width: geometry.size.width, height: geometry.size.height)
            .clipped()
        }
        .task { await model.loadIfNeeded() }
        .task(id: selectedTab) {
            if selectedTab == .tus { await model.loadTUSIfNeeded() }
        }
        .alert(item: $journalToDelete) { entry in
            Alert(
                title: Text("Defter yazısı silinsin mi?"),
                message: Text("Bu işlem yalnız seçili yazıyı siler."),
                primaryButton: .cancel(Text("Vazgeç")),
                secondaryButton: .destructive(Text("Sil")) {
                    Task { await model.deleteJournal(entry) }
                }
            )
        }
        .accessibilityIdentifier("adhd.workspace")
    }

    private var header: some View {
        ViewThatFits(in: .horizontal) {
            HStack(spacing: 12) {
                title
                Spacer(minLength: 8)
                tabPicker
                refreshButton
            }
            VStack(alignment: .leading, spacing: 8) {
                HStack { title; Spacer(); refreshButton }
                tabPicker.frame(maxWidth: .infinity)
            }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
        .background(.bar)
    }

    private var title: some View {
        Label {
            VStack(alignment: .leading, spacing: 1) {
                Text("Ritimler ve defter").font(.headline)
                Text("Seri değil, küçük ve ayarlanabilir denemeler")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        } icon: {
            Image(systemName: "checklist")
                .foregroundStyle(DivanPalette.wine)
        }
        .accessibilityElement(children: .combine)
    }

    private var tabPicker: some View {
        Picker("ADHD çalışma bölümü", selection: $selectedTab) {
            ForEach(Tab.allCases) { Text($0.title).tag($0) }
        }
        .pickerStyle(.segmented)
        .labelsHidden()
        .frame(maxWidth: 360)
        .accessibilityIdentifier("adhd.tabs")
    }

    private var refreshButton: some View {
        Button {
            Task {
                if selectedTab == .tus {
                    await model.reloadTUS()
                } else {
                    await model.reload()
                }
            }
        } label: {
            Image(systemName: "arrow.clockwise")
        }
        .buttonStyle(.plain)
        .disabled(selectedTab == .tus ? model.tusIsBusy : model.isBusy)
        .help(selectedTab == .tus ? "TUS çalışma planını yenile" : "Ritimleri ve defteri yenile")
        .accessibilityLabel(
            selectedTab == .tus ? "TUS çalışma planını yenile" : "Ritimleri ve defteri yenile"
        )
    }

    private var safetyBanner: some View {
        VStack(alignment: .leading, spacing: 6) {
            Label("Şimdi gerçek destek öncelikli", systemImage: "cross.circle.fill")
                .font(.callout.weight(.semibold))
            Text(model.safetyMessage)
                .font(.caption)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.red.opacity(0.10))
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("adhd.safety")
    }

    @ViewBuilder
    private var tusView: some View {
        if let tus = model.tusSnapshot, tus.contractIsSupported {
            StructuredWorkspaceCard {
                HStack(alignment: .top, spacing: 12) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("TUS çalışma koçu")
                            .font(.title3.weight(.semibold))
                        Text("Ders, konu, kaynak ve adet bilgileriyle tek küçük adıma odaklanır.")
                            .font(.callout)
                            .foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    Spacer(minLength: 8)
                    Toggle("TUS modu", isOn: Binding(
                        get: { tus.enabled },
                        set: { enabled in
                            Task { await model.setTUSMode(enabled) }
                        }
                    ))
                    .toggleStyle(.switch)
                    .disabled(
                        model.tusIsBusy
                            || (!tus.enabled
                                && (tus.safetyHold || !tus.catalog.available))
                    )
                    .accessibilityIdentifier("adhd.tus.mode")
                }
                if let boundary = tus.notices.contentBoundary {
                    Text(boundary)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Label(
                    "\(tus.catalog.lessons) ders · \(tus.catalog.readingAreas) okuma alanı · \(tus.catalog.questionAreas) soru alanı",
                    systemImage: "books.vertical"
                )
                .font(.caption)
                .foregroundStyle(.secondary)
                if let questionCount = tus.catalog.questionCount,
                   let sentenceCount = tus.catalog.sentenceCount {
                    Text("\(questionCount) soru · \(sentenceCount) cümle")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }

            if tus.safetyHold {
                StructuredWorkspaceCard {
                    Label("Çalışma planı güvenlik nedeniyle duraklatıldı.", systemImage: "pause.circle.fill")
                        .foregroundStyle(.red)
                }
            } else if !tus.enabled {
                StructuredWorkspaceCard {
                    Text("TUS modu kapalı")
                        .font(.headline)
                    Text("Açtığınızda koç size her seferinde yalnız bir kısa soru sorar.")
                        .foregroundStyle(.secondary)
                }
            } else if !tus.catalog.available || tus.catalogChanged == true {
                StructuredWorkspaceCard {
                    Label(
                        tus.catalogChanged == true
                            ? "TUS konu kataloğu değişti"
                            : "TUS konu kataloğu kullanılamıyor",
                        systemImage: "exclamationmark.triangle"
                    )
                    .font(.headline)
                    Text(
                        tus.catalogChanged == true
                            ? "Yeni katalogla seçimleri yeniden başlatın. Önceki yanıtlar soru veya cümle metni içermez."
                            : "Paketlenmiş katalog yeniden kullanılabilir olduğunda planı hazırlayın. Soru veya cümle metni yüklenmez."
                    )
                        .font(.callout)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                    if tus.allowedActions.contains("restart") {
                        Button("Planı yeniden hazırla") {
                            Task { await model.restartTUS() }
                        }
                        .buttonStyle(.borderedProminent)
                    }
                }
            } else {
                tusHistory(tus.history)
                if let question = tus.question {
                    tusQuestion(question)
                }
                if let plan = tus.plan {
                    tusPlan(plan, allowedActions: Set(tus.allowedActions))
                }
            }

            if let noStreak = tus.notices.noStreak,
               let noDebt = tus.notices.noDebt {
                Text("\(noStreak) \(noDebt)")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        } else if model.tusIsBusy {
            loadingCard("TUS çalışma alanı yükleniyor…")
        } else {
            StructuredWorkspaceCard {
                Text("TUS çalışma alanı yüklenemedi.")
                    .font(.headline)
                Button("Yeniden dene") { Task { await model.reloadTUS() } }
                    .buttonStyle(.bordered)
            }
        }
    }

    @ViewBuilder
    private func tusHistory(_ history: [ADHDTUSAnswer]) -> some View {
        if !history.isEmpty {
            VStack(alignment: .leading, spacing: 8) {
                ForEach(history) { item in
                    VStack(alignment: .leading, spacing: 5) {
                        Text(item.question)
                            .font(.callout)
                        Text(item.answer)
                            .font(.callout.weight(.semibold))
                            .padding(.horizontal, 10)
                            .padding(.vertical, 7)
                            .background(DivanPalette.wine.opacity(0.10))
                            .clipShape(RoundedRectangle(cornerRadius: 10))
                    }
                    .accessibilityElement(children: .combine)
                }
            }
            .accessibilityIdentifier("adhd.tus.history")
        }
    }

    private func tusQuestion(_ question: ADHDTUSQuestion) -> some View {
        StructuredWorkspaceCard {
            Label("ADHD Koçu", systemImage: "bubble.left.and.bubble.right.fill")
                .font(.caption.weight(.semibold))
                .foregroundStyle(DivanPalette.wine)
            Text(question.prompt)
                .font(.headline)
                .fixedSize(horizontal: false, vertical: true)

            if question.filterable {
                HStack {
                    TextField("Konu veya kaynak ara", text: $model.tusSearch)
                        .textFieldStyle(.roundedBorder)
                        .onSubmit { Task { await model.searchTUSAreas() } }
                    Button("Ara") { Task { await model.searchTUSAreas() } }
                        .buttonStyle(.bordered)
                }
                if question.hasMore {
                    Text("\(question.totalOptions) alan içinde arama yapabilirsiniz.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }

            if question.options.contains(where: { $0.id == "custom" }) {
                Stepper(
                    "Özel süre: \(model.tusCustomMinutes) dakika",
                    value: $model.tusCustomMinutes,
                    in: 5...180,
                    step: 5
                )
            }

            if question.options.isEmpty {
                Text("Bu aramayla eşleşen konu veya kaynak bulunamadı.")
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .accessibilityIdentifier("adhd.tus.empty-search")
            } else {
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 180), spacing: 8)], spacing: 8) {
                    ForEach(question.options) { option in
                        Button {
                            Task { await model.answerTUS(question, option: option) }
                        } label: {
                            VStack(alignment: .leading, spacing: 3) {
                                Text(option.label).font(.callout.weight(.semibold))
                                if let description = option.description, !description.isEmpty {
                                    Text(description)
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                }
                            }
                            .frame(maxWidth: .infinity, alignment: .leading)
                        }
                        .buttonStyle(.bordered)
                        .disabled(model.tusIsBusy)
                    }
                }
            }
        }
        .accessibilityIdentifier("adhd.tus.question")
    }

    private func tusPlan(
        _ plan: ADHDTUSPlan,
        allowedActions: Set<String>
    ) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            StructuredWorkspaceCard {
                Text(plan.title).font(.title3.weight(.semibold))
                Text(plan.summary)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                tusAreaSummary(plan)
                if plan.status == "finished" {
                    Label(
                        "Bugünkü tur burada tamamlandı. Yarım kalan adımlar yarına borç değil.",
                        systemImage: "checkmark.circle"
                    )
                    .font(.callout)
                    .foregroundStyle(.secondary)
                } else {
                    ProgressView(
                        value: Double(plan.progress.completed),
                        total: Double(max(plan.progress.total, 1))
                    )
                    Text("\(plan.progress.completed) / \(plan.progress.total) küçük adım")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }

            if let step = plan.currentStep {
                StructuredWorkspaceCard {
                    Text("Şimdi yalnız bunu yap")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(DivanPalette.wine)
                    Text(step.title).font(.headline)
                    if let detail = step.detail, !detail.isEmpty {
                        Text(detail).fixedSize(horizontal: false, vertical: true)
                    }
                    Label(
                        tusStepMeasure(step),
                        systemImage: "timer"
                    )
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    if allowedActions.contains("complete_step") {
                        Button("Bu küçük adım tamam") {
                            Task { await model.completeTUSStep() }
                        }
                        .buttonStyle(.borderedProminent)
                        .disabled(model.tusIsBusy)
                    }
                }
                .accessibilityIdentifier("adhd.tus.current-step")
            }

            let future = plan.status == "finished" ? [] : plan.steps.filter {
                !$0.visible && $0.status == "pending"
            }
            if !future.isEmpty {
                DisclosureGroup("Sonraki adımlar (\(future.count))") {
                    VStack(alignment: .leading, spacing: 8) {
                        ForEach(future) { step in
                            Text("• \(step.title) · \(step.durationMinutes) dk")
                                .font(.callout)
                                .foregroundStyle(.secondary)
                        }
                    }
                    .padding(.top, 6)
                }
            }

            ViewThatFits(in: .horizontal) {
                HStack { tusPlanButtons(plan, allowedActions: allowedActions) }
                VStack { tusPlanButtons(plan, allowedActions: allowedActions) }
            }
        }
        .accessibilityIdentifier("adhd.tus.plan")
    }

    @ViewBuilder
    private func tusAreaSummary(_ plan: ADHDTUSPlan) -> some View {
        if let reading = plan.readingArea {
            Label(
                "Okuma: \(reading.name)\(reading.source.map { " · \($0)" } ?? "") · \(reading.availableCount) \(reading.unit)",
                systemImage: "book"
            )
            .font(.caption)
            .foregroundStyle(.secondary)
        }
        if let questions = plan.questionArea {
            Label(
                "Soru: \(questions.name)\(questions.source.map { " · \($0)" } ?? "") · \(questions.availableCount) \(questions.unit)",
                systemImage: "checkmark.circle"
            )
            .font(.caption)
            .foregroundStyle(.secondary)
        }
    }

    private func tusStepMeasure(_ step: ADHDTUSStep) -> String {
        guard let quantity = step.quantity,
              let unit = step.unit, !unit.isEmpty else {
            return "\(step.durationMinutes) dk"
        }
        return "\(step.durationMinutes) dk · \(quantity) \(unit)"
    }

    @ViewBuilder
    private func tusPlanButtons(
        _ plan: ADHDTUSPlan,
        allowedActions: Set<String>
    ) -> some View {
        if allowedActions.contains("start") {
            Button("Planı başlat") { Task { await model.startTUS() } }
                .buttonStyle(.borderedProminent)
        }
        if allowedActions.contains("pause") {
            Button("Duraklat") { Task { await model.pauseTUS() } }
                .buttonStyle(.bordered)
        }
        if allowedActions.contains("resume") {
            Button("Devam et") { Task { await model.resumeTUS() } }
                .buttonStyle(.borderedProminent)
        }
        if allowedActions.contains("finish") {
            Button("Bugünlük bitir") { Task { await model.finishTUS() } }
                .buttonStyle(.bordered)
        }
        if allowedActions.contains("restart") {
            Button("Planı yeniden hazırla") { Task { await model.restartTUS() } }
                .buttonStyle(.bordered)
        }
        if allowedActions.contains("cancel") {
            Button("Planı bırak", role: .destructive) {
                Task { await model.cancelTUS() }
            }
            .buttonStyle(.bordered)
        }
    }

    @ViewBuilder
    private var todayView: some View {
        if model.snapshot == nil {
            loadingCard("Bugünkü küçük denemeler yükleniyor…")
        } else if let event = model.openEvents.first,
                  let habit = model.habit(for: event) {
            todayEventCard(event: event, habit: habit)
        } else if let habit = model.activeHabits.first(where: \.isActive) {
            StructuredWorkspaceCard {
                Text(habit.title).font(.title3.weight(.semibold))
                if let tiny = habit.tinyAction, !tiny.isEmpty {
                    Text(tiny).fixedSize(horizontal: false, vertical: true)
                }
                if let cue = habit.cue, !cue.isEmpty {
                    Text("Başlama ipucu: \(cue)")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                }
                Label(
                    "Haftada \(habit.targetPerWeek) esnek deneme",
                    systemImage: "calendar.badge.clock"
                )
                .font(.caption)
                .foregroundStyle(.secondary)
                ViewThatFits(in: .horizontal) {
                    HStack { startNowButton(habit); scheduleButton(habit) }
                    VStack { startNowButton(habit); scheduleButton(habit) }
                }
            }
        } else {
            StructuredWorkspaceCard {
                Label("Etkin ritim yok", systemImage: "checklist")
                    .font(.title3.weight(.semibold))
                Text("Haftada iki küçük denemeyle başlayabilirsiniz.")
                    .foregroundStyle(.secondary)
                Button("İlk ritmi oluştur") {
                    model.prepareNewHabit()
                    habitFormExpanded = true
                    selectedTab = .routines
                }
                .buttonStyle(.borderedProminent)
            }
        }

        reviewCards
        if let notice = model.snapshot?.notices.noShame {
            Label(notice, systemImage: "heart.text.square")
                .font(.caption)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private func todayEventCard(event: ADHDEvent, habit: ADHDHabit) -> some View {
        StructuredWorkspaceCard {
            Text(habit.title).font(.title3.weight(.semibold))
            if let tiny = habit.tinyAction, !tiny.isEmpty { Text(tiny) }
            HStack(spacing: 8) {
                Label(event.status == "started" ? "Başlandı" : "Planlandı",
                      systemImage: "circle.fill")
                Text(Date(timeIntervalSince1970: event.scheduledFor), style: .time)
            }
            .font(.caption)
            .foregroundStyle(.secondary)

            Picker("Sürtünme (isteğe bağlı)", selection: $model.eventFriction) {
                Text("Seçmek istemiyorum").tag("")
                Text("Başlamak").tag("start")
                Text("Karar vermek").tag("decision")
                Text("Sürdürmek").tag("sustain")
                Text("Bitirmek").tag("finish")
                Text("Duygusal yük").tag("emotion")
                Text("Çevre / dikkat dağıtıcılar").tag("environment")
            }
            Stepper(
                "Yaklaşık süre: \(model.eventEffortMinutes) dk",
                value: $model.eventEffortMinutes,
                in: 0...1_440,
                step: 5
            )
            TextField("Kısa not (isteğe bağlı)", text: $model.eventNote)

            ViewThatFits(in: .horizontal) {
                HStack { eventButtons(event) }
                VStack { eventButtons(event) }
            }
        }
    }

    @ViewBuilder
    private func eventButtons(_ event: ADHDEvent) -> some View {
        if event.status == "scheduled" {
            Button("Başla") { Task { await model.updateEvent(event, action: .start) } }
                .buttonStyle(.bordered)
        }
        Button("Yaptım") { Task { await model.updateEvent(event, action: .done) } }
            .buttonStyle(.borderedProminent)
        Button("Kısmen yaptım") {
            Task { await model.updateEvent(event, action: .partial) }
        }
        .buttonStyle(.bordered)
        Button("Bugün değil") { Task { await model.updateEvent(event, action: .skip) } }
            .buttonStyle(.bordered)
    }

    @ViewBuilder
    private var reviewCards: some View {
        let reviewIDs = Set(model.snapshot?.reviewDue ?? [])
        let habits = model.activeHabits.filter {
            reviewIDs.contains($0.id) || $0.reviewDue
        }
        if !habits.isEmpty {
            Text("İki haftalık değerlendirme")
                .font(.headline)
            ForEach(habits) { habit in
                StructuredWorkspaceCard {
                    Text(habit.title).font(.headline)
                    Text("Ritim size uyacak biçimde kalsın, küçülsün veya dursun. Hedef kendiliğinden artmaz.")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                    Menu("Değerlendir") {
                        reviewButton("Aynı kalsın", habit, "keep")
                        reviewButton("Daha küçük", habit, "smaller")
                        reviewButton("Bir artır", habit, "increase")
                        reviewButton("Bir azalt", habit, "decrease")
                        reviewButton("Duraklat", habit, "pause")
                    }
                    .accessibilityLabel("\(habit.title) ritmini değerlendir")
                }
            }
        }
    }

    private func reviewButton(_ title: String, _ habit: ADHDHabit, _ decision: String) -> some View {
        Button(title) {
            Task { await model.changeHabit(habit, action: .review, decision: decision) }
        }
    }

    private func startNowButton(_ habit: ADHDHabit) -> some View {
        Button("Şimdi başla") { Task { await model.startNow(habit) } }
            .buttonStyle(.borderedProminent)
            .disabled(model.isBusy)
            .help("Bildirim kurmadan küçük denemeyi başlat")
    }

    private func scheduleButton(_ habit: ADHDHabit) -> some View {
        Button("Tek denemeyi zamanla") { model.prepareSchedule(habit) }
            .buttonStyle(.bordered)
            .disabled(model.isBusy)
    }

    @ViewBuilder
    private var routinesView: some View {
        StructuredWorkspaceCard {
            DisclosureGroup(isExpanded: $habitFormExpanded) {
                habitForm.padding(.top, 10)
            } label: {
                HStack {
                    Label(
                        model.editingHabitID == nil ? "Yeni ritim" : "Ritmi düzenle",
                        systemImage: "plus.circle"
                    )
                    Spacer()
                    if !habitFormExpanded {
                        Text("Haftalık, esnek")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
            }
        }

        if let scheduledID = model.scheduleHabitID,
           let habit = model.snapshot?.habits.first(where: { $0.id == scheduledID }) {
            scheduleCard(habit)
        }

        ForEach(model.activeHabits) { habit in
            StructuredWorkspaceCard {
                HStack(alignment: .firstTextBaseline) {
                    Text(habit.title).font(.headline)
                    Spacer()
                    Text(habit.isPaused ? "Duraklatıldı" : "Etkin")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(habit.isPaused ? .secondary : DivanPalette.wine)
                }
                if let tiny = habit.tinyAction, !tiny.isEmpty {
                    Text("En küçük biçim: \(tiny)")
                }
                if let cue = habit.cue, !cue.isEmpty {
                    Text("İpucu: \(cue)")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                }
                Text("Haftada \(habit.targetPerWeek) deneme")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                ViewThatFits(in: .horizontal) {
                    HStack { habitActions(habit) }
                    VStack(alignment: .leading) { habitActions(habit) }
                }
            }
        }
    }

    private var habitForm: some View {
        VStack(alignment: .leading, spacing: 10) {
            TextField("Ritim adı", text: $model.habitTitle)
                .accessibilityIdentifier("adhd.habit.title")
            TextField("Başlama ipucu", text: $model.habitCue)
            TextField("En küçük hareket", text: $model.habitTinyAction)
            Stepper(
                "Haftada \(model.habitTargetPerWeek) deneme",
                value: $model.habitTargetPerWeek,
                in: 1...7
            )
            Text("Tercih günleri — plan, zorunluluk değildir")
                .font(.caption)
                .foregroundStyle(.secondary)
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 72))], spacing: 8) {
                ForEach(Array(dayNames.enumerated()), id: \.offset) { index, title in
                    Toggle(title, isOn: Binding(
                        get: { model.habitPreferredDays.contains(index) },
                        set: { _ in model.togglePreferredDay(index) }
                    ))
                    .toggleStyle(.button)
                    .controlSize(.small)
                }
            }
            TextField("Tercih saati (SS:DD, bildirim kurmaz)", text: $model.habitReminderTime)
            HStack {
                Button("Kaydet") { Task { await model.saveHabit() } }
                    .buttonStyle(.borderedProminent)
                    .disabled(model.isBusy)
                Button("Temizle") { model.prepareNewHabit() }
                    .buttonStyle(.bordered)
            }
        }
    }

    private var dayNames: [String] {
        ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"]
    }

    @ViewBuilder
    private func habitActions(_ habit: ADHDHabit) -> some View {
        Button("Düzenle") {
            model.editHabit(habit)
            habitFormExpanded = true
        }
        Button("Zamanla") { model.prepareSchedule(habit) }
        Button(habit.isPaused ? "Devam et" : "Duraklat") {
            Task {
                await model.changeHabit(
                    habit,
                    action: habit.isPaused ? .resume : .pause
                )
            }
        }
        Button("Arşivle", role: .destructive) {
            Task { await model.changeHabit(habit, action: .archive) }
        }
    }

    private func scheduleCard(_ habit: ADHDHabit) -> some View {
        StructuredWorkspaceCard {
            Text("Tek deneme · \(habit.title)").font(.headline)
            DatePicker(
                "Tarih ve saat",
                selection: $model.scheduleDate,
                in: Date().addingTimeInterval(20)...Date().addingTimeInterval(366 * 86_400)
            )
            Toggle(
                "Bu tek deneme için hatırlatıcı kurulmasını istiyorum.",
                isOn: $model.scheduleConfirmed
            )
            .fixedSize(horizontal: false, vertical: true)
            HStack {
                Button("Zamanla") { Task { await model.saveSchedule() } }
                    .buttonStyle(.borderedProminent)
                    .disabled(!model.scheduleConfirmed || model.isBusy)
                Button("Vazgeç", action: model.cancelSchedule)
            }
        }
        .accessibilityIdentifier("adhd.schedule")
    }

    @ViewBuilder
    private var notebookView: some View {
        if let monitoring = model.snapshot?.notices.monitoring {
            Label(monitoring, systemImage: "exclamationmark.shield")
                .font(.caption)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        StructuredWorkspaceCard {
            DisclosureGroup(isExpanded: $journalFormExpanded) {
                journalForm.padding(.top, 10)
            } label: {
                Label(
                    model.editingJournalID == nil ? "Yeni defter yazısı" : "Yazıyı düzenle",
                    systemImage: "square.and.pencil"
                )
            }
        }
        ForEach(model.snapshot?.journalEntries ?? []) { entry in
            StructuredWorkspaceCard {
                HStack {
                    Text(ADHDJournalEntryType(rawValue: entry.entryType)?.title ?? "Defter")
                        .font(.headline)
                    Spacer()
                    Label(
                        entry.shareWithCoach ? "Koçla paylaşılıyor" : "Özel",
                        systemImage: entry.shareWithCoach ? "person.crop.circle.badge.checkmark" : "lock"
                    )
                    .font(.caption)
                    .foregroundStyle(.secondary)
                }
                Text(entry.content)
                    .textSelection(.enabled)
                    .fixedSize(horizontal: false, vertical: true)
                HStack {
                    Button("Düzenle") {
                        model.editJournal(entry)
                        journalFormExpanded = true
                    }
                    Button("Sil", role: .destructive) { journalToDelete = entry }
                }
            }
        }
    }

    private var journalForm: some View {
        VStack(alignment: .leading, spacing: 10) {
            Picker("Yazı türü", selection: $model.journalType) {
                ForEach(ADHDJournalEntryType.allCases) { Text($0.title).tag($0) }
            }
            TextEditor(text: $model.journalContent)
                .font(.body)
                .frame(minHeight: 120)
                .overlay {
                    RoundedRectangle(cornerRadius: 7)
                        .stroke(Color(nsColor: .separatorColor))
                }
                .accessibilityLabel("Defter yazısı")
                .accessibilityIdentifier("adhd.journal.content")
            Toggle(
                "Hassas ve yalnız bana özel",
                isOn: Binding(
                    get: { model.journalSensitive },
                    set: model.setJournalSensitive
                )
            )
            Toggle(
                "Hassas değil; ADHD koçuyla paylaş",
                isOn: Binding(
                    get: { model.journalShareWithCoach },
                    set: model.setJournalSharing
                )
            )
            Text("Paylaşım kapalıyken yazı koçun sohbet bağlamına girmez.")
                .font(.caption)
                .foregroundStyle(.secondary)
            HStack {
                Button("Deftere kaydet") { Task { await model.saveJournal() } }
                    .buttonStyle(.borderedProminent)
                    .disabled(model.isBusy)
                Button("Temizle", action: model.prepareNewJournal)
            }
        }
    }

    private func loadingCard(_ text: String) -> some View {
        StructuredWorkspaceCard {
            HStack { ProgressView(); Text(text).foregroundStyle(.secondary) }
        }
    }

    private var statusBar: some View {
        HStack(spacing: 8) {
            if model.isBusy || model.tusIsBusy {
                ProgressView().controlSize(.small)
            }
            let visibleOperation = model.tusIsBusy
                ? model.tusOperationDescription : model.operationDescription
            Text(visibleOperation.isEmpty
                 ? model.statusMessage : visibleOperation)
                .font(.caption)
                .foregroundStyle(.secondary)
                .lineLimit(2)
            Spacer()
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 7)
        .frame(minHeight: 30)
        .background(.bar)
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("adhd.status")
    }
}

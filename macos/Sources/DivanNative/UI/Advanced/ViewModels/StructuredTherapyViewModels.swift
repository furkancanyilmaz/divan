import Foundation
import SwiftUI

public struct StructuredWorkspaceFailure: Identifiable, Equatable {
    public let id = UUID()
    public let title: String
    public let message: String

    public init(title: String, message: String) {
        self.title = title
        self.message = message
    }

    public static func == (lhs: Self, rhs: Self) -> Bool { lhs.id == rhs.id }
}

@MainActor
public final class ADHDWorkspaceViewModel: ObservableObject {
    public let conversationID: Int

    @Published public private(set) var snapshot: ADHDWorkspaceSnapshot?
    @Published public private(set) var isBusy = false
    @Published public private(set) var operationDescription = ""
    @Published public var failure: StructuredWorkspaceFailure?
    @Published public var statusMessage = ""
    @Published public var safetyMessage = ""
    @Published public private(set) var tusSnapshot: ADHDTUSPlannerSnapshot?
    @Published public private(set) var tusIsBusy = false
    @Published public private(set) var tusOperationDescription = ""
    @Published public var tusSearch = ""
    @Published public var tusCustomMinutes = 25

    @Published public var editingHabitID: Int?
    @Published public var habitTitle = ""
    @Published public var habitCue = ""
    @Published public var habitTinyAction = ""
    @Published public var habitTargetPerWeek = 2
    @Published public var habitPreferredDays = Set<Int>()
    @Published public var habitReminderTime = ""

    @Published public var scheduleHabitID: Int?
    @Published public var scheduleDate = Date().addingTimeInterval(3_600)
    @Published public var scheduleConfirmed = false

    @Published public var eventFriction = ""
    @Published public var eventEffortMinutes = 0
    @Published public var eventNote = ""

    @Published public var editingJournalID: Int?
    @Published public var journalContent = ""
    @Published public var journalType: ADHDJournalEntryType = .freewrite
    @Published public var journalSensitive = true
    @Published public var journalShareWithCoach = false

    private let dataSource: any StructuredTherapyDataSource
    private var hasLoaded = false
    private var hasLoadedTUS = false
    private var pendingRequestIDs: [String: String] = [:]

    public init(
        dataSource: any StructuredTherapyDataSource,
        conversationID: Int
    ) {
        self.dataSource = dataSource
        self.conversationID = conversationID
    }

    public var activeHabits: [ADHDHabit] {
        (snapshot?.habits ?? []).filter { $0.status != "archived" }
    }

    public var openEvents: [ADHDEvent] {
        (snapshot?.events ?? []).filter(\.isOpen).sorted {
            $0.scheduledFor < $1.scheduledFor
        }
    }

    public func habit(for event: ADHDEvent) -> ADHDHabit? {
        snapshot?.habits.first { $0.id == event.habit }
    }

    public func loadIfNeeded() async {
        guard !hasLoaded else { return }
        await reload()
    }

    public func reload() async {
        guard !isBusy else { return }
        isBusy = true
        operationDescription = "Ritimler ve defter yükleniyor…"
        failure = nil
        defer {
            isBusy = false
            operationDescription = ""
        }
        do {
            snapshot = try await dataSource.adhdDashboard(
                conversationID: conversationID
            )
            hasLoaded = true
        } catch {
            failure = Self.failure("Çalışma alanı açılamadı", error)
        }
    }

    public func loadTUSIfNeeded() async {
        guard !hasLoadedTUS else { return }
        await reloadTUS()
    }

    public func reloadTUS(query: String? = nil) async {
        guard !tusIsBusy else { return }
        tusIsBusy = true
        tusOperationDescription = "TUS çalışma planı yükleniyor…"
        failure = nil
        defer {
            tusIsBusy = false
            tusOperationDescription = ""
        }
        do {
            let minimumRevision = tusSnapshot?.revision ?? 0
            let value = try await dataSource.adhdTUSPlanner(
                conversationID: conversationID,
                query: query
            )
            guard value.contractIsSupported,
                  value.conversationID == conversationID,
                  value.revision >= minimumRevision else {
                throw DivanUIClientError("TUS çalışma sözleşmesi doğrulanamadı.")
            }
            tusSnapshot = value
            hasLoadedTUS = true
        } catch {
            // A failed contract/load must never leave an interactive stale
            // planner on screen. The server remains the only resume source.
            tusSnapshot = nil
            hasLoadedTUS = false
            failure = Self.failure("TUS çalışma alanı açılamadı", error)
        }
    }

    public func searchTUSAreas() async {
        guard tusSnapshot?.question?.filterable == true else { return }
        let value = tusSearch.trimmingCharacters(in: .whitespacesAndNewlines)
        guard value.count <= 80 else {
            failure = .init(
                title: "Arama fazla uzun",
                message: "Konu veya kaynak araması en fazla 80 karakter olabilir."
            )
            return
        }
        await reloadTUS(query: value.isEmpty ? nil : value)
    }

    public func setTUSMode(_ enabled: Bool) async {
        await performTUS(.setMode, enabled: enabled)
    }

    public func answerTUS(_ question: ADHDTUSQuestion, option: ADHDTUSOption) async {
        guard let current = tusSnapshot?.question,
              current.id == question.id,
              current.options.contains(option) else {
            failure = .init(
                title: "TUS sorusu güncel değil",
                message: "Güncel tek soruyu yeniden yükleyip seçim yapın."
            )
            return
        }
        await performTUS(
            .answer,
            questionID: question.id,
            optionID: option.id,
            customMinutes: option.id == "custom" ? tusCustomMinutes : nil
        )
    }

    public func restartTUS() async { await performTUS(.restart) }

    public func startTUS() async {
        guard let planID = tusSnapshot?.plan?.id else {
            failure = .init(
                title: "TUS planı hazır değil",
                message: "Önce kısa çalışma sorularını tamamlayın."
            )
            return
        }
        await performTUS(.start, planID: planID)
    }

    public func pauseTUS() async { await performTUS(.pause) }
    public func resumeTUS() async { await performTUS(.resume) }

    public func completeTUSStep() async {
        guard let plan = tusSnapshot?.plan,
              let stepID = plan.currentStep?.id else {
            failure = .init(
                title: "TUS adımı bulunamadı",
                message: "Güncel planı yenileyip yeniden deneyin."
            )
            return
        }
        await performTUS(.completeStep, planID: plan.id, stepID: stepID)
    }

    public func finishTUS() async {
        guard let planID = tusSnapshot?.plan?.id else { return }
        await performTUS(.finish, planID: planID)
    }

    public func cancelTUS() async {
        await performTUS(.cancel, planID: tusSnapshot?.plan?.id)
    }

    public func editHabit(_ habit: ADHDHabit) {
        editingHabitID = habit.id
        habitTitle = habit.title
        habitCue = habit.cue ?? ""
        habitTinyAction = habit.tinyAction ?? ""
        habitTargetPerWeek = habit.targetPerWeek
        habitPreferredDays = Set(habit.preferredDays)
        habitReminderTime = habit.reminderLocalTime ?? ""
    }

    public func prepareNewHabit() {
        editingHabitID = nil
        habitTitle = ""
        habitCue = ""
        habitTinyAction = ""
        habitTargetPerWeek = 2
        habitPreferredDays = []
        habitReminderTime = ""
    }

    public func togglePreferredDay(_ day: Int) {
        if habitPreferredDays.contains(day) {
            habitPreferredDays.remove(day)
        } else {
            habitPreferredDays.insert(day)
        }
    }

    public func saveHabit() async {
        let title = habitTitle.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !title.isEmpty else {
            failure = .init(title: "Ritim adı gerekli", message: "Kısa ve somut bir ad yazın.")
            return
        }
        let action: ADHDHabitAction = editingHabitID == nil ? .create : .update
        let key = [
            "habit", action.rawValue, String(editingHabitID ?? 0), title,
            habitCue, habitTinyAction, String(habitTargetPerWeek),
            habitPreferredDays.sorted().map(String.init).joined(separator: ","),
            habitReminderTime,
        ].joined(separator: "|")
        let requestID = requestID(for: key, prefix: "native-adhd-habit")
        let mutation = ADHDHabitMutation(
            action: action,
            conversationID: conversationID,
            requestID: requestID,
            habitID: editingHabitID,
            title: title,
            cue: habitCue,
            tinyAction: habitTinyAction,
            targetPerWeek: habitTargetPerWeek,
            preferredDays: habitPreferredDays.sorted(),
            reminderLocalTime: habitReminderTime,
            timezone: TimeZone.current.identifier
        )
        await perform("Ritim kaydediliyor…", key: key, operation: {
            _ = try await dataSource.mutateADHDHabit(mutation)
        }, onSuccess: {
            prepareNewHabit()
            statusMessage = "Ritim kaydedildi. Hatırlatıcı kendiliğinden kurulmadı."
        })
    }

    public func changeHabit(
        _ habit: ADHDHabit,
        action: ADHDHabitAction,
        decision: String? = nil
    ) async {
        let key = "habit|\(action.rawValue)|\(habit.id)|\(decision ?? "")"
        let mutation = ADHDHabitMutation(
            action: action,
            conversationID: conversationID,
            requestID: requestID(for: key, prefix: "native-adhd-habit"),
            habitID: habit.id,
            decision: decision
        )
        await perform("Ritim güncelleniyor…", key: key, operation: {
            _ = try await dataSource.mutateADHDHabit(mutation)
        }, onSuccess: {
            statusMessage = action == .review
                ? "Değerlendirmeniz kaydedildi; hedef otomatik değiştirilmedi."
                : "Ritim güncellendi."
        })
    }

    public func startNow(_ habit: ADHDHabit) async {
        let key = "habit|start-now|\(habit.id)"
        let mutation = ADHDHabitMutation(
            action: .startNow,
            conversationID: conversationID,
            requestID: requestID(for: key, prefix: "native-adhd-start"),
            habitID: habit.id
        )
        await perform("Bildirimsiz deneme başlatılıyor…", key: key, operation: {
            _ = try await dataSource.mutateADHDHabit(mutation)
        }, onSuccess: {
            statusMessage = "Deneme başladı. Bildirim kurulmadı."
        })
    }

    public func prepareSchedule(_ habit: ADHDHabit) {
        scheduleHabitID = habit.id
        scheduleDate = Date().addingTimeInterval(3_600)
        scheduleConfirmed = false
    }

    public func cancelSchedule() {
        scheduleHabitID = nil
        scheduleConfirmed = false
    }

    public func saveSchedule() async {
        guard let habitID = scheduleHabitID, scheduleConfirmed else {
            failure = .init(
                title: "Açık onay gerekli",
                message: "Bu tek deneme için bildirim kurulacağını onaylayın."
            )
            return
        }
        let seconds = floor(scheduleDate.timeIntervalSince1970)
        let key = "habit|schedule|\(habitID)|\(seconds)"
        let mutation = ADHDHabitMutation(
            action: .schedule,
            conversationID: conversationID,
            requestID: requestID(for: key, prefix: "native-adhd-schedule"),
            habitID: habitID,
            scheduledFor: seconds
        )
        await perform("Tek deneme zamanlanıyor…", key: key, operation: {
            _ = try await dataSource.mutateADHDHabit(mutation)
        }, onSuccess: {
            cancelSchedule()
            statusMessage = "Tek deneme zamanlandı."
        })
    }

    public func updateEvent(_ event: ADHDEvent, action: ADHDEventAction) async {
        let key = [
            "event", action.rawValue, String(event.id), String(eventEffortMinutes),
            eventFriction, eventNote,
        ].joined(separator: "|")
        let mutation = ADHDEventMutation(
            action: action,
            conversationID: conversationID,
            eventID: event.id,
            requestID: requestID(for: key, prefix: "native-adhd-event"),
            effortMinutes: eventEffortMinutes,
            friction: eventFriction,
            note: eventNote
        )
        await perform("Deneme kaydediliyor…", key: key, operation: {
            _ = try await dataSource.mutateADHDEvent(mutation)
        }, onSuccess: {
            eventFriction = ""
            eventEffortMinutes = 0
            eventNote = ""
            statusMessage = "Deneme kaydedildi; burada seri veya borç tutulmaz."
        })
    }

    public func editJournal(_ entry: ADHDJournalEntry) {
        editingJournalID = entry.id
        journalContent = entry.content
        journalType = ADHDJournalEntryType(rawValue: entry.entryType) ?? .freewrite
        journalSensitive = entry.sensitive
        journalShareWithCoach = entry.shareWithCoach
    }

    public func prepareNewJournal() {
        editingJournalID = nil
        journalContent = ""
        journalType = .freewrite
        journalSensitive = true
        journalShareWithCoach = false
    }

    public func setJournalSensitive(_ value: Bool) {
        journalSensitive = value
        if value { journalShareWithCoach = false }
    }

    public func setJournalSharing(_ value: Bool) {
        journalShareWithCoach = value
        if value { journalSensitive = false }
    }

    public func saveJournal() async {
        let content = journalContent.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !content.isEmpty else {
            failure = .init(title: "Defter yazısı gerekli", message: "Kendi sözlerinizle kısa bir not yazın.")
            return
        }
        let action: ADHDJournalAction = editingJournalID == nil ? .create : .update
        let key = [
            "journal", action.rawValue, String(editingJournalID ?? 0), content,
            journalType.rawValue, String(journalSensitive),
            String(journalShareWithCoach),
        ].joined(separator: "|")
        let mutation = ADHDJournalMutation(
            action: action,
            conversationID: conversationID,
            requestID: requestID(for: key, prefix: "native-adhd-journal"),
            entryID: editingJournalID,
            content: content,
            entryType: journalType,
            shareWithCoach: journalShareWithCoach,
            sensitive: journalSensitive
        )
        await perform("Defter yazısı kaydediliyor…", key: key, operation: {
            let response = try await dataSource.mutateADHDJournal(mutation)
            if let safety = response.safety, safety.detected {
                safetyMessage = safety.message
            }
        }, onSuccess: {
            prepareNewJournal()
            statusMessage = "Defter yazısı kaydedildi. Bu alan acil destek tarafından izlenmez."
        })
    }

    public func deleteJournal(_ entry: ADHDJournalEntry) async {
        let key = "journal|delete|\(entry.id)"
        let mutation = ADHDJournalMutation(
            action: .delete,
            conversationID: conversationID,
            requestID: requestID(for: key, prefix: "native-adhd-journal"),
            entryID: entry.id
        )
        await perform("Defter yazısı siliniyor…", key: key, operation: {
            _ = try await dataSource.mutateADHDJournal(mutation)
        }, onSuccess: {
            if editingJournalID == entry.id { prepareNewJournal() }
            statusMessage = "Defter yazısı silindi."
        })
    }

    public func dismissFailure() { failure = nil }

    private func performTUS(
        _ action: ADHDTUSAction,
        enabled: Bool? = nil,
        questionID: String? = nil,
        optionID: String? = nil,
        customMinutes: Int? = nil,
        planID: String? = nil,
        stepID: String? = nil
    ) async {
        guard !tusIsBusy else { return }
        guard let current = tusSnapshot else {
            failure = .init(
                title: "TUS çalışma alanı hazır değil",
                message: "Önce alanı yenileyin."
            )
            return
        }
        guard current.allowedActions.contains(action.rawValue) else {
            failure = .init(
                title: "TUS işlemi artık kullanılamıyor",
                message: "Plan başka bir aşamada. Güncel çalışma durumunu yenileyin."
            )
            return
        }
        let key = [
            "tus", action.rawValue, String(current.revision),
            String(enabled ?? false), questionID ?? "", optionID ?? "",
            customMinutes.map(String.init) ?? "", planID ?? "", stepID ?? "",
        ].joined(separator: "|")
        let requestID = requestID(for: key, prefix: "native-adhd-tus")
        let mutation = ADHDTUSMutation(
            action: action,
            conversationID: conversationID,
            expectedRevision: current.revision,
            requestID: requestID,
            enabled: enabled,
            questionID: questionID,
            optionID: optionID,
            customMinutes: customMinutes,
            planID: planID,
            stepID: stepID
        )
        tusIsBusy = true
        tusOperationDescription = "TUS çalışma planı güncelleniyor…"
        failure = nil
        defer {
            tusIsBusy = false
            tusOperationDescription = ""
        }
        do {
            let response = try await dataSource.mutateADHDTUS(mutation)
            guard response.contractIsSupported,
                  response.conversationID == conversationID,
                  response.ok == true,
                  response.action == action.rawValue,
                  response.revision == current.revision + 1 else {
                tusSnapshot = nil
                hasLoadedTUS = false
                throw DivanUIClientError("TUS çalışma yanıtı güncel değil.")
            }
            tusSnapshot = response
            pendingRequestIDs.removeValue(forKey: key)
            statusMessage = "TUS çalışma planı güncellendi."
        } catch {
            if Self.tusRequiresReload(error) {
                tusSnapshot = nil
                hasLoadedTUS = false
            }
            failure = Self.failure("TUS işlemi tamamlanamadı", error)
        }
    }

    private func perform(
        _ description: String,
        key: String,
        operation: () async throws -> Void,
        onSuccess: () -> Void
    ) async {
        guard !isBusy else { return }
        isBusy = true
        operationDescription = description
        failure = nil
        defer {
            isBusy = false
            operationDescription = ""
        }
        do {
            try await operation()
        } catch {
            failure = Self.failure("İşlem tamamlanamadı", error)
            return
        }
        do {
            snapshot = try await dataSource.adhdDashboard(
                conversationID: conversationID
            )
            pendingRequestIDs.removeValue(forKey: key)
            onSuccess()
        } catch {
            // The mutation response already confirmed a durable save. Do not
            // label it failed. Preserve both the form and request ID so an
            // explicit retry is an exact idempotent replay, not a new action.
            failure = Self.failure(
                "Kaydedildi; görünüm yenilenemedi",
                error
            )
        }
    }

    private func requestID(for key: String, prefix: String) -> String {
        if let current = pendingRequestIDs[key] { return current }
        let value = "\(prefix)-\(UUID().uuidString.lowercased())"
        pendingRequestIDs[key] = value
        return value
    }

    private static func failure(_ title: String, _ error: Error) -> StructuredWorkspaceFailure {
        .init(
            title: title,
            message: (error as? LocalizedError)?.errorDescription
                ?? error.localizedDescription
        )
    }

    private static func tusRequiresReload(_ error: Error) -> Bool {
        if let api = error as? DivanAPIError {
            return api.statusCode == 409
                || api.errorCode?.hasPrefix("tus_") == true
                || api.errorCode == "safety_hold"
                || api.message == "TUS çalışma sözleşmesi doğrulanamadı."
        }
        return (error as? DivanUIClientError)?.userMessage
            == "TUS çalışma yanıtı güncel değil."
    }
}

@MainActor
public final class SchemaPathViewModel: ObservableObject {
    public let conversationID: Int

    @Published public private(set) var snapshot: SchemaPathSnapshot?
    @Published public private(set) var isBusy = false
    @Published public private(set) var operationDescription = ""
    @Published public var failure: StructuredWorkspaceFailure?
    @Published public var statusMessage = ""
    @Published public var modeEnableConfirmed = false
    @Published public var historicalScanConfirmed = false

    @Published public var currentTrigger = ""
    @Published public var need = ""
    @Published public var earlierEcho = ""
    @Published public var skipOrigin = false
    @Published public var exception = ""
    @Published public var alternative = ""
    @Published public var goodEnough = ""
    @Published public var followup = ""

    @Published public var selectedMethodID = ""
    @Published public var methodConfirmed = false
    @Published public var orientationConfirmed = false
    @Published public var realityClear = false
    @Published public var sleepActivationClear = false
    @Published public var supportAvailable = false
    @Published public var methodIntensity = 3
    @Published public var stopSignal = "Dur"

    @Published public var practiceVariable = ""
    @Published public var practiceConstant = ""
    @Published public var practicePrediction = ""
    @Published public var practiceAction = ""
    @Published public var practiceResult = ""
    @Published public var practiceTinyVersion = ""
    @Published public var practiceTargetPerWeek = 2
    @Published public var practiceConfirmed = false

    // Focus, user-authored origin and age-by-age growth remain drafts until
    // the user presses their explicit save buttons.
    @Published public var originConfidence = "unknown"
    @Published public var originAgeText = ""
    @Published public var originAgeRange = ""
    @Published public var originScene = ""
    @Published public var originUnmetNeed = ""
    @Published public var growthAgeText = ""
    @Published public var growthLabel = ""
    @Published public var growthThenResponses: [Int: String] = [:]
    @Published public var growthNowResponses: [Int: String] = [:]
    @Published public var growthDifferences: [Int: String] = [:]
    @Published public var healthyAdultEvidence = ""

    private let dataSource: any StructuredTherapyDataSource
    private var hasLoaded = false
    private var hydratedPathID: Int?
    private var pendingRequestIDs: [String: String] = [:]
    private var analysisPollToken = UUID()

    public init(
        dataSource: any StructuredTherapyDataSource,
        conversationID: Int
    ) {
        self.dataSource = dataSource
        self.conversationID = conversationID
    }

    public var activePath: SchemaPath? { snapshot?.activePath }
    public var phase: String { activePath?.phase ?? "listening" }
    public var schemaMode: SchemaTherapyModeState? { snapshot?.schemaMode }
    public var turnAnalysis: SchemaTurnAnalysisState? { snapshot?.turnAnalysis }
    public var focus: SchemaFocusState? { snapshot?.focus }
    public var focusOffer: SchemaFocusOffer? { focus?.offer }
    public var chosenFocus: SchemaFocusChoice? { focus?.chosen }
    public var origin: SchemaOriginState? { snapshot?.origin }
    public var growth: SchemaGrowthState? { snapshot?.growth }
    public var healthyAdult: SchemaHealthyAdultState? { snapshot?.healthyAdult }
    public var presentTransfer: SchemaPresentTransferState? {
        snapshot?.presentTransfer
    }
    public var queuedCandidates: [SchemaCandidate] {
        if activePath != nil, let explicit = snapshot?.queuedCandidates {
            return explicit
        }
        return (snapshot?.candidates ?? []).filter {
            $0.deferredForNextSession == true || $0.decisionState == "deferred"
        }
    }
    public var visibleCandidates: [SchemaCandidate] {
        if activePath != nil { return [] }
        let queued = Set(queuedCandidates.map(\.id))
        return (snapshot?.candidates ?? []).filter {
            !queued.contains($0.id) && $0.scope != "private"
                && $0.scope != "excluded" && !$0.sensitive
                && !["dismissed", "rejected"].contains($0.decisionState ?? "")
        }
    }
    public var listeningReady: Bool {
        guard let snapshot else { return false }
        return snapshot.completedTurns >= snapshot.minimumListeningTurns
    }

    public func allows(_ action: SchemaPathAction) -> Bool {
        snapshot?.allows(action) == true
    }

    public func loadIfNeeded() async {
        guard !hasLoaded else { return }
        await reload()
    }

    public func reload() async {
        guard !isBusy else { return }
        isBusy = true
        operationDescription = "Şema çalışma yolu yükleniyor…"
        failure = nil
        defer {
            isBusy = false
            operationDescription = ""
        }
        do {
            let value = try await dataSource.schemaPath(conversationID: conversationID)
            apply(value)
            hasLoaded = true
            scheduleAnalysisPollIfNeeded(value)
        } catch {
            failure = Self.failure("Şema çalışma yolu açılamadı", error)
        }
    }

    public func setSchemaMode(enabled: Bool) async {
        if enabled && !modeEnableConfirmed {
            failure = .init(
                title: "Açık onay gerekli",
                message: "Gelecekte tamamlanan Kerem yanıtlarının seçili model sağlayıcısıyla inceleneceğini onaylayın. Bu seçim geçmiş mesajları kapsamaz."
            )
            return
        }
        let provider = turnAnalysis?.provider
        if enabled && provider == nil {
            failure = .init(
                title: "Sağlayıcı doğrulanamadı",
                message: "Bu cihazdaki sağlayıcı ve model görünmeden Şema terapisi modu onaylanamaz. Görünümü yenileyin."
            )
            return
        }
        let key = [
            "schema", "mode", String(enabled),
            provider?.id ?? "none", provider?.model ?? "none",
        ].joined(separator: "|")
        let mutation = SchemaTurnAnalysisMutation(
            action: .setMode,
            conversationID: conversationID,
            requestID: requestID(for: key),
            enabled: enabled,
            providerID: enabled ? provider?.id : nil,
            modelID: enabled ? provider?.model : nil
        )
        await performAnalysis(
            enabled ? "Şema terapisi modu açılıyor…" : "Şema terapisi modu kapatılıyor…",
            key: key,
            mutation: mutation,
            success: enabled
                ? "Bu cihaz için Şema terapisi modu onaylandı. Yalnız bundan sonra tamamlanan mesaj çiftleri incelenecek."
                : "Şema terapisi modu kapatıldı."
        )
        if enabled { modeEnableConfirmed = false }
    }

    public func scanHistoricalTurns() async {
        guard historicalScanConfirmed else {
            failure = .init(
                title: "Geçmiş kapsamı için onay gerekli",
                message: "Uygun geçmiş kullanıcı–Kerem mesaj çiftlerinin seçili sağlayıcıyla tek tek inceleneceğini onaylayın."
            )
            return
        }
        guard let provider = turnAnalysis?.provider else {
            failure = .init(
                title: "Sağlayıcı doğrulanamadı",
                message: "Çalışma yolunu yenileyip sağlayıcı ve model kapsamını tekrar inceleyin."
            )
            return
        }
        let key = [
            "schema", "scan", provider.id, provider.model,
            String(turnAnalysis?.targetMessageId ?? 0),
        ].joined(separator: "|")
        let mutation = SchemaTurnAnalysisMutation(
            action: .scanHistory,
            conversationID: conversationID,
            requestID: requestID(for: key),
            consent: true,
            providerID: provider.id,
            modelID: provider.model
        )
        await performAnalysis(
            "Geçmiş tamamlanmış mesaj çiftleri sıraya alınıyor…",
            key: key,
            mutation: mutation,
            success: "Geçmiş mesaj çifti incelemesi başladı; kaldığı yerden sürdürülebilir."
        )
        historicalScanConfirmed = false
    }

    public func retryHistoricalScan() async {
        guard let jobID = turnAnalysis?.job?.id else {
            failure = .init(
                title: "Yeniden denenecek tarama yok",
                message: "Durumu yenileyip geçmiş inceleme kapsamını tekrar kontrol edin."
            )
            return
        }
        let key = "schema|retry-scan|\(jobID)"
        await performAnalysis(
            "Geçmiş inceleme kaldığı yerden sürdürülüyor…",
            key: key,
            mutation: SchemaTurnAnalysisMutation(
                action: .retryScan,
                conversationID: conversationID,
                requestID: requestID(for: key),
                jobID: jobID
            ),
            success: "Geçmiş inceleme kaldığı yerden yeniden başladı."
        )
    }

    public func reviewCandidate(
        _ candidate: SchemaCandidate,
        decision: SchemaCandidateDecision,
        context: String = ""
    ) async {
        let key = "schema|review|\(candidate.id)|\(decision.rawValue)|\(context)"
        let mutation = SchemaPathMutation(
            action: .reviewCandidate,
            conversationID: conversationID,
            requestID: requestID(for: key),
            claimID: candidate.id,
            decision: decision,
            context: decision == .contextual ? context : nil
        )
        await perform("Değerlendirmeniz kaydediliyor…", keys: [key]) {
            try await dataSource.mutateSchemaPath(mutation).snapshot
        }
    }

    public func startPath(_ candidate: SchemaCandidate) async {
        guard activePath == nil else {
            failure = .init(
                title: "Önce açık çalışmayı tamamlayın",
                message: "Bu çalışma bitince diğerlerini başka görüşmede ele alacağız."
            )
            return
        }
        let key = "schema|start|\(candidate.id)"
        let mutation = SchemaPathMutation(
            action: .start,
            conversationID: conversationID,
            requestID: requestID(for: key),
            claimID: candidate.id
        )
        await perform("Çalışma yolu açılıyor…", keys: [key]) {
            try await dataSource.mutateSchemaPath(mutation).snapshot
        }
    }

    public func saveExploration() async {
        let trigger = currentTrigger.trimmingCharacters(in: .whitespacesAndNewlines)
        let needText = need.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trigger.isEmpty, !needText.isEmpty else {
            failure = .init(
                title: "İki güncel alan gerekli",
                message: "Bugünkü tetikleyiciyi ve bugün ihtiyaç duyduğunuz şeyi kendi sözlerinizle yazın."
            )
            return
        }
        var records: [(String, String)] = [
            ("current_trigger", trigger), ("need", needText),
        ]
        if !earlierEcho.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            records.append(("earlier_echo", earlierEcho))
        } else if skipOrigin {
            records.append(("skip_origin", "selected"))
        }
        if !exception.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            records.append(("exception", exception))
        }
        if !alternative.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            records.append(("alternative", alternative))
        }
        guard let pathID = activePath?.id else { return }
        let keys = records.map { "schema|record|\(pathID)|\($0.0)|\($0.1)" }
            + ["schema|advance|\(pathID)|focus"]
        await perform("Güncel döngü kaydediliyor…", keys: keys) {
            for (index, row) in records.enumerated() {
                let mutation = SchemaPathMutation(
                    action: .record,
                    conversationID: conversationID,
                    requestID: requestID(for: keys[index]),
                    pathID: pathID,
                    kind: row.0,
                    value: row.1
                )
                _ = try await dataSource.mutateSchemaPath(mutation)
            }
            let advance = SchemaPathMutation(
                action: .advance,
                conversationID: conversationID,
                requestID: requestID(for: keys.last!),
                pathID: pathID,
                toPhase: "focus"
            )
            return try await dataSource.mutateSchemaPath(advance).snapshot
        }
    }

    public func chooseFocus(_ candidate: SchemaFocusCandidate) async {
        guard let pathID = activePath?.id else { return }
        let key = "schema|focus|choose|\(pathID)|\(candidate.modeKey)"
        let mutation = SchemaPathMutation(
            action: .chooseFocus,
            conversationID: conversationID,
            requestID: requestID(for: key),
            pathID: pathID,
            modeKey: candidate.modeKey
        )
        await perform("Çalışma odağı seçiliyor…", keys: [key]) {
            try await dataSource.mutateSchemaPath(mutation).snapshot
        }
    }

    public func declineFocus() async {
        guard let pathID = activePath?.id else { return }
        let key = "schema|focus|decline|\(pathID)|\(focusOffer?.id ?? 0)"
        let mutation = SchemaPathMutation(
            action: .declineFocus,
            conversationID: conversationID,
            requestID: requestID(for: key),
            pathID: pathID
        )
        await perform("Odak önerisi kapatılıyor…", keys: [key]) {
            try await dataSource.mutateSchemaPath(mutation).snapshot
        }
    }

    public func advanceFocusToMethods() async {
        await advance(to: "method", description: "Seçilen odakla yöntemlere geçiliyor…")
    }

    public func saveOrigin() async {
        guard let pathID = activePath?.id else { return }
        let trimmedAge = originAgeText.trimmingCharacters(in: .whitespacesAndNewlines)
        let age: Int?
        if trimmedAge.isEmpty {
            age = nil
        } else if let parsed = Int(trimmedAge), (0...120).contains(parsed) {
            age = parsed
        } else {
            failure = .init(
                title: "Yaş geçersiz",
                message: "Yaşı 0–120 arasında tam sayı olarak yazın veya boş bırakın."
            )
            return
        }
        let key = [
            "schema", "origin", String(pathID), originConfidence,
            trimmedAge, originAgeRange, originScene, originUnmetNeed,
        ].joined(separator: "|")
        let mutation = SchemaPathMutation(
            action: .recordOrigin,
            conversationID: conversationID,
            requestID: requestID(for: key),
            pathID: pathID,
            authoredBy: "user",
            age: age,
            ageRange: originAgeRange,
            scene: originScene,
            unmetNeed: originUnmetNeed,
            confidence: originConfidence
        )
        await perform("Kendi anlattığınız köken kaydediliyor…", keys: [key]) {
            try await dataSource.mutateSchemaPath(mutation).snapshot
        }
    }

    public func addGrowthStage() async {
        guard let pathID = activePath?.id else { return }
        let trimmedAge = growthAgeText.trimmingCharacters(in: .whitespacesAndNewlines)
        let age: Int?
        if trimmedAge.isEmpty {
            age = nil
        } else if let parsed = Int(trimmedAge), (0...120).contains(parsed) {
            age = parsed
        } else {
            failure = .init(
                title: "Basamak yaşı geçersiz",
                message: "Yaşı 0–120 arasında tam sayı olarak yazın veya kısa bir ad kullanın."
            )
            return
        }
        let label = growthLabel.trimmingCharacters(in: .whitespacesAndNewlines)
        guard age != nil || !label.isEmpty else {
            failure = .init(
                title: "Basamak adı gerekli",
                message: "Bir yaş veya ‘bugün’ gibi kısa bir basamak adı yazın."
            )
            return
        }
        let key = "schema|growth|add|\(pathID)|\(trimmedAge)|\(label)"
        let mutation = SchemaPathMutation(
            action: .addGrowthStage,
            conversationID: conversationID,
            requestID: requestID(for: key),
            pathID: pathID,
            age: age,
            label: label
        )
        await perform("Büyütme basamağı ekleniyor…", keys: [key]) {
            try await dataSource.mutateSchemaPath(mutation).snapshot
        }
        if failure == nil {
            growthAgeText = ""
            growthLabel = ""
        }
    }

    public func saveGrowth(_ stage: SchemaGrowthStage) async {
        guard let pathID = activePath?.id else { return }
        let thenText = growthThenResponses[stage.id, default: stage.thenResponse]
        let nowText = growthNowResponses[stage.id, default: stage.nowResponse]
        let differenceText = growthDifferences[stage.id, default: stage.difference]
        let key = [
            "schema", "growth", "record", String(pathID), String(stage.id),
            thenText, nowText, differenceText,
        ].joined(separator: "|")
        let mutation = SchemaPathMutation(
            action: .recordGrowth,
            conversationID: conversationID,
            requestID: requestID(for: key),
            pathID: pathID,
            stageID: stage.id,
            thenResponse: thenText,
            nowResponse: nowText,
            difference: differenceText
        )
        await perform("Büyütme yanıtları kaydediliyor…", keys: [key]) {
            try await dataSource.mutateSchemaPath(mutation).snapshot
        }
    }

    public func markHealthyAdult() async {
        guard let pathID = activePath?.id else { return }
        let evidence = healthyAdultEvidence.trimmingCharacters(
            in: .whitespacesAndNewlines
        )
        guard !evidence.isEmpty else {
            failure = .init(
                title: "Kendi cümleniz gerekli",
                message: "Bugün koruyan, sınır koyan veya şefkatli davranan yanınızı kendi sözlerinizle yazın."
            )
            return
        }
        let key = "schema|healthy-adult|\(pathID)|\(evidence)"
        let mutation = SchemaPathMutation(
            action: .markHealthyAdult,
            conversationID: conversationID,
            requestID: requestID(for: key),
            pathID: pathID,
            evidence: evidence
        )
        await perform("Sağlıklı Yetişkin işareti kaydediliyor…", keys: [key]) {
            try await dataSource.mutateSchemaPath(mutation).snapshot
        }
        if failure == nil { healthyAdultEvidence = "" }
    }

    public func chooseMethod(_ method: SchemaPathMethod) async {
        guard methodConfirmed else {
            failure = .init(
                title: "Açık onay gerekli",
                message: "Yöntemi incelediğinizi ve seçtiğinizi onaylayın."
            )
            return
        }
        guard let pathID = activePath?.id else { return }
        let key = "schema|method|\(pathID)|\(method.id)|\(methodIntensity)|\(stopSignal)"
        let precheck: SchemaPathPrecheck? = method.requiresPrecheck
            ? .init(
                orientationConfirmed: orientationConfirmed,
                realityClear: realityClear,
                sleepActivationClear: sleepActivationClear,
                intensity: methodIntensity,
                supportAvailable: supportAvailable,
                stopSignal: stopSignal
            ) : nil
        let mutation = SchemaPathMutation(
            action: .chooseMethod,
            conversationID: conversationID,
            requestID: requestID(for: key),
            pathID: pathID,
            methodID: method.methodId,
            confirmed: true,
            precheck: precheck
        )
        await perform("Yöntem seçiminiz kaydediliyor…", keys: [key]) {
            try await dataSource.mutateSchemaPath(mutation).snapshot
        }
    }

    public func saveGoodEnough() async {
        await recordSingle(kind: "good_enough", value: goodEnough,
                           description: "Bugün için yeterli işaret kaydediliyor…")
    }

    public func advanceToPractice() async {
        await advance(to: "practice", description: "İsteğe bağlı pratiğe geçiliyor…")
    }

    public func savePractice() async {
        guard practiceConfirmed, let pathID = activePath?.id else {
            failure = .init(
                title: "Açık seçim gerekli",
                message: "Küçük deneyi kendi seçiminizle eklediğinizi onaylayın."
            )
            return
        }
        let practice = SchemaPractice(
            variable: practiceVariable,
            constant: practiceConstant,
            prediction: practicePrediction,
            action: practiceAction,
            observableResult: practiceResult,
            tinyVersion: practiceTinyVersion,
            targetPerWeek: practiceTargetPerWeek
        )
        let key = "schema|practice|\(pathID)|\(practiceVariable)|\(practiceAction)"
        let mutation = SchemaPathMutation(
            action: .assignPractice,
            conversationID: conversationID,
            requestID: requestID(for: key),
            pathID: pathID,
            experiment: practice,
            userConfirmed: true
        )
        await perform("Küçük deney kaydediliyor…", keys: [key]) {
            try await dataSource.mutateSchemaPath(mutation).snapshot
        }
    }

    public func skipPractice() async {
        await recordSingle(
            kind: "skip_practice", value: "selected",
            description: "Pratik seçmeme kararınız kaydediliyor…"
        )
    }

    public func advanceToFollowup() async {
        await advance(to: "followup", description: "Takip aşamasına geçiliyor…")
    }

    public func saveFollowup() async {
        await recordSingle(
            kind: "followup", value: followup,
            description: "Takip notu kaydediliyor…"
        )
    }

    public func pauseOrResume() async {
        guard let path = activePath else { return }
        let action: SchemaPathAction = path.status == "paused" ? .resume : .pause
        let key = "schema|\(action.rawValue)|\(path.id)|\(path.revision)"
        let mutation = SchemaPathMutation(
            action: action,
            conversationID: conversationID,
            requestID: requestID(for: key),
            pathID: path.id
        )
        await perform(
            action == .pause ? "Çalışma yolu duraklatılıyor…" : "Çalışma yolu sürdürülüyor…",
            keys: [key]
        ) {
            try await dataSource.mutateSchemaPath(mutation).snapshot
        }
    }

    public func stop() async {
        guard let path = activePath else { return }
        let key = "schema|stop|\(path.id)|\(path.revision)"
        let mutation = SchemaPathMutation(
            action: .stop,
            conversationID: conversationID,
            requestID: requestID(for: key),
            pathID: path.id,
            reason: "Kullanıcı yerel çalışma alanından durdurdu"
        )
        await perform("Çalışma yolu durduruluyor…", keys: [key]) {
            try await dataSource.mutateSchemaPath(mutation).snapshot
        }
    }

    public func close() async {
        guard let path = activePath else { return }
        let key = "schema|close|\(path.id)|\(path.revision)"
        let mutation = SchemaPathMutation(
            action: .close,
            conversationID: conversationID,
            requestID: requestID(for: key),
            pathID: path.id
        )
        await perform("Çalışma yolu tamamlanıyor…", keys: [key]) {
            try await dataSource.mutateSchemaPath(mutation).snapshot
        }
    }

    public func dismissFailure() { failure = nil }

    private func recordSingle(kind: String, value: String, description: String) async {
        guard let pathID = activePath?.id else { return }
        let text = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else {
            failure = .init(title: "Kısa bir not gerekli", message: "Bu alanı kendi sözlerinizle doldurun.")
            return
        }
        let key = "schema|record|\(pathID)|\(kind)|\(text)"
        let mutation = SchemaPathMutation(
            action: .record,
            conversationID: conversationID,
            requestID: requestID(for: key),
            pathID: pathID,
            kind: kind,
            value: text
        )
        await perform(description, keys: [key]) {
            try await dataSource.mutateSchemaPath(mutation).snapshot
        }
    }

    private func advance(to phase: String, description: String) async {
        guard let path = activePath else { return }
        let key = "schema|advance|\(path.id)|\(phase)|\(path.revision)"
        let mutation = SchemaPathMutation(
            action: .advance,
            conversationID: conversationID,
            requestID: requestID(for: key),
            pathID: path.id,
            toPhase: phase
        )
        await perform(description, keys: [key]) {
            try await dataSource.mutateSchemaPath(mutation).snapshot
        }
    }

    private func perform(
        _ description: String,
        keys: [String],
        operation: () async throws -> SchemaPathSnapshot
    ) async {
        guard !isBusy else { return }
        isBusy = true
        operationDescription = description
        failure = nil
        defer {
            isBusy = false
            operationDescription = ""
        }
        do {
            let value = try await operation()
            keys.forEach { pendingRequestIDs.removeValue(forKey: $0) }
            apply(value)
            statusMessage = "Seçiminiz kaydedildi."
        } catch {
            failure = Self.failure("İşlem tamamlanamadı", error)
        }
    }

    private func performAnalysis(
        _ description: String,
        key: String,
        mutation: SchemaTurnAnalysisMutation,
        success: String
    ) async {
        guard !isBusy else { return }
        isBusy = true
        operationDescription = description
        failure = nil
        defer {
            isBusy = false
            operationDescription = ""
        }
        do {
            _ = try await dataSource.mutateSchemaTurnAnalysis(mutation)
            let value = try await dataSource.schemaPath(conversationID: conversationID)
            pendingRequestIDs.removeValue(forKey: key)
            apply(value)
            hasLoaded = true
            statusMessage = success
            scheduleAnalysisPollIfNeeded(value)
        } catch {
            failure = Self.failure("İşlem tamamlanamadı", error)
        }
    }

    private func apply(_ value: SchemaPathSnapshot) {
        snapshot = value
        guard let path = value.activePath else {
            hydratedPathID = nil
            return
        }
        if hydratedPathID != path.id {
            currentTrigger = path.latestRecord("current_trigger")
            need = path.latestRecord("need")
            earlierEcho = path.latestRecord("earlier_echo")
            skipOrigin = !path.latestRecord("skip_origin").isEmpty
            exception = path.latestRecord("exception")
            alternative = path.latestRecord("alternative")
            goodEnough = path.latestRecord("good_enough")
            followup = path.latestRecord("followup")
            selectedMethodID = path.methodId ?? ""
            if let origin = value.origin {
                originConfidence = origin.confidence
                originAgeText = origin.age.map(String.init) ?? ""
                originAgeRange = origin.ageRange
                originScene = origin.scene
                originUnmetNeed = origin.unmetNeed
            }
            for stage in value.growth?.stages ?? [] {
                growthThenResponses[stage.id] = stage.thenResponse
                growthNowResponses[stage.id] = stage.nowResponse
                growthDifferences[stage.id] = stage.difference
            }
            hydratedPathID = path.id
        }
    }

    private func scheduleAnalysisPollIfNeeded(_ value: SchemaPathSnapshot) {
        guard value.turnAnalysis?.processing == true else {
            analysisPollToken = UUID()
            return
        }
        let token = UUID()
        analysisPollToken = token
        Task { [weak self] in
            guard let self else { return }
            for _ in 0..<120 {
                try? await Task.sleep(for: .seconds(2))
                guard self.analysisPollToken == token else { return }
                do {
                    let latest = try await self.dataSource.schemaPath(
                        conversationID: self.conversationID
                    )
                    guard self.analysisPollToken == token else { return }
                    self.apply(latest)
                    if latest.turnAnalysis?.processing != true {
                        self.analysisPollToken = UUID()
                        self.statusMessage = "Tamamlanmış mesaj çifti incelemesi güncellendi."
                        return
                    }
                } catch {
                    // A transient polling failure is retried without erasing
                    // the last durable progress snapshot.
                }
            }
        }
    }

    private func requestID(for key: String) -> String {
        if let current = pendingRequestIDs[key] { return current }
        let value = "native-schema-path-\(UUID().uuidString.lowercased())"
        pendingRequestIDs[key] = value
        return value
    }

    private static func failure(_ title: String, _ error: Error) -> StructuredWorkspaceFailure {
        .init(
            title: title,
            message: (error as? LocalizedError)?.errorDescription
                ?? error.localizedDescription
        )
    }
}

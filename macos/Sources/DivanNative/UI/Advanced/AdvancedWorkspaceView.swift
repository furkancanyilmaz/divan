import SwiftUI

/// Native entry point for Divan's advanced work surfaces.
///
/// The host app supplies an `AdvancedWorkspaceDataSource` adapter. This view
/// deliberately knows nothing about HTTP, JSON, Core DTOs, or runtime startup.
public struct AdvancedWorkspaceView: View {
    @StateObject private var model: AdvancedWorkspaceViewModel
    /// Çalışma kullanılamadığında kullanıcıyı konuşmalara geri götüren
    /// isteğe bağlı çıkış. Host uygulama sağlar; bu katman navigasyonu bilmez.
    private let onExit: (() -> Void)?
    @Environment(\.divanWindowToolbarProvidesIdentity)
    private var windowToolbarProvidesIdentity

    public init(
        dataSource: any AdvancedWorkspaceDataSource,
        context: AdvancedWorkspaceContext,
        initialModule: AdvancedModule = .chairWork,
        onExit: (() -> Void)? = nil
    ) {
        _model = StateObject(
            wrappedValue: AdvancedWorkspaceViewModel(
                dataSource: dataSource,
                context: context,
                initialModule: initialModule
            )
        )
        self.onExit = onExit
    }

    public init(model: AdvancedWorkspaceViewModel, onExit: (() -> Void)? = nil) {
        _model = StateObject(wrappedValue: model)
        self.onExit = onExit
    }

    public var body: some View {
        GeometryReader { geometry in
            let safeInsets = geometry.safeAreaInsets
            let contentWidth = max(
                0,
                geometry.size.width - safeInsets.leading - safeInsets.trailing
            )
            let contentHeight = max(
                0,
                geometry.size.height - safeInsets.top - safeInsets.bottom
            )
            VStack(spacing: 0) {
                if let failure = model.failure {
                    AdvancedFailureBanner(
                        failure: failure,
                        retry: { Task { await model.retryFailure() } },
                        dismiss: model.dismissFailure
                    )
                }
                if model.clinicalSafetyHold, model.selectedModule.isClinical {
                    AdvancedSafetyHoldBanner()
                        .padding(.horizontal, 12)
                        .padding(.vertical, 8)
                }

                compactWorkspace
                    .frame(
                        minWidth: 0,
                        maxWidth: .infinity,
                        minHeight: 0,
                        maxHeight: .infinity
                    )
                    .layoutPriority(1)
            }
            .frame(
                width: contentWidth,
                height: contentHeight,
                alignment: .top
            )
            .clipped()
            .overlay(alignment: .bottomTrailing) {
                AdvancedOperationStatus(description: model.operationDescription)
                    .padding(16)
            }
            .overlay {
                if model.isLoading {
                    VStack(spacing: 10) {
                        ProgressView()
                        Text("İleri çalışma alanı hazırlanıyor…")
                            .foregroundStyle(.secondary)
                    }
                    .padding(20)
                    .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 12))
                    .accessibilityElement(children: .combine)
                    .accessibilityLabel("İleri çalışma alanı hazırlanıyor")
                }
            }
        }
        .task { await model.loadIfNeeded() }
        .frame(
            minWidth: 0,
            maxWidth: .infinity,
            minHeight: 0,
            idealHeight: 1,
            maxHeight: .infinity
        )
    }

    private var compactWorkspace: some View {
        VStack(spacing: 0) {
            ViewThatFits(in: .horizontal) {
                HStack(spacing: 10) {
                    compactModulePicker
                    Spacer(minLength: 4)
                    if !windowToolbarProvidesIdentity {
                        if let masterName = model.context.masterName, !masterName.isEmpty {
                            Text(masterName)
                                .font(.caption.weight(.semibold))
                                .lineLimit(1)
                                .truncationMode(.middle)
                        }
                        AISimulationBadge()
                    }
                    compactRefreshButton
                }
                HStack(spacing: 10) {
                    compactModulePicker
                    Spacer(minLength: 4)
                    if !windowToolbarProvidesIdentity {
                        AISimulationBadge()
                    }
                    compactRefreshButton
                }
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 9)
            .background(.bar)

            Divider()
            moduleDetail
                .frame(
                    minWidth: 0,
                    maxWidth: .infinity,
                    minHeight: 0,
                    maxHeight: .infinity
                )
                .layoutPriority(1)
        }
        .frame(
            minWidth: 0,
            maxWidth: .infinity,
            minHeight: 0,
            maxHeight: .infinity
        )
        .clipped()
    }

    private var compactModulePicker: some View {
        Picker("İleri çalışma", selection: moduleSelection) {
            ForEach(visibleModules) { module in
                Label(module.shortTitle, systemImage: module.systemImage)
                    .tag(Optional(module))
                    .disabled(!model.moduleIsAvailable(module))
            }
        }
        .pickerStyle(.menu)
        .labelsHidden()
        .accessibilityLabel("İleri çalışma seç")
    }

    private var visibleModules: [AdvancedModule] {
        AdvancedModule.allCases.filter {
            $0 == model.selectedModule || model.moduleIsAvailable($0)
        }
    }

    private var compactRefreshButton: some View {
        Button {
            Task { await model.reloadWorkspace() }
        } label: {
            Image(systemName: "arrow.clockwise")
        }
        .buttonStyle(.plain)
        .keyboardShortcut("r", modifiers: [.command])
        .disabled(model.isPerformingAction || model.isLoading)
        .accessibilityLabel("Çalışma alanını yenile")
        .help("Çalışma alanını yenile")
    }

    private var moduleSelection: Binding<AdvancedModule?> {
        Binding(
            get: { model.selectedModule },
            set: { module in
                if let module { model.selectModule(module) }
            }
        )
    }

    @ViewBuilder
    private var moduleDetail: some View {
        if let reason = model.unavailableReason(for: model.selectedModule) {
            AdvancedUnavailableState(
                title: unavailableTitle(for: model.selectedModule),
                message: reason,
                nextStep: unavailableNextStep(for: model.selectedModule),
                accessibilityIdentifier: unavailableIdentifier(for: model.selectedModule),
                exitAction: onExit
            )
        } else {
            switch model.selectedModule {
            case .chairWork:
                ChairWorkView(model: model)
            case .reparenting:
                ReparentingImageryView(model: model)
            case .livingMap:
                LivingMapView(model: model)
            case .wifiSync:
                WiFiSyncView(model: model)
            }
        }
    }

    private func unavailableTitle(for module: AdvancedModule) -> String {
        if !model.context.allowsClinicalWork, module.isClinical {
            return "Bu görüşmede deneyimsel çalışma kapalı"
        }
        return switch module {
        case .chairWork: "Bu ustada sandalye çalışması bulunmuyor"
        case .reparenting: "Bu ustada yeniden ebeveynlik-imgeleme bulunmuyor"
        case .livingMap: "Yaşayan harita kullanılamıyor"
        case .wifiSync: "Wi-Fi eşitleme kullanılamıyor"
        }
    }

    private func unavailableNextStep(for module: AdvancedModule) -> String {
        if !model.context.allowsClinicalWork, module.isClinical {
            return "Sol listedeki açık terapi seanslarından birini seçin. Açık seans yoksa Ustalar’dan yeni bir terapi seansı başlatın."
        }
        return switch module {
        case .chairWork:
            "Sol listedeki açık seanslardan Perls veya Young gibi sandalye protokolü sunan bir terapisti seçin."
        case .reparenting:
            "Sol listedeki açık seanslardan Young veya Arntz gibi imgeleme-yeniden ebeveynlik protokolü sunan bir terapisti seçin."
        case .livingMap:
            "Çalışma alanını yenileyin veya yaşayan haritası bulunan başka bir açık seans seçin."
        case .wifiSync:
            "Her iki cihazın aynı Wi-Fi ağında ve Divan’ın açık olduğundan emin olup yeniden deneyin."
        }
    }

    private func unavailableIdentifier(for module: AdvancedModule) -> String {
        switch module {
        case .chairWork: "chairUnavailableState"
        case .reparenting: "imageryUnavailableState"
        case .livingMap: "livingMapUnavailableState"
        case .wifiSync: "wifiSyncUnavailableState"
        }
    }

}

import AppKit
import SwiftUI

@MainActor
final class DivanApplicationDelegate: NSObject, NSApplicationDelegate {
    weak var runtimeLoader: DivanRuntimeLoader?
    private var terminationInProgress = false

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard let runtimeLoader else { return .terminateNow }
        guard !terminationInProgress else { return .terminateLater }
        terminationInProgress = true
        Task {
            await runtimeLoader.stop()
            sender.reply(toApplicationShouldTerminate: true)
        }
        return .terminateLater
    }
}

@main
@MainActor
struct DivanApp: App {
    @NSApplicationDelegateAdaptor(DivanApplicationDelegate.self)
    private var appDelegate
    @StateObject private var model: DivanViewModel
    private let runtimeLoader: DivanRuntimeLoader
    private let advancedDataSource: any AdvancedWorkspaceDataSource

    init() {
        let loader = DivanRuntimeLoader(controller: RuntimeController())
        runtimeLoader = loader
        advancedDataSource = CoreAdvancedWorkspaceDataSource(loader: loader)
        let displayPreferencesStore = UserDefaultsDivanDisplayPreferencesStore()
        _model = StateObject(wrappedValue: DivanViewModel(
            dataSource: CoreDivanUIDataSource(loader: loader),
            displayPreferencesStore: displayPreferencesStore
        ))
    }

    var body: some Scene {
        WindowGroup("Divan") {
            DivanRootView(model: model, advancedDataSource: advancedDataSource)
                .frame(minWidth: 480, minHeight: 360)
                .task {
                    appDelegate.runtimeLoader = runtimeLoader
                }
        }
        .defaultSize(width: 1280, height: 780)
        .windowToolbarStyle(.unifiedCompact)
        .commands {
            SidebarCommands()
            DivanNativeCommands(model: model)
        }
    }
}

private struct DivanNativeCommands: Commands {
    @ObservedObject var model: DivanViewModel

    var body: some Commands {
        CommandGroup(replacing: .newItem) {
            Button("Yeni Görüşme…") {
                model.prepareNewSession()
            }
            .keyboardShortcut("n", modifiers: [.command])
        }

        CommandMenu("Divan") {
            Button("Son Konuşmalar") { model.selectDestination(.recent) }
                .keyboardShortcut("1", modifiers: [.command])
            Button("Arşiv") { model.selectDestination(.archived) }
                .keyboardShortcut("2", modifiers: [.command])
            Divider()
            Button("Ustalar") { model.selectDestination(.masters) }
                .keyboardShortcut("3", modifiers: [.command])
            Button("Çalışmalar") { model.selectDestination(.works) }
                .keyboardShortcut("4", modifiers: [.command])
            Button("Yaşayan Harita") { model.selectDestination(.livingMap) }
                .keyboardShortcut("5", modifiers: [.command])
            Button("Cihaz Eşitleme") { model.selectDestination(.sync) }
                .keyboardShortcut("6", modifiers: [.command])
            Divider()
            Button("Görünümü Yenile") {
                Task { await model.refreshCurrentDestination() }
            }
            .keyboardShortcut("r", modifiers: [.command])
        }

        CommandGroup(replacing: .appSettings) {
            Button("Sağlayıcı ve Ayarlar…") {
                model.selectDestination(.settings)
            }
            .keyboardShortcut(",", modifiers: [.command])
        }
    }
}

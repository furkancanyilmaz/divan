import SwiftUI

@main
struct DivanApp: App {
    @StateObject private var runtime = PythonRuntime()
    @Environment(\.scenePhase) private var scenePhase

    var body: some Scene {
        WindowGroup {
            ZStack {
                RootView(runtime: runtime)
                if scenePhase != .active {
                    DivanPrivacyCover()
                }
            }
            .preferredColorScheme(.light)
        }
    }
}

private struct DivanPrivacyCover: View {
    var body: some View {
        ZStack {
            Color(red: 0.95, green: 0.92, blue: 0.85)
            VStack(spacing: 10) {
                Image(systemName: "text.book.closed.fill")
                    .font(.system(size: 36, weight: .semibold))
                Text("divan")
                    .font(.system(.title2, design: .serif, weight: .semibold))
            }
            .foregroundStyle(Color(red: 0.35, green: 0.16, blue: 0.12))
            .accessibilityElement(children: .combine)
            .accessibilityLabel("Divan gizlilik perdesi")
        }
        .ignoresSafeArea()
    }
}

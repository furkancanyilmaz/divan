import SwiftUI

struct RootView: View {
    @ObservedObject var runtime: PythonRuntime

    var body: some View {
        Group {
            switch runtime.state {
            case .idle, .starting:
                RuntimeLoadingView()
            case .running(let endpoint):
                DivanWebView(endpoint: endpoint)
                    .ignoresSafeArea(.container, edges: .bottom)
            case .failed(let message):
                RuntimeFailureView(message: message) {
                    Task { await runtime.start() }
                }
            }
        }
        .background(Color(red: 0.95, green: 0.92, blue: 0.85))
        .task {
            guard case .idle = runtime.state else { return }
            await runtime.start()
        }
    }
}

private struct RuntimeLoadingView: View {
    var body: some View {
        VStack(spacing: 14) {
            Image(systemName: "text.book.closed.fill")
                .font(.system(size: 42, weight: .semibold))
                .foregroundStyle(Color(red: 0.35, green: 0.16, blue: 0.12))
                .accessibilityHidden(true)
            Text("divan")
                .font(.system(.title2, design: .serif, weight: .semibold))
            ProgressView()
                .tint(Color(red: 0.35, green: 0.16, blue: 0.12))
            Text("yerel çalışma alanı hazırlanıyor")
                .font(.footnote)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .accessibilityElement(children: .combine)
    }
}

private struct RuntimeFailureView: View {
    let message: String
    let retry: () -> Void

    var body: some View {
        VStack(spacing: 16) {
            Image(systemName: "exclamationmark.lock.fill")
                .font(.system(size: 38))
                .foregroundStyle(Color(red: 0.35, green: 0.16, blue: 0.12))
                .accessibilityHidden(true)
            Text("Yerel çalışma alanı açılamadı")
                .font(.system(.title3, design: .serif, weight: .semibold))
            Text(message)
                .font(.callout)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .textSelection(.enabled)
            Button("Yeniden dene", action: retry)
                .buttonStyle(.borderedProminent)
                .tint(Color(red: 0.35, green: 0.16, blue: 0.12))
        }
        .padding(28)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

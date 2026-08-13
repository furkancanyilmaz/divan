import Foundation

struct RuntimeEndpoint: Equatable, Sendable {
    let baseURL: URL
}

enum PythonRuntimeError: LocalizedError {
    case embeddedFrameworkNotIntegrated
    case invalidEndpoint

    var errorDescription: String? {
        switch self {
        case .embeddedFrameworkNotIntegrated:
            return "Gömülü Python çalışma zamanı henüz bu iOS paketine bağlanmadı. Simülatörde geliştirme yapmak için DIVAN_RUNTIME_URL değişkenine bir loopback adresi verilebilir."
        case .invalidEndpoint:
            return "Çalışma zamanı yalnızca bu cihazdaki güvenli loopback adresinden açılabilir."
        }
    }
}

protocol PythonRuntimeBackend: Sendable {
    func start() async throws -> RuntimeEndpoint
    func stop() async
}

@MainActor
final class PythonRuntime: ObservableObject {
    enum State: Equatable {
        case idle
        case starting
        case running(RuntimeEndpoint)
        case failed(String)
    }

    @Published private(set) var state: State = .idle
    private let backend: any PythonRuntimeBackend

    init(backend: any PythonRuntimeBackend = CPythonServerBackend()) {
        self.backend = backend
    }

    func start() async {
        guard state != .starting else { return }
        state = .starting

        do {
            let endpoint = try await backend.start()
            guard LoopbackURLPolicy.isLoopbackHTTP(endpoint.baseURL) else {
                throw PythonRuntimeError.invalidEndpoint
            }
            state = .running(endpoint)
        } catch {
            state = .failed(error.localizedDescription)
        }
    }

    func stop() async {
        await backend.stop()
        state = .idle
    }
}

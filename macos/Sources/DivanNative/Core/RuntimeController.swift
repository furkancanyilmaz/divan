import Combine
import Foundation

@MainActor
public final class RuntimeController: ObservableObject {
    @Published public private(set) var state: RuntimeState = .idle
    @Published public private(set) var client: APIClient?
    @Published public private(set) var bootstrapPayload: BootstrapPayload?

    private let runtime: CoreRuntime

    public init(runtime: CoreRuntime = CoreRuntime()) {
        self.runtime = runtime
    }

    public func start() async {
        guard state != .starting else { return }
        state = .starting
        do {
            let endpoint = try await runtime.start()
            let apiClient = try APIClient(endpoint: endpoint)
            let payload = try await apiClient.bootstrap()
            client = apiClient
            bootstrapPayload = payload
            state = .running(endpoint)
        } catch {
            client = nil
            bootstrapPayload = nil
            state = .failed(error.localizedDescription)
        }
    }

    public func stop() async {
        state = .stopping
        client = nil
        bootstrapPayload = nil
        await runtime.stop()
        state = .idle
    }

    public func retry() async {
        await stop()
        await start()
    }
}

import Foundation

enum LoopbackURLPolicy {
    private static let permittedHosts: Set<String> = ["localhost", "127.0.0.1", "::1"]

    static func isLoopbackHTTP(_ url: URL) -> Bool {
        guard let scheme = url.scheme?.lowercased(),
              scheme == "http" || scheme == "https",
              let host = url.host?.lowercased(),
              permittedHosts.contains(host),
              url.user == nil,
              url.password == nil else {
            return false
        }
        return true
    }

    static func isSameOrigin(_ candidate: URL, as endpoint: URL) -> Bool {
        guard isLoopbackHTTP(candidate), isLoopbackHTTP(endpoint) else { return false }
        return candidate.scheme?.lowercased() == endpoint.scheme?.lowercased()
            && candidate.host?.lowercased() == endpoint.host?.lowercased()
            && effectivePort(candidate) == effectivePort(endpoint)
    }

    static func isExternalWebURL(_ url: URL) -> Bool {
        guard let scheme = url.scheme?.lowercased(), scheme == "http" || scheme == "https" else {
            return false
        }
        return !isLoopbackHTTP(url)
    }

    private static func effectivePort(_ url: URL) -> Int? {
        if let port = url.port { return port }
        switch url.scheme?.lowercased() {
        case "http": return 80
        case "https": return 443
        default: return nil
        }
    }
}
